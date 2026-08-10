#include "twin_control_protocol.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char g_line[TWIN_CONTROL_LINE_MAX + 1U];
static uint8_t g_line_length;
static uint8_t g_line_overflow;
static TwinControlParams g_pending_params;
static uint8_t g_has_pending_params;
static uint8_t g_restore_baseline;
static uint8_t g_motion_inhibited;
static const char *g_rollback_reason;
static int16_t g_last_speed_max;
static float g_last_kp;
static float g_last_ki;
static float g_last_kd;
static const char g_hex[] = "0123456789ABCDEF";

/* --- Task 2B safety state --- */

/* Flag: main loop should reset integral/last_err on next iteration. */
static uint8_t g_controller_reset_flag;

/* Pending status events for S-frame generation (bounded FIFO).
   Depth 4 covers all realistic batch-command scenarios. */
static TwinControlStatus g_status_fifo[TWIN_CONTROL_STATUS_FIFO_SIZE];
static uint8_t g_status_fifo_head;    /* next write index */
static uint8_t g_status_fifo_count;   /* entries in FIFO */

/* Identity of the most recent R command campaign/run.
   Used for S frames triggered by timeout/line-loss events. */
static char g_current_campaign_id[TWIN_CONTROL_CAMPAIGN_ID_MAX + 1U];
static char g_current_run_id[TWIN_CONTROL_RUN_ID_MAX + 1U];

/* Line-loss duration tracking (tick_ms from main loop). */
static uint32_t g_line_lost_start_ms;
static uint8_t g_line_lost_active;

/* Authoritative-state cache: always reflects the last emitted safety state.
   Used on TCP CONNECT to give the PC a reliable view of motor permission. */
static char g_last_state[TWIN_CONTROL_STATE_MAX + 1U];
static char g_last_reason[TWIN_CONTROL_REASON_MAX + 1U];

/* --- Health baseline: command heartbeat + 1s lease (Task 3) --- */
static uint8_t  g_heartbeat_pending;      /* parse 到有效 H 帧置位（布尔量）   */
static uint32_t g_heartbeat_count;        /* 任何状态收到有效 H 都计（parse 时）*/
static uint32_t g_heartbeat_timeout_count;
static uint8_t  g_heartbeat_last_reason;  /* HEALTH_HEARTBEAT_REASON_*         */
static uint32_t g_last_heartbeat_ms;      /* 最近续约时刻（仅 RUNNING 态租约） */
static uint32_t g_last_seen_heartbeat_ms; /* P1-4：最近消费的有效 H（任何状态）*/
static uint8_t  g_was_running;            /* inhibited→running 边沿（租约开启）*/

/* Sentinel identifiers used before any R command is received. */
#define SENTINEL_CAMPAIGN "none"
#define SENTINEL_RUN "none"

/* --- end Task 2B --- */

static uint8_t is_identifier(const char *value)
{
    uint8_t length = 0U;
    while (*value != '\0') {
        char c = *value++;
        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
              (c >= '0' && c <= '9') || c == '-')) return 0U;
        if (++length > TWIN_CONTROL_CAMPAIGN_ID_MAX) return 0U;
    }
    return (length > 0U) ? 1U : 0U;
}

static uint8_t bounded_length(const char *value, uint8_t maximum, uint8_t *length)
{
    uint8_t index;
    for (index = 0U; index <= maximum; ++index) {
        if (value[index] == '\0') {
            *length = index;
            return (index > 0U) ? 1U : 0U;
        }
    }
    return 0U;
}

static uint8_t is_bounded_identifier(const char *value, uint8_t maximum)
{
    uint8_t length;
    uint8_t index;
    if (!bounded_length(value, maximum, &length)) return 0U;
    for (index = 0U; index < length; ++index) {
        char c = value[index];
        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
              (c >= '0' && c <= '9') || c == '-')) return 0U;
    }
    return 1U;
}

static uint8_t is_bounded_status_text(const char *value, uint8_t maximum)
{
    uint8_t length;
    uint8_t index;
    if (!bounded_length(value, maximum, &length)) return 0U;
    for (index = 0U; index < length; ++index) {
        uint8_t c = (uint8_t)value[index];
        if (c < 0x20U || c > 0x7EU || c == (uint8_t)',') return 0U;
    }
    return 1U;
}

