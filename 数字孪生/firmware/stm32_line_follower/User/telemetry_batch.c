#include "telemetry_batch.h"

#include <string.h>

void telemetry_batch_init(TelemetryBatch *batch)
{
    telemetry_batch_clear(batch);
}

void telemetry_batch_clear(TelemetryBatch *batch)
{
    batch->len = 0U;
    batch->count = 0U;
}

uint8_t telemetry_batch_append(TelemetryBatch *batch,
                               const uint8_t *frame,
                               uint16_t frame_len,
                               uint8_t *overwrote)
{
    uint16_t offset;

    if (overwrote != 0) *overwrote = 0U;
    if (batch == 0 || frame == 0 ||
        frame_len != TELEMETRY_BATCH_FRAME_SIZE) {
        return 0U;
    }

    if (batch->count >= TELEMETRY_BATCH_MAX_FRAMES) {
        /* Keep the latest eight frames; the queue is intentionally droppable. */
        memmove(batch->data,
                batch->data + TELEMETRY_BATCH_FRAME_SIZE,
                TELEMETRY_BATCH_MAX_BYTES - TELEMETRY_BATCH_FRAME_SIZE);
        offset = TELEMETRY_BATCH_MAX_BYTES - TELEMETRY_BATCH_FRAME_SIZE;
        if (overwrote != 0) *overwrote = 1U;
    } else {
        offset = (uint16_t)batch->count * TELEMETRY_BATCH_FRAME_SIZE;
        batch->count++;
    }

    memcpy(batch->data + offset, frame, TELEMETRY_BATCH_FRAME_SIZE);
    batch->len = (uint16_t)batch->count * TELEMETRY_BATCH_FRAME_SIZE;
    return 1U;
}

uint8_t telemetry_batch_has_data(const TelemetryBatch *batch)
{
    return (batch != 0 && batch->count != 0U && batch->len != 0U) ? 1U : 0U;
}

uint8_t telemetry_batch_count(const TelemetryBatch *batch)
{
    return batch == 0 ? 0U : batch->count;
}

uint16_t telemetry_batch_length(const TelemetryBatch *batch)
{
    return batch == 0 ? 0U : batch->len;
}

const uint8_t *telemetry_batch_data(const TelemetryBatch *batch)
{
    return batch == 0 ? 0 : batch->data;
}

void telemetry_batch_consume(TelemetryBatch *batch)
{
    if (batch != 0) telemetry_batch_clear(batch);
}

uint8_t telemetry_batch_copy_prefix(const TelemetryBatch *src,
                                    TelemetryBatch *dst,
                                    uint8_t max_frames)
{
    uint8_t count;

    if (src == 0 || dst == 0 || max_frames == 0U) return 0U;
    telemetry_batch_clear(dst);
    count = src->count;
    if (count > max_frames) count = max_frames;
    if (count == 0U) return 0U;
    memcpy(dst->data, src->data,
           (uint16_t)count * TELEMETRY_BATCH_FRAME_SIZE);
    dst->count = count;
    dst->len = (uint16_t)count * TELEMETRY_BATCH_FRAME_SIZE;
    return 1U;
}

uint8_t telemetry_batch_drop_prefix(TelemetryBatch *batch,
                                     uint8_t frame_count)
{
    uint8_t remaining;
    uint16_t drop_bytes;

    if (batch == 0 || frame_count == 0U) return 0U;
    if (frame_count > batch->count) frame_count = batch->count;
    if (frame_count == 0U) return 0U;

    remaining = (uint8_t)(batch->count - frame_count);
    drop_bytes = (uint16_t)frame_count * TELEMETRY_BATCH_FRAME_SIZE;
    if (remaining != 0U) {
        memmove(batch->data, batch->data + drop_bytes,
                (uint16_t)remaining * TELEMETRY_BATCH_FRAME_SIZE);
    }
    batch->count = remaining;
    batch->len = (uint16_t)remaining * TELEMETRY_BATCH_FRAME_SIZE;
    return 1U;
}

uint8_t telemetry_batch_drop_at(TelemetryBatch *batch, uint8_t index)
{
    uint8_t remaining;
    uint16_t offset;

    if (batch == 0 || index >= batch->count) return 0U;
    remaining = (uint8_t)(batch->count - index - 1U);
    offset = (uint16_t)index * TELEMETRY_BATCH_FRAME_SIZE;
    if (remaining != 0U) {
        memmove(batch->data + offset,
                batch->data + offset + TELEMETRY_BATCH_FRAME_SIZE,
                (uint16_t)remaining * TELEMETRY_BATCH_FRAME_SIZE);
    }
    batch->count--;
    batch->len = (uint16_t)batch->count * TELEMETRY_BATCH_FRAME_SIZE;
    return 1U;
}
