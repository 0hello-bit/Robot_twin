/* Host C contract tests for the ClockSync-only UDP link boundary.
 *
 * The UDP link must share the existing IPD parser and CIPSEND state-machine
 * boundary without becoming a second control, telemetry, or health path.
 */

#include <stdio.h>
#include <string.h>

#include "esp_runtime_transport.h"

extern volatile EspTransportDiagnosticSnapshot
    g_esp_transport_diagnostic_snapshot;

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static const TwinControlParams k_baseline = {
    35.0F, 0.0F, 10.0F, 680, 1U, "baseline"
};

static volatile uint8_t s_tcp_connected;
static volatile uint8_t s_tcp_client_id;

static void feed_text(const char *text)
{
    while (*text != '\0') {
        esp_transport_process_byte((uint8_t)*text++);
    }
}

static void feed_ipd(uint8_t link_id, const char *body)
{
    char frame[160];
    uint8_t checksum = 0U;
    size_t i;

    for (i = 0U; i < strlen(body); ++i) {
        checksum ^= (uint8_t)body[i];
    }
    sprintf(frame, "+IPD,%u,%zu:%s,%02X\n", (unsigned)link_id,
            strlen(body) + 4U, body, (unsigned)checksum);
    feed_text(frame);
}

static int test_udp_boundary_events_are_recorded(void)
{
    EspTransportDiagnosticSnapshot diagnostic;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);
    esp_transport_set_now_ms(1234U);

    feed_ipd(ESP_CLOCK_SYNC_UDP_LINK_ID, "Q,17");
    esp_transport_get_diagnostic(&diagnostic);

    CHECK(diagnostic.ipd_prefix_seen_count == 1U);
    CHECK(diagnostic.ipd_header_parse_error_count == 0U);
    CHECK(diagnostic.udp_ipd_header_accepted_count == 1U);
    CHECK(diagnostic.udp_ipd_complete_count == 1U);
    CHECK(diagnostic.udp_q_candidate_count == 1U);
    CHECK(diagnostic.udp_q_parse_ok_count == 1U);
    CHECK(diagnostic.udp_q_parse_reject_count == 0U);
    CHECK(diagnostic.clock_queue_accepted_count == 1U);
    CHECK(diagnostic.clock_queue_rejected_pending_count == 0U);
    CHECK(diagnostic.last_event_code == ESP_TRANSPORT_EVENT_QUEUE_ACCEPTED);
    CHECK(diagnostic.last_event_tick_ms == 1234U);
    CHECK(diagnostic.last_link_id == ESP_CLOCK_SYNC_UDP_LINK_ID);
    CHECK(diagnostic.last_sequence == 17U);
    CHECK(diagnostic.last_ipd_length == (uint16_t)(strlen("Q,17") + 4U));
    CHECK(g_esp_transport_diagnostic_snapshot.ipd_prefix_seen_count ==
          diagnostic.ipd_prefix_seen_count);
    CHECK(g_esp_transport_diagnostic_snapshot.clock_queue_accepted_count ==
          diagnostic.clock_queue_accepted_count);
    return 0;
}

static int test_udp_q_parse_reject_and_ipd_error_are_recorded(void)
{
    EspTransportDiagnosticSnapshot diagnostic;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);

    feed_ipd(ESP_CLOCK_SYNC_UDP_LINK_ID, "Q,0");
    esp_transport_get_diagnostic(&diagnostic);

    CHECK(diagnostic.ipd_prefix_seen_count == 1U);
    CHECK(diagnostic.ipd_header_parse_error_count == 0U);
    CHECK(diagnostic.udp_q_candidate_count == 1U);
    CHECK(diagnostic.udp_q_parse_ok_count == 0U);
    CHECK(diagnostic.udp_q_parse_reject_count == 1U);
    CHECK(diagnostic.clock_queue_accepted_count == 0U);
    CHECK(diagnostic.last_event_code == ESP_TRANSPORT_EVENT_Q_PARSE_REJECT);

    feed_text("+IPD,4,x:\n");
    esp_transport_get_diagnostic(&diagnostic);

    CHECK(diagnostic.ipd_prefix_seen_count == 2U);
    CHECK(diagnostic.ipd_header_parse_error_count == 1U);
    CHECK(diagnostic.udp_q_candidate_count == 1U);
    CHECK(diagnostic.udp_q_parse_ok_count == 0U);
    CHECK(diagnostic.udp_q_parse_reject_count == 1U);
    CHECK(diagnostic.clock_queue_accepted_count == 0U);
    CHECK(diagnostic.ipd_error_count == 1U);
    CHECK(diagnostic.last_event_code ==
          ESP_TRANSPORT_EVENT_IPD_HEADER_PARSE_ERROR);
    CHECK(diagnostic.last_link_id == 0xFFU);
    CHECK(diagnostic.last_sequence == 0U);
    return 0;
}

