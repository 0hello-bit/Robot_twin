#ifndef TIMING_DIAGNOSTIC_H
#define TIMING_DIAGNOSTIC_H

#include <stdint.h>

/* Additive diagnostic frame. Existing telemetry/control frames are unchanged. */
#define TIMING_DIAGNOSTIC_TYPE          0x7FU
#define TIMING_DIAGNOSTIC_SCHEMA_VERSION 1U
#define TIMING_DIAGNOSTIC_PAYLOAD_LEN   48U
#define TIMING_DIAGNOSTIC_FRAME_SIZE    53U

#define TIMING_DIAGNOSTIC_FLAG_SAMPLE_VALID 0x01U
#define TIMING_DIAGNOSTIC_FLAG_TX_START     0x02U
#define TIMING_DIAGNOSTIC_FLAG_TX_TERMINAL  0x04U
#define TIMING_DIAGNOSTIC_FLAG_SEND_OK      0x08U

typedef struct {
    uint32_t t_imu_start_ms;
    uint32_t t_imu_done_ms;
    uint32_t t_sensor_done_ms;
    uint32_t t_state_ms;
    uint32_t t_enqueue_ms;
    uint32_t t_tx_start_ms;
    uint32_t t_send_ok_ms;
    uint32_t sample_seq;
} TelemetryTimingRecord;

typedef struct {
    uint8_t schema_version;
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

static inline void timing_diag_put_u16(uint8_t *buf, uint16_t value)
{
    buf[0] = (uint8_t)(value & 0xFFU);
    buf[1] = (uint8_t)((value >> 8) & 0xFFU);
}

static inline void timing_diag_put_u32(uint8_t *buf, uint32_t value)
{
    buf[0] = (uint8_t)(value & 0xFFU);
    buf[1] = (uint8_t)((value >> 8) & 0xFFU);
    buf[2] = (uint8_t)((value >> 16) & 0xFFU);
    buf[3] = (uint8_t)((value >> 24) & 0xFFU);
}

static inline uint8_t timing_diagnostic_encode(
    uint8_t *buffer, const TimingDiagnosticSnapshot *snapshot)
{
    uint8_t checksum;
    uint8_t i;

    buffer[0] = 0xAAU;
    buffer[1] = 0x55U;
    buffer[2] = TIMING_DIAGNOSTIC_TYPE;
    buffer[3] = TIMING_DIAGNOSTIC_PAYLOAD_LEN;
    buffer[4] = TIMING_DIAGNOSTIC_SCHEMA_VERSION;
    buffer[5] = snapshot->flags;
    timing_diag_put_u16(buffer + 6, snapshot->batch_id);
    buffer[8] = snapshot->batch_count;
    buffer[9] = snapshot->pending_count;
    timing_diag_put_u16(buffer + 10, snapshot->overwrite_total);
    timing_diag_put_u32(buffer + 12, snapshot->t_imu_start_ms);
    timing_diag_put_u32(buffer + 16, snapshot->t_imu_done_ms);
    timing_diag_put_u32(buffer + 20, snapshot->t_sensor_done_ms);
    timing_diag_put_u32(buffer + 24, snapshot->t_state_ms);
    timing_diag_put_u32(buffer + 28, snapshot->t_enqueue_ms);
    timing_diag_put_u32(buffer + 32, snapshot->t_tx_start_ms);
    timing_diag_put_u32(buffer + 36, snapshot->t_send_ok_ms);
    timing_diag_put_u32(buffer + 40, snapshot->batch_first_tick_ms);
    timing_diag_put_u32(buffer + 44, snapshot->batch_last_tick_ms);
    timing_diag_put_u32(buffer + 48, snapshot->sample_seq);

    checksum = TIMING_DIAGNOSTIC_TYPE ^ TIMING_DIAGNOSTIC_PAYLOAD_LEN;
    for (i = 0U; i < TIMING_DIAGNOSTIC_PAYLOAD_LEN; i++) {
        checksum ^= buffer[4U + i];
    }
    buffer[52] = checksum;
    return TIMING_DIAGNOSTIC_FRAME_SIZE;
}

#endif /* TIMING_DIAGNOSTIC_H */