static uint8_t is_finite_float(float value)
{
    return (value == value && value < 3.4e38F && value > -3.4e38F) ? 1U : 0U;
}

static uint8_t parse_float(const char *text, float *value)
{
    char *end;
    double parsed = strtod(text, &end);
    if (*text == '\0' || *end != '\0') return 0U;
    *value = (float)parsed;
    return is_finite_float(*value);
}

static uint8_t parse_bounded_gain(const char *text, float *value,
                                  float minimum, float maximum)
{
    if (!parse_float(text, value)) return 0U;
    return (*value >= minimum && *value <= maximum) ? 1U : 0U;
}

static uint8_t is_decimal_text(const char *text, uint8_t first_must_be_nonzero)
{
    if (*text == '\0' || (first_must_be_nonzero && *text == '0')) return 0U;
    while (*text != '\0') {
        if (*text < '0' || *text > '9') return 0U;
        ++text;
    }
    return 1U;
}

static uint8_t parse_u32(const char *text, uint32_t *value)
{
    char *end;
    unsigned long parsed;
    if (!is_decimal_text(text, 1U)) return 0U;
    errno = 0;
    parsed = strtoul(text, &end, 10);
    if (*end != '\0' || errno == ERANGE || parsed > 0xFFFFFFFFUL) return 0U;
    *value = (uint32_t)parsed;
    return 1U;
}

static uint8_t parse_clock_sync_u32(const char *text, uint32_t *value)
{
    char *end;
    unsigned long parsed;
    if (!is_decimal_text(text, 0U)) return 0U;
    errno = 0;
    parsed = strtoul(text, &end, 10);
    if (*end != '\0' || errno == ERANGE || parsed > 0xFFFFFFFFUL) return 0U;
    *value = (uint32_t)parsed;
    return 1U;
}

static uint8_t parse_speed(const char *text, int16_t *value)
{
    char *end;
    long parsed;
    if (!is_decimal_text(text, 0U)) return 0U;
    parsed = strtol(text, &end, 10);
    if (*end != '\0' || parsed < TWIN_CONTROL_SPEED_MIN ||
        parsed > TWIN_CONTROL_SPEED_MAX) return 0U;
    *value = (int16_t)parsed;
    return 1U;
}

static uint8_t exceeds_float_step(float candidate, float active, float maximum_step)
{
    float difference = candidate - active;
    return (difference > maximum_step || difference < -maximum_step) ? 1U : 0U;
}

static uint8_t checksum(const char *data, uint16_t length)
{
    uint8_t value = 0U;
    uint16_t index;
    for (index = 0U; index < length; ++index) value ^= (uint8_t)data[index];
    return value;
}

static int8_t hex_value(char value)
{
    if (value >= '0' && value <= '9') return (int8_t)(value - '0');
    if (value >= 'A' && value <= 'F') return (int8_t)(value - 'A' + 10);
    return -1;
}

static void copy_text(char *destination, uint16_t destination_size, const char *source)
{
    uint16_t index = 0U;
    if (destination_size == 0U) return;
    while (source[index] != '\0' && index + 1U < destination_size) {
        destination[index] = source[index];
        ++index;
    }
    destination[index] = '\0';
}

static void clear_result(TwinControlResult *result)
{
    if (result != 0) memset(result, 0, sizeof(*result));
}

static void make_result(TwinControlResult *result, uint8_t applied,
                        const char *campaign_id, uint32_t version, const char *reason)
{
    clear_result(result);
    if (result == 0) return;
    result->has_ack = 1U;
    result->applied = applied;
    result->motion_inhibited = g_motion_inhibited;
    result->version = version;
    copy_text(result->campaign_id, sizeof(result->campaign_id), campaign_id);
    copy_text(result->reason, sizeof(result->reason), reason);
}

/* --- Task 2B: internal status event queue --- */

static void clear_status(TwinControlStatus *status)
{
    if (status != 0) memset(status, 0, sizeof(*status));
}

