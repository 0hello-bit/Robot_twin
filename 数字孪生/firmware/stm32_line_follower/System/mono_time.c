#include "stm32f10x.h"
#include "mono_time.h"

/* 32 位单调毫秒计数器（TIM3 1kHz 更新中断累加）。 */
static volatile uint32_t g_mono_ms = 0U;

void mono_time_init(void)
{
    TIM_TimeBaseInitTypeDef t;
    NVIC_InitTypeDef nvic;

    /* TIM3 在 APB1；系统 72MHz（SYSCLK_FREQ_72MHz），APB1 分频 2 时
       TIM3CLK = 72MHz。PSC=71 → 1MHz 计数，ARR=999 → 1ms 更新中断。 */
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM3, ENABLE);

    t.TIM_Prescaler = 72U - 1U;
    t.TIM_CounterMode = TIM_CounterMode_Up;
    t.TIM_Period = 1000U - 1U;
    t.TIM_ClockDivision = TIM_CKD_DIV1;
    t.TIM_RepetitionCounter = 0U;
    TIM_TimeBaseInit(TIM3, &t);

    TIM_ClearFlag(TIM3, TIM_FLAG_Update);
    TIM_ITConfig(TIM3, TIM_IT_Update, ENABLE);

    nvic.NVIC_IRQChannel = TIM3_IRQn;
    nvic.NVIC_IRQChannelPreemptionPriority = 1U;
    nvic.NVIC_IRQChannelSubPriority = 0U;
    nvic.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&nvic);

    g_mono_ms = 0U;
    TIM_Cmd(TIM3, ENABLE);
}

uint32_t mono_now_ms(void)
{
    return g_mono_ms;
}

/* TIM3 1kHz 更新中断：单调毫秒累加。 */
void TIM3_IRQHandler(void)
{
    if (TIM_GetITStatus(TIM3, TIM_IT_Update) != RESET) {
        TIM_ClearITPendingBit(TIM3, TIM_IT_Update);
        g_mono_ms++;
    }
}
