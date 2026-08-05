#include "stm32f10x.h"
#include "Delay.h"
#include "Sensor.h"
#include "mpu6050.h"

#define DIAG_SIGNATURE 0x47414944UL /* "DIAG" in little endian memory */
#define DIAG_VERSION   1UL

typedef struct
{
    uint32_t signature;
    uint32_t version;
    uint32_t heartbeat;

    uint32_t gpioa_idr;
    uint32_t gpioa_odr;
    uint32_t gpiob_idr;
    uint32_t gpiob_odr;

    uint32_t sensor_bits;
    uint32_t sensor_seen_low;
    uint32_t sensor_seen_high;
    uint32_t sensor_change_count[4];

    uint32_t mpu_id;
    uint32_t mpu_ready;
    int32_t mpu_ax;
    int32_t mpu_ay;
    int32_t mpu_az;
    int32_t mpu_gx;
    int32_t mpu_gy;
    int32_t mpu_gz;
    uint32_t mpu_change_count;

    uint32_t esp_rx_count;
    uint32_t esp_ok_count;
    uint32_t esp_error_count;
    uint32_t esp_last_rx_tick;
    uint32_t esp_tail_write;
    uint8_t esp_tail[64];

    uint32_t tim2_cr1;
    uint32_t tim4_cr1;
    uint32_t tim2_ccr[4];
    uint32_t tim4_ccr[4];

    uint32_t esp_scan_done;
    uint32_t esp_selected_baud;
    uint32_t esp_scan_baud[6];
    uint32_t esp_scan_rx[6];
    uint32_t esp_scan_ok[6];
} DiagnosticState;

volatile DiagnosticState g_diag;

static void MotorPins_ForceLow(void)
{
    GPIO_InitTypeDef gpio;

    RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM2 |
                           RCC_APB1Periph_TIM4, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA |
                           RCC_APB2Periph_GPIOB, ENABLE);

    TIM_Cmd(TIM2, DISABLE);
    TIM_Cmd(TIM4, DISABLE);
    TIM_DeInit(TIM2);
    TIM_DeInit(TIM4);

    GPIO_ResetBits(GPIOA, GPIO_Pin_0 | GPIO_Pin_1 |
                          GPIO_Pin_2 | GPIO_Pin_3);
    GPIO_ResetBits(GPIOB, GPIO_Pin_6 | GPIO_Pin_7 |
                          GPIO_Pin_8 | GPIO_Pin_9);

    GPIO_StructInit(&gpio);
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Speed = GPIO_Speed_2MHz;

    gpio.GPIO_Pin = GPIO_Pin_0 | GPIO_Pin_1 |
                    GPIO_Pin_2 | GPIO_Pin_3;
    GPIO_Init(GPIOA, &gpio);

    gpio.GPIO_Pin = GPIO_Pin_6 | GPIO_Pin_7 |
                    GPIO_Pin_8 | GPIO_Pin_9;
    GPIO_Init(GPIOB, &gpio);

    GPIO_ResetBits(GPIOA, GPIO_Pin_0 | GPIO_Pin_1 |
                          GPIO_Pin_2 | GPIO_Pin_3);
    GPIO_ResetBits(GPIOB, GPIO_Pin_6 | GPIO_Pin_7 |
                          GPIO_Pin_8 | GPIO_Pin_9);
}

static void ESP_USART1_Init(uint32_t baud)
{
    GPIO_InitTypeDef gpio;
    USART_InitTypeDef usart;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_USART1 |
                           RCC_APB2Periph_GPIOA, ENABLE);

    gpio.GPIO_Pin = GPIO_Pin_9;
    gpio.GPIO_Mode = GPIO_Mode_AF_PP;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOA, &gpio);

    gpio.GPIO_Pin = GPIO_Pin_10;
    gpio.GPIO_Mode = GPIO_Mode_IN_FLOATING;
    GPIO_Init(GPIOA, &gpio);

    USART_StructInit(&usart);
    usart.USART_BaudRate = baud;
    usart.USART_WordLength = USART_WordLength_8b;
    usart.USART_StopBits = USART_StopBits_1;
    usart.USART_Parity = USART_Parity_No;
    usart.USART_HardwareFlowControl = USART_HardwareFlowControl_None;
    usart.USART_Mode = USART_Mode_Tx | USART_Mode_Rx;
    USART_Init(USART1, &usart);
    USART_Cmd(USART1, ENABLE);
}

