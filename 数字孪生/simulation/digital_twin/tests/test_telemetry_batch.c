#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* The production header is intentionally included by the red test. */
#include "telemetry_rate.h"
#include "telemetry_batch.h"

static void test_extended_frame_encoder_layout_and_checksum(void)
{
    uint8_t frame[TELEMETRY_BATCH_FRAME_SIZE];
    uint8_t checksum;
    uint8_t i;

    telemetry_frame_encode(
        frame,
        1, 0, 1, 0,
        -321, 654, -123, 456,
        -77, 88, 987654U, -12345,
        0x0FU, 0x21U,
        -32768, -1, 0, 1, 32767, -2222,
        0xF1234567U);

    assert(frame[0] == 0xAAU);
    assert(frame[1] == 0x55U);
    assert(frame[2] == 0x01U);
    assert(frame[3] == 42U);
    assert(frame[30] == 0x00U && frame[31] == 0x80U);
    assert(frame[32] == 0xFFU && frame[33] == 0xFFU);
    assert(frame[34] == 0x00U && frame[35] == 0x00U);
    assert(frame[36] == 0x01U && frame[37] == 0x00U);
    assert(frame[38] == 0xFFU && frame[39] == 0x7FU);
    assert(frame[40] == 0x52U && frame[41] == 0xF7U);
    assert(frame[42] == 0x67U && frame[43] == 0x45U);
    assert(frame[44] == 0x23U && frame[45] == 0xF1U);

    checksum = 0x01U ^ 42U;
    for (i = 4U; i < 46U; i++) checksum ^= frame[i];
    assert(frame[46] == checksum);
}

static void test_current_wire_capacity_contract(void)
{
    assert(TELEMETRY_BATCH_FRAME_SIZE == 47U);
    assert(TELEMETRY_BATCH_MAX_FRAMES == 16U);
    assert(TELEMETRY_BATCH_SEND_MAX_FRAMES == 5U);
    assert(TELEMETRY_BATCH_MAX_BYTES == 752U);
    assert(TELEMETRY_BATCH_SEND_MAX_BYTES == 235U);
    assert(TELEMETRY_INTERVAL_MS == 30U);
    assert(telemetry_rate_due(29U, 0U) == 0U);
    assert(telemetry_rate_due(30U, 0U) == 1U);
    assert(telemetry_rate_due(0U, 0xFFFFFFF0U) == 1U);
}

static void make_frame(uint8_t *frame, uint8_t value)
{
    uint16_t i;
    for (i = 0U; i < TELEMETRY_BATCH_FRAME_SIZE; i++) {
        frame[i] = value;
    }
}