/* Queue a status event for S-frame generation (bounded FIFO).
   When the FIFO is full the oldest entry is silently dropped —
   the newest event always has a slot.  This is safe because the
   main loop drains the FIFO every ~5ms and multiple campaigns are
   never interleaved in V1. */
static void queue_event(const char *state, const char *reason, uint32_t tick_ms)
{
    TwinControlStatus *slot = &g_status_fifo[g_status_fifo_head];
    clear_status(slot);
    copy_text(slot->campaign_id, sizeof(slot->campaign_id),
              g_current_campaign_id);
    copy_text(slot->run_id, sizeof(slot->run_id),
              g_current_run_id);
    copy_text(slot->state, sizeof(slot->state), state);
    copy_text(slot->reason, sizeof(slot->reason), reason);
    slot->tick_ms = tick_ms;
    /* Update authoritative-state cache (always matches the last event). */
    copy_text(g_last_state, sizeof(g_last_state), state);
    copy_text(g_last_reason, sizeof(g_last_reason), reason);
    g_status_fifo_head = (g_status_fifo_head + 1U) % TWIN_CONTROL_STATUS_FIFO_SIZE;
    if (g_status_fifo_count < TWIN_CONTROL_STATUS_FIFO_SIZE) {
        g_status_fifo_count++;
    }
    /* When full (count == SIZE), head wraps and overwrites the oldest entry.
       count stays at SIZE — the caller still sees FIFO_SIZE entries available,
       but the oldest has been replaced. */
}

/* --- end Task 2B --- */

static uint8_t split_fields(char *body, char **fields, uint8_t expected_count)
{
    uint8_t count = 0U;
    char *cursor = body;
    fields[count++] = cursor;
    while (*cursor != '\0') {
        if (*cursor == ',') {
            *cursor = '\0';
            if (count >= expected_count) return 0U;
            fields[count++] = cursor + 1;
        }
        ++cursor;
    }
    return (count == expected_count) ? 1U : 0U;
}

static uint8_t verify_frame(char *line, char **fields, uint8_t expected_count)
{
    uint16_t length = (uint16_t)strlen(line);
    char *last_comma;
    int8_t high;
    int8_t low;
    if (length < 4U) return 0U;
    last_comma = strrchr(line, ',');
    if (last_comma == 0 || strlen(last_comma + 1) != 2U) return 0U;
    high = hex_value(last_comma[1]);
    low = hex_value(last_comma[2]);
    if (high < 0 || low < 0 || checksum(line, (uint16_t)(last_comma - line)) !=
        (uint8_t)((high << 4) | low)) return 0U;
    *last_comma = '\0';
    return split_fields(line, fields, expected_count);
}

static uint8_t parse_parameter(char *line, TwinControlResult *result)
{
    char *fields[7];
    TwinControlParams candidate;
    uint32_t version;
    if (!verify_frame(line, fields, 7U) || strcmp(fields[0], "P") != 0) return 0U;
    if (!is_identifier(fields[1]) || !parse_u32(fields[2], &version)) return 0U;
    copy_text(candidate.campaign_id, sizeof(candidate.campaign_id), fields[1]);
    candidate.version = version;
    if (!parse_bounded_gain(fields[3], &candidate.kp, TWIN_CONTROL_KP_MIN, TWIN_CONTROL_KP_MAX) ||
        !parse_bounded_gain(fields[4], &candidate.ki, TWIN_CONTROL_KI_MIN, TWIN_CONTROL_KI_MAX) ||
        !parse_bounded_gain(fields[5], &candidate.kd, TWIN_CONTROL_KD_MIN, TWIN_CONTROL_KD_MAX) ||
        !parse_speed(fields[6], &candidate.speed_max)) {
        make_result(result, 0U, candidate.campaign_id, candidate.version, "PARAM_BOUNDS");
        return 1U;
    }
    if (g_restore_baseline) {
        make_result(result, 0U, candidate.campaign_id, candidate.version, "INHIBITED");
        return 1U;
    }
    if (exceeds_float_step(candidate.kp, g_last_kp, TWIN_CONTROL_KP_STEP_MAX) ||
        exceeds_float_step(candidate.ki, g_last_ki, TWIN_CONTROL_KI_STEP_MAX) ||
        exceeds_float_step(candidate.kd, g_last_kd, TWIN_CONTROL_KD_STEP_MAX) ||
        (candidate.speed_max - g_last_speed_max) > TWIN_CONTROL_SPEED_STEP_MAX ||
        (g_last_speed_max - candidate.speed_max) > TWIN_CONTROL_SPEED_STEP_MAX) {
        make_result(result, 0U, candidate.campaign_id, candidate.version, "STEP_LIMIT");
        return 1U;
    }
    if (g_has_pending_params) {
        make_result(result, 0U, candidate.campaign_id, candidate.version, "PENDING");
        return 1U;
    }
    g_pending_params = candidate;
    g_has_pending_params = 1U;
    return 0U;
}

