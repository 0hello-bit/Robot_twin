#include "stm32f10x.h"                  // Device header

/******************************************************************************
 * 红外巡线传感器驱动（TCRT5000型，4路）
 *
 * 引脚分配：
 *   PB1 → Sensor0（最左侧）
 *   PB0 → Sensor1（左中）
 *   PB4 → Sensor2（右中）
 *   PB5 → Sensor3（最右侧）
 *
 * 注意：实际传感器输出极性请以实物为准，代码注释为1=白底/0=黑线
 ******************************************************************************/

/*
	SENSOR0(B1)  SENSOR1(B0)  SENSOR2(B4)  SENSOR3(B5)
*/
void Sensor_Init()
{
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);
	
	GPIO_InitTypeDef GPIO_InitStructure;
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_0|GPIO_Pin_1|GPIO_Pin_4|GPIO_Pin_5;
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU;
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
	GPIO_Init(GPIOB, &GPIO_InitStructure);
}

/* 读取最左侧传感器（PB1）状态 */
uint8_t Sensor0_Get_State()
{
	return GPIO_ReadInputDataBit(GPIOB,GPIO_Pin_1);
}

/* 读取左中传感器（PB0）状态 */
uint8_t Sensor1_Get_State()
{
	return GPIO_ReadInputDataBit(GPIOB,GPIO_Pin_0);
}

/* 读取右中传感器（PB4）状态 */
uint8_t Sensor2_Get_State()
{
	return GPIO_ReadInputDataBit(GPIOB,GPIO_Pin_4);
}

/* 读取最右侧传感器（PB5）状态 */
uint8_t Sensor3_Get_State()
{
	return GPIO_ReadInputDataBit(GPIOB,GPIO_Pin_5);
}
