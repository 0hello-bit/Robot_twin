#ifndef TELEMETRY_BATCH_H
#define TELEMETRY_BATCH_H

#include <stdint.h>

#define TELEMETRY_BATCH_FRAME_SIZE 47U
#define TELEMETRY_BATCH_MAX_FRAMES 16U
#define TELEMETRY_BATCH_SEND_MAX_FRAMES 5U
#define TELEMETRY_BATCH_MAX_BYTES \
    (TELEMETRY_BATCH_FRAME_SIZE * TELEMETRY_BATCH_MAX_FRAMES)
#define TELEMETRY_BATCH_SEND_MAX_BYTES \
    (TELEMETRY_BATCH_FRAME_SIZE * TELEMETRY_BATCH_SEND_MAX_FRAMES)

/* A fixed-size, latest-sixteen queue for droppable telemetry frames. */
typedef struct {
    uint8_t data[TELEMETRY_BATCH_MAX_BYTES];
    uint16_t len;
    uint8_t count;
} TelemetryBatch;

/* Encode one TCP telemetry frame.  The output buffer must hold 47 bytes. */
void telemetry_frame_encode(
    uint8_t *frame,
    int16_t s0, int16_t s1, int16_t s2, int16_t s3,
    int16_t m1, int16_t m2, int16_t m3, int16_t m4,
    int16_t error, int16_t pid_output,
    uint32_t tick, int32_t yaw,
    uint8_t imu_validity, uint8_t imu_init_status,
    int16_t imu_ax, int16_t imu_ay, int16_t imu_az,
    int16_t imu_gx, int16_t imu_gy, int16_t imu_gz,
    uint32_t sample_seq);

void telemetry_batch_init(TelemetryBatch *batch);
void telemetry_batch_clear(TelemetryBatch *batch);

/* Returns 1 on success.  *overwrote is set when the oldest frame was dropped. */
uint8_t telemetry_batch_append(TelemetryBatch *batch,
                               const uint8_t *frame,
                               uint16_t frame_len,
                               uint8_t *overwrote);

uint8_t telemetry_batch_has_data(const TelemetryBatch *batch);
uint8_t telemetry_batch_count(const TelemetryBatch *batch);
uint16_t telemetry_batch_length(const TelemetryBatch *batch);
const uint8_t *telemetry_batch_data(const TelemetryBatch *batch);
void telemetry_batch_consume(TelemetryBatch *batch);

/* Copy at most max_frames from the FIFO head into dst without consuming src. */
uint8_t telemetry_batch_copy_prefix(const TelemetryBatch *src,
                                    TelemetryBatch *dst,
                                    uint8_t max_frames);

/* Remove exactly up to frame_count frames from the FIFO head. */
uint8_t telemetry_batch_drop_prefix(TelemetryBatch *batch,
                                     uint8_t frame_count);

/* Remove one frame at index while preserving the order of the others. */
uint8_t telemetry_batch_drop_at(TelemetryBatch *batch, uint8_t index);

#endif /* TELEMETRY_BATCH_H */
