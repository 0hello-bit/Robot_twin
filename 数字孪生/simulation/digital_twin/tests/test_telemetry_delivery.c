#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "telemetry_delivery.h"

static void make_frame(uint8_t *frame, uint8_t value)
{
    uint16_t i;
    for (i = 0U; i < TELEMETRY_BATCH_FRAME_SIZE; i++) {
        frame[i] = value;
    }
}

static void append_value(TelemetryDelivery *delivery, uint8_t value)
{
    uint8_t frame[TELEMETRY_BATCH_FRAME_SIZE];
    uint8_t overwritten = 0xA5U;
    make_frame(frame, value);
    assert(telemetry_delivery_append(delivery, frame, sizeof(frame),
                                     &overwritten) == 1U);
}

static void test_success_consumes_only_the_committed_prefix(void)
{
    TelemetryDelivery delivery;
    const TelemetryBatch *inflight;

    telemetry_delivery_init(&delivery);
    append_value(&delivery, 0x11U);
    append_value(&delivery, 0x22U);
    append_value(&delivery, 0x33U);
    append_value(&delivery, 0x44U);
    append_value(&delivery, 0x55U);
    append_value(&delivery, 0x66U);
    append_value(&delivery, 0x77U);
    append_value(&delivery, 0x88U);
    append_value(&delivery, 0x99U);
    append_value(&delivery, 0xAAU);

    assert(telemetry_delivery_prepare(&delivery) == 1U);
    inflight = telemetry_delivery_inflight(&delivery);
    assert(inflight != 0);
    assert(telemetry_batch_count(inflight) == 5U);
    assert(telemetry_batch_data(inflight)[0] == 0x11U);
    assert(telemetry_batch_count(&delivery.pending) == 10U);

    telemetry_delivery_commit_success(&delivery);
    assert(telemetry_batch_count(&delivery.pending) == 5U);
    assert(telemetry_batch_data(&delivery.pending)[0] == 0x66U);
    assert(telemetry_delivery_inflight(&delivery) == 0);
}

static void test_failure_retains_same_inflight_payload_without_duplication(void)
{
    TelemetryDelivery delivery;
    const TelemetryBatch *first;
    const TelemetryBatch *retry;

    telemetry_delivery_init(&delivery);
    append_value(&delivery, 0x31U);
    append_value(&delivery, 0x32U);
    append_value(&delivery, 0x33U);
    assert(telemetry_delivery_prepare(&delivery) == 1U);
    first = telemetry_delivery_inflight(&delivery);
    telemetry_delivery_retain_failure(&delivery);
    append_value(&delivery, 0x34U);
    assert(telemetry_delivery_prepare(&delivery) == 1U);
    retry = telemetry_delivery_inflight(&delivery);
    assert(retry != 0);
    assert(telemetry_batch_count(retry) == 3U);
    assert(telemetry_batch_data(retry)[0] == telemetry_batch_data(first)[0]);
    assert(telemetry_batch_data(retry)[2U * TELEMETRY_BATCH_FRAME_SIZE] == 0x33U);
    assert(telemetry_batch_count(&delivery.pending) == 4U);
}

static void test_connection_clear_drops_pending_and_inflight(void)
{
    TelemetryDelivery delivery;

    telemetry_delivery_init(&delivery);
    append_value(&delivery, 0x41U);
    assert(telemetry_delivery_prepare(&delivery) == 1U);
    telemetry_delivery_clear(&delivery);
    assert(telemetry_delivery_has_data(&delivery) == 0U);
    assert(telemetry_delivery_inflight(&delivery) == 0);
    assert(telemetry_batch_count(&delivery.pending) == 0U);
}

static void test_overflow_does_not_drop_inflight_prefix(void)
{
    TelemetryDelivery delivery;
    uint8_t overwritten;
    uint8_t value;

    telemetry_delivery_init(&delivery);
    for (value = 0U; value < TELEMETRY_BATCH_MAX_FRAMES; value++) {
        append_value(&delivery, value);
    }

    assert(telemetry_delivery_prepare(&delivery) == 1U);
    overwritten = 0U;
    append_value(&delivery, 0x10U);
    (void)overwritten;

    /* The five-frame retry prefix must remain in pending.  The oldest
       droppable frame is the first frame after that protected prefix. */
    assert(telemetry_batch_data(&delivery.pending)[0U] == 0x00U);
    assert(telemetry_batch_data(&delivery.pending)[
               4U * TELEMETRY_BATCH_FRAME_SIZE] == 0x04U);
    assert(telemetry_batch_data(&delivery.pending)[
               5U * TELEMETRY_BATCH_FRAME_SIZE] == 0x06U);

    telemetry_delivery_commit_success(&delivery);
    assert(telemetry_batch_count(&delivery.pending) == 11U);
    assert(telemetry_batch_data(&delivery.pending)[0U] == 0x06U);
    assert(telemetry_batch_data(&delivery.pending)[
               10U * TELEMETRY_BATCH_FRAME_SIZE] == 0x10U);
}

int main(void)
{
    test_success_consumes_only_the_committed_prefix();
    test_failure_retains_same_inflight_payload_without_duplication();
    test_connection_clear_drops_pending_and_inflight();
    test_overflow_does_not_drop_inflight_prefix();
    puts("telemetry_delivery: all tests passed");
    return 0;
}