static int test_global_diagnostic_snapshot_resets_on_init(void)
{
    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);

    CHECK(g_esp_transport_diagnostic_snapshot.ipd_prefix_seen_count == 0U);
    CHECK(g_esp_transport_diagnostic_snapshot.ipd_header_parse_error_count ==
          0U);
    CHECK(g_esp_transport_diagnostic_snapshot.last_event_code ==
          ESP_TRANSPORT_EVENT_NONE);
    CHECK(g_esp_transport_diagnostic_snapshot.last_link_id == 0xFFU);
    return 0;
}

static int test_zero_length_ipd_records_prefix_and_completion(void)
{
    EspTransportDiagnosticSnapshot diagnostic;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);

    feed_text("+IPD,4,0:");
    esp_transport_get_diagnostic(&diagnostic);

    CHECK(diagnostic.ipd_prefix_seen_count == 1U);
    CHECK(diagnostic.ipd_header_parse_error_count == 0U);
    CHECK(diagnostic.udp_ipd_header_accepted_count == 1U);
    CHECK(diagnostic.udp_ipd_complete_count == 1U);
    CHECK(diagnostic.last_event_code == ESP_TRANSPORT_EVENT_IPD_COMPLETE);
    CHECK(diagnostic.last_link_id == ESP_CLOCK_SYNC_UDP_LINK_ID);
    CHECK(diagnostic.last_ipd_length == 0U);
    return 0;
}

static int test_udp_queue_reject_pending_is_recorded(void)
{
    EspTransportDiagnosticSnapshot diagnostic;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);

    feed_ipd(ESP_CLOCK_SYNC_UDP_LINK_ID, "Q,17");
    feed_ipd(ESP_CLOCK_SYNC_UDP_LINK_ID, "Q,18");
    esp_transport_get_diagnostic(&diagnostic);

    CHECK(diagnostic.udp_q_parse_ok_count == 2U);
    CHECK(diagnostic.clock_queue_accepted_count == 1U);
    CHECK(diagnostic.clock_queue_rejected_pending_count == 1U);
    CHECK(diagnostic.last_event_code ==
          ESP_TRANSPORT_EVENT_QUEUE_REJECTED_PENDING);
    CHECK(diagnostic.last_link_id == ESP_CLOCK_SYNC_UDP_LINK_ID);
    CHECK(diagnostic.last_sequence == 18U);
    return 0;
}

static int test_tcp_q_does_not_increment_udp_boundary_counters(void)
{
    EspTransportDiagnosticSnapshot diagnostic;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);

    feed_ipd(0U, "Q,19");
    esp_transport_get_diagnostic(&diagnostic);

    CHECK(diagnostic.udp_ipd_header_accepted_count == 0U);
    CHECK(diagnostic.udp_ipd_complete_count == 0U);
    CHECK(diagnostic.udp_q_candidate_count == 0U);
    CHECK(diagnostic.udp_q_parse_ok_count == 0U);
    CHECK(diagnostic.clock_queue_accepted_count == 0U);
    return 0;
}

