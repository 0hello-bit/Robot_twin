#include "stm32f10x.h"
#include "Motor.h"

#define M1_DIR  0
#define M2_DIR  0
#define M3_DIR  0
#define M4_DIR  0

enum {
    MOTOR_PWM_MAX = 999,
    MOTOR_PWM_PERIOD_COUNTS = MOTOR_PWM_MAX + 1,
    MOTOR_PWM_PRESCALER_COUNTS = 72
};

static void _MotorSet(int ch, int speed)
{
    if (speed > MOTOR_PWM_MAX) speed = MOTOR_PWM_MAX;
    if (speed < -MOTOR_PWM_MAX) speed = -MOTOR_PWM_MAX;

    uint8_t dir;
    uint16_t pwm = (speed < 0) ? (uint16_t)(-speed) : (uint16_t)speed;

    switch (ch) {
        case 1:
            dir = (M1_DIR) ? (speed >= 0) : (speed < 0);
            if (dir) { TIM_SetCompare2(TIM2, 0); TIM_SetCompare1(TIM2, pwm); }
            else     { TIM_SetCompare1(TIM2, 0); TIM_SetCompare2(TIM2, pwm); }
            break;
        case 2:
            dir = (M2_DIR) ? (speed >= 0) : (speed < 0);
            if (dir) { TIM_SetCompare3(TIM2, 0); TIM_SetCompare4(TIM2, pwm); }
            else     { TIM_SetCompare4(TIM2, 0); TIM_SetCompare3(TIM2, pwm); }
            break;
        case 3:
            dir = (M3_DIR) ? (speed >= 0) : (speed < 0);
            if (dir) { TIM_SetCompare1(TIM4, 0); TIM_SetCompare2(TIM4, pwm); }
            else     { TIM_SetCompare2(TIM4, 0); TIM_SetCompare1(TIM4, pwm); }
            break;
        case 4:
            dir = (M4_DIR) ? (speed >= 0) : (speed < 0);
            if (dir) { TIM_SetCompare4(TIM4, 0); TIM_SetCompare3(TIM4, pwm); }
            else     { TIM_SetCompare3(TIM4, 0); TIM_SetCompare4(TIM4, pwm); }
            break;
    }
}

void Motor_Init(void)
{
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM2, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);

    GPIO_InitTypeDef g;
    g.GPIO_Mode = GPIO_Mode_AF_PP;
    g.GPIO_Pin = GPIO_Pin_0 | GPIO_Pin_1 | GPIO_Pin_2 | GPIO_Pin_3;
    g.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOA, &g);

    TIM_TimeBaseInitTypeDef t;
    TIM_InternalClockConfig(TIM2);
    t.TIM_ClockDivision = TIM_CKD_DIV1;
    t.TIM_CounterMode = TIM_CounterMode_Up;
    t.TIM_Period = MOTOR_PWM_PERIOD_COUNTS - 1;
    t.TIM_Prescaler = MOTOR_PWM_PRESCALER_COUNTS - 1;
    t.TIM_RepetitionCounter = 0;
    TIM_TimeBaseInit(TIM2, &t);

    TIM_OCInitTypeDef o;
    TIM_OCStructInit(&o);
    o.TIM_OCMode = TIM_OCMode_PWM1;
    o.TIM_OCPolarity = TIM_OCPolarity_High;
    o.TIM_OutputState = TIM_OutputState_Enable;
    o.TIM_Pulse = 0;
    TIM_OC1Init(TIM2, &o); TIM_OC2Init(TIM2, &o);
    TIM_OC3Init(TIM2, &o); TIM_OC4Init(TIM2, &o);
    TIM_Cmd(TIM2, ENABLE);

    RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM4, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);

    g.GPIO_Mode = GPIO_Mode_AF_PP;
    g.GPIO_Pin = GPIO_Pin_6 | GPIO_Pin_7 | GPIO_Pin_8 | GPIO_Pin_9;
    g.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOB, &g);

    TIM_InternalClockConfig(TIM4);
    t.TIM_Period = MOTOR_PWM_PERIOD_COUNTS - 1;
    t.TIM_Prescaler = MOTOR_PWM_PRESCALER_COUNTS - 1;
    TIM_TimeBaseInit(TIM4, &t);

    TIM_OCStructInit(&o);
    o.TIM_OCMode = TIM_OCMode_PWM1;
    o.TIM_OCPolarity = TIM_OCPolarity_High;
    o.TIM_OutputState = TIM_OutputState_Enable;
    o.TIM_Pulse = 0;
    TIM_OC1Init(TIM4, &o); TIM_OC2Init(TIM4, &o);
    TIM_OC3Init(TIM4, &o); TIM_OC4Init(TIM4, &o);
    TIM_Cmd(TIM4, ENABLE);
}

void Motor_Write(int16_t m1, int16_t m2, int16_t m3, int16_t m4)
{
    _MotorSet(1, m1);
    _MotorSet(2, m2);
    _MotorSet(3, m3);
    _MotorSet(4, m4);
}

void Motor1_SetSpeed(uint8_t Dir, uint16_t Speed) { _MotorSet(1, Dir ? -(int)Speed : (int)Speed); }
void Motor2_SetSpeed(uint8_t Dir, uint16_t Speed) { _MotorSet(2, Dir ? -(int)Speed : (int)Speed); }
void Motor3_SetSpeed(uint8_t Dir, uint16_t Speed) { _MotorSet(3, Dir ? -(int)Speed : (int)Speed); }
void Motor4_SetSpeed(uint8_t Dir, uint16_t Speed) { _MotorSet(4, Dir ? -(int)Speed : (int)Speed); }

void Car_Stop(void)    { Motor_Write(0, 0, 0, 0); }
void Car_Forward(uint16_t s)  { Motor_Write(s, s, s, s); }
void Car_Backward(uint16_t s) { Motor_Write(-(int)s, -(int)s, -(int)s, -(int)s); }
void Car_TurnLeft(uint16_t s)  { Motor_Write(-(int)s, (int)s, (int)s, -(int)s); }
void Car_TurnRight(uint16_t s) { Motor_Write((int)s, -(int)s, -(int)s, (int)s); }
void Car_TransLeft(uint16_t s) { Motor_Write(-(int)s, (int)s, -(int)s, (int)s); }
void Car_TransRight(uint16_t s){ Motor_Write((int)s, -(int)s, (int)s, -(int)s); }

void Motor_Prevent_Madness(void)
{
    Motor_Write(0, 0, 0, 0);
}
