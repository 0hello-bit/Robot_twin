#include "health_watchdog.h"
#include "stm32f10x_iwdg.h"

void iwdg_init_and_enable(void)
{
    /* PR=IWDG_Prescaler_64，RLR=1249 → 名义 2.0s；
       LSI 30–60kHz → 实际 [~1.33, ~2.67]s（设计 §7.2）。 */
    IWDG_WriteAccessCmd(IWDG_WriteAccess_Enable);
    IWDG_SetPrescaler(IWDG_Prescaler_64);
    IWDG_SetReload(HEALTH_IWDG_RELOAD_VALUE);
    IWDG_ReloadCounter();
    IWDG_Enable();
}

void iwdg_feed(void)
{
    IWDG_ReloadCounter();
}
