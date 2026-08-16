#include "esp_runtime_transport.h"
#include "esp_at_diagnostic.h"
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
static uint8_t s_pending_clock_sync_link_id;
static uint8_t s_clock_sync_udp_connected;
static uint32_t s_now_ms;
static char s_at_line[32];
static uint8_t s_at_line_len;
static EspAtDiagnostic s_at_diagnostic;
static uint8_t s_ipd_prefix_len;
static uint8_t s_ipd_prefix_suppressed;
static uint8_t s_ipd_payload_link_id;
static uint8_t s_ipd_payload_route;
static uint16_t s_ipd_payload_length;
static uint8_t s_ipd_payload_active;
static uint8_t s_udp_q_candidate;
volatile EspTransportDiagnosticSnapshot
    g_esp_transport_diagnostic_snapshot;

#define s_transport_diagnostic g_esp_transport_diagnostic_snapshot

static const uint8_t s_ipd_prefix[] = { '+', 'I', 'P', 'D', ',' };

/* 连接代次：每次 CONNECT 递增。跨代次的 pending/retry 帧不得互相泄漏
   （Task 4B-4 fix, Codex review remediation）。 */
static uint32_t s_connection_generation;

#define IPD_PAYLOAD_ROUTE_UNKNOWN 0U
#define IPD_PAYLOAD_ROUTE_CONTROL 1U
#define IPD_PAYLOAD_ROUTE_DROP    2U

static uint8_t esp_transport_queue_clock_sync_from_ipd(
    const TwinControlClockSync *clock_sync, uint8_t source_link_id,
    uint16_t ipd_length);

static void transport_diagnostic_event(uint8_t event_code,
                                       uint8_t link_id,
                                       uint32_t sequence,
                                       uint16_t ipd_length)
{
    s_transport_diagnostic.last_event_code = event_code;
    s_transport_diagnostic.last_link_id = link_id;
    s_transport_diagnostic.last_sequence = sequence;
    s_transport_diagnostic.last_ipd_length = ipd_length;
    s_transport_diagnostic.last_event_tick_ms = s_now_ms;
}

static void transport_diagnostic_reset(void)
{
    memset((void *)&s_transport_diagnostic, 0, sizeof(s_transport_diagnostic));
    s_transport_diagnostic.last_event_code = ESP_TRANSPORT_EVENT_NONE;
    s_transport_diagnostic.last_link_id = 0xFFU;
}

static uint8_t transport_diagnostic_is_udp_link(uint8_t link_id)
{
    return (link_id == ESP_CLOCK_SYNC_UDP_LINK_ID) ? 1U : 0U;
}

static uint8_t transport_diagnostic_is_udp_payload(void)
{
    return (s_ipd_payload_active &&
            transport_diagnostic_is_udp_link(s_ipd_payload_link_id)) ? 1U : 0U;
}

static void clear_pending_clock_sync(void)
{
    memset(&s_pending_clock_sync, 0, sizeof(s_pending_clock_sync));
    s_has_pending_clock_sync = 0U;
    s_clock_sync_event = 0U;
    s_pending_clock_sync_link_id = 0xFFU;
}

static void clear_pending_frames(uint8_t preserve_udp_clock_sync)
{
    s_pending_ack_len = 0U;
    s_pending_status_len = 0U;
    if (!preserve_udp_clock_sync ||
        !s_has_pending_clock_sync ||
        s_pending_clock_sync_link_id != ESP_CLOCK_SYNC_UDP_LINK_ID) {
        clear_pending_clock_sync();
    }
    s_now_ms = 0U;
    s_ipd_prefix_len = 0U;
    s_ipd_prefix_suppressed = 0U;
    s_ipd_payload_link_id = 0xFFU;
    s_ipd_payload_route = IPD_PAYLOAD_ROUTE_UNKNOWN;
    s_ipd_payload_length = 0U;
    s_ipd_payload_active = 0U;
    s_udp_q_candidate = 0U;
    esp_at_diagnostic_init(&s_at_diagnostic);
}

static void feed_at_response_byte(uint8_t byte)
{
    esp_at_diagnostic_feed_response_byte(&s_at_diagnostic, byte);
}

