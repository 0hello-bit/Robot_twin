#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "twin_control_protocol.h"

#define CHECK(expression) do { \
    if (!(expression)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expression); \
        return 1; \
    } \
} while (0)

static const TwinControlParams k_baseline = {
    35.0F, 0.0F, 10.0F, 680, 1U, "baseline"
};

static void make_frame(char *output, unsigned int output_size, const char *body)
{
    unsigned int index;
    unsigned char value = 0U;
    unsigned int length = (unsigned int)strlen(body);
    if (length + 5U > output_size) {
        fputs("test frame buffer too small\n", stderr);
        exit(2);
    }
    for (index = 0U; index < length; ++index) value ^= (unsigned char)body[index];
    memcpy(output, body, length);
    sprintf(output + length, ",%02X\n", value);
}

static unsigned char feed(const char *frame, TwinControlResult *result)
{
    unsigned char has_result = 0U;
    unsigned int index;
    for (index = 0U; frame[index] != '\0'; ++index) {
        has_result = twin_control_receive_byte((unsigned char)frame[index], result);
    }
    return has_result;
}

static unsigned char feed_bytes(const unsigned char *bytes, unsigned int length,
                                TwinControlResult *result)
{
    unsigned char has_result = 0U;
    unsigned int index;
    for (index = 0U; index < length; ++index) {
        has_result = twin_control_receive_byte(bytes[index], result);
    }
    return has_result;
}

static int active_is_baseline(const TwinControlParams *active)
{
    return active->kp == k_baseline.kp && active->ki == k_baseline.ki &&
           active->kd == k_baseline.kd && active->speed_max == k_baseline.speed_max &&
           active->version == k_baseline.version && strcmp(active->campaign_id, "baseline") == 0;
}

static int queue_legal_candidate(TwinControlParams *active, TwinControlResult *result)
{
    char frame[96];
    twin_control_init(&k_baseline);
    *active = k_baseline;
    make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
    CHECK(feed(frame, result) == 0U);
    return 0;
}

static int apply_legal_candidate(TwinControlParams *active, TwinControlResult *result)
{
    char start[96];
    /* Must first START to clear default inhibit */
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    CHECK(feed(start, result) == 0U);
    CHECK(twin_control_motion_inhibited() == 0U);
    CHECK(queue_legal_candidate(active, result) == 0);
    CHECK(twin_control_apply_pending(active, &k_baseline, result) == 1U);
    CHECK(result->has_ack == 1U && result->applied == 1U);
    CHECK(active->version == 2U && active->kp == 40.0F);
    CHECK(!active_is_baseline(active));
    return 0;
}

static void set_status(TwinControlStatus *status, const char *campaign_id,
                       const char *run_id, const char *state,
                       const char *reason, uint32_t tick_ms)
{
    memset(status, 0, sizeof(*status));
    strcpy(status->campaign_id, campaign_id);
    strcpy(status->run_id, run_id);
    strcpy(status->state, state);
    strcpy(status->reason, reason);
    status->tick_ms = tick_ms;
}

static int bytes_are(const char *value, unsigned int length, char expected)
{
    unsigned int index;
    for (index = 0U; index < length; ++index) {
        if (value[index] != expected) return 0;
    }
    return 1;
}

static int status_failure_preserves_output(const TwinControlStatus *status,
                                           uint16_t output_size)
{
    char output[TWIN_CONTROL_LINE_MAX];
    memset(output, '@', sizeof(output));
    return twin_control_encode_status(status, output, output_size) == 0U &&
           bytes_are(output, sizeof(output), '@');
}

static int ack_failure_preserves_output(const TwinControlResult *result,
                                        uint16_t output_size)
{
    char output[TWIN_CONTROL_LINE_MAX];
    memset(output, '@', sizeof(output));
    return twin_control_encode_ack(result, output, output_size) == 0U &&
           bytes_are(output, sizeof(output), '@');
}

static void set_ack_result(TwinControlResult *result, const char *campaign_id,
                           uint32_t version, unsigned char applied,
                           const char *reason)
{
    memset(result, 0, sizeof(*result));
    result->has_ack = 1U;
    result->applied = applied;
    result->version = version;
    strcpy(result->campaign_id, campaign_id);
    strcpy(result->reason, reason);
}

/* ===== Task 2B New Tests ===== */

/* [2B-1] Default motion inhibited after init */
static int test_default_motion_inhibited(void)
{
    twin_control_init(&k_baseline);
    CHECK(twin_control_motion_inhibited() == 1U);
    /* Even after applying pending (none), motion stays inhibited */
    {
        TwinControlParams active = k_baseline;
        TwinControlResult result;
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
        CHECK(twin_control_motion_inhibited() == 1U);
    }
    return 0;
}

/* [2B-2] INIT status event is queued after init */
static int test_init_produces_status(void)
{
    TwinControlStatus st;
    twin_control_init(&k_baseline);
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "INIT") == 0);
    CHECK(strcmp(st.reason, "MOTION_INHIBITED") == 0);
    CHECK(strcmp(st.campaign_id, "none") == 0);
    CHECK(strcmp(st.run_id, "none") == 0);
    /* Second consume returns empty */
    memset(&st, 0xAA, sizeof(st));
    CHECK(twin_control_consume_pending_status(&st) == 0U);
    CHECK(st.campaign_id[0] == '\0');
    return 0;
}

/* [2B-3] START clears motion inhibit and queues RUNNING event */
static int test_start_uninhibits_and_queues_running(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];
    TwinControlParams active = k_baseline;

    /* Baseline ready: init, send START */
    twin_control_init(&k_baseline);
    CHECK(twin_control_motion_inhibited() == 1U);
    twin_control_consume_pending_status(&st); /* drain INIT */

    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 0U);

    /* Check RUNNING status event */
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "RUNNING") == 0);
    CHECK(strcmp(st.reason, "START") == 0);
    CHECK(strcmp(st.campaign_id, "camp-001") == 0);
    CHECK(strcmp(st.run_id, "run-001") == 0);

    /* Now params can be applied */
    make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(active.kp == 40.0F);
    return 0;
}

