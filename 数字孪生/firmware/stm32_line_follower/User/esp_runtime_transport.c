#include "esp_runtime_transport.h"
#include <string.h>

static IpdParser s_parser;
static volatile uint8_t *s_tcp_connected;
static volatile uint8_t *s_client_id;
static char s_pending_ack[TWIN_CONTROL_LINE_MAX + 1U];
static uint16_t s_pending_ack_len;
static char s_pending_status[TWIN_CONTROL_LINE_MAX + 1U];
static uint16_t s_pending_status_len;
static TwinControlClockSync s_pending_clock_sync;
static uint8_t s_has_pending_clock_sync;
static uint8_t s_clock_sync_event;
static uint8_t s_disconnect_event;
static uint32_t s_now_ms;
static char s_at_line[32];
static uint8_t s_at_line_len;

/* 连接代次：每次 CONNECT 递增。跨代次的 pending/retry 帧不得互相泄漏
   （Task 4B-4 fix, Codex review remediation）。 */
static uint32_t s_connection_generation;

static void clear_pending_frames(void)
{
    s_pending_ack_len = 0U;
    s_pending_status_len = 0U;
    memset(&s_pending_clock_sync, 0, sizeof(s_pending_clock_sync));
    s_has_pending_clock_sync = 0U;
    s_clock_sync_event = 0U;
    s_now_ms = 0U;
}

static void process_at_line(void)
{
    if (s_at_line_len < 2U) return;
    uint8_t id = (uint8_t)(s_at_line[0] - '0');
    if (id > 4U) return;
    if (strstr(s_at_line + 2, "CONNECT") != 0) {
        /* 新连接代次：丢弃任何旧客户端遗留的 pending ACK/STATUS，
           协议层随后会为新连接生成 authoritative status。 */
        s_connection_generation++;
        clear_pending_frames();
        *s_client_id = id;
        *s_tcp_connected = 1U;
    } else if (strstr(s_at_line + 2, "CLOSED") != 0) {
        if (*s_client_id == id) {
            /* Safety: transitioning from connected to disconnected.
               Stop motors, request baseline restore, and queue TIMEOUT
               event.  Must happen in the same main-loop iteration as
               the CLOSED byte, before any PID/MotorOut path. */
            if (*s_tcp_connected) {
                twin_control_timeout();
            }
            *s_tcp_connected = 0U;
            *s_client_id = 0xFF;
            /* 连接已断：transport 内部 pending 帧不再有效。 */
            clear_pending_frames();
            s_disconnect_event = 1U;
        }
    }
}

void esp_transport_init(volatile uint8_t *tcp_connected_flag,
                         volatile uint8_t *tcp_client_id_ptr)
{
    ipd_parser_init(&s_parser);
    s_tcp_connected = tcp_connected_flag;
    s_client_id = tcp_client_id_ptr;
    s_pending_ack_len = 0U;
    s_pending_status_len = 0U;
    memset(&s_pending_clock_sync, 0, sizeof(s_pending_clock_sync));
    s_has_pending_clock_sync = 0U;
    s_clock_sync_event = 0U;
    s_disconnect_event = 0U;
    s_now_ms = 0U;
    s_at_line_len = 0U;
    s_connection_generation = 0U;
}

void esp_transport_process_byte(uint8_t byte)
{
    esp_transport_process_byte_at(byte, s_now_ms, 0U, s_now_ms);
}

void esp_transport_process_byte_at(uint8_t byte, uint32_t uart_rx_tick_ms,
                                   uint8_t uart_rx_timestamp_valid,
                                   uint32_t parse_observed_tick_ms)
{
    uint8_t ipd_state = ipd_parser_feed(&s_parser, byte);
    if (ipd_state == IPD_STATE_PAYLOAD || ipd_state == IPD_STATE_COMPLETE) {
        TwinControlResult result;
        TwinControlClockSync clock_sync;
        uint8_t has_result = twin_control_receive_byte_timed(
            byte, uart_rx_tick_ms, uart_rx_timestamp_valid,
            parse_observed_tick_ms, &result, &clock_sync);
        if (clock_sync.has_reply) {
            (void)esp_transport_queue_clock_sync(&clock_sync);
        }
        if (has_result && result.has_ack) {
            s_pending_ack_len = twin_control_encode_ack(
                &result, s_pending_ack, sizeof(s_pending_ack));
        }
        return;
    }
    if (byte == '\n') {
        if (s_at_line_len > 0U) process_at_line();
        s_at_line_len = 0U;
    } else if (byte != '\r' && byte != '>') {
        /* '>' 是 CIPSEND 提示符，不属于任何 AT 行；若让它进入 at_line，
           紧随其后的 "0,CLOSED"/"0,CONNECT" 会被当成脏行跳过，导致
           断连/连接事件漏检（Task 4B-4 fix, Codex review remediation）。 */
        if (s_at_line_len < sizeof(s_at_line) - 1U) {
            s_at_line[s_at_line_len++] = (char)byte;
            s_at_line[s_at_line_len] = '\0';
        }
    }
}