/* Task 2B: parse_run now saves campaign/run identity and queues S events. */
static void parse_run(char *line)
{
    char *fields[4];
    if (!verify_frame(line, fields, 4U) || strcmp(fields[0], "R") != 0 ||
        !is_identifier(fields[1]) || !is_identifier(fields[2])) return;

    /* Save latest campaign/run identity for timeout/line-loss S frames. */
    copy_text(g_current_campaign_id, sizeof(g_current_campaign_id), fields[1]);
    copy_text(g_current_run_id, sizeof(g_current_run_id), fields[2]);

    if (strcmp(fields[3], "STOP") == 0) {
        g_restore_baseline = 1U;
        g_motion_inhibited = 1U;
        g_rollback_reason = "STOP";
        g_heartbeat_last_reason = HEALTH_HEARTBEAT_REASON_STOP;
        g_was_running = 0U;
        queue_event("STOPPED", "STOP", 0U);
    } else if (strcmp(fields[3], "RESTORE_BASELINE") == 0) {
        g_restore_baseline = 1U;
        g_motion_inhibited = 1U;
        g_rollback_reason = "RESTORE_BASELINE";
        g_heartbeat_last_reason = HEALTH_HEARTBEAT_REASON_RESTORE_BASELINE;
        g_was_running = 0U;
        queue_event("STOPPED", "RESTORE_BASELINE", 0U);
    } else if (strcmp(fields[3], "START") == 0 && !g_restore_baseline) {
        g_motion_inhibited = 0U;
        queue_event("RUNNING", "START", 0U);
    }
}

/* Task 3: 心跳命令解析。H,campaign,run,cs\n —— 校验通过且 campaign/run 与
   当前 R 命令身份匹配才置 g_heartbeat_pending（防旧状态误关联）。 */
static void parse_heartbeat(char *line)
{
    char *fields[3];
    if (!verify_frame(line, fields, 3U) || strcmp(fields[0], "H") != 0) return;
    if (!is_identifier(fields[1]) || !is_identifier(fields[2])) return;
    if (strcmp(fields[1], g_current_campaign_id) != 0 ||
        strcmp(fields[2], g_current_run_id) != 0) return;
    /* P1-4：每条校验/身份匹配的 H 都在 parse 时计入 count（即使 pending
       已经为 1），同一次 RX drain 中的多条有效 H 不再合并。无效 H 不计。 */
    g_heartbeat_count++;
    g_heartbeat_pending = 1U;
}

static uint8_t parse_clock_sync(char *line, uint32_t now_ms,
                                TwinControlClockSync *clock_sync)
{
    char *fields[2];
    uint32_t sequence;
    if (clock_sync == 0 || !verify_frame(line, fields, 2U) ||
        strcmp(fields[0], "Q") != 0 ||
        !parse_clock_sync_u32(fields[1], &sequence) || sequence == 0U) {
        return 0U;
    }
    clock_sync->has_reply = 1U;
    clock_sync->sequence = sequence;
    clock_sync->mcu_rx_tick_ms = now_ms;
    return 1U;
}