static int test_tcp_ipd_error_is_not_attributed_to_udp(void)
{
    EspTransportDiagnosticSnapshot diagnostic;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);

    feed_text("+IPD,0,x:\n");
    esp_transport_get_diagnostic(&diagnostic);

    CHECK(diagnostic.udp_ipd_header_accepted_count == 0U);
    CHECK(diagnostic.udp_ipd_complete_count == 0U);
    CHECK(diagnostic.ipd_prefix_seen_count == 1U);
    CHECK(diagnostic.ipd_header_parse_error_count == 1U);
    CHECK(diagnostic.ipd_error_count == 1U);
    CHECK(diagnostic.udp_q_candidate_count == 0U);
    CHECK(diagnostic.udp_q_parse_ok_count == 0U);
    CHECK(diagnostic.udp_q_parse_reject_count == 0U);
    CHECK(diagnostic.clock_queue_accepted_count == 0U);
    CHECK(diagnostic.clock_queue_rejected_pending_count == 0U);
    CHECK(diagnostic.last_event_code ==
          ESP_TRANSPORT_EVENT_IPD_HEADER_PARSE_ERROR);
    CHECK(diagnostic.last_link_id == 0xFFU);
    return 0;
}

static int test_direct_queue_does_not_reuse_udp_context(void)
{
    TwinControlClockSync clock_sync;
    EspTransportDiagnosticSnapshot diagnostic;
    uint8_t link_id = 0U;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);
    memset(&clock_sync, 0, sizeof(clock_sync));
    clock_sync.has_reply = 1U;
    clock_sync.sequence = 21U;

    CHECK(esp_transport_queue_clock_sync(&clock_sync) == 1U);
    CHECK(esp_transport_pending_clock_sync_link_id(&link_id) == 1U);
    CHECK(link_id == 0xFFU);
    esp_transport_get_diagnostic(&diagnostic);
    CHECK(diagnostic.clock_queue_accepted_count == 0U);
    CHECK(diagnostic.clock_queue_rejected_pending_count == 0U);
    return 0;
}

static int test_udp_connect_does_not_replace_tcp_session(void)
{
    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);

    feed_text("4,CONNECT\r\n");

    CHECK(s_tcp_connected == 0U);
    CHECK(s_tcp_client_id == 0xFFU);
    CHECK(esp_transport_clock_sync_udp_connected() == 1U);
    CHECK(esp_transport_connection_generation() == 0U);
    return 0;
}

static int test_udp_q_remembers_source_link(void)
{
    TwinControlClockSync clock_sync;
    uint8_t link_id = 0xFFU;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);
    feed_text("4,CONNECT\r\n");
    feed_ipd(4U, "Q,17");

    CHECK(esp_transport_has_pending_clock_sync() == 1U);
    CHECK(esp_transport_pending_clock_sync_link_id(&link_id) == 1U);
    CHECK(link_id == ESP_CLOCK_SYNC_UDP_LINK_ID);
    CHECK(esp_transport_peek_pending_clock_sync(&clock_sync) == 1U);
    CHECK(clock_sync.sequence == 17U);
    CHECK(esp_transport_pending_clock_sync_sendable() == 1U);
    return 0;
}

static int test_udp_q_is_sendable_without_observed_connect_event(void)
{
    TwinControlClockSync clock_sync;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);
    /* A UDP datagram can arrive even when setup-phase CONNECT was not
       observed by the STM32 parser.  The received Q proves link 4 reached
       the firmware and should permit the matching CIPSEND attempt. */
    feed_ipd(4U, "Q,171");

    CHECK(esp_transport_peek_pending_clock_sync(&clock_sync) == 1U);
    CHECK(clock_sync.sequence == 171U);
    CHECK(esp_transport_pending_clock_sync_sendable() == 1U);
    return 0;
}

static int test_udp_non_clock_payload_does_not_enter_control_parser(void)
{
    TwinControlParams active = k_baseline;
    TwinControlResult result;

    twin_control_init(&k_baseline);
    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);
    feed_text("4,CONNECT\r\n");
    feed_ipd(4U, "P,camp-001,2,40,0,10,680");

    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 0U);
    CHECK(active.kp == k_baseline.kp);
    CHECK(esp_transport_diagnostic_request_ready() == 0U);
    return 0;
}

