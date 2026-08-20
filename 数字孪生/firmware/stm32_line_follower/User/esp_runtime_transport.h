#ifndef ESP_RUNTIME_TRANSPORT_H
#define ESP_RUNTIME_TRANSPORT_H

#include <stdint.h>
#include "ipd_parser.h"
#include "twin_control_protocol.h"

/* Keep the droppable streams quiet after a ClockSync request is accepted so
 * the matching T response is not measured behind a newly started telemetry
 * or diagnostic transaction. */
#define ESP_CLOCK_QUIET_WINDOW_MS 2000U

typedef struct {
    uint32_t until_ms;
    uint8_t armed;
} EspClockQuietWindow;

/* Initialise the ESP transport layer.
   Must be called once before any ProcessByte calls. */
void esp_transport_init(volatile uint8_t *tcp_connected_flag,
                         volatile uint8_t *tcp_client_id_ptr);

/* Process one byte from the ESP UART using the compatibility timing path.
   - AT responses, noise, CONNECT/CLOSED lines are handled internally.
   - +IPD headers are parsed; payload bytes feed twin_control_receive_byte().
   - If a P/R frame produces a terminal TwinControlResult, the ACK is
     encoded and queued for sending.
   Call esp_transport_has_pending_ack() / esp_transport_has_pending_status()
   after each main loop iteration to check if A/S frames need sending.
*/
void esp_transport_process_byte(uint8_t byte);

/* Timed RX path.  The first tick is captured by the UART ISR and the second
   is the main-context parser observation.  They are deliberately separate. */
void esp_transport_process_byte_at(uint8_t byte, uint32_t uart_rx_tick_ms,
                                   uint8_t uart_rx_timestamp_valid,
                                   uint32_t parse_observed_tick_ms);

/* Set the compatibility parser-observed tick used by the legacy byte API. */
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

/* Consume the one-shot event raised when a new Q response is queued. */
uint8_t esp_transport_take_clock_sync_event(void);

/* Consume the one-shot event raised when the active TCP client closes. */
uint8_t esp_transport_take_disconnect_event(void);

/* Copy the pending Q sample without consuming it.  The caller may use the
 * copy to prepare a late-materialized CIPSEND payload. */
uint8_t esp_transport_peek_pending_clock_sync(TwinControlClockSync *output);

/* Consume the pending Q sample only after its CIPSEND transaction has
 * actually been accepted by the TX state machine. */
void esp_transport_consume_pending_clock_sync(void);

/* Wrap-safe quiet-window helpers used by main.c and host tests. */
void esp_clock_quiet_init(EspClockQuietWindow *window);
void esp_clock_quiet_arm(EspClockQuietWindow *window, uint32_t now_ms);
uint8_t esp_clock_quiet_active(EspClockQuietWindow *window, uint32_t now_ms);
void esp_clock_quiet_reset(EspClockQuietWindow *window);

/* Retrieve and clear the pending ACK text (null-terminated ASCII, with \n).
   Returns 0 if no pending ACK. */
uint16_t esp_transport_get_pending_ack(char *output, uint16_t output_size);

/* Retrieve and clear the pending status text (null-terminated ASCII, with \n).
   Returns 0 if no pending status. */
uint16_t esp_transport_get_pending_status(char *output, uint16_t output_size);

/* Queue one Q result without replacing an outstanding response. */
uint8_t esp_transport_queue_clock_sync(const TwinControlClockSync *clock_sync);

/* Encode and consume the pending T response with the named CIPSEND transaction
   start boundary supplied by the caller. */
uint16_t esp_transport_get_pending_clock_sync(char *output,
                                               uint16_t output_size,
                                               uint32_t t_transaction_started_tick_ms);

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

#endif /* ESP_RUNTIME_TRANSPORT_H */
