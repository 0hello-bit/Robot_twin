#ifndef _MPU6050_H_
#define _MPU6050_H_

#include "stm32f10x.h"
#include <stdint.h>

#define MPU6050_ADDR         0x68
#define MPU6050_WHO_AM_I     0x75
#define MPU6050_WHO_AM_I_MPU6050 0x68U
#define MPU6050_WHO_AM_I_MPU6500 0x70U
#define MPU6050_PWR_MGMT_1   0x6B
#define MPU6050_PWR_MGMT_2   0x6C
#define MPU6050_SMPLRT_DIV   0x19
#define MPU6050_CONFIG       0x1A
#define MPU6050_GYRO_CONFIG  0x1B
#define MPU6050_ACCEL_CONFIG 0x1C
#define MPU6050_ACCEL_XOUT_H 0x3B
#define MPU6050_GYRO_XOUT_H  0x43
#define MPU6050_TEMP_OUT_H    0x41

/* Per-boot and per-cycle observability flags carried by telemetry. */
#define MPU6050_VALIDITY_INIT       0x01U
#define MPU6050_VALIDITY_BIAS       0x02U
#define MPU6050_VALIDITY_READ       0x04U
#define MPU6050_VALIDITY_UPDATED    0x08U
#define MPU6050_VALIDITY_DT_CLAMPED 0x10U
#define MPU6050_VALIDITY_FUSION_REQUIRED \
    (MPU6050_VALIDITY_INIT | MPU6050_VALIDITY_BIAS | \
     MPU6050_VALIDITY_READ | MPU6050_VALIDITY_UPDATED)

/* Boot initialization outcome.  The value is retained for this boot and is
   separate from the per-cycle validity bit mask above. */
#define MPU6050_INIT_STATUS_OK                  0x00U
#define MPU6050_INIT_STATUS_NOT_ATTEMPTED       0x01U
#define MPU6050_INIT_STATUS_RESET_WRITE        0x10U
#define MPU6050_INIT_STATUS_WAKE_WRITE         0x11U
#define MPU6050_INIT_STATUS_SAMPLE_RATE_WRITE  0x12U
#define MPU6050_INIT_STATUS_CONFIG_WRITE       0x13U
#define MPU6050_INIT_STATUS_GYRO_CONFIG_WRITE  0x14U
#define MPU6050_INIT_STATUS_ACCEL_CONFIG_WRITE 0x15U
#define MPU6050_INIT_STATUS_WHO_AM_I_READ      0x20U
#define MPU6050_INIT_STATUS_WHO_AM_I_MISMATCH  0x21U
#define MPU6050_INIT_STATUS_BIAS_READ          0x30U

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
/* Read WHO_AM_I once through STM32 hardware I2C2 as a read-only cross-check
   of the existing PB10/PB11 software-I2C path. */
uint8_t MPU6050_ReadHardwareID(void);
uint8_t MPU6050_GetObservedID(void);
uint8_t MPU6050_GetHardwareObservedID(void);
void MPU6050_ReadAll(void);
void MPU6050_UpdateYaw(float dt);
uint8_t MPU6050_GetValidityFlags(void);
uint8_t MPU6050_GetInitStatus(void);
void MPU6050_SetDtClamped(uint8_t clamped);
uint8_t MPU6050_ValidityAllowsFusion(uint8_t flags);

#endif
