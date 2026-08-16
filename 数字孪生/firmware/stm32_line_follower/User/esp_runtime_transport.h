#ifndef ESP_RUNTIME_TRANSPORT_H
#define ESP_RUNTIME_TRANSPORT_H

#include <stdint.h>
#include "ipd_parser.h"
#include "twin_control_protocol.h"
#include "esp_at_diagnostic.h"

/* A short firmware-side quiet period after a clock probe is accepted. */
#define ESP_CLOCK_QUIET_WINDOW_MS 2000U

/* Reserved only for the ClockSync transport-isolation experiment.  The
 * telemetry, health, and control streams continue to use the TCP session. */
#define ESP_CLOCK_SYNC_UDP_LINK_ID 4U

/* Stable event codes for the read-only transport boundary snapshot. */
typedef enum {
    ESP_TRANSPORT_EVENT_NONE = 0,
    ESP_TRANSPORT_EVENT_IPD_HEADER_ACCEPTED = 1,
    ESP_TRANSPORT_EVENT_IPD_COMPLETE = 2,
    ESP_TRANSPORT_EVENT_IPD_ERROR = 3,
    ESP_TRANSPORT_EVENT_Q_CANDIDATE = 4,
    ESP_TRANSPORT_EVENT_Q_PARSE_OK = 5,
    ESP_TRANSPORT_EVENT_Q_PARSE_REJECT = 6,
    ESP_TRANSPORT_EVENT_QUEUE_ACCEPTED = 7,
    ESP_TRANSPORT_EVENT_QUEUE_REJECTED_PENDING = 8,
    ESP_TRANSPORT_EVENT_IPD_PREFIX_SEEN = 9,
    ESP_TRANSPORT_EVENT_IPD_HEADER_PARSE_ERROR = 10
} EspTransportEventCode;

/* Read-only counters for locating a ClockSync UDP request boundary.  These
 * values describe firmware parser/queue events; they are not UART wire-time
 * or physical-network observations. */
typedef struct {
    uint32_t udp_ipd_header_accepted_count;
    uint32_t udp_ipd_complete_count;
    /* Global parser errors; a malformed header does not prove its link ID. */
    uint32_t ipd_error_count;
    uint32_t udp_q_candidate_count;
    uint32_t udp_q_parse_ok_count;
    uint32_t udp_q_parse_reject_count;
    uint32_t clock_queue_accepted_count;
    uint32_t clock_queue_rejected_pending_count;
    /* Latest event only; counters preserve the boundary history. */
    uint8_t last_event_code;
    uint8_t last_link_id;
    uint16_t last_ipd_length;
    uint32_t last_event_tick_ms;
    uint32_t last_sequence;
    /* Prefix/header counters are global because link ID is not known yet. */
    uint32_t ipd_prefix_seen_count;
    uint32_t ipd_header_parse_error_count;
} EspTransportDiagnosticSnapshot;

/* Stable symbol for non-invasive debugger Watch/Memory inspection. */
extern volatile EspTransportDiagnosticSnapshot
    g_esp_transport_diagnostic_snapshot;

typedef struct {
    uint32_t until_ms;
    uint8_t armed;
} EspClockQuietWindow;

/* Initialise the ESP transport layer.
   Must be called once before any ProcessByte calls. */
void esp_transport_init(volatile uint8_t *tcp_connected_flag,
                         volatile uint8_t *tcp_client_id_ptr);

/* Process one byte from the ESP UART.
   - AT responses, noise, CONNECT/CLOSED lines are handled internally.
   - +IPD headers are parsed; payload bytes feed twin_control_receive_byte().
   - If a P/R frame produces a terminal TwinControlResult, the ACK is
     encoded and queued for sending.
   Call esp_transport_has_pending_ack() / esp_transport_has_pending_status()
   after each main loop iteration to check if A/S frames need sending.
*/
uint8_t esp_transport_process_byte(uint8_t byte);

/* Copy the current transport-boundary counters without consuming or
   changing any transport state. */
void esp_transport_get_diagnostic(EspTransportDiagnosticSnapshot *output);

/* Set the monotonic tick used when the next RX byte reaches the protocol
   parser.  The firmware caller updates this immediately before processing
   each byte; host callers may leave the default at zero. */
void esp_transport_set_now_ms(uint32_t now_ms);

/* Returns non-zero if an ACK has been queued by the last ProcessByte call. */
uint8_t esp_transport_has_pending_ack(void);

/* Returns non-zero if the status queue is empty (ready to accept a new one).
   Returns 0 if a previous status is still pending and should not be overwritten. */
uint8_t esp_transport_can_queue_status(void);

/* Returns non-zero if a status frame has been queued. */
uint8_t esp_transport_has_pending_status(void);

/* Returns non-zero if a Q request has produced a pending T response. */
uint8_t esp_transport_has_pending_clock_sync(void);

