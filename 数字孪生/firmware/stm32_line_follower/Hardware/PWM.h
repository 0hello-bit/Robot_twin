#ifndef _PWM_H_
#define _PWM_H_

/*============================================================================
 * 独立PWM模块接口（本项目未使用）
 *
 * 功能：单独控制TIM2_CH3(PA2)和TIM2_CH4(PA3)的PWM输出
 * 注意：与Motor_Init()冲突，不可同时调用
 *============================================================================*/

void PWM_Init(void);
void PWM_SetPrescaler(uint16_t Prescaler);
void PWM_SetCompare3(uint16_t Compare);
void PWM_SetCompare4(uint16_t Compare);
#endif
