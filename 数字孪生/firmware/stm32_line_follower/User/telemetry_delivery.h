#ifndef TELEMETRY_DELIVERY_H
#define TELEMETRY_DELIVERY_H

#include <stdint.h>

#include "telemetry_batch.h"

/* Explicit ownership for droppable telemetry:
 * pending remains authoritative until a SEND OK commits its prefix;
 * inflight is a stable copy used by the current CIPSEND transaction. */
typedef struct {
    TelemetryBatch pending;
    TelemetryBatch inflight;
    uint8_t inflight_valid;
} TelemetryDelivery;

void telemetry_delivery_init(TelemetryDelivery *delivery);
void telemetry_delivery_clear(TelemetryDelivery *delivery);

uint8_t telemetry_delivery_append(TelemetryDelivery *delivery,
                                  const uint8_t *frame,
                                  uint16_t frame_len,
                                  uint8_t *overwrote);
uint8_t telemetry_delivery_has_data(const TelemetryDelivery *delivery);

/* Prepare one <=248-byte CIPSEND payload without consuming pending data. */
uint8_t telemetry_delivery_prepare(TelemetryDelivery *delivery);
const TelemetryBatch *telemetry_delivery_inflight(
    const TelemetryDelivery *delivery);

/* SEND OK commits exactly the prepared prefix. */
void telemetry_delivery_commit_success(TelemetryDelivery *delivery);

/* ERROR, busy, or timeout retains the prepared payload for retry. */
void telemetry_delivery_retain_failure(TelemetryDelivery *delivery);

#endif /* TELEMETRY_DELIVERY_H */