static void ESP_FlushRX(void)
{
    while (USART_GetFlagStatus(USART1, USART_FLAG_RXNE) != RESET)
    {
        (void)USART_ReceiveData(USART1);
    }
}

static void ESP_SendAT(void)
{
    static const char command[] = "AT\r\n";
    uint32_t i;

    for (i = 0; i < sizeof(command) - 1; ++i)
    {
        uint32_t timeout = 100000UL;
        while ((USART_GetFlagStatus(USART1, USART_FLAG_TXE) == RESET) &&
               (timeout > 0UL))
        {
            --timeout;
        }
        if (timeout == 0UL)
        {
            ++g_diag.esp_error_count;
            return;
        }
        USART_SendData(USART1, (uint16_t)command[i]);
    }
}

static void ESP_ReadAvailable(uint32_t tick)
{
    static uint8_t previous = 0;

    while (USART_GetFlagStatus(USART1, USART_FLAG_RXNE) != RESET)
    {
        uint8_t value = (uint8_t)USART_ReceiveData(USART1);
        uint32_t index = g_diag.esp_tail_write & 63UL;

        g_diag.esp_tail[index] = value;
        ++g_diag.esp_tail_write;
        ++g_diag.esp_rx_count;
        g_diag.esp_last_rx_tick = tick;

        if ((previous == 'O') && (value == 'K'))
        {
            ++g_diag.esp_ok_count;
        }
        previous = value;
    }

    if (USART_GetFlagStatus(USART1, USART_FLAG_ORE) != RESET)
    {
        (void)USART_ReceiveData(USART1);
        ++g_diag.esp_error_count;
    }
}

static void ESP_ScanBaudRates(void)
{
    static const uint32_t baud_rates[6] = {
        115200UL, 9600UL, 57600UL, 74880UL, 38400UL, 19200UL
    };
    uint32_t i;

    for (i = 0; i < 6; ++i)
    {
        uint32_t attempt;
        uint32_t start_rx;
        uint32_t start_ok;

        g_diag.esp_scan_baud[i] = baud_rates[i];
        ESP_USART1_Init(baud_rates[i]);
        Delay_ms(100);
        ESP_FlushRX();
        start_rx = g_diag.esp_rx_count;
        start_ok = g_diag.esp_ok_count;

        for (attempt = 0; attempt < 3; ++attempt)
        {
            uint32_t wait_step;
            ESP_SendAT();
            for (wait_step = 0; wait_step < 40; ++wait_step)
            {
                Delay_ms(10);
                ESP_ReadAvailable(attempt * 40UL + wait_step);
            }
        }

        g_diag.esp_scan_rx[i] = g_diag.esp_rx_count - start_rx;
        g_diag.esp_scan_ok[i] = g_diag.esp_ok_count - start_ok;
        if ((g_diag.esp_selected_baud == 0UL) &&
            (g_diag.esp_scan_ok[i] > 0UL))
        {
            g_diag.esp_selected_baud = baud_rates[i];
        }
    }

    if (g_diag.esp_selected_baud == 0UL)
    {
        g_diag.esp_selected_baud = 115200UL;
    }
    ESP_USART1_Init(g_diag.esp_selected_baud);
    ESP_FlushRX();
    g_diag.esp_scan_done = 1UL;
}

