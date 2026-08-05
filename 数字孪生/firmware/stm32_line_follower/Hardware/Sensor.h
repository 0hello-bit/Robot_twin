#ifndef _SENSOR_H_
#define _SENSOR_H_

/*============================================================================
 * 红外巡线传感器接口（TCRT5000型，4路）
 *
 * 引脚：PB1=最左, PB0=左中, PB4=右中, PB5=最右
 * 每个传感器返回0或1（1=白底，0=黑线，以实际传感器为准）
 *
 * 典型4路巡线组合：
 *   1 0 0 1 → 直行    1 1 0 1 → 右转
 *   1 1 1 0 → 急右转  1 0 1 1 → 左转
 *   0 1 1 1 → 急左转  1 1 1 1 → 出线
 *============================================================================*/

void Sensor_Init(void);
uint8_t Sensor0_Get_State(void);
uint8_t Sensor1_Get_State(void);
uint8_t Sensor2_Get_State(void);
uint8_t Sensor3_Get_State(void);
#endif