static uint8_t parse_line(TwinControlResult *result, uint32_t now_ms,
                          TwinControlClockSync *clock_sync)
{
    if (g_line_length == 0U || g_line_overflow) return 0U;
    g_line[g_line_length] = '\0';
    if (g_line[0] == 'P') return parse_parameter(g_line, result);
    if (g_line[0] == 'R') parse_run(g_line);
    if (g_line[0] == 'H') parse_heartbeat(g_line);
    if (g_line[0] == 'Q') {
        (void)parse_clock_sync(g_line, now_ms, clock_sync);
        return 0U;
    }
    return 0U;
}

void twin_control_init(const TwinControlParams *baseline)
{
    g_line_length = 0U;
    g_line_overflow = 0U;
    g_has_pending_params = 0U;
    g_restore_baseline = 0U;
    /* Task 2B: firmware resets with motion INHIBITED by default.
       Only a valid R,...,START command (without pending rollback)
       can clear this. */
    g_motion_inhibited = 1U;
    g_rollback_reason = 0;
    g_last_speed_max = baseline->speed_max;
    g_last_kp = baseline->kp;
    g_last_ki = baseline->ki;
    g_last_kd = baseline->kd;

    /* Task 2B: clear safety state */
    g_controller_reset_flag = 0U;
    g_status_fifo_head = 0U;
    g_status_fifo_count = 0U;
    g_line_lost_active = 0U;
    g_line_lost_start_ms = 0U;

    /* Task 3: clear heartbeat / lease state */
    g_heartbeat_pending = 0U;
    g_heartbeat_count = 0U;
    g_heartbeat_timeout_count = 0U;
    g_heartbeat_last_reason = HEALTH_HEARTBEAT_REASON_NONE;
    g_last_heartbeat_ms = 0U;
    g_last_seen_heartbeat_ms = 0U;
    g_was_running = 0U;

    /* Set sentinel identity for pre-command S frames. */
    copy_text(g_current_campaign_id, sizeof(g_current_campaign_id), SENTINEL_CAMPAIGN);
    copy_text(g_current_run_id, sizeof(g_current_run_id), SENTINEL_RUN);

    /* Queue INIT status event — always observable after reset. */
    queue_event("INIT", "MOTION_INHIBITED", 0U);
    /* Authoritative cache matches INIT immediately. */
    copy_text(g_last_state, sizeof(g_last_state), "INIT");
    copy_text(g_last_reason, sizeof(g_last_reason), "MOTION_INHIBITED");
}

uint8_t twin_control_receive_byte(uint8_t byte, TwinControlResult *result)
{
    return twin_control_receive_byte_at(byte, 0U, result, 0);
}

uint8_t twin_control_receive_byte_at(uint8_t byte, uint32_t now_ms,
                                     TwinControlResult *result,
                                     TwinControlClockSync *clock_sync)
{
    clear_result(result);
    if (clock_sync != 0) memset(clock_sync, 0, sizeof(*clock_sync));
    if (byte == '\r') {
        g_line_overflow = 1U;
        return 0U;
    }
    if (byte == '\n') {
        uint8_t has_result = parse_line(result, now_ms, clock_sync);
        g_line_length = 0U;
        g_line_overflow = 0U;
        return has_result;
    }
    if (byte < 0x20U || byte > 0x7EU) {
        g_line_overflow = 1U;
        return 0U;
    }
    if (g_line_overflow) return 0U;
    if (g_line_length >= TWIN_CONTROL_LINE_MAX) {
        g_line_overflow = 1U;
        return 0U;
    }
    g_line[g_line_length++] = (char)byte;
    return 0U;
}