static void observe_non_ipd_byte(uint8_t byte, uint8_t prior_ipd_state)
{
    uint8_t i;

    if (s_ipd_prefix_suppressed) return;
    if (prior_ipd_state == IPD_STATE_HEADER ||
        prior_ipd_state == IPD_STATE_PAYLOAD) return;

    if (s_ipd_prefix_len > 0U) {
        if (s_ipd_prefix_len < (uint8_t)sizeof(s_ipd_prefix) &&
            byte == s_ipd_prefix[s_ipd_prefix_len]) {
            s_ipd_prefix_len++;
            if (s_ipd_prefix_len == (uint8_t)sizeof(s_ipd_prefix)) {
                s_ipd_prefix_len = 0U;
                s_ipd_prefix_suppressed = 1U;
            }
            return;
        }
        for (i = 0U; i < s_ipd_prefix_len; ++i) {
            feed_at_response_byte(s_ipd_prefix[i]);
        }
        s_ipd_prefix_len = 0U;
    }

    if (byte == '+' && prior_ipd_state != IPD_STATE_HEADER &&
        prior_ipd_state != IPD_STATE_PAYLOAD &&
        prior_ipd_state != IPD_STATE_COMPLETE) {
        s_ipd_prefix_len = 1U;
        return;
    }
    feed_at_response_byte(byte);
}

static void finish_non_ipd_observation(uint8_t ipd_state)
{
    if (s_ipd_prefix_suppressed &&
        (ipd_state == IPD_STATE_COMPLETE || ipd_state == IPD_STATE_ERROR)) {
        s_ipd_prefix_suppressed = 0U;
    }
}

