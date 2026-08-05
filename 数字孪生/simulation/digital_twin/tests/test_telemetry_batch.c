#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* The production header is intentionally included by the red test. */
#include "telemetry_batch.h"

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
    assert(telemetry_batch_data(&batch)[29] == 0x22U);
    assert(telemetry_batch_data(&batch)[58] == 0x33U);
}

static void test_full_batch_drops_oldest_and_keeps_latest_three(void)
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

    assert(overwritten == 1U);
    assert(telemetry_batch_count(&batch) == 3U);
    assert(telemetry_batch_length(&batch) == TELEMETRY_BATCH_MAX_BYTES);
    assert(telemetry_batch_data(&batch)[0] == 0x22U);
    assert(telemetry_batch_data(&batch)[29] == 0x33U);
    assert(telemetry_batch_data(&batch)[58] == 0x44U);
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
    test_appends_three_frames_without_overwrite();
    test_full_batch_drops_oldest_and_keeps_latest_three();
    test_consume_clears_batch_and_rejects_wrong_frame_size();
    puts("telemetry_batch: all tests passed");
    return 0;
}