uint8_t twin_control_apply_pending(TwinControlParams *active,
                                   const TwinControlParams *baseline,
                                   TwinControlResult *result)
{
    clear_result(result);
    if (g_restore_baseline) {
        if (g_has_pending_params) {
            make_result(result, 0U, g_pending_params.campaign_id,
                        g_pending_params.version, g_rollback_reason);
        }
        *active = *baseline;
        g_last_speed_max = baseline->speed_max;
        g_last_kp = baseline->kp;
        g_last_ki = baseline->ki;
        g_last_kd = baseline->kd;
        g_has_pending_params = 0U;
        g_restore_baseline = 0U;
        g_rollback_reason = 0;
        /* Task 2B: signal main loop to reset controller state (integral, etc.). */
        g_controller_reset_flag = 1U;
        return 1U;
    }
    if (!g_has_pending_params) return 0U;
    *active = g_pending_params;
    g_last_speed_max = active->speed_max;
    g_last_kp = active->kp;
    g_last_ki = active->ki;
    g_last_kd = active->kd;
    g_has_pending_params = 0U;
    make_result(result, 1U, active->campaign_id, active->version, "APPLIED");
    /* Task 2B: new parameter version applied — reset controller state
       to prevent cross-candidate integral / last-err pollution. */
    g_controller_reset_flag = 1U;
    return 1U;
}

void twin_control_timeout(void)
{
    g_restore_baseline = 1U;
    g_motion_inhibited = 1U;
    g_rollback_reason = "TIMEOUT";
    /* Task 3: legacy command/disconnect timeout reason (heartbeat lease
       timeout overwrites to HEARTBEAT in twin_control_heartbeat_tick). */
    g_heartbeat_last_reason = HEALTH_HEARTBEAT_REASON_LEGACY_TIMEOUT;
    g_was_running = 0U;
    /* Task 2B: queue TIMEOUT status event. */
    queue_event("STOPPED", "TIMEOUT", 0U);
}

uint8_t twin_control_motion_inhibited(void)
{
    return g_motion_inhibited;
}

/* --- Task 2B: new public API --- */

uint8_t twin_control_consume_controller_reset_flag(void)
{
    uint8_t value = g_controller_reset_flag;
    g_controller_reset_flag = 0U;
    return value;
}

uint8_t twin_control_consume_pending_status(TwinControlStatus *status)
{
    if (status == 0) return 0U;
    if (g_status_fifo_count == 0U) {
        clear_status(status);
        return 0U;
    }
    /* Read from tail = (head - count + SIZE) % SIZE */
    uint8_t tail = (g_status_fifo_head + TWIN_CONTROL_STATUS_FIFO_SIZE - g_status_fifo_count)
                   % TWIN_CONTROL_STATUS_FIFO_SIZE;
    *status = g_status_fifo[tail];
    clear_status(&g_status_fifo[tail]);
    g_status_fifo_count--;
    return 1U;
}

uint8_t twin_control_has_pending_status(void)
{
    return (g_status_fifo_count != 0U) ? 1U : 0U;
}

uint8_t twin_control_report_line_lost(uint32_t tick_ms)
{
    if (!g_motion_inhibited) {
        if (!g_line_lost_active) {
            /* Start of a new line-loss event. */
            g_line_lost_active = 1U;
            g_line_lost_start_ms = tick_ms;
        } else if (tick_ms - g_line_lost_start_ms >= TWIN_CONTROL_LINE_LOST_MAX_MS) {
            /* Cumulative loss exceeded threshold — hard stop.
               Set flags directly (don't call twin_control_timeout which
               would add a TIMEOUT event to the FIFO). */
            g_restore_baseline = 1U;
            g_motion_inhibited = 1U;
            g_rollback_reason = "LINE_LOST";
            g_heartbeat_last_reason = HEALTH_HEARTBEAT_REASON_LINE_LOST;
            g_was_running = 0U;
            queue_event("STOPPED", "LINE_LOST", tick_ms);
            return 1U;
        }
    }
    return 0U;
}

void twin_control_report_line_found(void)
{
    g_line_lost_active = 0U;
    g_line_lost_start_ms = 0U;
}

void twin_control_queue_authoritative_status(void)
{
    /* Queue the cached authoritative state.
       On first CONNECT after reset this sends INIT/MOTION_INHIBITED.
       On reconnect after a timeout/stop this sends STOPPED/TIMEOUT or STOPPED/STOP.
       During normal operation this sends RUNNING/START. */
    queue_event(g_last_state, g_last_reason, 0U);
}

/* --- end Task 2B --- */

/* --- Health baseline: heartbeat + 1s lease (Task 3) --- */

