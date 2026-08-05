#ifndef _MOTOR_H_
#define _MOTOR_H_

/*============================================================================
 * 四路直流电机驱动接口（L9110S + TIM2/TIM4硬件PWM）
 *
 * 行驶函数：Car_Forward / Car_Backward / Car_TurnLeft / Car_TurnRight
 *           Car_TransLeft / Car_TransRight（麦轮横行）/ Car_Stop
 * 单电机控制：Motor1~4_SetSpeed(Dir, Speed)
 * Speed范围：0~999
 *============================================================================*/

void Motor_Init(void);
void Car_Stop(void);
void Car_Forward(uint16_t Speed);
void Car_Backward(uint16_t Speed);
void Car_TurnLeft(uint16_t Speed);
void Car_TurnRight(uint16_t Speed);
void Car_TransLeft(uint16_t Speed);
void Car_TransRight(uint16_t Speed);
void Motor1_SetSpeed(uint8_t Dir, uint16_t Speed);
void Motor2_SetSpeed(uint8_t Dir, uint16_t Speed);
void Motor3_SetSpeed(uint8_t Dir, uint16_t Speed);
void Motor4_SetSpeed(uint8_t Dir, uint16_t Speed);

/* 统一输出：m1~m4 可正可负，正值=前进 */
void Motor_Write(int16_t m1, int16_t m2, int16_t m3, int16_t m4);
/* 防止电机疯转 */
void Motor_Prevent_Madness(void);

#endif