static void test_appends_three_frames_without_overwrite(void)
{
    TelemetryBatch batch;
    uint8_t frame[TELEMETRY_BATCH_FRAME_SIZE];
    uint8_t overwritten;

    telemetry_batch_init(&batch);
    make_frame(frame, 0x11U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    assert(overwritten == 0U);
    make_frame(frame, 0x22U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    assert(overwritten == 0U);
    make_frame(frame, 0x33U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    assert(overwritten == 0U);

    assert(telemetry_batch_count(&batch) == 3U);
    assert(telemetry_batch_length(&batch) == 3U * TELEMETRY_BATCH_FRAME_SIZE);
    assert(telemetry_batch_data(&batch)[0] == 0x11U);
    assert(telemetry_batch_data(&batch)[TELEMETRY_BATCH_FRAME_SIZE] == 0x22U);
    assert(telemetry_batch_data(&batch)[2U * TELEMETRY_BATCH_FRAME_SIZE] == 0x33U);
}

static void test_appends_eight_frames_without_overwrite(void)
{
    TelemetryBatch batch;
    uint8_t frame[TELEMETRY_BATCH_FRAME_SIZE];
    uint8_t overwritten;

    telemetry_batch_init(&batch);
    make_frame(frame, 0x11U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x22U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x33U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x44U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x55U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));

    make_frame(frame, 0x66U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x77U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x88U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));

    assert(overwritten == 0U);
    assert(telemetry_batch_count(&batch) == 8U);
    assert(telemetry_batch_length(&batch) == 8U * TELEMETRY_BATCH_FRAME_SIZE);
    assert(telemetry_batch_data(&batch)[0] == 0x11U);
    assert(telemetry_batch_data(&batch)[TELEMETRY_BATCH_FRAME_SIZE] == 0x22U);
    assert(telemetry_batch_data(&batch)[2U * TELEMETRY_BATCH_FRAME_SIZE] == 0x33U);
    assert(telemetry_batch_data(&batch)[3U * TELEMETRY_BATCH_FRAME_SIZE] == 0x44U);
    assert(telemetry_batch_data(&batch)[4U * TELEMETRY_BATCH_FRAME_SIZE] == 0x55U);
    assert(telemetry_batch_data(&batch)[5U * TELEMETRY_BATCH_FRAME_SIZE] == 0x66U);
    assert(telemetry_batch_data(&batch)[6U * TELEMETRY_BATCH_FRAME_SIZE] == 0x77U);
    assert(telemetry_batch_data(&batch)[7U * TELEMETRY_BATCH_FRAME_SIZE] == 0x88U);
}

static void test_full_batch_drops_oldest_and_keeps_latest_sixteen(void)
{
    TelemetryBatch batch;
    uint8_t frame[TELEMETRY_BATCH_FRAME_SIZE];
    uint8_t overwritten;

    telemetry_batch_init(&batch);
    make_frame(frame, 0x11U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x22U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x33U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x44U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x55U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x66U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x77U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x88U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0x99U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0xAAU);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0xBBU);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0xCCU);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0xDDU);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0xEEU);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0xF1U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0xF2U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    make_frame(frame, 0xF3U);
    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));

    assert(overwritten == 1U);
    assert(telemetry_batch_count(&batch) == 16U);
    assert(telemetry_batch_length(&batch) == TELEMETRY_BATCH_MAX_BYTES);
    assert(telemetry_batch_data(&batch)[0] == 0x22U);
    assert(telemetry_batch_data(&batch)[TELEMETRY_BATCH_FRAME_SIZE] == 0x33U);
    assert(telemetry_batch_data(&batch)[14U * TELEMETRY_BATCH_FRAME_SIZE] == 0xF2U);
    assert(telemetry_batch_data(&batch)[15U * TELEMETRY_BATCH_FRAME_SIZE] == 0xF3U);
}

static void test_consume_clears_batch_and_rejects_wrong_frame_size(void)
{
    TelemetryBatch batch;
    uint8_t frame[TELEMETRY_BATCH_FRAME_SIZE];
    uint8_t overwritten = 0xA5U;

    telemetry_batch_init(&batch);
    make_frame(frame, 0x55U);
    assert(!telemetry_batch_append(&batch, frame,
                                   TELEMETRY_BATCH_FRAME_SIZE - 1U,
                                   &overwritten));
    assert(overwritten == 0U);
    assert(telemetry_batch_count(&batch) == 0U);
    assert(telemetry_batch_length(&batch) == 0U);

    assert(telemetry_batch_append(&batch, frame, sizeof(frame), &overwritten));
    telemetry_batch_consume(&batch);
    assert(telemetry_batch_count(&batch) == 0U);
    assert(telemetry_batch_length(&batch) == 0U);
    assert(!telemetry_batch_has_data(&batch));
}

int main(void)
{
    test_extended_frame_encoder_layout_and_checksum();
    test_current_wire_capacity_contract();
    test_appends_three_frames_without_overwrite();
    test_appends_eight_frames_without_overwrite();
    test_full_batch_drops_oldest_and_keeps_latest_sixteen();
    test_consume_clears_batch_and_rejects_wrong_frame_size();
    puts("telemetry_batch: all tests passed");
    return 0;
}
