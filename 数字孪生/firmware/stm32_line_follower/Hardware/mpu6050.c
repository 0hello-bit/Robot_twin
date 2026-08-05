#include "mpu6050.h"
#include "Delay.h"

/* I2C2: PB10=SCL, PB11=SDA */
#define SCL_PORT  GPIOB
#define SCL_PIN   GPIO_Pin_10
#define SDA_PORT  GPIOB
#define SDA_PIN   GPIO_Pin_11

MPU6050_Data mpu_data;

/* ---- 软件I2C ---- */
static void SDA_OUT(void)
{
    GPIO_InitTypeDef g;
    g.GPIO_Pin = SDA_PIN;
    g.GPIO_Mode = GPIO_Mode_Out_OD;
    g.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(SDA_PORT, &g);
}
static void SDA_IN(void)
{
    GPIO_InitTypeDef g;
    g.GPIO_Pin = SDA_PIN;
    g.GPIO_Mode = GPIO_Mode_IPU;
    g.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(SDA_PORT, &g);
}
static void SCL_H(void) { GPIO_SetBits(SCL_PORT, SCL_PIN); }
static void SCL_L(void) { GPIO_ResetBits(SCL_PORT, SCL_PIN); }
static void SDA_H(void) { GPIO_SetBits(SDA_PORT, SDA_PIN); }
static void SDA_L(void) { GPIO_ResetBits(SDA_PORT, SDA_PIN); }
static uint8_t SDA_R(void) { return GPIO_ReadInputDataBit(SDA_PORT, SDA_PIN); }

static void i2c_delay(void)
{
    volatile uint8_t i = 10;
    while (i--);
}

static void i2c_start(void)
{
    SDA_OUT();
    SDA_H(); SCL_H(); i2c_delay();
    SDA_L(); i2c_delay();
    SCL_L(); i2c_delay();
}

static void i2c_stop(void)
{
    SDA_OUT();
    SCL_L(); i2c_delay();
    SDA_L(); i2c_delay();
    SCL_H(); i2c_delay();
    SDA_H(); i2c_delay();
}

static void i2c_ack(void)
{
    SCL_L(); i2c_delay();
    SDA_OUT();
    SDA_L(); i2c_delay();
    SCL_H(); i2c_delay();
    SCL_L(); i2c_delay();
}

static void i2c_nack(void)
{
    SCL_L(); i2c_delay();
    SDA_OUT();
    SDA_H(); i2c_delay();
    SCL_H(); i2c_delay();
    SCL_L(); i2c_delay();
}

static uint8_t i2c_wait_ack(void)
{
    uint32_t timeout = 1000;
    uint8_t ack;
    SDA_IN();
    SCL_H(); i2c_delay();
    while (SDA_R() && timeout--) {
        i2c_delay();
    }
    ack = SDA_R() ? 0 : 1;
    SCL_L(); i2c_delay();
    return ack;
}

static void i2c_write_byte(uint8_t data)
{
    uint8_t i;
    SDA_OUT();
    SCL_L();
    for (i = 0; i < 8; i++) {
        if (data & 0x80) SDA_H(); else SDA_L();
        data <<= 1;
        i2c_delay();
        SCL_H(); i2c_delay();
        SCL_L(); i2c_delay();
    }
}

static uint8_t i2c_read_byte(uint8_t ack)
{
    uint8_t i, val = 0;
    SDA_IN();
    for (i = 0; i < 8; i++) {
        SCL_L(); i2c_delay();
        SCL_H(); i2c_delay();
        val <<= 1;
        if (SDA_R()) val |= 1;
    }
    if (ack) i2c_ack(); else i2c_nack();
    return val;
}

/* ---- MPU6050 寄存器读写 ---- */
static uint8_t MPU6050_WriteReg(uint8_t reg, uint8_t val)
{
    uint8_t ok = 1;
    i2c_start();
    i2c_write_byte(MPU6050_ADDR << 1);
    ok &= i2c_wait_ack();
    i2c_write_byte(reg);
    ok &= i2c_wait_ack();
    i2c_write_byte(val);
    ok &= i2c_wait_ack();
    i2c_stop();
    return ok;
}

static uint8_t MPU6050_ReadReg(uint8_t reg, uint8_t *value)
{
    uint8_t val = 0;
    uint8_t ok = 1;
    i2c_start();
    i2c_write_byte(MPU6050_ADDR << 1);
    ok &= i2c_wait_ack();
    i2c_write_byte(reg);
    ok &= i2c_wait_ack();
    i2c_start();
    i2c_write_byte((MPU6050_ADDR << 1) | 1);
    ok &= i2c_wait_ack();
    val = i2c_read_byte(0);
    i2c_stop();
    if (value) *value = val;
    return ok;
}