/* [2B-4] STOP inhibits motion and queues STOPPED/STOP event */
static int test_stop_inhibits_and_queues_status(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st); /* drain INIT */
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    twin_control_consume_pending_status(&st); /* drain RUNNING */

    /* Send STOP */
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,STOP");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);

    /* Check STOPPED/STOP status event */
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "STOP") == 0);
    CHECK(strcmp(st.campaign_id, "camp-001") == 0);
    CHECK(strcmp(st.run_id, "run-001") == 0);
    return 0;
}

/* [2B-5] RESTORE_BASELINE inhibits and queues STOPPED/RESTORE_BASELINE event */
static int test_restore_baseline_inhibits_and_queues_status(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    twin_control_consume_pending_status(&st); /* drain RUNNING */

    make_frame(frame, sizeof(frame), "R,camp-001,run-002,RESTORE_BASELINE");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);

    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "RESTORE_BASELINE") == 0);
    CHECK(strcmp(st.campaign_id, "camp-001") == 0);
    CHECK(strcmp(st.run_id, "run-002") == 0);
    return 0;
}

/* [2B-6] TIMEOUT inhibits and queues STOPPED/TIMEOUT event */
static int test_timeout_inhibits_and_queues_status(void)
{
    TwinControlStatus st;
    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);

    twin_control_timeout();
    CHECK(twin_control_motion_inhibited() == 1U);

    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "TIMEOUT") == 0);
    return 0;
}

/* [2B-7] START is ignored when restore is pending (g_restore_baseline set) */
static int test_start_ignored_when_restore_pending(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];
    TwinControlParams active = k_baseline;

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);

    /* STOP first */
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,STOP");
    CHECK(feed(frame, &result) == 0U);
    twin_control_consume_pending_status(&st);

    /* Now g_restore_baseline is set. Send START before apply_pending — must be ignored */
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 1U); /* still inhibited */

    /* Apply restore (clears g_restore_baseline) */
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(active_is_baseline(&active));
    CHECK(twin_control_motion_inhibited() == 1U); /* still inhibited after restore */

    /* Now START should work */
    make_frame(frame, sizeof(frame), "R,camp-001,run-002,START");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 0U);
    return 0;
}

/* [2B-8] Controller reset flag is set on new parameter apply */
static int test_controller_reset_flag_on_parameter_apply(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];
    TwinControlParams active = k_baseline;

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);

    /* Drain any START-related status */
    twin_control_consume_pending_status(&st);

    /* Queue and apply a parameter */
    make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_consume_controller_reset_flag() == 0U); /* not yet */
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(twin_control_consume_controller_reset_flag() == 1U); /* set on apply */
    CHECK(twin_control_consume_controller_reset_flag() == 0U); /* consumed */
    return 0;
}

/* [2B-9] Controller reset flag is set on rollback (STOP/TIMEOUT/RESTORE_BASELINE) */
static int test_controller_reset_flag_on_rollback(void)
{
    const char *actions[] = { "STOP", "RESTORE_BASELINE" };
    unsigned int index;
    for (index = 0U; index < sizeof(actions) / sizeof(actions[0]); ++index) {
        TwinControlStatus st;
        TwinControlResult result;
        char frame[96];
        char body[96];
        TwinControlParams active = k_baseline;

        twin_control_init(&k_baseline);
        twin_control_consume_pending_status(&st);
        make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
        CHECK(feed(frame, &result) == 0U);
        twin_control_consume_pending_status(&st);

        make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
        CHECK(feed(frame, &result) == 0U);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(twin_control_consume_controller_reset_flag() == 1U);

        /* now rollback */
        sprintf(body, "R,camp-001,run-001,%s", actions[index]);
        make_frame(frame, sizeof(frame), body);
        CHECK(feed(frame, &result) == 0U);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(twin_control_consume_controller_reset_flag() == 1U);
        CHECK(twin_control_consume_controller_reset_flag() == 0U);
    }

    /* TIMEOUT rollback */
    {
        TwinControlStatus st;
        TwinControlResult result;
        TwinControlParams active = k_baseline;
        char frame[96];

        twin_control_init(&k_baseline);
        twin_control_consume_pending_status(&st);
        make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
        CHECK(feed(frame, &result) == 0U);
        twin_control_consume_pending_status(&st);
        make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
        CHECK(feed(frame, &result) == 0U);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(twin_control_consume_controller_reset_flag() == 1U);

        twin_control_timeout();
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(twin_control_consume_controller_reset_flag() == 1U);
        CHECK(twin_control_consume_controller_reset_flag() == 0U);
    }
    return 0;
}

/* [2B-10] Line loss within threshold does NOT trigger hard stop */
static int test_line_lost_within_threshold(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 0U);
    twin_control_consume_pending_status(&st); /* drain RUNNING */

    /* Report line lost for 500 ms (under 1000ms threshold) */
    CHECK(twin_control_report_line_lost(0U) == 0U);   /* start at 0 */
    CHECK(twin_control_report_line_lost(500U) == 0U);  /* 500ms, still under */
    CHECK(twin_control_motion_inhibited() == 0U);       /* not triggered */

    /* Line found resets */
    twin_control_report_line_found();
    CHECK(twin_control_report_line_lost(600U) == 0U);  /* fresh loss */
    CHECK(twin_control_motion_inhibited() == 0U);
    return 0;
}

/* [2B-11] Line loss exceeding threshold triggers hard stop */
static int test_line_lost_exceeds_threshold(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 0U);
    twin_control_consume_pending_status(&st); /* drain RUNNING */

    /* Report line lost for 1000ms — exactly at threshold */
    CHECK(twin_control_report_line_lost(0U) == 0U);
    CHECK(twin_control_report_line_lost(999U) == 0U);  /* 999ms, still under */
    CHECK(twin_control_report_line_lost(1000U) == 1U); /* 1000ms → HARD STOP */

    CHECK(twin_control_motion_inhibited() == 1U);

    /* Verify LINE_LOST status event */
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "LINE_LOST") == 0);
    return 0;
}

/* [2B-12] Line-found resets the loss timer */
static int test_line_found_resets_loss_timer(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 0U);
    twin_control_consume_pending_status(&st); /* drain RUNNING */

    /* Lost for 600ms, then found */
    CHECK(twin_control_report_line_lost(0U) == 0U);
    CHECK(twin_control_report_line_lost(600U) == 0U);
    twin_control_report_line_found();

    /* Lost again starting from 700ms — timer should reset */
    CHECK(twin_control_report_line_lost(700U) == 0U); /* start of new loss */
    CHECK(twin_control_report_line_lost(1200U) == 0U); /* 500ms elapsed, under */
    CHECK(twin_control_report_line_lost(1700U) == 1U); /* 1000ms → HARD STOP */
    return 0;
}

