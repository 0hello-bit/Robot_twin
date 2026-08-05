#ifndef MONO_TIME_H
#define MONO_TIME_H

#include <stdint.h>

/* ── Task 4B-4 fix: 真实单调毫秒时钟源 ─────────────────────────────
 *
 * 背景：旧固件时间 = `g_loop_count * LOOP_DELAY_MS`，依赖主循环节奏；
 * CIPSEND 阻塞时 tick 不按真实时间推进（review 事实 #2），导致 PC 端
 * ClockSync 失效。
 *
 * 本模块用 TIM3 产生 1kHz 更新中断，累加 32 位单调毫秒计数器：
 *   - 独立于主循环和 Delay_ms()（Delay_ms 复用 SysTick 轮询，二者互不干扰）
 *   - TIM3 在项目外设占用扫描中未被应用使用（Motor 用 TIM2/TIM4，无 TIM3）
 *   - uint32 回绕周期 ≈ 49.7 天；差值用回绕安全运算（mono_time_core）
 */

/* 初始化 TIM3 1kHz 更新中断并清零单调毫秒计数。开机调用一次。 */
void mono_time_init(void);

/* 当前单调毫秒（uint32 ms）。 */
uint32_t mono_now_ms(void);

#endif /* MONO_TIME_H */
