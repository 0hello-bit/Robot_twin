#ifndef TEST_MPU_STM32F10X_H
#define TEST_MPU_STM32F10X_H

#include <stdint.h>

typedef enum { DISABLE = 0, ENABLE = 1 } FunctionalState;

typedef struct {
    uint16_t GPIO_Pin;
    uint32_t GPIO_Speed;
    uint32_t GPIO_Mode;
} GPIO_InitTypeDef;

typedef struct { unsigned id; } GPIO_TypeDef;

extern GPIO_TypeDef g_test_gpio_b;

#define GPIOB (&g_test_gpio_b)
#define RCC_APB2Periph_GPIOB 1U
#define GPIO_Pin_10 (1U << 10)
#define GPIO_Pin_11 (1U << 11)
#define GPIO_Mode_Out_OD 1U
#define GPIO_Mode_IPU 2U
#define GPIO_Speed_50MHz 50U

void RCC_APB2PeriphClockCmd(uint32_t peripheral, FunctionalState state);
void GPIO_Init(GPIO_TypeDef *gpio, GPIO_InitTypeDef *config);
void GPIO_SetBits(GPIO_TypeDef *gpio, uint16_t pin);
void GPIO_ResetBits(GPIO_TypeDef *gpio, uint16_t pin);
uint8_t GPIO_ReadInputDataBit(GPIO_TypeDef *gpio, uint16_t pin);

#endif
