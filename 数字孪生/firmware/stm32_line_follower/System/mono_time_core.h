#ifndef MONO_TIME_CORE_H
#define MONO_TIME_CORE_H

#include <stdint.h>

/* ── Task 4B-4 fix: 32 位单调毫秒纯逻辑（无硬件依赖，可 Host C 测试） ──
 *
 * 固件时间从 `g_loop_count * LOOP_DELAY_MS`（循环计数推演）改为独立的
 * 32 位单调毫秒源（TIM3 1kHz 中断累加，见 mono_time.h）。本模块只包含
 * 与硬件无关的纯时间逻辑：回绕安全差值、边界钳制、截止判断。
 *
 * 单位：毫秒（ms），uint32 回绕周期 = 2^32 ms ≈ 49.7 天。
 * 所有差值均按模 2^32 运算，时间跨度 < 2^31 ms 时结果正确。
 */

/* now - prev（模 2^32），回绕安全。 */
uint32_t mono_elapsed_ms(uint32_t prev, uint32_t now);

/* 把 dt 钳制到 [min_ms, max_ms]（min <= max 且均 > 0）。 */
uint32_t mono_clamp_dt_ms(uint32_t dt_ms, uint32_t min_ms, uint32_t max_ms);

/* now 是否已到/超过 base（回绕安全）：(int32_t)(now - base) >= 0。 */
uint8_t mono_is_after_ms(uint32_t now, uint32_t base);

#endif /* MONO_TIME_CORE_H */