void twin_control_heartbeat(uint32_t now_ms)
{
    /* P1-4：消费有效 pending → 始终更新 last_seen（heartbeat_age_ms 口径）。 */
    g_last_seen_heartbeat_ms = now_ms;
    /* 续约仅 RUNNING 态生效（STOPPED 到达的迟发 H 只更新 seen、不续约）。
       计数已在 parse_heartbeat 完成，此处不再 +1。 */
    if (!g_motion_inhibited) {
        g_last_heartbeat_ms = now_ms;
    }
}

uint8_t twin_control_consume_heartbeat_pending(void)
{
    uint8_t value = g_heartbeat_pending;
    g_heartbeat_pending = 0U;
    return value;
}

uint8_t twin_control_heartbeat_tick(uint32_t now_ms)
{
    if (g_motion_inhibited) return 0U;
    /* inhibited→running 边沿：START 立即开启 1s 租约。 */
    if (!g_was_running) {
        g_last_heartbeat_ms = now_ms;
        g_was_running = 1U;
        return 0U;
    }
    if ((uint32_t)(now_ms - g_last_heartbeat_ms) >= TWIN_CONTROL_HEARTBEAT_LEASE_MS) {
        g_heartbeat_timeout_count++;
        twin_control_timeout();   /* S 帧 reason 保持 TIMEOUT（兼容） */
        g_heartbeat_last_reason = HEALTH_HEARTBEAT_REASON_HEARTBEAT;
        g_was_running = 0U;
        return 1U;
    }
    return 0U;
}

uint8_t twin_control_health_motion_state(void)
{
    if (strcmp(g_last_state, "RUNNING") == 0) return HEALTH_MOTION_STATE_RUNNING;
    if (strcmp(g_last_state, "INIT") == 0) return HEALTH_MOTION_STATE_INIT;
    if (strcmp(g_last_state, "STOPPED") == 0) {
        if (strcmp(g_last_reason, "TIMEOUT") == 0) return HEALTH_MOTION_STATE_TIMEOUT;
        if (strcmp(g_last_reason, "LINE_LOST") == 0) return HEALTH_MOTION_STATE_LINE_LOST;
        return HEALTH_MOTION_STATE_STOPPED;
    }
    return HEALTH_MOTION_STATE_UNKNOWN;
}

uint8_t twin_control_lease_active(uint32_t now_ms)
{
    if (g_motion_inhibited) return 0U;
    return ((uint32_t)(now_ms - g_last_heartbeat_ms) < TWIN_CONTROL_HEARTBEAT_LEASE_MS)
           ? 1U : 0U;
}

uint16_t twin_control_heartbeat_count(void)
{
    return (uint16_t)g_heartbeat_count;
}

uint16_t twin_control_heartbeat_timeout_count(void)
{
    return (uint16_t)g_heartbeat_timeout_count;
}

uint8_t twin_control_heartbeat_last_reason(void)
{
    return g_heartbeat_last_reason;
}

uint32_t twin_control_heartbeat_age_ms(uint32_t now_ms)
{
    /* P1-4：年龄 = 距最后消费的有效 H（last_seen），独立于租约续约时刻；
       从未收到有效 H 返回 0xFFFFFFFF。 */
    if (g_heartbeat_count == 0U) return 0xFFFFFFFFU;
    return (uint32_t)(now_ms - g_last_seen_heartbeat_ms);
}

/* --- end Task 3 --- */

uint16_t twin_control_encode_ack(const TwinControlResult *result,
                                 char *output,
                                 uint16_t output_size)
{
    char body[80];
    int written;
    uint16_t length;
    uint8_t value;
    if (result == 0 || output == 0 || !result->has_ack) return 0U;
    written = sprintf(body, "A,%s,%lu,%s,%s", result->campaign_id,
                      (unsigned long)result->version,
                      result->applied ? "APPLIED" : "REJECTED", result->reason);
    if (written < 0 || written >= (int)sizeof(body)) return 0U;
    length = (uint16_t)written;
    if ((uint32_t)length + 5U > output_size) return 0U;
    value = checksum(body, length);
    memcpy(output, body, length);
    output[length++] = ',';
    output[length++] = g_hex[(value >> 4) & 0x0FU];
    output[length++] = g_hex[value & 0x0FU];
    output[length++] = '\n';
    output[length] = '\0';
    return length;
}