static uint32_t ReadSensorBits(void)
{
    uint32_t bits = 0;
    bits |= ((uint32_t)Sensor0_Get_State() << 0);
    bits |= ((uint32_t)Sensor1_Get_State() << 1);
    bits |= ((uint32_t)Sensor2_Get_State() << 2);
    bits |= ((uint32_t)Sensor3_Get_State() << 3);
    return bits;
}

int main(void)
{
    uint32_t tick = 0;
    uint32_t previous_sensors;
    int16_t previous_ax = 0;
    int16_t previous_ay = 0;
    int16_t previous_az = 0;
    int16_t previous_gz = 0;

    g_diag.signature = DIAG_SIGNATURE;
    g_diag.version = DIAG_VERSION;

    MotorPins_ForceLow();

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_AFIO, ENABLE);
    GPIO_PinRemapConfig(GPIO_Remap_SWJ_JTAGDisable, ENABLE);
    Sensor_Init();
    previous_sensors = ReadSensorBits();
    g_diag.sensor_bits = previous_sensors;
    g_diag.sensor_seen_low = (~previous_sensors) & 0x0FUL;
    g_diag.sensor_seen_high = previous_sensors & 0x0FUL;

    MPU6050_Init();
    g_diag.mpu_id = MPU6050_ReadID();

    ESP_ScanBaudRates();

    while (1)
    {
        uint32_t sensors;
        uint32_t changed;
        uint32_t i;

        MotorPins_ForceLow();

        sensors = ReadSensorBits();
        changed = sensors ^ previous_sensors;
        for (i = 0; i < 4; ++i)
        {
            if ((changed & (1UL << i)) != 0UL)
            {
                ++g_diag.sensor_change_count[i];
            }
        }
        previous_sensors = sensors;
        g_diag.sensor_bits = sensors;
        g_diag.sensor_seen_low |= (~sensors) & 0x0FUL;
        g_diag.sensor_seen_high |= sensors & 0x0FUL;

        MPU6050_ReadAll();
        g_diag.mpu_ready = mpu_data.ready;
        g_diag.mpu_ax = mpu_data.ax;
        g_diag.mpu_ay = mpu_data.ay;
        g_diag.mpu_az = mpu_data.az;
        g_diag.mpu_gx = mpu_data.gx;
        g_diag.mpu_gy = mpu_data.gy;
        g_diag.mpu_gz = mpu_data.gz;
        if ((mpu_data.ax != previous_ax) ||
            (mpu_data.ay != previous_ay) ||
            (mpu_data.az != previous_az) ||
            (mpu_data.gz != previous_gz))
        {
            ++g_diag.mpu_change_count;
        }
        previous_ax = mpu_data.ax;
        previous_ay = mpu_data.ay;
        previous_az = mpu_data.az;
        previous_gz = mpu_data.gz;

        if ((tick % 100UL) == 0UL)
        {
            ESP_SendAT();
        }
        ESP_ReadAvailable(tick);

        g_diag.gpioa_idr = GPIOA->IDR;
        g_diag.gpioa_odr = GPIOA->ODR;
        g_diag.gpiob_idr = GPIOB->IDR;
        g_diag.gpiob_odr = GPIOB->ODR;
        g_diag.tim2_cr1 = TIM2->CR1;
        g_diag.tim4_cr1 = TIM4->CR1;
        g_diag.tim2_ccr[0] = TIM2->CCR1;
        g_diag.tim2_ccr[1] = TIM2->CCR2;
        g_diag.tim2_ccr[2] = TIM2->CCR3;
        g_diag.tim2_ccr[3] = TIM2->CCR4;
        g_diag.tim4_ccr[0] = TIM4->CCR1;
        g_diag.tim4_ccr[1] = TIM4->CCR2;
        g_diag.tim4_ccr[2] = TIM4->CCR3;
        g_diag.tim4_ccr[3] = TIM4->CCR4;

        ++tick;
        g_diag.heartbeat = tick;
        Delay_ms(10);
    }
}