static uint8_t MPU6050_ReadBytes(uint8_t reg, uint8_t *buf, uint8_t len)
{
    uint8_t i;
    uint8_t ok = 1;
    i2c_start();
    i2c_write_byte(MPU6050_ADDR << 1);
    ok &= i2c_wait_ack();
    i2c_write_byte(reg);
    ok &= i2c_wait_ack();
    i2c_start();
    i2c_write_byte((MPU6050_ADDR << 1) | 1);
    ok &= i2c_wait_ack();
    for (i = 0; i < len; i++) {
        buf[i] = i2c_read_byte(i < (len - 1) ? 1 : 0);
    }
    i2c_stop();
    return ok;
}

/* ---- 公共接口 ---- */
void MPU6050_Init(void)
{
    GPIO_InitTypeDef g;
    uint8_t id;
    uint8_t i;
    uint8_t buf[6];
    int32_t bias_sum = 0;

    mpu_data.ready = 0;
    mpu_data.gz_bias = 0;
    mpu_data.yaw = 0.0f;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);

    g.GPIO_Pin = SCL_PIN;
    g.GPIO_Mode = GPIO_Mode_Out_OD;
    g.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(SCL_PORT, &g);

    SDA_OUT();

    /* 复位 */
    if (!MPU6050_WriteReg(MPU6050_PWR_MGMT_1, 0x80)) return;
    Delay_ms(100);

    /* 唤醒, 时钟源=PLL X轴陀螺 */
    if (!MPU6050_WriteReg(MPU6050_PWR_MGMT_1, 0x01)) return;
    Delay_ms(10);

    /* 采样率 = 1kHz / (1+4) = 200Hz */
    if (!MPU6050_WriteReg(MPU6050_SMPLRT_DIV, 0x04)) return;

    /* 低通滤波 ~44Hz */
    if (!MPU6050_WriteReg(MPU6050_CONFIG, 0x03)) return;

    /* 陀螺仪: ±500°/s */
    if (!MPU6050_WriteReg(MPU6050_GYRO_CONFIG, 0x08)) return;

    /* 加速度计: ±4g */
    if (!MPU6050_WriteReg(MPU6050_ACCEL_CONFIG, 0x08)) return;

    Delay_ms(50);

    id = MPU6050_ReadID();
    if (id != 0x68) return;

    /* 小车静止时采样陀螺仪零偏，避免 yaw 上电后快速漂移。 */
    for (i = 0; i < 100; i++) {
        if (!MPU6050_ReadBytes(MPU6050_GYRO_XOUT_H, buf, 6)) return;
        mpu_data.gz = (int16_t)((buf[4] << 8) | buf[5]);
        bias_sum += mpu_data.gz;
        Delay_ms(2);
    }
    mpu_data.gz_bias = (int16_t)(bias_sum / 100);
    mpu_data.gz = 0;
    mpu_data.ready = 1;
}

uint8_t MPU6050_ReadID(void)
{
    uint8_t id = 0;
    if (!MPU6050_ReadReg(MPU6050_WHO_AM_I, &id)) return 0;
    return id;
}

void MPU6050_ReadAll(void)
{
    uint8_t buf[14];
    if (!MPU6050_ReadBytes(MPU6050_ACCEL_XOUT_H, buf, 14)) {
        /* 读失败时冻结姿态积分，避免把通信故障当成零速率继续积分。 */
        mpu_data.ready = 0;
        return;
    }

    mpu_data.ax = (int16_t)((buf[0] << 8) | buf[1]);
    mpu_data.ay = (int16_t)((buf[2] << 8) | buf[3]);
    mpu_data.az = (int16_t)((buf[4] << 8) | buf[5]);
    /* buf[6,7] = temp, skip */
    mpu_data.gx = (int16_t)((buf[8]  << 8) | buf[9]);
    mpu_data.gy = (int16_t)((buf[10] << 8) | buf[11]);
    mpu_data.gz = (int16_t)((buf[12] << 8) | buf[13]);
    mpu_data.ready = 1;
}

/* Z轴角速度积分得到偏航角, ±500°/s => 65.5 LSB/(°/s) */
void MPU6050_UpdateYaw(float dt)
{
    float gz_dps;
    if (!mpu_data.ready || dt <= 0.0f) return;
    gz_dps = (float)(mpu_data.gz - mpu_data.gz_bias) / 65.5f;
    /* 低通滤波去除噪声 */
    static float yaw_vel = 0;
    yaw_vel = yaw_vel * 0.85f + gz_dps * 0.15f;
    mpu_data.yaw += yaw_vel * dt;
}
