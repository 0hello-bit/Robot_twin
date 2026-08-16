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
    return telemetry_delivery_append_timed(delivery, frame, frame_len, 0,
                                           overwrote);
}

uint8_t telemetry_delivery_append_timed(TelemetryDelivery *delivery,
                                        const uint8_t *frame,
                                        uint16_t frame_len,
                                        const TelemetryTimingRecord *timing,
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
    appended = telemetry_batch_append_timed(&delivery->pending, frame,
                                            frame_len, timing,
                                            &appended_overwrote);
    if (overwrote != 0) {
        *overwrote = (uint8_t)(dropped || appended_overwrote);
    }
    return appended;
}

void telemetry_delivery_mark_last_pending_enqueue(
    TelemetryDelivery *delivery, uint32_t now_ms)
{
    uint8_t index;
    if (delivery == 0 || delivery->pending.count == 0U) return;
    index = (uint8_t)(delivery->pending.count - 1U);
    delivery->pending.timing[index].t_enqueue_ms = now_ms;
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

uint8_t telemetry_delivery_prepare_latest(TelemetryDelivery *delivery,
                                           uint8_t *dropped)
{
    uint8_t pending_count;
    uint8_t drop_count = 0U;

    if (dropped != 0) *dropped = 0U;
    if (delivery == 0) return 0U;
    if (delivery->inflight_valid) return 1U;

    pending_count = telemetry_batch_count(&delivery->pending);
    if (pending_count > TELEMETRY_BATCH_SEND_MAX_FRAMES) {
        drop_count = (uint8_t)(pending_count
                               - TELEMETRY_BATCH_SEND_MAX_FRAMES);
        if (!telemetry_batch_drop_prefix(&delivery->pending, drop_count)) {
            return 0U;
        }
    }
    if (!telemetry_batch_copy_prefix(
            &delivery->pending, &delivery->inflight,
            TELEMETRY_BATCH_SEND_MAX_FRAMES)) {
        return 0U;
    }
    delivery->inflight_valid = 1U;
    if (dropped != 0) *dropped = drop_count;
    return 1U;
}

const TelemetryBatch *telemetry_delivery_inflight(
    const TelemetryDelivery *delivery)
{
    if (delivery == 0 || !delivery->inflight_valid) return 0;
    return &delivery->inflight;
}

void telemetry_delivery_mark_inflight_tx_start(TelemetryDelivery *delivery,
                                               uint32_t now_ms)
{
    uint8_t i;
    if (delivery == 0 || !delivery->inflight_valid) return;
    for (i = 0U; i < delivery->inflight.count; i++) {
        delivery->inflight.timing[i].t_tx_start_ms = now_ms;
    }
}

void telemetry_delivery_mark_inflight_send_ok(TelemetryDelivery *delivery,
                                              uint32_t now_ms)
{
    uint8_t i;
    if (delivery == 0 || !delivery->inflight_valid) return;
    for (i = 0U; i < delivery->inflight.count; i++) {
        delivery->inflight.timing[i].t_send_ok_ms = now_ms;
    }
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
