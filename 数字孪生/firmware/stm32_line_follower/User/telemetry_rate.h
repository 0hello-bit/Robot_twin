#ifndef TELEMETRY_RATE_H
#define TELEMETRY_RATE_H

#include <stdint.h>

#define TELEMETRY_INTERVAL_MS 30U

/* Emit once at the configured interval. A wrapped or regressed clock is
   treated as due so the scheduler cannot stall across uint32 rollover. */
static uint8_t telemetry_rate_due(uint32_t now_ms, uint32_t last_ms)
{
    if (now_ms < last_ms) return 1U;
    return ((uint32_t)(now_ms - last_ms) >= TELEMETRY_INTERVAL_MS) ? 1U : 0U;
}

#endif /* TELEMETRY_RATE_H */