static void process_at_line(void)
{
    if (s_at_line_len < 2U) return;
    uint8_t id = (uint8_t)(s_at_line[0] - '0');
    if (id > 4U) return;
    if (strstr(s_at_line + 2, "CONNECT") != 0) {
        if (id == ESP_CLOCK_SYNC_UDP_LINK_ID) {
            s_clock_sync_udp_connected = 1U;
            return;
        }
        /* 新连接代次：丢弃任何旧客户端遗留的 pending ACK/STATUS，
           协议层随后会为新连接生成 authoritative status。 */
        s_connection_generation++;
        clear_pending_frames(1U);
        *s_client_id = id;
        *s_tcp_connected = 1U;
    } else if (strstr(s_at_line + 2, "CLOSED") != 0) {
        if (id == ESP_CLOCK_SYNC_UDP_LINK_ID) {
            s_clock_sync_udp_connected = 0U;
            if (s_has_pending_clock_sync &&
                s_pending_clock_sync_link_id == ESP_CLOCK_SYNC_UDP_LINK_ID) {
                memset(&s_pending_clock_sync, 0,
                       sizeof(s_pending_clock_sync));
                s_has_pending_clock_sync = 0U;
                s_clock_sync_event = 0U;
                s_pending_clock_sync_link_id = 0xFFU;
            }
            return;
        }
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
            clear_pending_frames(1U);
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
    s_pending_clock_sync_link_id = 0xFFU;
    s_clock_sync_udp_connected = 0U;
    s_now_ms = 0U;
    s_at_line_len = 0U;
    s_ipd_prefix_len = 0U;
    s_ipd_prefix_suppressed = 0U;
    s_ipd_payload_link_id = 0xFFU;
    s_ipd_payload_route = IPD_PAYLOAD_ROUTE_UNKNOWN;
    s_ipd_payload_length = 0U;
    s_ipd_payload_active = 0U;
    s_udp_q_candidate = 0U;
    s_connection_generation = 0U;
    transport_diagnostic_reset();
    esp_at_diagnostic_init(&s_at_diagnostic);
}

uint8_t esp_transport_process_byte(uint8_t byte)
{
    uint8_t prior_ipd_state = s_parser.state;
    uint8_t ipd_state = ipd_parser_feed(&s_parser, byte);
    if (ipd_state == IPD_STATE_ERROR) {
        s_transport_diagnostic.ipd_error_count++;
        if (prior_ipd_state == IPD_STATE_HEADER) {
            s_transport_diagnostic.ipd_header_parse_error_count++;
            transport_diagnostic_event(
                ESP_TRANSPORT_EVENT_IPD_HEADER_PARSE_ERROR,
                0xFFU, 0U, 0U);
        } else {
            transport_diagnostic_event(ESP_TRANSPORT_EVENT_IPD_ERROR,
                                       0xFFU, 0U, 0U);
        }
        s_ipd_payload_active = 0U;
        s_udp_q_candidate = 0U;
    }
    if (ipd_state == IPD_STATE_HEADER ||
        (ipd_state == IPD_STATE_IDLE && s_parser.state == IPD_STATE_HEADER)) {
        /* Header bytes belong exclusively to ipd_parser.  Returning before
           the generic AT-line accumulator prevents "+IPD,...:" from being
           joined with the next CONNECT/CLOSED line. */
        if (s_parser.header_len == 0U) {
            /* The prefix observer has already seen '+IPD' and the parser
               consumes the completing comma on this byte.  Remove only that
               prefix from the AT-line scratch buffer before suppressing the
               rest of the header. */
            s_at_line_len = 0U;
            s_at_line[0] = '\0';
            s_transport_diagnostic.ipd_prefix_seen_count++;
            transport_diagnostic_event(
                ESP_TRANSPORT_EVENT_IPD_PREFIX_SEEN,
                0xFFU, 0U, 0U);
        }
        s_ipd_prefix_len = 0U;
        s_ipd_prefix_suppressed = 1U;
        if (s_parser.state == IPD_STATE_PAYLOAD) {
            s_ipd_payload_link_id = (uint8_t)ipd_parser_get_id(&s_parser);
            s_ipd_payload_length = (uint16_t)ipd_parser_get_length(&s_parser);
            s_ipd_payload_active = 1U;
            s_ipd_payload_route =
                (s_ipd_payload_link_id == ESP_CLOCK_SYNC_UDP_LINK_ID)
                ? IPD_PAYLOAD_ROUTE_UNKNOWN : IPD_PAYLOAD_ROUTE_CONTROL;
            s_udp_q_candidate = 0U;
            if (transport_diagnostic_is_udp_payload()) {
                s_transport_diagnostic.udp_ipd_header_accepted_count++;
                transport_diagnostic_event(
                    ESP_TRANSPORT_EVENT_IPD_HEADER_ACCEPTED,
                    s_ipd_payload_link_id, 0U, s_ipd_payload_length);
            }
        }
        return ipd_state;
    }
    if (ipd_state == IPD_STATE_PAYLOAD || ipd_state == IPD_STATE_COMPLETE) {
        TwinControlResult result;
        TwinControlClockSync clock_sync;
        uint8_t has_result = 0U;
        memset(&result, 0, sizeof(result));
        memset(&clock_sync, 0, sizeof(clock_sync));
        if (ipd_state == IPD_STATE_COMPLETE && !s_ipd_payload_active) {
            /* Zero-length +IPD frames complete on the header colon. */
            s_ipd_payload_link_id = (uint8_t)ipd_parser_get_id(&s_parser);
            s_ipd_payload_length = (uint16_t)ipd_parser_get_length(&s_parser);
            s_ipd_payload_active = 1U;
            s_ipd_payload_route =
                transport_diagnostic_is_udp_link(s_ipd_payload_link_id)
                ? IPD_PAYLOAD_ROUTE_UNKNOWN : IPD_PAYLOAD_ROUTE_CONTROL;
            s_udp_q_candidate = 0U;
            if (transport_diagnostic_is_udp_payload()) {
                s_transport_diagnostic.udp_ipd_header_accepted_count++;
                transport_diagnostic_event(
                    ESP_TRANSPORT_EVENT_IPD_HEADER_ACCEPTED,
                    s_ipd_payload_link_id, 0U, s_ipd_payload_length);
            }
        }
        if (ipd_state == IPD_STATE_COMPLETE &&
            transport_diagnostic_is_udp_payload()) {
            s_transport_diagnostic.udp_ipd_complete_count++;
            transport_diagnostic_event(
                ESP_TRANSPORT_EVENT_IPD_COMPLETE,
                s_ipd_payload_link_id, 0U, s_ipd_payload_length);
        }
        if (s_ipd_payload_route == IPD_PAYLOAD_ROUTE_UNKNOWN) {
            s_ipd_payload_route = (byte == (uint8_t)'Q')
                ? IPD_PAYLOAD_ROUTE_CONTROL : IPD_PAYLOAD_ROUTE_DROP;
            if (transport_diagnostic_is_udp_payload() && byte == (uint8_t)'Q') {
                s_udp_q_candidate = 1U;
                s_transport_diagnostic.udp_q_candidate_count++;
                transport_diagnostic_event(
                    ESP_TRANSPORT_EVENT_Q_CANDIDATE,
                    s_ipd_payload_link_id, 0U, s_ipd_payload_length);
            }
        }
        if (s_ipd_payload_route == IPD_PAYLOAD_ROUTE_CONTROL) {
            has_result = twin_control_receive_byte_at(
                byte, s_now_ms, &result, &clock_sync);
            if (clock_sync.has_reply) {
                if (transport_diagnostic_is_udp_payload()) {
                    s_transport_diagnostic.udp_q_parse_ok_count++;
                    transport_diagnostic_event(
                        ESP_TRANSPORT_EVENT_Q_PARSE_OK,
                        s_ipd_payload_link_id, clock_sync.sequence,
                        s_ipd_payload_length);
                }
                (void)esp_transport_queue_clock_sync_from_ipd(
                    &clock_sync, s_ipd_payload_link_id,
                    s_ipd_payload_length);
            }
            if (s_ipd_payload_link_id != ESP_CLOCK_SYNC_UDP_LINK_ID) {
                (void)esp_at_diagnostic_feed_request_byte(
                    &s_at_diagnostic, byte);
            }
        }
        if (ipd_state == IPD_STATE_COMPLETE &&
            transport_diagnostic_is_udp_payload() && s_udp_q_candidate) {
            if (!clock_sync.has_reply) {
                s_transport_diagnostic.udp_q_parse_reject_count++;
                transport_diagnostic_event(
                    ESP_TRANSPORT_EVENT_Q_PARSE_REJECT,
                    s_ipd_payload_link_id, 0U, s_ipd_payload_length);
            }
        }
        finish_non_ipd_observation(ipd_state);
        if (has_result && result.has_ack) {
            s_pending_ack_len = twin_control_encode_ack(
                &result, s_pending_ack, sizeof(s_pending_ack));
        }
        if (ipd_state == IPD_STATE_COMPLETE) {
            s_ipd_payload_active = 0U;
            s_udp_q_candidate = 0U;
        }
        return ipd_state;
    }
    observe_non_ipd_byte(byte, prior_ipd_state);
    finish_non_ipd_observation(ipd_state);
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
    return ipd_state;
}

void esp_transport_get_diagnostic(EspTransportDiagnosticSnapshot *output)
{
    if (output == 0) return;
    *output = s_transport_diagnostic;
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

uint8_t esp_transport_clock_sync_udp_connected(void)
{
    return s_clock_sync_udp_connected;
}

uint8_t esp_transport_pending_clock_sync_link_id(uint8_t *link_id)
{
    if (!s_has_pending_clock_sync || link_id == 0) return 0U;
    *link_id = s_pending_clock_sync_link_id;
    return 1U;
}

uint8_t esp_transport_pending_clock_sync_sendable(void)
{
    if (!s_has_pending_clock_sync) return 0U;
    if (s_pending_clock_sync_link_id == ESP_CLOCK_SYNC_UDP_LINK_ID) {
        /* A received UDP Q is the transport-local proof that link 4 can
           accept the matching response.  UDP does not require a TCP-style
           CONNECT event to authorize the CIPSEND transaction. */
        return 1U;
    }
    if (s_tcp_connected == 0 || s_client_id == 0) return 0U;
    return (*s_tcp_connected &&
            *s_client_id == s_pending_clock_sync_link_id) ? 1U : 0U;
}

uint8_t esp_transport_take_clock_sync_event(void)
{
    uint8_t event = s_clock_sync_event;
    s_clock_sync_event = 0U;
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
    s_pending_clock_sync_link_id = 0xFFU;
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

static uint8_t queue_clock_sync_pending(
    const TwinControlClockSync *clock_sync, uint8_t source_link_id)
{
    if (clock_sync == 0 || !clock_sync->has_reply) return 0U;
    if (s_has_pending_clock_sync) return 0U;
    s_pending_clock_sync = *clock_sync;
    s_has_pending_clock_sync = 1U;
    s_pending_clock_sync_link_id = source_link_id;
    s_clock_sync_event = 1U;
    return 1U;
}

static uint8_t esp_transport_queue_clock_sync_from_ipd(
    const TwinControlClockSync *clock_sync, uint8_t source_link_id,
    uint16_t ipd_length)
{
    uint8_t accepted = queue_clock_sync_pending(clock_sync, source_link_id);
    if (transport_diagnostic_is_udp_link(source_link_id)) {
        if (accepted) {
            s_transport_diagnostic.clock_queue_accepted_count++;
            transport_diagnostic_event(
                ESP_TRANSPORT_EVENT_QUEUE_ACCEPTED, source_link_id,
                clock_sync->sequence, ipd_length);
        } else if (clock_sync != 0 && clock_sync->has_reply &&
                   s_has_pending_clock_sync) {
            s_transport_diagnostic.clock_queue_rejected_pending_count++;
            transport_diagnostic_event(
                ESP_TRANSPORT_EVENT_QUEUE_REJECTED_PENDING, source_link_id,
                clock_sync->sequence, ipd_length);
        }
    }
    return accepted;
}

uint8_t esp_transport_queue_clock_sync(const TwinControlClockSync *clock_sync)
{
    return queue_clock_sync_pending(clock_sync, 0xFFU);
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
                                              uint32_t mcu_tx_tick_ms)
{
    uint16_t length;
    if (!s_has_pending_clock_sync || output == 0 || output_size == 0U) return 0U;
    length = twin_control_encode_clock_sync(&s_pending_clock_sync,
                                            mcu_tx_tick_ms,
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

uint8_t esp_transport_diagnostic_request_ready(void)
{
    return esp_at_diagnostic_request_ready(&s_at_diagnostic);
}

uint8_t esp_transport_start_diagnostic(uint32_t now_ms,
                                       uint8_t connected,
                                       uint8_t motion_inhibited,
                                       uint8_t cipsend_idle,
                                       uint8_t critical_pending)
{
    return esp_at_diagnostic_start(&s_at_diagnostic, now_ms, connected,
                                   motion_inhibited, cipsend_idle,
                                   critical_pending);
}

uint8_t esp_transport_diagnostic_command(const char **command,
                                         uint16_t *length,
                                         const char **query_id)
{
    return esp_at_diagnostic_command(&s_at_diagnostic, command, length,
                                     query_id);
}

void esp_transport_diagnostic_mark_command_sent(uint32_t now_ms)
{
    esp_at_diagnostic_mark_command_sent_at(&s_at_diagnostic, now_ms);
}

void esp_transport_diagnostic_mark_command_byte_sent(uint32_t now_ms)
{
    esp_at_diagnostic_mark_command_byte_sent(&s_at_diagnostic, now_ms);
}

void esp_transport_diagnostic_feed_response_byte(uint8_t byte)
{
    esp_at_diagnostic_feed_response_byte(&s_at_diagnostic, byte);
}

void esp_transport_diagnostic_tick(uint32_t now_ms)
{
    esp_at_diagnostic_tick(&s_at_diagnostic, now_ms);
}

uint8_t esp_transport_diagnostic_response_ready(void)
{
    return esp_at_diagnostic_response_ready(&s_at_diagnostic);
}

uint16_t esp_transport_diagnostic_peek_response(char *output,
                                               uint16_t output_size)
{
    return esp_at_diagnostic_peek_response(&s_at_diagnostic, output,
                                           output_size);
}

void esp_transport_diagnostic_consume_response(void)
{
    esp_at_diagnostic_consume_response(&s_at_diagnostic);
}

uint8_t esp_transport_diagnostic_busy(void)
{
    return esp_at_diagnostic_busy(&s_at_diagnostic);
}