void esp_transport_set_now_ms(uint32_t now_ms)
{
    s_now_ms = now_ms;
}

uint8_t esp_transport_has_pending_ack(void)
{
    return (s_pending_ack_len > 0U) ? 1U : 0U;
}

uint8_t esp_transport_has_pending_status(void)
{
    return (s_pending_status_len > 0U) ? 1U : 0U;
}

uint8_t esp_transport_has_pending_clock_sync(void)
{
    return s_has_pending_clock_sync;
}

uint8_t esp_transport_take_clock_sync_event(void)
{
    uint8_t event = s_clock_sync_event;
    s_clock_sync_event = 0U;
    return event;
}

uint8_t esp_transport_take_disconnect_event(void)
{
    uint8_t event = s_disconnect_event;
    s_disconnect_event = 0U;
    return event;
}

uint8_t esp_transport_peek_pending_clock_sync(TwinControlClockSync *output)
{
    if (!s_has_pending_clock_sync || output == 0) return 0U;
    *output = s_pending_clock_sync;
    return 1U;
}

void esp_transport_consume_pending_clock_sync(void)
{
    memset(&s_pending_clock_sync, 0, sizeof(s_pending_clock_sync));
    s_has_pending_clock_sync = 0U;
}

uint8_t esp_transport_can_queue_status(void)
{
    return (s_pending_status_len == 0U) ? 1U : 0U;
}

uint16_t esp_transport_get_pending_ack(char *output, uint16_t output_size)
{
    if (s_pending_ack_len == 0U || output == 0 || output_size == 0U) return 0U;
    uint16_t copy_len = s_pending_ack_len;
    if (copy_len >= output_size) copy_len = output_size - 1U;
    memcpy(output, s_pending_ack, copy_len);
    output[copy_len] = '\0';
    s_pending_ack_len = 0U;
    return copy_len;
}

uint16_t esp_transport_get_pending_status(char *output, uint16_t output_size)
{
    if (s_pending_status_len == 0U || output == 0 || output_size == 0U) return 0U;
    uint16_t copy_len = s_pending_status_len;
    if (copy_len >= output_size) copy_len = output_size - 1U;
    memcpy(output, s_pending_status, copy_len);
    output[copy_len] = '\0';
    s_pending_status_len = 0U;
    return copy_len;
}

uint8_t esp_transport_queue_clock_sync(const TwinControlClockSync *clock_sync)
{
    if (clock_sync == 0 || !clock_sync->has_reply ||
        s_has_pending_clock_sync) return 0U;
    s_pending_clock_sync = *clock_sync;
    s_has_pending_clock_sync = 1U;
    s_clock_sync_event = 1U;
    return 1U;
}

void esp_clock_quiet_init(EspClockQuietWindow *window)
{
    if (window == 0) return;
    window->until_ms = 0U;
    window->armed = 0U;
}

void esp_clock_quiet_arm(EspClockQuietWindow *window, uint32_t now_ms)
{
    if (window == 0) return;
    window->until_ms = now_ms + ESP_CLOCK_QUIET_WINDOW_MS;
    window->armed = 1U;
}

uint8_t esp_clock_quiet_active(EspClockQuietWindow *window, uint32_t now_ms)
{
    if (window == 0 || !window->armed) return 0U;
    if ((int32_t)(now_ms - window->until_ms) >= 0) {
        window->armed = 0U;
        return 0U;
    }
    return 1U;
}

void esp_clock_quiet_reset(EspClockQuietWindow *window)
{
    esp_clock_quiet_init(window);
}

uint16_t esp_transport_get_pending_clock_sync(char *output,
                                               uint16_t output_size,
                                               uint32_t t_transaction_started_tick_ms)
{
    uint16_t length;
    if (!s_has_pending_clock_sync || output == 0 || output_size == 0U) return 0U;
    length = twin_control_encode_clock_sync(&s_pending_clock_sync,
                                            t_transaction_started_tick_ms,
                                            output, output_size);
    if (length > 0U) {
        esp_transport_consume_pending_clock_sync();
    }
    return length;
}

void esp_transport_queue_status(const TwinControlStatus *status)
{
    s_pending_status_len = twin_control_encode_status(
        status, s_pending_status, sizeof(s_pending_status));
}

void esp_transport_queue_ack(const TwinControlResult *result)
{
    s_pending_ack_len = twin_control_encode_ack(
        result, s_pending_ack, sizeof(s_pending_ack));
}

uint8_t esp_transport_apply_and_ack(TwinControlParams *active,
                                     const TwinControlParams *baseline)
{
    TwinControlResult result;
    uint8_t applied = twin_control_apply_pending(active, baseline, &result);
    if (applied && result.has_ack) {
        esp_transport_queue_ack(&result);
    }
    return applied;
}

uint32_t esp_transport_connection_generation(void)
{
    return s_connection_generation;
}
