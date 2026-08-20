#ifndef TIMING_DIAGNOSTIC_H
#define TIMING_DIAGNOSTIC_H

#include <stdint.h>

#define TIMING_DIAGNOSTIC_TYPE 0x7FU
#define TIMING_DIAGNOSTIC_SCHEMA_VERSION 1U
#define TIMING_DIAGNOSTIC_PAYLOAD_LEN 48U
#define TIMING_DIAGNOSTIC_FRAME_SIZE 53U

#define TIMING_DIAGNOSTIC_FLAG_SAMPLE_VALID 0x01U
#define TIMING_DIAGNOSTIC_FLAG_TX_START    0x02U
#define TIMING_DIAGNOSTIC_FLAG_TX_TERMINAL 0x04U
#define TIMING_DIAGNOSTIC_FLAG_SEND_OK    0x08U

typedef struct {
    uint8_t flags;
    uint16_t batch_id;
    uint8_t batch_count;
    uint8_t pending_count;
    uint16_t overwrite_total;
    uint32_t t_imu_start_ms;
    uint32_t t_imu_done_ms;
    uint32_t t_sensor_done_ms;
    uint32_t t_state_ms;
    uint32_t t_enqueue_ms;
    uint32_t t_tx_start_ms;
    uint32_t t_send_ok_ms;
    uint32_t batch_first_tick_ms;
    uint32_t batch_last_tick_ms;
    uint32_t sample_seq;
} TimingDiagnosticSnapshot;

uint16_t timing_diagnostic_encode(uint8_t *frame,
                                  const TimingDiagnosticSnapshot *snapshot);

#endif /* TIMING_DIAGNOSTIC_H */