/* [2B-13] Mutation killer: default motion is NOT enabled */
static int test_killer_default_not_motion_allowed(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];
    TwinControlParams active = k_baseline;

    /* After plain init without any command, motion MUST be inhibited.
       If someone accidentally changes init to set inhibited=0, this fails. */
    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);

    CHECK(twin_control_motion_inhibited() == 1U);

    /* Try to apply a P command without START — it should be queued but
       since restore_baseline is 0, the P should queue as pending.
       But motion is still inhibited. */
    make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(result.applied == 1U); /* P applies fine (no restore pending) */
    /* BUT motion is still inhibited — motors don't spin */
    CHECK(twin_control_motion_inhibited() == 1U);
    return 0;
}

/* [2B-14] Mutation killer: corrupted START frame does NOT bypass inhibit */
static int test_killer_corrupted_start_does_not_bypass(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    CHECK(twin_control_motion_inhibited() == 1U);

    /* Wrong command type */
    make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);

    /* Corrupted checksum on START */
    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    {
        char bad[96];
        make_frame(bad, sizeof(bad), "R,camp-001,run-001,START");
        bad[strlen(bad) - 3U] = '0'; /* corrupt checksum */
        CHECK(feed(bad, &result) == 0U);
        CHECK(twin_control_motion_inhibited() == 1U);
    }

    /* CR before LF on START */
    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    {
        char crlf[96];
        make_frame(crlf, sizeof(crlf), "R,camp-001,run-001,START");
        crlf[strlen(crlf) - 1U] = '\0';
        strcat(crlf, "\r\n");
        CHECK(feed(crlf, &result) == 0U);
        CHECK(twin_control_motion_inhibited() == 1U);
    }

    /* Invalid campaign id on START */
    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp$001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);

    return 0;
}

/* [2B-15] Mutation killer: line-loss threshold does NOT degrade under load */
static int test_killer_line_loss_threshold_constant(void)
{
    /* Verify the constant is at the documented value */
    {
        unsigned int v = TWIN_CONTROL_LINE_LOST_MAX_MS;
        CHECK(v == 1000U);
    }

    /* Verify that 999ms does not trigger, 1000ms does */
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);

    /* Edge: exactly at boundary */
    twin_control_report_line_found(); /* ensure clean state */
    CHECK(twin_control_report_line_lost(0U) == 0U);
    CHECK(twin_control_report_line_lost(999U) == 0U);
    CHECK(twin_control_report_line_lost(1000U) == 1U);
    return 0;
}

/* [2B-16] Status events are not lost: consume after each transition */
static int test_killer_status_events_not_lost(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];
    TwinControlParams active = k_baseline;

    twin_control_init(&k_baseline);
    /* INIT event */
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "INIT") == 0);

    /* START event */
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "RUNNING") == 0);

    /* STOP event */
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,STOP");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "STOP") == 0);

    /* Restart: apply restore first (clears g_restore_baseline), then START */
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    make_frame(frame, sizeof(frame), "R,camp-001,run-002,START");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "RUNNING") == 0);
    CHECK(strcmp(st.reason, "START") == 0);

    /* RESTORE_BASELINE event */
    make_frame(frame, sizeof(frame), "R,camp-001,run-003,RESTORE_BASELINE");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "RESTORE_BASELINE") == 0);
    return 0;
}

/* [2B-17] Null consume_pending_status does not crash */
static int test_consume_pending_status_null(void)
{
    twin_control_init(&k_baseline);
    /* Must not crash */
    twin_control_consume_pending_status(0);
    return 0;
}

/* [2B-18] FIFO preserves multiple events in order */
static int test_fifo_preserves_multiple_events(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);

    make_frame(frame, sizeof(frame), "R,camp-001,run-001,STOP");
    CHECK(feed(frame, &result) == 0U);
    make_frame(frame, sizeof(frame), "R,camp-002,run-002,RESTORE_BASELINE");
    CHECK(feed(frame, &result) == 0U);

    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.reason, "STOP") == 0);
    CHECK(strcmp(st.campaign_id, "camp-001") == 0);

    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.reason, "RESTORE_BASELINE") == 0);
    CHECK(strcmp(st.campaign_id, "camp-002") == 0);

    CHECK(twin_control_consume_pending_status(&st) == 0U);
    return 0;
}

/* [2B-19] Same-batch START-STOP preserves both events */
static int test_batch_start_then_stop(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);

    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,STOP");
    CHECK(feed(frame, &result) == 0U);

    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "RUNNING") == 0);
    CHECK(strcmp(st.reason, "START") == 0);

    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "STOP") == 0);

    CHECK(twin_control_consume_pending_status(&st) == 0U);
    return 0;
}

/* [2B-20] Same-batch STOP-RESTORE_BASELINE preserves both */
static int test_batch_stop_then_restore(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    twin_control_consume_pending_status(&st);

    make_frame(frame, sizeof(frame), "R,camp-001,run-001,STOP");
    CHECK(feed(frame, &result) == 0U);
    make_frame(frame, sizeof(frame), "R,camp-001,run-002,RESTORE_BASELINE");
    CHECK(feed(frame, &result) == 0U);

    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "STOP") == 0);

    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "RESTORE_BASELINE") == 0);
    CHECK(strcmp(st.run_id, "run-002") == 0);

    CHECK(twin_control_consume_pending_status(&st) == 0U);
    return 0;
}

/* [2B-21] TIMEOUT-LINE_LOST: LINE_LOST overwrites TIMEOUT by design */
static int test_batch_timeout_then_line_lost(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    twin_control_consume_pending_status(&st);

    CHECK(twin_control_report_line_lost(0U) == 0U);
    CHECK(twin_control_report_line_lost(1000U) == 1U);

    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "LINE_LOST") == 0);
    CHECK(twin_control_consume_pending_status(&st) == 0U);
    return 0;
}