static int test_tcp_q_keeps_tcp_source_and_tcp_connect_behavior(void)
{
    TwinControlClockSync clock_sync;
    uint8_t link_id = 0xFFU;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);
    feed_text("0,CONNECT\r\n");
    feed_ipd(0U, "Q,18");

    CHECK(s_tcp_connected == 1U);
    CHECK(s_tcp_client_id == 0U);
    CHECK(esp_transport_pending_clock_sync_link_id(&link_id) == 1U);
    CHECK(link_id == 0U);
    CHECK(esp_transport_peek_pending_clock_sync(&clock_sync) == 1U);
    CHECK(clock_sync.sequence == 18U);
    return 0;
}

static int test_tcp_connection_events_preserve_udp_clock_sync_pending(void)
{
    TwinControlClockSync clock_sync;
    uint8_t link_id = 0xFFU;

    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);

    feed_text("4,CONNECT\r\n");
    feed_ipd(4U, "Q,19");
    CHECK(esp_transport_has_pending_clock_sync() == 1U);
    CHECK(esp_transport_clock_sync_udp_connected() == 1U);

    feed_text("0,CONNECT\r\n");
    CHECK(s_tcp_connected == 1U);
    CHECK(esp_transport_clock_sync_udp_connected() == 1U);
    CHECK(esp_transport_pending_clock_sync_link_id(&link_id) == 1U);
    CHECK(link_id == ESP_CLOCK_SYNC_UDP_LINK_ID);
    CHECK(esp_transport_peek_pending_clock_sync(&clock_sync) == 1U);
    CHECK(clock_sync.sequence == 19U);

    feed_text("0,CLOSED\r\n");
    CHECK(s_tcp_connected == 0U);
    CHECK(esp_transport_clock_sync_udp_connected() == 1U);
    CHECK(esp_transport_peek_pending_clock_sync(&clock_sync) == 1U);
    CHECK(clock_sync.sequence == 19U);
    return 0;
}

static int test_udp_closed_does_not_stop_active_tcp_control_session(void)
{
    s_tcp_connected = 0U;
    s_tcp_client_id = 0xFFU;
    twin_control_init(&k_baseline);
    esp_transport_init(&s_tcp_connected, &s_tcp_client_id);

    feed_text("4,CONNECT\r\n");
    feed_text("0,CONNECT\r\n");
    feed_ipd(0U, "R,camp-001,run-001,START");
    CHECK(twin_control_motion_inhibited() == 0U);

    feed_text("4,CLOSED\r\n");

    CHECK(s_tcp_connected == 1U);
    CHECK(s_tcp_client_id == 0U);
    CHECK(twin_control_motion_inhibited() == 0U);
    CHECK(esp_transport_clock_sync_udp_connected() == 0U);
    return 0;
}

int main(void)
{
    if (test_global_diagnostic_snapshot_resets_on_init()) return 1;
    if (test_zero_length_ipd_records_prefix_and_completion()) return 1;
    if (test_udp_boundary_events_are_recorded()) return 1;
    if (test_udp_q_parse_reject_and_ipd_error_are_recorded()) return 1;
    if (test_udp_queue_reject_pending_is_recorded()) return 1;
    if (test_tcp_q_does_not_increment_udp_boundary_counters()) return 1;
    if (test_tcp_ipd_error_is_not_attributed_to_udp()) return 1;
    if (test_direct_queue_does_not_reuse_udp_context()) return 1;
    if (test_udp_connect_does_not_replace_tcp_session()) return 1;
    if (test_udp_q_remembers_source_link()) return 1;
    if (test_udp_q_is_sendable_without_observed_connect_event()) return 1;
    if (test_udp_non_clock_payload_does_not_enter_control_parser()) return 1;
    if (test_tcp_q_keeps_tcp_source_and_tcp_connect_behavior()) return 1;
    if (test_tcp_connection_events_preserve_udp_clock_sync_pending()) return 1;
    if (test_udp_closed_does_not_stop_active_tcp_control_session()) return 1;
    puts("PASS test_esp_transport_udp");
    return 0;
}
