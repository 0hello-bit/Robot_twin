#include "telemetry_delivery.h"

void telemetry_delivery_init(TelemetryDelivery *delivery)
{
    if (delivery == 0) return;
    telemetry_batch_init(&delivery->pending);
    telemetry_batch_init(&delivery->inflight);
    delivery->inflight_valid = 0U;
}

void telemetry_delivery_clear(TelemetryDelivery *delivery)
{
    if (delivery == 0) return;
    telemetry_batch_clear(&delivery->pending);
    telemetry_batch_clear(&delivery->inflight);
    delivery->inflight_valid = 0U;
}

uint8_t telemetry_delivery_append(TelemetryDelivery *delivery,
                                  const uint8_t *frame,
                                  uint16_t frame_len,
                                  uint8_t *overwrote)
{
    uint8_t dropped = 0U;
    uint8_t appended_overwrote = 0U;
    uint8_t protected_count;
    uint8_t pending_count;
    uint8_t appended;

    if (delivery == 0) {
        if (overwrote != 0) *overwrote = 0U;
        return 0U;
    }
    if (delivery->inflight_valid
        && telemetry_batch_count(&delivery->pending)
               >= TELEMETRY_BATCH_MAX_FRAMES) {
        protected_count = telemetry_batch_count(&delivery->inflight);
        pending_count = telemetry_batch_count(&delivery->pending);
        if (protected_count >= pending_count) {
            if (overwrote != 0) *overwrote = 1U;
            return 0U;
        }
        dropped = telemetry_batch_drop_at(&delivery->pending,
                                          protected_count);
    }
    appended = telemetry_batch_append(&delivery->pending, frame, frame_len,
                                      &appended_overwrote);
    if (overwrote != 0) {
        *overwrote = (uint8_t)(dropped || appended_overwrote);
    }
    return appended;
}

uint8_t telemetry_delivery_has_data(const TelemetryDelivery *delivery)
{
    if (delivery == 0) return 0U;
    return (delivery->inflight_valid
            || telemetry_batch_has_data(&delivery->pending)) ? 1U : 0U;
}

uint8_t telemetry_delivery_prepare(TelemetryDelivery *delivery)
{
    if (delivery == 0) return 0U;
    if (delivery->inflight_valid) return 1U;
    if (!telemetry_batch_copy_prefix(
            &delivery->pending, &delivery->inflight,
            TELEMETRY_BATCH_SEND_MAX_FRAMES)) {
        return 0U;
    }
    delivery->inflight_valid = 1U;
    return 1U;
}

const TelemetryBatch *telemetry_delivery_inflight(
    const TelemetryDelivery *delivery)
{
    if (delivery == 0 || !delivery->inflight_valid) return 0;
    return &delivery->inflight;
}

void telemetry_delivery_commit_success(TelemetryDelivery *delivery)
{
    uint8_t count;
    if (delivery == 0 || !delivery->inflight_valid) return;
    count = telemetry_batch_count(&delivery->inflight);
    (void)telemetry_batch_drop_prefix(&delivery->pending, count);
    telemetry_batch_clear(&delivery->inflight);
    delivery->inflight_valid = 0U;
}

void telemetry_delivery_retain_failure(TelemetryDelivery *delivery)
{
    /* The in-flight copy intentionally remains owned by this delivery queue. */
    (void)delivery;
}
