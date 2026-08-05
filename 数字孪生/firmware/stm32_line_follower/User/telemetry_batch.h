#ifndef TELEMETRY_BATCH_H
#define TELEMETRY_BATCH_H

#include <stdint.h>

#define TELEMETRY_BATCH_FRAME_SIZE 29U
#define TELEMETRY_BATCH_MAX_FRAMES 3U
#define TELEMETRY_BATCH_MAX_BYTES \
    (TELEMETRY_BATCH_FRAME_SIZE * TELEMETRY_BATCH_MAX_FRAMES)

/* A fixed-size, latest-three queue for droppable telemetry frames. */
typedef struct {
    uint8_t data[TELEMETRY_BATCH_MAX_BYTES];
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

uint8_t telemetry_batch_has_data(const TelemetryBatch *batch);
uint8_t telemetry_batch_count(const TelemetryBatch *batch);
uint16_t telemetry_batch_length(const TelemetryBatch *batch);
const uint8_t *telemetry_batch_data(const TelemetryBatch *batch);
void telemetry_batch_consume(TelemetryBatch *batch);

#endif /* TELEMETRY_BATCH_H */
