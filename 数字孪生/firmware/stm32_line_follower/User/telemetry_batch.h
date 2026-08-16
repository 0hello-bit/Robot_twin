#ifndef TELEMETRY_BATCH_H
#define TELEMETRY_BATCH_H

#include <stdint.h>
#include "timing_diagnostic.h"

#define TELEMETRY_BATCH_FRAME_SIZE 31U
#define TELEMETRY_BATCH_MAX_FRAMES 16U
#define TELEMETRY_BATCH_SEND_MAX_FRAMES 5U
#define TELEMETRY_BATCH_MAX_BYTES \
    (TELEMETRY_BATCH_FRAME_SIZE * TELEMETRY_BATCH_MAX_FRAMES)
#define TELEMETRY_BATCH_SEND_MAX_BYTES \
    (TELEMETRY_BATCH_FRAME_SIZE * TELEMETRY_BATCH_SEND_MAX_FRAMES)

/* A fixed-size latest-window queue for droppable telemetry frames. */
typedef struct {
    uint8_t data[TELEMETRY_BATCH_MAX_BYTES];
    TelemetryTimingRecord timing[TELEMETRY_BATCH_MAX_FRAMES];
    uint16_t len;
    uint8_t count;
} TelemetryBatch;

void telemetry_batch_init(TelemetryBatch *batch);
void telemetry_batch_clear(TelemetryBatch *batch);

/* Returns 1 on success.  *overwrote is set when the oldest frame was dropped. */
uint8_t telemetry_batch_append(TelemetryBatch *batch,
                               const uint8_t *frame,
                               uint16_t frame_len,
                               uint8_t *overwrote);

/* Append a wire frame together with the stage timestamps that produced it. */
uint8_t telemetry_batch_append_timed(TelemetryBatch *batch,
                                     const uint8_t *frame,
                                     uint16_t frame_len,
                                     const TelemetryTimingRecord *timing,
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
