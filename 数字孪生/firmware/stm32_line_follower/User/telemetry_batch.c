#include "telemetry_batch.h"

#include <string.h>

void telemetry_frame_encode(
    uint8_t *frame,
    int16_t s0, int16_t s1, int16_t s2, int16_t s3,
    int16_t m1, int16_t m2, int16_t m3, int16_t m4,
    int16_t error, int16_t pid_output,
    uint32_t tick, int32_t yaw,
    uint8_t imu_validity, uint8_t imu_init_status,
    int16_t imu_ax, int16_t imu_ay, int16_t imu_az,
    int16_t imu_gx, int16_t imu_gy, int16_t imu_gz,
    uint32_t sample_seq)
{
    uint8_t type = 0x01U;
    uint8_t len = 42U;
    uint8_t checksum;
    uint8_t i;
    int32_t yaw_int = yaw;

    if (frame == 0) return;

    frame[4] = (uint8_t)(s0 & 0xFF);
    frame[5] = (uint8_t)(s1 & 0xFF);
    frame[6] = (uint8_t)(s2 & 0xFF);
    frame[7] = (uint8_t)(s3 & 0xFF);
    frame[8] = (uint8_t)(m1 & 0xFF);
    frame[9] = (uint8_t)((m1 >> 8) & 0xFF);
    frame[10] = (uint8_t)(m2 & 0xFF);
    frame[11] = (uint8_t)((m2 >> 8) & 0xFF);
    frame[12] = (uint8_t)(m3 & 0xFF);
    frame[13] = (uint8_t)((m3 >> 8) & 0xFF);
    frame[14] = (uint8_t)(m4 & 0xFF);
    frame[15] = (uint8_t)((m4 >> 8) & 0xFF);
    frame[16] = (uint8_t)(error & 0xFF);
    frame[17] = (uint8_t)((error >> 8) & 0xFF);
    frame[18] = (uint8_t)(pid_output & 0xFF);
    frame[19] = (uint8_t)((pid_output >> 8) & 0xFF);
    frame[20] = (uint8_t)(tick & 0xFF);
    frame[21] = (uint8_t)((tick >> 8) & 0xFF);
    frame[22] = (uint8_t)((tick >> 16) & 0xFF);
    frame[23] = (uint8_t)((tick >> 24) & 0xFF);
    frame[24] = (uint8_t)(yaw_int & 0xFF);
    frame[25] = (uint8_t)((yaw_int >> 8) & 0xFF);
    frame[26] = (uint8_t)((yaw_int >> 16) & 0xFF);
    frame[27] = (uint8_t)((yaw_int >> 24) & 0xFF);
    frame[28] = imu_validity;
    frame[29] = imu_init_status;
    frame[30] = (uint8_t)(imu_ax & 0xFF);
    frame[31] = (uint8_t)((imu_ax >> 8) & 0xFF);
    frame[32] = (uint8_t)(imu_ay & 0xFF);
    frame[33] = (uint8_t)((imu_ay >> 8) & 0xFF);
    frame[34] = (uint8_t)(imu_az & 0xFF);
    frame[35] = (uint8_t)((imu_az >> 8) & 0xFF);
    frame[36] = (uint8_t)(imu_gx & 0xFF);
    frame[37] = (uint8_t)((imu_gx >> 8) & 0xFF);
    frame[38] = (uint8_t)(imu_gy & 0xFF);
    frame[39] = (uint8_t)((imu_gy >> 8) & 0xFF);
    frame[40] = (uint8_t)(imu_gz & 0xFF);
    frame[41] = (uint8_t)((imu_gz >> 8) & 0xFF);
    frame[42] = (uint8_t)(sample_seq & 0xFF);
    frame[43] = (uint8_t)((sample_seq >> 8) & 0xFF);
    frame[44] = (uint8_t)((sample_seq >> 16) & 0xFF);
    frame[45] = (uint8_t)((sample_seq >> 24) & 0xFF);

    checksum = type ^ len;
    for (i = 4U; i < 46U; i++) checksum ^= frame[i];

    frame[0] = 0xAAU;
    frame[1] = 0x55U;
    frame[2] = type;
    frame[3] = len;
    frame[46] = checksum;
}

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
        /* Keep the latest sixteen frames; the queue is intentionally droppable. */
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
