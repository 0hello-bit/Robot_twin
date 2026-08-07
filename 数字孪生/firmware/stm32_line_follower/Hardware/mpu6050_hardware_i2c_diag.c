#include "mpu6050.h"
#include "stm32f10x_i2c.h"

/* Independent read-only cross-check on the same PB10/PB11 pins. */
#define MPU6050_HW_I2C_TIMEOUT 100000UL
#define MPU6050_HW_SCL_PIN     GPIO_Pin_10
#define MPU6050_HW_SDA_PIN     GPIO_Pin_11

static uint8_t s_hardware_observed_id;

static uint8_t HardwareI2C_WaitEvent(uint32_t event)
{
    uint32_t timeout = MPU6050_HW_I2C_TIMEOUT;

    while (timeout-- > 0UL) {
        if (I2C_CheckEvent(I2C2, event) == SUCCESS) return 1U;
        if (I2C_GetFlagStatus(I2C2, I2C_FLAG_AF) == SET ||
            I2C_GetFlagStatus(I2C2, I2C_FLAG_ARLO) == SET ||
            I2C_GetFlagStatus(I2C2, I2C_FLAG_BERR) == SET ||
            I2C_GetFlagStatus(I2C2, I2C_FLAG_OVR) == SET) {
            return 0U;
        }
    }
    return 0U;
}

static void HardwareI2C_Stop(void)
{
    I2C_GenerateSTOP(I2C2, ENABLE);
    I2C_AcknowledgeConfig(I2C2, ENABLE);
    I2C_Cmd(I2C2, DISABLE);
    I2C_DeInit(I2C2);
}

/* This function must remain read-only: it is evidence collection, not an
   alternate initialization path. The normal software-I2C driver runs after
   this function and owns the pins for the rest of the application. */
uint8_t MPU6050_ReadHardwareID(void)
{
    GPIO_InitTypeDef gpio;
    I2C_InitTypeDef i2c;
    uint8_t id = 0U;
    uint8_t ok = 0U;

    s_hardware_observed_id = 0U;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB | RCC_APB2Periph_AFIO,
                           ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_I2C2, ENABLE);

    gpio.GPIO_Pin = MPU6050_HW_SCL_PIN | MPU6050_HW_SDA_PIN;
    gpio.GPIO_Mode = GPIO_Mode_AF_OD;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOB, &gpio);

    I2C_DeInit(I2C2);
    I2C_StructInit(&i2c);
    i2c.I2C_ClockSpeed = 100000UL;
    i2c.I2C_Mode = I2C_Mode_I2C;
    i2c.I2C_DutyCycle = I2C_DutyCycle_2;
    i2c.I2C_OwnAddress1 = 0U;
    i2c.I2C_Ack = I2C_Ack_Enable;
    i2c.I2C_AcknowledgedAddress = I2C_AcknowledgedAddress_7bit;
    I2C_Init(I2C2, &i2c);
    I2C_Cmd(I2C2, ENABLE);

    I2C_GenerateSTART(I2C2, ENABLE);
    if (!HardwareI2C_WaitEvent(I2C_EVENT_MASTER_MODE_SELECT)) goto cleanup;
    I2C_Send7bitAddress(I2C2, (uint8_t)(MPU6050_ADDR << 1),
                        I2C_Direction_Transmitter);
    if (!HardwareI2C_WaitEvent(
            I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED)) goto cleanup;
    I2C_SendData(I2C2, MPU6050_WHO_AM_I);
    if (!HardwareI2C_WaitEvent(I2C_EVENT_MASTER_BYTE_TRANSMITTED))
        goto cleanup;

    I2C_GenerateSTART(I2C2, ENABLE);
    if (!HardwareI2C_WaitEvent(I2C_EVENT_MASTER_MODE_SELECT)) goto cleanup;
    I2C_Send7bitAddress(I2C2, (uint8_t)((MPU6050_ADDR << 1) | 1U),
                        I2C_Direction_Receiver);
    if (!HardwareI2C_WaitEvent(
            I2C_EVENT_MASTER_RECEIVER_MODE_SELECTED)) goto cleanup;

    I2C_AcknowledgeConfig(I2C2, DISABLE);
    I2C_GenerateSTOP(I2C2, ENABLE);
    if (!HardwareI2C_WaitEvent(I2C_EVENT_MASTER_BYTE_RECEIVED)) goto cleanup;
    id = I2C_ReceiveData(I2C2);
    ok = 1U;

cleanup:
    HardwareI2C_Stop();
    if (ok) s_hardware_observed_id = id;
    return ok;
}

uint8_t MPU6050_GetHardwareObservedID(void)
{
    return s_hardware_observed_id;
}