/* [2B-22] FIFO overflow drops oldest */
static int test_fifo_overflow_drops_oldest(void)
{
    TwinControlStatus st;
    TwinControlResult result;
    char frame[96];
    unsigned int i;

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(frame, sizeof(frame), "R,camp-001,run-001,START");
    CHECK(feed(frame, &result) == 0U);
    twin_control_consume_pending_status(&st);

    for (i = 0U; i < 5U; i++) {
        char body[32];
        sprintf(body, "R,camp-001,run-%03u,STOP", i);
        make_frame(frame, sizeof(frame), body);
        CHECK(feed(frame, &result) == 0U);
        sprintf(body, "R,camp-001,run-%03u,START", i);
        make_frame(frame, sizeof(frame), body);
        CHECK(feed(frame, &result) == 0U);
    }

    unsigned int count = 0U;
    while (twin_control_consume_pending_status(&st)) count++;
    CHECK(count > 0U && count <= TWIN_CONTROL_STATUS_FIFO_SIZE);
    return 0;
}



/* [2B-24] Authoritative state cache tracks last event */
static int test_authoritative_state_cached(void)
{
    TwinControlStatus st;

    /* INIT */
    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st); /* drain INIT */
    twin_control_queue_authoritative_status();
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "INIT") == 0);
    CHECK(strcmp(st.reason, "MOTION_INHIBITED") == 0);

    /* After START */
    {
        TwinControlResult r;
        char f[96];
        make_frame(f, sizeof(f), "R,camp-001,run-001,START");
        CHECK(feed(f, &r) == 0U);
        twin_control_consume_pending_status(&st);
        twin_control_queue_authoritative_status();
        CHECK(twin_control_consume_pending_status(&st) == 1U);
        CHECK(strcmp(st.state, "RUNNING") == 0);
        CHECK(strcmp(st.reason, "START") == 0);
    }

    /* After STOP */
    {
        TwinControlResult r;
        char f[96];
        make_frame(f, sizeof(f), "R,camp-001,run-001,STOP");
        CHECK(feed(f, &r) == 0U);
        twin_control_consume_pending_status(&st);
        twin_control_queue_authoritative_status();
        CHECK(twin_control_consume_pending_status(&st) == 1U);
        CHECK(strcmp(st.state, "STOPPED") == 0);
        CHECK(strcmp(st.reason, "STOP") == 0);
    }

    /* After TIMEOUT */
    {
        twin_control_init(&k_baseline);
        twin_control_consume_pending_status(&st);
        twin_control_timeout();
        twin_control_consume_pending_status(&st);
        twin_control_queue_authoritative_status();
        CHECK(twin_control_consume_pending_status(&st) == 1U);
        CHECK(strcmp(st.state, "STOPPED") == 0);
        CHECK(strcmp(st.reason, "TIMEOUT") == 0);
    }

    /* After LINE_LOST */
    {
        TwinControlResult r;
        char f[96];
        twin_control_init(&k_baseline);
        twin_control_consume_pending_status(&st);
        make_frame(f, sizeof(f), "R,camp-001,run-001,START");
        CHECK(feed(f, &r) == 0U);
        twin_control_consume_pending_status(&st);
        CHECK(twin_control_report_line_lost(0U) == 0U);
        CHECK(twin_control_report_line_lost(1000U) == 1U);
        twin_control_consume_pending_status(&st);
        twin_control_queue_authoritative_status();
        CHECK(twin_control_consume_pending_status(&st) == 1U);
        CHECK(strcmp(st.state, "STOPPED") == 0);
        CHECK(strcmp(st.reason, "LINE_LOST") == 0);
    }
    return 0;
}

/* [2B-25] Authoritative state survives FIFO overflow */
static int test_authoritative_survives_fifo_overflow(void)
{
    TwinControlStatus st;
    TwinControlResult r;
    char f[96];
    unsigned int i;

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(f, sizeof(f), "R,camp-001,run-001,START");
    CHECK(feed(f, &r) == 0U);
    twin_control_consume_pending_status(&st);

    /* Overfill FIFO: send STOP (sets g_restore_baseline=1, queues event)
       then START which is correctly IGNORED because g_restore_baseline is 1.
       Only STOP events go into the FIFO. */
    for (i = 0U; i < 5U; i++) {
        char b[32];
        sprintf(b, "R,camp-001,run-%03u,STOP", i);
        make_frame(f, sizeof(f), b);
        CHECK(feed(f, &r) == 0U);
        /* After STOP, g_restore_baseline=1 — START correctly does nothing */
        sprintf(b, "R,camp-001,run-%03u,START", i);
        make_frame(f, sizeof(f), b);
        CHECK(feed(f, &r) == 0U);
    }

    /* Even though FIFO overflowed, authoritative cache has the last
       non-ignored state (STOPPED/STOP).  Motion IS inhibited. */
    CHECK(twin_control_motion_inhibited() == 1U);
    while (twin_control_consume_pending_status(&st));

    twin_control_queue_authoritative_status();
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "STOP") == 0);
    return 0;
}

/* [2B-26] FIFO full + non-safety event: safety event already inhibited motion,
   authoritative state still available on connect */
static int test_fifo_full_safety_still_inhibits(void)
{
    TwinControlStatus st;
    TwinControlResult r;
    char f[96];
    unsigned int i;

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(&st);
    make_frame(f, sizeof(f), "R,camp-001,run-001,START");
    CHECK(feed(f, &r) == 0U);
    twin_control_consume_pending_status(&st);
    CHECK(twin_control_motion_inhibited() == 0U);

    /* Overfill FIFO with STOP events (START correctly ignored when
       g_restore_baseline is 1).  Motion stays inhibited synchronously
       regardless of FIFO state. */
    for (i = 0U; i < 5U; i++) {
        char b[32];
        sprintf(b, "R,camp-001,run-%03u,STOP", i);
        make_frame(f, sizeof(f), b);
        CHECK(feed(f, &r) == 0U);
        /* START is correctly ignored: g_restore_baseline == 1 */
        sprintf(b, "R,camp-001,run-%03u,START", i);
        make_frame(f, sizeof(f), b);
        CHECK(feed(f, &r) == 0U);
    }
    /* Motion is still inhibited (all STARTs were correctly ignored) */
    CHECK(twin_control_motion_inhibited() == 1U);

    /* Another STOP: still inhibited, authoritative cache confirms STOPPED */
    make_frame(f, sizeof(f), "R,camp-001,run-099,STOP");
    CHECK(feed(f, &r) == 0U);
    CHECK(twin_control_motion_inhibited() == 1U); /* synchronous — no S event needed */

    /* Authoritative cache has STOPPED/STOP */
    while (twin_control_consume_pending_status(&st));
    twin_control_queue_authoritative_status();
    CHECK(twin_control_consume_pending_status(&st) == 1U);
    CHECK(strcmp(st.state, "STOPPED") == 0);
    CHECK(strcmp(st.reason, "STOP") == 0);
    return 0;
}

