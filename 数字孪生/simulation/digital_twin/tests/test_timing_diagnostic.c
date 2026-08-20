#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "timing_diagnostic.h"

static uint32_t read_u32(const uint8_t *buf)
{
    return ((uint32_t)buf[0])
         | ((uint32_t)buf[1] << 8)
         | ((uint32_t)buf[2] << 16)
         | ((uint32_t)buf[3] << 24);
}

static void test_encoder_preserves_schema_and_stage_fields(void)
{
    TimingDiagnosticSnapshot snapshot = {0};
    uint8_t frame[TIMING_DIAGNOSTIC_FRAME_SIZE];
    uint8_t checksum;
    uint8_t i;

    snapshot.flags = TIMING_DIAGNOSTIC_FLAG_SAMPLE_VALID
                   | TIMING_DIAGNOSTIC_FLAG_TX_START
                   | TIMING_DIAGNOSTIC_FLAG_TX_TERMINAL
                   | TIMING_DIAGNOSTIC_FLAG_SEND_OK;
    snapshot.batch_id = 7U;
    snapshot.batch_count = 8U;
    snapshot.pending_count = 11U;
    snapshot.overwrite_total = 3U;
    snapshot.t_imu_start_ms = 1000U;
    snapshot.t_imu_done_ms = 1001U;
    snapshot.t_sensor_done_ms = 1002U;
    snapshot.t_state_ms = 1004U;
    snapshot.t_enqueue_ms = 1005U;
    snapshot.t_tx_start_ms = 1120U;
    snapshot.t_send_ok_ms = 1150U;
    snapshot.batch_first_tick_ms = 980U;
    snapshot.batch_last_tick_ms = 1004U;
    snapshot.sample_seq = 42U;

    assert(timing_diagnostic_encode(frame, &snapshot)
           == TIMING_DIAGNOSTIC_FRAME_SIZE);
    assert(frame[0] == 0xAAU && frame[1] == 0x55U);
    assert(frame[2] == TIMING_DIAGNOSTIC_TYPE);
    assert(frame[3] == TIMING_DIAGNOSTIC_PAYLOAD_LEN);
    assert(frame[4] == TIMING_DIAGNOSTIC_SCHEMA_VERSION);
    assert(frame[5] == 0x0FU);
    assert(read_u32(frame + 12U) == 1000U);
    assert(read_u32(frame + 28U) == 1005U);
    assert(read_u32(frame + 32U) == 1120U);
    assert(read_u32(frame + 36U) == 1150U);
    assert(read_u32(frame + 48U) == 42U);

    checksum = TIMING_DIAGNOSTIC_TYPE ^ TIMING_DIAGNOSTIC_PAYLOAD_LEN;
    for (i = 0U; i < TIMING_DIAGNOSTIC_PAYLOAD_LEN; i++) {
        checksum ^= frame[4U + i];
    }
    assert(frame[52] == checksum);
}

int main(void)
{
    test_encoder_preserves_schema_and_stage_fields();
    puts("timing_diagnostic: all tests passed");
    return 0;
}
