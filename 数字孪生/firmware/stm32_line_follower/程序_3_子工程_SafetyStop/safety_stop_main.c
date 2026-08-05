#include "stm32f10x.h"

/*
 * Temporary safety firmware.
 *
 * The four motor drivers are controlled by:
 *   TIM2_CH1..CH4 -> PA0..PA3
 *   TIM4_CH1..CH4 -> PB6..PB9
 *
 * Both control inputs of every motor are forced low.  No sensor, Wi-Fi,
 * IMU, or motion-control code is started.
 */
static void MotorPins_ForceLow(void)
{
    GPIO_InitTypeDef gpio;

    RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM2 |
                           RCC_APB1Periph_TIM4, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA |
                           RCC_APB2Periph_GPIOB, ENABLE);

    TIM_Cmd(TIM2, DISABLE);
    TIM_Cmd(TIM4, DISABLE);
    TIM_DeInit(TIM2);
    TIM_DeInit(TIM4);

    GPIO_ResetBits(GPIOA, GPIO_Pin_0 | GPIO_Pin_1 |
                          GPIO_Pin_2 | GPIO_Pin_3);
    GPIO_ResetBits(GPIOB, GPIO_Pin_6 | GPIO_Pin_7 |
                          GPIO_Pin_8 | GPIO_Pin_9);

    GPIO_StructInit(&gpio);
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Speed = GPIO_Speed_2MHz;

    gpio.GPIO_Pin = GPIO_Pin_0 | GPIO_Pin_1 |
                    GPIO_Pin_2 | GPIO_Pin_3;
    GPIO_Init(GPIOA, &gpio);

    gpio.GPIO_Pin = GPIO_Pin_6 | GPIO_Pin_7 |
                    GPIO_Pin_8 | GPIO_Pin_9;
    GPIO_Init(GPIOB, &gpio);

    GPIO_ResetBits(GPIOA, GPIO_Pin_0 | GPIO_Pin_1 |
                          GPIO_Pin_2 | GPIO_Pin_3);
    GPIO_ResetBits(GPIOB, GPIO_Pin_6 | GPIO_Pin_7 |
                          GPIO_Pin_8 | GPIO_Pin_9);
}

int main(void)
{
    __disable_irq();
    MotorPins_ForceLow();

    while (1)
    {
        GPIO_ResetBits(GPIOA, GPIO_Pin_0 | GPIO_Pin_1 |
                              GPIO_Pin_2 | GPIO_Pin_3);
        GPIO_ResetBits(GPIOB, GPIO_Pin_6 | GPIO_Pin_7 |
                              GPIO_Pin_8 | GPIO_Pin_9);
    }
}
