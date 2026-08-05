#ifndef TEST_STM32F10X_H
#define TEST_STM32F10X_H

#include <stdint.h>

typedef enum { DISABLE = 0, ENABLE = 1 } FunctionalState;

typedef struct {
    uint16_t GPIO_Pin;
    uint32_t GPIO_Speed;
    uint32_t GPIO_Mode;
} GPIO_InitTypeDef;

typedef struct {
    uint16_t TIM_Prescaler;
    uint16_t TIM_CounterMode;
    uint16_t TIM_Period;
    uint16_t TIM_ClockDivision;
    uint8_t TIM_RepetitionCounter;
} TIM_TimeBaseInitTypeDef;

typedef struct {
    uint16_t TIM_OCMode;
    uint16_t TIM_OutputState;
    uint16_t TIM_Pulse;
    uint16_t TIM_OCPolarity;
} TIM_OCInitTypeDef;

typedef struct {
    unsigned id;
    uint16_t ccr[4];
    int enabled;
} TIM_TypeDef;

typedef struct { unsigned id; } GPIO_TypeDef;

extern TIM_TypeDef g_test_tim2;
extern TIM_TypeDef g_test_tim4;
extern GPIO_TypeDef g_test_gpioa;
extern GPIO_TypeDef g_test_gpiob;

#define TIM2 (&g_test_tim2)
#define TIM4 (&g_test_tim4)
#define GPIOA (&g_test_gpioa)
#define GPIOB (&g_test_gpiob)

#define RCC_APB1Periph_TIM2 1U
#define RCC_APB1Periph_TIM4 2U
#define RCC_APB2Periph_GPIOA 4U
#define RCC_APB2Periph_GPIOB 8U
#define GPIO_Pin_0  (1U << 0)
#define GPIO_Pin_1  (1U << 1)
#define GPIO_Pin_2  (1U << 2)
#define GPIO_Pin_3  (1U << 3)
#define GPIO_Pin_6  (1U << 6)
#define GPIO_Pin_7  (1U << 7)
#define GPIO_Pin_8  (1U << 8)
#define GPIO_Pin_9  (1U << 9)
#define GPIO_Mode_AF_PP 2U
#define GPIO_Speed_50MHz 50U
#define TIM_CKD_DIV1 0U
#define TIM_CounterMode_Up 0U
#define TIM_OCMode_PWM1 1U
#define TIM_OCPolarity_High 1U
#define TIM_OutputState_Enable 1U

void RCC_APB1PeriphClockCmd(uint32_t peripheral, FunctionalState state);
void RCC_APB2PeriphClockCmd(uint32_t peripheral, FunctionalState state);
void GPIO_Init(GPIO_TypeDef *gpio, GPIO_InitTypeDef *config);
void TIM_InternalClockConfig(TIM_TypeDef *timer);
void TIM_TimeBaseInit(TIM_TypeDef *timer, TIM_TimeBaseInitTypeDef *config);
void TIM_OCStructInit(TIM_OCInitTypeDef *config);
void TIM_OC1Init(TIM_TypeDef *timer, TIM_OCInitTypeDef *config);
void TIM_OC2Init(TIM_TypeDef *timer, TIM_OCInitTypeDef *config);
void TIM_OC3Init(TIM_TypeDef *timer, TIM_OCInitTypeDef *config);
void TIM_OC4Init(TIM_TypeDef *timer, TIM_OCInitTypeDef *config);
void TIM_Cmd(TIM_TypeDef *timer, FunctionalState state);
void TIM_SetCompare1(TIM_TypeDef *timer, uint16_t value);
void TIM_SetCompare2(TIM_TypeDef *timer, uint16_t value);
void TIM_SetCompare3(TIM_TypeDef *timer, uint16_t value);
void TIM_SetCompare4(TIM_TypeDef *timer, uint16_t value);

#endif
