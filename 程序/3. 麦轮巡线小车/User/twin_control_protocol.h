#ifndef TWIN_CONTROL_PROTOCOL_H
#define TWIN_CONTROL_PROTOCOL_H

#include <stdint.h>

#define TWIN_CONTROL_CAMPAIGN_ID_MAX 16U
#define TWIN_CONTROL_RUN_ID_MAX 16U
#define TWIN_CONTROL_STATE_MAX 16U
#define TWIN_CONTROL_REASON_MAX 16U
#define TWIN_CONTROL_LINE_MAX 96U

/* Task 2B: maximum consecutive line-loss duration (ms) before hard stop.
   This is an initial conservative value for the Task 2B test bench;
   it may be calibrated after real-track characterisation. */
#define TWIN_CONTROL_LINE_LOST_MAX_MS 1000U

/* Bounded FIFO depth for S status events.
   At most this many events can be queued between main-loop consumption cycles.
   When full, the oldest entry is dropped (newest always has a slot).
   Safety-critical events (STOP,TIMEOUT,LINE_LOST) are consumed every loop
   iteration (~5ms) so 4 entries covers any realistic batch scenario. */
#define TWIN_CONTROL_STATUS_FIFO_SIZE 4U

/* Safety bounds shared with the Python reference protocol. */
#define TWIN_CONTROL_SPEED_MIN 260
#define TWIN_CONTROL_SPEED_MAX 680
#define TWIN_CONTROL_SPEED_STEP_MAX 100
#define TWIN_CONTROL_KP_MIN 20.0F
#define TWIN_CONTROL_KP_MAX 50.0F
#define TWIN_CONTROL_KP_STEP_MAX 5.0F
#define TWIN_CONTROL_KI_MIN 0.0F
#define TWIN_CONTROL_KI_MAX 5.0F
#define TWIN_CONTROL_KI_STEP_MAX 1.0F
#define TWIN_CONTROL_KD_MIN 5.0F
#define TWIN_CONTROL_KD_MAX 20.0F
#define TWIN_CONTROL_KD_STEP_MAX 3.0F

typedef struct {
    float kp;
    float ki;
    float kd;
    int16_t speed_max;
    uint32_t version;
    char campaign_id[TWIN_CONTROL_CAMPAIGN_ID_MAX + 1U];
} TwinControlParams;

typedef struct {
    uint8_t has_ack;
    uint8_t applied;
    uint8_t motion_inhibited;
    uint32_t version;
    char campaign_id[TWIN_CONTROL_CAMPAIGN_ID_MAX + 1U];
    char reason[TWIN_CONTROL_REASON_MAX + 1U];
} TwinControlResult;

typedef struct {
    char campaign_id[TWIN_CONTROL_CAMPAIGN_ID_MAX + 1U];
    char run_id[TWIN_CONTROL_RUN_ID_MAX + 1U];
    char state[TWIN_CONTROL_STATE_MAX + 1U];
    char reason[TWIN_CONTROL_REASON_MAX + 1U];
    uint32_t tick_ms;
} TwinControlStatus;

void twin_control_init(const TwinControlParams *baseline);
/* The caller supplies result storage and immediately owns every terminal P result. */
uint8_t twin_control_receive_byte(uint8_t byte, TwinControlResult *result);
uint8_t twin_control_apply_pending(TwinControlParams *active,
                                   const TwinControlParams *baseline,
                                   TwinControlResult *result);
void twin_control_timeout(void);
uint8_t twin_control_motion_inhibited(void);
uint16_t twin_control_encode_ack(const TwinControlResult *result,
                                 char *output,
                                 uint16_t output_size);
uint16_t twin_control_encode_status(const TwinControlStatus *status,
                                    char *output,
                                    uint16_t output_size);

/* --- Task 2B safety-hardening API --- */

/* Firmware starts with motion inhibited after init.
   Only a valid R,...,START command (without pending rollback) clears it.
   ESP init failure, TCP disconnect, TIMEOUT, STOP, RESTORE_BASELINE,
   protocol errors, and line-loss hard stop all re-enable inhibit. */

/* Retrieve and clear the controller-reset flag (integral term, last error, etc.).
   Called by the main loop after every apply_pending / rollback cycle.
   Returns 1 if the controller state should be reset. */
uint8_t twin_control_consume_controller_reset_flag(void);

/* Retrieve and clear the latest pending status event for S-frame generation.
   Returns 1 if a status event was available (written to *status).
   The caller should pass the retrieved status to esp_transport_queue_status(). */
uint8_t twin_control_consume_pending_status(TwinControlStatus *status);

/* Report that the line is currently lost (all sensors white), at the given
   monotonic tick_ms.  If the cumulative loss duration exceeds
   TWIN_CONTROL_LINE_LOST_MAX_MS, a hard stop (timeout + inhibit) is triggered
   and a LINE_LOST status event is queued.
   Returns 1 if a hard stop was triggered on this call. */
uint8_t twin_control_report_line_lost(uint32_t tick_ms);

/* Report that the line has been re-acquired.  Resets the line-loss timer. */
void twin_control_report_line_found(void);

/* Queue the current authoritative safety state as an S event.
   Called on TCP CONNECT so the PC always receives the real motor-permission
   state, regardless of whether earlier S events were lost during disconnect. */
void twin_control_queue_authoritative_status(void);

#endif
