#include "timing_diagnostic.h"

static void write_u16(uint8_t *dst, uint16_t value)
{
    dst[0] = (uint8_t)(value & 0xFFU);
    dst[1] = (uint8_t)((value >> 8) & 0xFFU);
}

static void write_u32(uint8_t *dst, uint32_t value)
{
    dst[0] = (uint8_t)(value & 0xFFU);
    dst[1] = (uint8_t)((value >> 8) & 0xFFU);
    dst[2] = (uint8_t)((value >> 16) & 0xFFU);
    dst[3] = (uint8_t)((value >> 24) & 0xFFU);
}

uint16_t timing_diagnostic_encode(uint8_t *frame,
                                  const TimingDiagnosticSnapshot *snapshot)
{
    uint8_t checksum;
    uint8_t i;
    uint8_t *payload;

    if (frame == 0 || snapshot == 0) return 0U;

    frame[0] = 0xAAU;
    frame[1] = 0x55U;
    frame[2] = TIMING_DIAGNOSTIC_TYPE;
    frame[3] = TIMING_DIAGNOSTIC_PAYLOAD_LEN;
    payload = frame + 4U;
    payload[0] = TIMING_DIAGNOSTIC_SCHEMA_VERSION;
    payload[1] = snapshot->flags;
    write_u16(payload + 2U, snapshot->batch_id);
    payload[4] = snapshot->batch_count;
    payload[5] = snapshot->pending_count;
    write_u16(payload + 6U, snapshot->overwrite_total);
    write_u32(payload + 8U, snapshot->t_imu_start_ms);
    write_u32(payload + 12U, snapshot->t_imu_done_ms);
    write_u32(payload + 16U, snapshot->t_sensor_done_ms);
    write_u32(payload + 20U, snapshot->t_state_ms);
    write_u32(payload + 24U, snapshot->t_enqueue_ms);
    write_u32(payload + 28U, snapshot->t_tx_start_ms);
    write_u32(payload + 32U, snapshot->t_send_ok_ms);
    write_u32(payload + 36U, snapshot->batch_first_tick_ms);
    write_u32(payload + 40U, snapshot->batch_last_tick_ms);
    write_u32(payload + 44U, snapshot->sample_seq);

    checksum = TIMING_DIAGNOSTIC_TYPE ^ TIMING_DIAGNOSTIC_PAYLOAD_LEN;
    for (i = 0U; i < TIMING_DIAGNOSTIC_PAYLOAD_LEN; i++) {
        checksum ^= payload[i];
    }
    frame[52] = checksum;
    return TIMING_DIAGNOSTIC_FRAME_SIZE;
}
