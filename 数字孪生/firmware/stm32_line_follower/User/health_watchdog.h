#ifndef HEALTH_WATCHDOG_H
#define HEALTH_WATCHDOG_H

#include <stdint.h>

/* ── IWDG 薄层（firmware health baseline，设计 §6.2/§7.2）─────────────
 *
 * PR=IWDG_Prescaler_64（分频 64）、RLR=1249 → 名义 2.0s。
 * STM32F103 LSI 30–60kHz（典型 40kHz）→ 实际范围 [~1333, ~2667]ms，
 * 不得伪称精确 2.000s。喂狗语义：证明上一轮已返回主循环顶部。
 */

#define HEALTH_IWDG_PRESCALER_DIV  64U
#define HEALTH_IWDG_RELOAD_VALUE   1249U
#define HEALTH_IWDG_NOMINAL_MS     2000U   /* 64×1250/40kHz */
#define HEALTH_IWDG_MIN_MS         1333U   /* 64×1250/60kHz ≈ 1333.3 */
#define HEALTH_IWDG_MAX_MS         2667U   /* 64×1250/30kHz ≈ 2666.7 */

/* 安全初始化完成、电机已归零、ESP_Setup 阻塞延时结束后调用一次。 */
void iwdg_init_and_enable(void);

/* 主循环每轮迭代顶部调用：IWDG_ReloadCounter()。 */
void iwdg_feed(void);

#endif /* HEALTH_WATCHDOG_H */