/* ===== End Task 2B New Tests ===== */

/* Existing tests (adapted: some need START before P) */

static int test_ack_encoder_contract(void)
{
    TwinControlResult result;
    char encoded[96];
    char expected[96];

    set_ack_result(&result, "camp-001", 2U, 1U, "APPLIED");
    make_frame(expected, sizeof(expected), "A,camp-001,2,APPLIED,APPLIED");
    CHECK(twin_control_encode_ack(&result, encoded, sizeof(encoded)) == strlen(expected));
    CHECK(strcmp(encoded, expected) == 0);

    CHECK(twin_control_encode_ack(&result, encoded, 33) == strlen(expected));

    CHECK(ack_failure_preserves_output(&result, 32));

    memset(&result, 0, sizeof(result));
    CHECK(ack_failure_preserves_output(&result, sizeof(encoded)));

    CHECK(twin_control_encode_ack(0, encoded, sizeof(encoded)) == 0U);

    set_ack_result(&result, "camp-001", 2U, 1U, "APPLIED");
    CHECK(twin_control_encode_ack(&result, 0, sizeof(encoded)) == 0U);

    CHECK(twin_control_encode_ack(0, 0, 0U) == 0U);
    return 0;
}

static int test_legal_parameter_applies_and_ack_encodes(void)
{
    TwinControlParams active;
    TwinControlResult result;
    char encoded[96];
    char expected[96];
    char start[96];

    twin_control_init(&k_baseline);
    /* Need START first */
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    CHECK(feed(start, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 0U);

    CHECK(queue_legal_candidate(&active, &result) == 0);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(result.has_ack == 1U && result.applied == 1U);
    CHECK(strcmp(result.campaign_id, "camp-001") == 0 && result.version == 2U);
    CHECK(active.kp == 40.0F && active.ki == 0.0F && active.kd == 10.0F && active.speed_max == 680);
    make_frame(expected, sizeof(expected), "A,camp-001,2,APPLIED,APPLIED");
    CHECK(twin_control_encode_ack(&result, encoded, sizeof(encoded)) == strlen(expected));
    CHECK(strcmp(encoded, expected) == 0);
    return 0;
}

static int test_status_encoder_matches_reference_vectors_and_capacity(void)
{
    TwinControlStatus status;
    char encoded[TWIN_CONTROL_LINE_MAX];
    char exact_capacity[48];
    char maximum[85];
    static const char expected[] =
        "S,camp-001,run-007,stopped,operator_stop,42,27\n";

    set_status(&status, "camp-001", "run-007", "stopped", "operator_stop", 42U);
    CHECK(twin_control_encode_status(&status, encoded, sizeof(encoded)) == strlen(expected));
    CHECK(strcmp(encoded, expected) == 0);
    CHECK(encoded[strlen(expected)] == '\0');
    CHECK(twin_control_encode_status(&status, exact_capacity, sizeof(exact_capacity)) ==
          strlen(expected));
    CHECK(strcmp(exact_capacity, expected) == 0);
    CHECK(status_failure_preserves_output(&status, (uint16_t)strlen(expected)));

    set_status(&status, "a", "b", "c", "d", 0U);
    CHECK(twin_control_encode_status(&status, encoded, sizeof(encoded)) == 15U);
    CHECK(strcmp(encoded, "S,a,b,c,d,0,4B\n") == 0);

    set_status(&status, "abcdefghijklmnop", "abcdefghijklmnop",
               "abcdefghijklmnop", "abcdefghijklmnop", 4294967295UL);
    CHECK(twin_control_encode_status(&status, maximum, sizeof(maximum)) == 84U);
    CHECK(maximum[84] == '\0');
    CHECK(status_failure_preserves_output(&status, 84U));
    return 0;
}

static int test_status_encoder_rejects_invalid_data_without_output_writes(void)
{
    TwinControlStatus status;

    set_status(&status, "camp-001", "run-007", "stopped", "operator_stop", 42U);
    status.campaign_id[0] = '\0';
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    set_status(&status, "camp-001", "run-007", "stopped", "operator_stop", 42U);
    status.run_id[0] = '\0';
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    set_status(&status, "camp-001", "run-007", "stopped", "operator_stop", 42U);
    status.state[0] = '\0';
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    set_status(&status, "camp-001", "run-007", "stopped", "operator_stop", 42U);
    status.reason[0] = '\0';
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    set_status(&status, "camp_001", "run-007", "stopped", "operator_stop", 42U);
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    set_status(&status, "camp-001", "run-007", "stopped", "operator_stop", 42U);
    status.run_id[0] = (char)-1;
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    set_status(&status, "camp-001", "run-007", "bad,state", "operator_stop", 42U);
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    set_status(&status, "camp-001", "run-007", "stopped", "bad\x1freason", 42U);
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    set_status(&status, "camp-001", "run-007", "bad\rstate", "operator_stop", 42U);
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    set_status(&status, "camp-001", "run-007", "stopped", "bad\nreason", 42U);
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    memset(status.reason, 'x', sizeof(status.reason));
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));

    memset(&status, 'x', sizeof(status));
    CHECK(status_failure_preserves_output(&status, TWIN_CONTROL_LINE_MAX));
    CHECK(twin_control_encode_status(0, 0, 0U) == 0U);
    return 0;
}

static int test_gain_and_speed_bounds_reject(void)
{
    const char *bodies[] = {
        "P,camp-001,2,19,0,10,680",
        "P,camp-001,2,35,-0.1,10,680",
        "P,camp-001,2,35,0,4,680",
        "P,camp-001,2,35,0,10,259",
        "P,camp-001,2,51,0,10,680",
        "P,camp-001,2,35,6,10,680",
        "P,camp-001,2,35,0,21,680",
        "P,camp-001,2,35,0,10,681"
    };
    unsigned int index;
    for (index = 0U; index < sizeof(bodies) / sizeof(bodies[0]); ++index) {
        TwinControlParams active = k_baseline;
        TwinControlResult result;
        char frame[96];
        char start[96];
        twin_control_init(&k_baseline);
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        feed(start, &result);
        make_frame(frame, sizeof(frame), bodies[index]);
        CHECK(feed(frame, &result) == 1U);
        CHECK(result.has_ack == 1U && result.applied == 0U);
        CHECK(strcmp(result.reason, "PARAM_BOUNDS") == 0);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
        CHECK(active_is_baseline(&active));
    }
    return 0;
}