uint16_t twin_control_encode_status(const TwinControlStatus *status,
                                    char *output,
                                    uint16_t output_size)
{
    char body[TWIN_CONTROL_LINE_MAX + 1U];
    int written;
    uint16_t length;
    uint8_t value;
    if (status == 0 || output == 0 ||
        !is_bounded_identifier(status->campaign_id, TWIN_CONTROL_CAMPAIGN_ID_MAX) ||
        !is_bounded_identifier(status->run_id, TWIN_CONTROL_RUN_ID_MAX) ||
        !is_bounded_status_text(status->state, TWIN_CONTROL_STATE_MAX) ||
        !is_bounded_status_text(status->reason, TWIN_CONTROL_REASON_MAX)) return 0U;
    written = sprintf(body, "S,%s,%s,%s,%s,%lu", status->campaign_id,
                      status->run_id, status->state, status->reason,
                      (unsigned long)status->tick_ms);
    if (written < 0 || written >= (int)sizeof(body)) return 0U;
    length = (uint16_t)written;
    if ((uint32_t)length + 5U > output_size) return 0U;
    value = checksum(body, length);
    memcpy(output, body, length);
    output[length++] = ',';
    output[length++] = g_hex[(value >> 4) & 0x0FU];
    output[length++] = g_hex[value & 0x0FU];
    output[length++] = '\n';
    output[length] = '\0';
    return length;
}

uint16_t twin_control_encode_clock_sync(const TwinControlClockSync *clock_sync,
                                        uint32_t mcu_tx_tick_ms,
                                        char *output,
                                        uint16_t output_size)
{
    char body[TWIN_CONTROL_LINE_MAX + 1U];
    int written;
    uint16_t length;
    uint8_t value;
    if (clock_sync == 0 || output == 0 || !clock_sync->has_reply ||
        clock_sync->sequence == 0U) return 0U;
    written = sprintf(body, "T,%lu,%lu,%lu",
                      (unsigned long)clock_sync->sequence,
                      (unsigned long)clock_sync->mcu_rx_tick_ms,
                      (unsigned long)mcu_tx_tick_ms);
    if (written < 0 || written >= (int)sizeof(body)) return 0U;
    length = (uint16_t)written;
    if ((uint32_t)length + 5U > output_size) return 0U;
    value = checksum(body, length);
    memcpy(output, body, length);
    output[length++] = ',';
    output[length++] = g_hex[(value >> 4) & 0x0FU];
    output[length++] = g_hex[value & 0x0FU];
    output[length++] = '\n';
    output[length] = '\0';
    return length;
}

uint16_t twin_control_encode_clock_sync_fixed(
    const TwinControlClockSync *clock_sync, uint32_t mcu_tx_tick_ms,
    char *output, uint16_t output_size)
{
    char body[TWIN_CONTROL_CLOCK_SYNC_FRAME_LEN];
    int written;
    uint16_t length;
    uint8_t value;

    if (clock_sync == 0 || output == 0 || !clock_sync->has_reply ||
        clock_sync->sequence == 0U || output_size <
        (uint16_t)(TWIN_CONTROL_CLOCK_SYNC_FRAME_LEN + 1U)) {
        return 0U;
    }
    written = sprintf(body, "T,%010lu,%010lu,%010lu",
                      (unsigned long)clock_sync->sequence,
                      (unsigned long)clock_sync->mcu_rx_tick_ms,
                      (unsigned long)mcu_tx_tick_ms);
    if (written != (int)(TWIN_CONTROL_CLOCK_SYNC_FRAME_LEN - 4U)) {
        return 0U;
    }
    length = (uint16_t)written;
    value = checksum(body, length);
    memcpy(output, body, length);
    output[length++] = ',';
    output[length++] = g_hex[(value >> 4) & 0x0FU];
    output[length++] = g_hex[value & 0x0FU];
    output[length++] = '\n';
    output[length] = '\0';
    return length;
}