/* Returns non-zero when the experiment UDP link has reported CONNECT. */
uint8_t esp_transport_clock_sync_udp_connected(void);

/* Returns the source link of the pending Q response without consuming it. */
uint8_t esp_transport_pending_clock_sync_link_id(uint8_t *link_id);

/* Returns non-zero only when the pending Q response's source link can accept
 * its matching CIPSEND transaction.  UDP readiness is established by the
 * received Q itself; TCP readiness still requires the active client link. */
uint8_t esp_transport_pending_clock_sync_sendable(void);

/* Consume the one-shot event raised when a new Q response was queued. */
uint8_t esp_transport_take_clock_sync_event(void);

/* Copy the pending Q sample without consuming it.  The caller may use the
 * copy to prepare a late-materialized CIPSEND payload. */
uint8_t esp_transport_peek_pending_clock_sync(TwinControlClockSync *output);

/* Consume the pending Q sample only after its CIPSEND transaction has
 * actually been accepted by the TX state machine. */
void esp_transport_consume_pending_clock_sync(void);

/* Retrieve and clear the pending ACK text (null-terminated ASCII, with \n).
   Returns 0 if no pending ACK. */
uint16_t esp_transport_get_pending_ack(char *output, uint16_t output_size);

/* Retrieve and clear the pending status text (null-terminated ASCII, with \n).
   Returns 0 if no pending status. */
uint16_t esp_transport_get_pending_status(char *output, uint16_t output_size);

/* Queue one Q result without replacing an outstanding response.  Direct
   callers do not provide a source link; +IPD callers use their explicit
   source context internally. */
uint8_t esp_transport_queue_clock_sync(const TwinControlClockSync *clock_sync);

/* Wrap-safe quiet-window helpers used by main.c and host tests. */
void esp_clock_quiet_init(EspClockQuietWindow *window);
void esp_clock_quiet_arm(EspClockQuietWindow *window, uint32_t now_ms);
uint8_t esp_clock_quiet_active(EspClockQuietWindow *window, uint32_t now_ms);
void esp_clock_quiet_reset(EspClockQuietWindow *window);

/* Encode and consume the pending T response with the dispatch tick supplied
   by the caller immediately before the CIPSEND transaction is started. */
uint16_t esp_transport_get_pending_clock_sync(char *output,
                                              uint16_t output_size,
                                              uint32_t mcu_tx_tick_ms);

/* Queue a status frame for sending.  Called by main.c on STOP/TIMEOUT/
   track-loss / run-timeout events. */
void esp_transport_queue_status(const TwinControlStatus *status);

/* Directly encode and queue an ACK.  Used when the caller already has
   a result to acknowledge. */
void esp_transport_queue_ack(const TwinControlResult *result);

/* Apply any pending parameter candidate at the safe point and queue
   the resulting ACK frame (APPLIED or REJECTED).  Returns 1 if a
   pending candidate was available (including rollback-cancelled), 0
   if nothing was pending.
   This is the single call site main.c should use, replacing the raw
   twin_control_apply_pending + manual esp_transport_queue_ack pattern. */
uint8_t esp_transport_apply_and_ack(TwinControlParams *active,
                                     const TwinControlParams *baseline);

/* Current connection generation.  Increments on every CONNECT line.
   Frames retained under an older generation must never be delivered to a
   new client — main.c uses this to drop stale ACK/STATUS at the connection
   boundary (Task 4B-4 fix, Codex review remediation). */
uint32_t esp_transport_connection_generation(void);

/* ESP AT capability preflight wrappers.  The diagnostic module is fed only
   from +IPD payload bytes for requests and from non-CIPSEND UART bytes for
   the fixed AT query responses. */
uint8_t esp_transport_diagnostic_request_ready(void);
uint8_t esp_transport_start_diagnostic(uint32_t now_ms,
                                       uint8_t connected,
                                       uint8_t motion_inhibited,
                                       uint8_t cipsend_idle,
                                       uint8_t critical_pending);
uint8_t esp_transport_diagnostic_command(const char **command,
                                         uint16_t *length,
                                         const char **query_id);
void esp_transport_diagnostic_mark_command_sent(uint32_t now_ms);
void esp_transport_diagnostic_mark_command_byte_sent(uint32_t now_ms);
void esp_transport_diagnostic_feed_response_byte(uint8_t byte);
void esp_transport_diagnostic_tick(uint32_t now_ms);
uint8_t esp_transport_diagnostic_response_ready(void);
uint16_t esp_transport_diagnostic_peek_response(char *output,
                                               uint16_t output_size);
void esp_transport_diagnostic_consume_response(void);
uint8_t esp_transport_diagnostic_busy(void);

#endif /* ESP_RUNTIME_TRANSPORT_H */
