#include "mono_time_core.h"

uint32_t mono_elapsed_ms(uint32_t prev, uint32_t now)
{
    return (uint32_t)(now - prev);
}

uint32_t mono_clamp_dt_ms(uint32_t dt_ms, uint32_t min_ms, uint32_t max_ms)
{
    if (dt_ms < min_ms) return min_ms;
    if (dt_ms > max_ms) return max_ms;
    return dt_ms;
}

uint8_t mono_is_after_ms(uint32_t now, uint32_t base)
{
    return ((int32_t)(now - base) >= 0) ? 1U : 0U;
}
