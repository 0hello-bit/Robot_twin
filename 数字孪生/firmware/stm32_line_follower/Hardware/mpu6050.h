#ifndef _MPU6050_H_
#define _MPU6050_H_

#include "stm32f10x.h"
#include <stdint.h>

#define MPU6050_ADDR         0x68
#define MPU6050_WHO_AM_I     0x75
#define MPU6050_PWR_MGMT_1   0x6B
#define MPU6050_PWR_MGMT_2   0x6C
#define MPU6050_SMPLRT_DIV   0x19
#define MPU6050_CONFIG       0x1A
#define MPU6050_GYRO_CONFIG  0x1B
#define MPU6050_ACCEL_CONFIG 0x1C
#define MPU6050_ACCEL_XOUT_H 0x3B
#define MPU6050_GYRO_XOUT_H  0x43
#define MPU6050_TEMP_OUT_H    0x41

typedef struct {
    int16_t ax, ay, az;
    int16_t gx, gy, gz;
    int16_t gz_bias;
    float yaw;
    uint8_t ready;
} MPU6050_Data;

extern MPU6050_Data mpu_data;

void MPU6050_Init(void);
uint8_t MPU6050_ReadID(void);
void MPU6050_ReadAll(void);
void MPU6050_UpdateYaw(float dt);

#endif