static int test_step_checksum_crlf_and_overlong_frames_reject(void)
{
    TwinControlParams active;
    TwinControlResult result;
    char frame[128];
    char overlong[TWIN_CONTROL_LINE_MAX + 3U];
    unsigned char valid_frame_with_nul[96];
    unsigned int valid_frame_length;
    char start[96];
    static const unsigned char embedded_nul[] = {
        'P', ',', 'c', 'a', 'm', 'p', '-', '0', '0', '1', ',', '2', ',',
        '4', '0', ',', '0', ',', '1', '0', ',', '6', '8', '0', ',', '6',
        'A', 0x00U, 'X', '\n'
    };

    twin_control_init(&k_baseline);
    active = k_baseline;
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    feed(start, &result);
    /* Apply baseline first (so we have a baseline to step from) */
    twin_control_apply_pending(&active, &k_baseline, &result);

    make_frame(frame, sizeof(frame), "P,camp-001,2,41,0,10,680");
    CHECK(feed(frame, &result) == 1U);
    CHECK(strcmp(result.reason, "STEP_LIMIT") == 0);

    twin_control_init(&k_baseline);
    active = k_baseline;
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    feed(start, &result);
    /* Apply step from baseline; step is ok */
    make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);

    twin_control_init(&k_baseline);
    active = k_baseline;
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    feed(start, &result);
    make_frame(frame, sizeof(frame), "P,camp-001,2,35,0,10,680");
    frame[strlen(frame) - 3U] = '0';
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
    CHECK(active_is_baseline(&active));

    twin_control_init(&k_baseline);
    active = k_baseline;
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    feed(start, &result);
    make_frame(frame, sizeof(frame), "P,camp-001,2,35,0,10,680");
    frame[strlen(frame) - 1U] = '\0';
    strcat(frame, "\r\n");
    CHECK(feed(frame, &result) == 0U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
    CHECK(active_is_baseline(&active));

    memset(overlong, 'X', TWIN_CONTROL_LINE_MAX + 1U);
    overlong[TWIN_CONTROL_LINE_MAX + 1U] = '\n';
    overlong[TWIN_CONTROL_LINE_MAX + 2U] = '\0';
    CHECK(feed(overlong, &result) == 0U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);

    twin_control_init(&k_baseline);
    active = k_baseline;
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    feed(start, &result);
    CHECK(feed_bytes(embedded_nul, sizeof(embedded_nul), &result) == 0U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
    CHECK(active_is_baseline(&active));

    twin_control_init(&k_baseline);
    active = k_baseline;
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    feed(start, &result);
    make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
    valid_frame_length = (unsigned int)strlen(frame);
    memcpy(valid_frame_with_nul, frame, valid_frame_length - 1U);
    valid_frame_with_nul[valid_frame_length - 1U] = 0x00U;
    valid_frame_with_nul[valid_frame_length] = '\n';
    CHECK(feed_bytes(valid_frame_with_nul, valid_frame_length + 1U, &result) == 0U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
    CHECK(active_is_baseline(&active));
    return 0;
}

static int test_second_pending_parameter_is_rejected(void)
{
    TwinControlParams active;
    TwinControlResult result;
    char second[96];
    char start[96];

    twin_control_init(&k_baseline);
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    feed(start, &result);
    twin_control_apply_pending(&active, &k_baseline, &result); /* no pending — returns 0 */
    CHECK(twin_control_consume_controller_reset_flag() == 0U);

    twin_control_consume_pending_status(NULL); /* drain leftover status */

    CHECK(queue_legal_candidate(&active, &result) == 0);
    make_frame(second, sizeof(second), "P,camp-001,3,35,0,10,680");
    CHECK(feed(second, &result) == 1U);
    CHECK(result.has_ack == 1U && result.applied == 0U && result.version == 3U);
    CHECK(strcmp(result.reason, "PENDING") == 0);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(active.version == 2U && active.kp == 40.0F);
    return 0;
}

static int test_pending_parameters_are_rejected_by_rollback(void)
{
    const char *actions[] = { "STOP", "RESTORE_BASELINE", "TIMEOUT" };
    unsigned int index;
    for (index = 0U; index < sizeof(actions) / sizeof(actions[0]); ++index) {
        TwinControlParams active;
        TwinControlResult result;
        char rollback[96];
        char body[96];
        char start[96];

        twin_control_init(&k_baseline);
        twin_control_consume_pending_status(NULL); /* drain INIT */
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        feed(start, &result);
        twin_control_consume_pending_status(NULL); /* drain RUNNING */
        CHECK(twin_control_motion_inhibited() == 0U);
        CHECK(queue_legal_candidate(&active, &result) == 0);
        if (strcmp(actions[index], "TIMEOUT") == 0) {
            twin_control_timeout();
        } else {
            sprintf(body, "R,camp-001,run-001,%s", actions[index]);
            make_frame(rollback, sizeof(rollback), body);
            CHECK(feed(rollback, &result) == 0U);
        }
        CHECK(twin_control_motion_inhibited() == 1U);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(result.has_ack == 1U && result.applied == 0U);
        CHECK(strcmp(result.campaign_id, "camp-001") == 0 && result.version == 2U);
        CHECK(strcmp(result.reason, actions[index]) == 0);
        CHECK(result.motion_inhibited == 1U);
        CHECK(active_is_baseline(&active));
    }
    return 0;
}

static int test_stop_restore_and_timeout_rollback_then_start(void)
{
    const char *actions[] = { "STOP", "RESTORE_BASELINE" };
    unsigned int index;
    for (index = 0U; index < sizeof(actions) / sizeof(actions[0]); ++index) {
        TwinControlParams active;
        TwinControlResult result;
        char run[96];
        char body[96];
        char start[96];

        CHECK(apply_legal_candidate(&active, &result) == 0);
        twin_control_consume_pending_status(NULL); /* drain RUNNING from START */

        sprintf(body, "R,camp-001,run-001,%s", actions[index]);
        make_frame(run, sizeof(run), body);
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        CHECK(feed(run, &result) == 0U);
        CHECK(twin_control_motion_inhibited() == 1U);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(result.has_ack == 0U);
        CHECK(active_is_baseline(&active));
        CHECK(twin_control_motion_inhibited() == 1U);
        CHECK(feed(start, &result) == 0U);
        CHECK(twin_control_motion_inhibited() == 0U);
        CHECK(active_is_baseline(&active));
    }

    {
        TwinControlParams active;
        TwinControlResult result;
        char start[96];
        CHECK(apply_legal_candidate(&active, &result) == 0);
        twin_control_consume_pending_status(NULL);
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        twin_control_timeout();
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(result.has_ack == 0U);
        CHECK(active_is_baseline(&active));
        CHECK(twin_control_motion_inhibited() == 1U);
        CHECK(feed(start, &result) == 0U);
        CHECK(twin_control_motion_inhibited() == 0U);
        CHECK(active_is_baseline(&active));
    }
    return 0;
}

static int test_start_cannot_bypass_or_corrupt_rollback(void)
{
    TwinControlParams active;
    TwinControlResult result;
    char stop[96];
    char start[96];
    char malformed[96];

    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(NULL);

    CHECK(apply_legal_candidate(&active, &result) == 0);
    twin_control_consume_pending_status(NULL);

    make_frame(stop, sizeof(stop), "R,camp-001,run-001,STOP");
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    CHECK(feed(stop, &result) == 0U);
    /* drain STOPPED status (don't check return — NULL always returns 0) */
    { TwinControlStatus _st; twin_control_consume_pending_status(&_st); }

    /* START while rollback pending — must be ignored */
    CHECK(feed(start, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(active_is_baseline(&active));
    CHECK(twin_control_motion_inhibited() == 1U);

    /* drain any status from restore + apply */
    { TwinControlStatus _st; twin_control_consume_pending_status(&_st); }
    /* Actually after apply_pending of restore, motion was still inhibited.
       Let's drain any pending status: */
    twin_control_consume_pending_status(NULL);
    start[strlen(start) - 3U] = '0';
    CHECK(feed(start, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);
    CHECK(active_is_baseline(&active));

    /* CR before LF on START */
    twin_control_init(&k_baseline);
    twin_control_consume_pending_status(NULL);
    active = k_baseline;
    make_frame(stop, sizeof(stop), "R,camp-001,run-001,STOP");
    CHECK(feed(stop, &result) == 0U);

    make_frame(malformed, sizeof(malformed), "R,camp-001,run-001,START");
    malformed[strlen(malformed) - 1U] = '\0';
    strcat(malformed, "\r\n");
    CHECK(feed(malformed, &result) == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);
    CHECK(active_is_baseline(&active));
    return 0;
}

static int test_version_overflow_does_not_become_a_parameter_update(void)
{
    const char *bodies[] = {
        "P,camp-001,4294967296,35,0,10,680",
        "P,camp-001,+2,35,0,10,680",
        "P,camp-001,02,35,0,10,680",
        "P,camp-001,2,35,0,10,+680"
    };
    unsigned int index;
    for (index = 0U; index < sizeof(bodies) / sizeof(bodies[0]); ++index) {
        TwinControlParams active = k_baseline;
        TwinControlResult result;
        char frame[128];
        char start[96];
        twin_control_init(&k_baseline);
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        feed(start, &result);
        make_frame(frame, sizeof(frame), bodies[index]);
        CHECK(feed(frame, &result) == 0U ||
              (result.has_ack == 1U && result.applied == 0U &&
               strcmp(result.reason, "PARAM_BOUNDS") == 0));
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
        CHECK(active_is_baseline(&active));
    }
    return 0;
}

static int test_ki_kd_speed_step_limits(void)
{
    char start[96];

    /* ki step: baseline 0, candidate 1.5, diff +1.5 > 1 -> rejected */
    {
        TwinControlParams active = k_baseline;
        TwinControlResult result;
        char frame[96];
        twin_control_init(&k_baseline);
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        feed(start, &result);
        twin_control_apply_pending(&active, &k_baseline, &result); /* apply baseline */
        make_frame(frame, sizeof(frame), "P,camp-001,2,35,1.5,10,680");
        CHECK(feed(frame, &result) == 1U);
        CHECK(strcmp(result.reason, "STEP_LIMIT") == 0);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
        CHECK(active_is_baseline(&active));
    }
    /* ki step: exactly +1.0 = step_max, must apply */
    {
        TwinControlParams active;
        TwinControlResult result;
        char frame[96];
        twin_control_init(&k_baseline);
        active = k_baseline;
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        feed(start, &result);
        twin_control_apply_pending(&active, &k_baseline, &result);
        make_frame(frame, sizeof(frame), "P,camp-001,2,35,1.0,10,680");
        CHECK(feed(frame, &result) == 0U);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(active.ki == 1.0F);
    }
    /* kd step: baseline 10, candidate 14, diff +4 > 3 -> rejected */
    {
        TwinControlParams active = k_baseline;
        TwinControlResult result;
        char frame[96];
        twin_control_init(&k_baseline);
        active = k_baseline;
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        feed(start, &result);
        twin_control_apply_pending(&active, &k_baseline, &result);
        make_frame(frame, sizeof(frame), "P,camp-001,2,35,0,14,680");
        CHECK(feed(frame, &result) == 1U);
        CHECK(strcmp(result.reason, "STEP_LIMIT") == 0);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
        CHECK(active_is_baseline(&active));
    }
    /* kd step: exactly +3.0 = step_max, must apply */
    {
        TwinControlParams active;
        TwinControlResult result;
        char frame[96];
        twin_control_init(&k_baseline);
        active = k_baseline;
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        feed(start, &result);
        twin_control_apply_pending(&active, &k_baseline, &result);
        make_frame(frame, sizeof(frame), "P,camp-001,2,35,0,13,680");
        CHECK(feed(frame, &result) == 0U);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(active.kd == 13.0F);
    }
    /* speed step: baseline 680, candidate 579, diff -101 < -100 -> rejected */
    {
        TwinControlParams active = k_baseline;
        TwinControlResult result;
        char frame[96];
        twin_control_init(&k_baseline);
        active = k_baseline;
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        feed(start, &result);
        twin_control_apply_pending(&active, &k_baseline, &result);
        make_frame(frame, sizeof(frame), "P,camp-001,2,35,0,10,579");
        CHECK(feed(frame, &result) == 1U);
        CHECK(strcmp(result.reason, "STEP_LIMIT") == 0);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
        CHECK(active_is_baseline(&active));
    }
    /* speed step: exactly -100 = step_max, must apply */
    {
        TwinControlParams active;
        TwinControlResult result;
        char frame[96];
        twin_control_init(&k_baseline);
        active = k_baseline;
        make_frame(start, sizeof(start), "R,camp-001,run-001,START");
        feed(start, &result);
        twin_control_apply_pending(&active, &k_baseline, &result);
        make_frame(frame, sizeof(frame), "P,camp-001,2,35,0,10,580");
        CHECK(feed(frame, &result) == 0U);
        CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
        CHECK(active.speed_max == 580);
    }
    return 0;
}

static int test_nul_killer(void)
{
    TwinControlParams active;
    TwinControlResult result;
    char frame[96];
    char start[96];
    unsigned char valid_frame_with_nul[96];
    unsigned int valid_frame_length;

    twin_control_init(&k_baseline);
    active = k_baseline;
    make_frame(start, sizeof(start), "R,camp-001,run-001,START");
    feed(start, &result);
    make_frame(frame, sizeof(frame), "P,camp-001,2,40,0,10,680");
    valid_frame_length = (unsigned int)strlen(frame);
    memcpy(valid_frame_with_nul, frame, valid_frame_length - 1U);
    valid_frame_with_nul[valid_frame_length - 1U] = 0x00U;
    valid_frame_with_nul[valid_frame_length] = '\n';
    CHECK(feed_bytes(valid_frame_with_nul, valid_frame_length + 1U, &result) == 0U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
    CHECK(active_is_baseline(&active));
    return 0;
}

static int run_all_tests(void)
{
    if (test_ack_encoder_contract()) return 1;
    if (test_legal_parameter_applies_and_ack_encodes()) return 1;
    if (test_status_encoder_matches_reference_vectors_and_capacity()) return 1;
    if (test_status_encoder_rejects_invalid_data_without_output_writes()) return 1;
    if (test_gain_and_speed_bounds_reject()) return 1;
    if (test_ki_kd_speed_step_limits()) return 1;
    if (test_step_checksum_crlf_and_overlong_frames_reject()) return 1;
    if (test_second_pending_parameter_is_rejected()) return 1;
    if (test_pending_parameters_are_rejected_by_rollback()) return 1;
    if (test_stop_restore_and_timeout_rollback_then_start()) return 1;
    if (test_start_cannot_bypass_or_corrupt_rollback()) return 1;
    if (test_version_overflow_does_not_become_a_parameter_update()) return 1;
    /* --- Task 2B safety tests --- */
    if (test_default_motion_inhibited()) return 1;
    if (test_init_produces_status()) return 1;
    if (test_start_uninhibits_and_queues_running()) return 1;
    if (test_stop_inhibits_and_queues_status()) return 1;
    if (test_restore_baseline_inhibits_and_queues_status()) return 1;
    if (test_timeout_inhibits_and_queues_status()) return 1;
    if (test_start_ignored_when_restore_pending()) return 1;
    if (test_controller_reset_flag_on_parameter_apply()) return 1;
    if (test_controller_reset_flag_on_rollback()) return 1;
    if (test_line_lost_within_threshold()) return 1;
    if (test_line_lost_exceeds_threshold()) return 1;
    if (test_line_found_resets_loss_timer()) return 1;
    if (test_killer_default_not_motion_allowed()) return 1;
    if (test_killer_corrupted_start_does_not_bypass()) return 1;
    if (test_killer_line_loss_threshold_constant()) return 1;
    if (test_killer_status_events_not_lost()) return 1;
    if (test_consume_pending_status_null()) return 1;
    if (test_fifo_preserves_multiple_events()) return 1;
    if (test_batch_start_then_stop()) return 1;
    if (test_batch_stop_then_restore()) return 1;
    if (test_batch_timeout_then_line_lost()) return 1;
    if (test_fifo_overflow_drops_oldest()) return 1;
    if (test_authoritative_state_cached()) return 1;
    if (test_authoritative_survives_fifo_overflow()) return 1;
    if (test_fifo_full_safety_still_inhibits()) return 1;
    /* FIFO tests replace the old overwrite test */
    /* --- end Task 2B --- */
    puts("PASS test_twin_control_protocol");
    return 0;
}

int main(int argc, char **argv)
{
    const char *selector = (argc > 1) ? argv[1] : "";
    int result;

    if (selector[0] == '\0') return run_all_tests();

    if (strcmp(selector, "all") == 0) result = run_all_tests();
    else if (strcmp(selector, "ack") == 0) result = test_ack_encoder_contract();
    else if (strcmp(selector, "bounds") == 0) result = test_gain_and_speed_bounds_reject();
    else if (strcmp(selector, "step") == 0) result = test_ki_kd_speed_step_limits();
    else if (strcmp(selector, "nul") == 0) result = test_nul_killer();
    else if (strcmp(selector, "rollback") == 0) result = test_pending_parameters_are_rejected_by_rollback();
    else if (strcmp(selector, "start") == 0) result = test_start_cannot_bypass_or_corrupt_rollback();
    /* Task 2B selectors */
    else if (strcmp(selector, "inhibit") == 0) result = test_default_motion_inhibited();
    else if (strcmp(selector, "line_lost") == 0) result = test_line_lost_exceeds_threshold();
    else if (strcmp(selector, "reset_flag") == 0) result = test_controller_reset_flag_on_rollback();
    else if (strcmp(selector, "status") == 0) result = test_init_produces_status();
    else if (strcmp(selector, "killer") == 0) {
        result = test_killer_default_not_motion_allowed();
        if (result) return result;
        result = test_killer_corrupted_start_does_not_bypass();
        if (result) return result;
        result = test_killer_line_loss_threshold_constant();
        if (result) return result;
        result = test_killer_status_events_not_lost();
    } else {
        fprintf(stderr, "FAIL unknown selector: %s\n", selector);
        return 2;
    }
    if (result) {
        fprintf(stderr, "FAIL %s\n", selector);
        return 1;
    }
    printf("PASS %s\n", selector);
    return 0;
}
