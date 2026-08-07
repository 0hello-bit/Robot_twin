#include <stdint.h>
#include <stdio.h>

#include "stm32f10x.h"
#include "mpu6050.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

/* RED-stage declarations: production header/implementation will provide
   these values and the accessor during the GREEN step. */
#define TEST_INIT_STATUS_OK                 0x00U
#define TEST_INIT_STATUS_RESET_WRITE        0x10U
#define TEST_INIT_STATUS_WHO_AM_I_READ      0x20U
#define TEST_INIT_STATUS_WHO_AM_I_MISMATCH  0x21U
#define TEST_INIT_STATUS_BIAS_READ          0x30U
extern uint8_t MPU6050_GetInitStatus(void);
extern uint8_t MPU6050_GetObservedID(void);

GPIO_TypeDef g_test_gpio_b = {2U};

static uint8_t g_scl_level;
static uint8_t g_sda_level;
static uint8_t g_sda_input;
static uint8_t g_tx_byte;
static uint8_t g_tx_bits;
static uint8_t g_tx_ready;
static uint8_t g_ack_phase;
static uint8_t g_ack_should_fail;
static uint8_t g_read_phase;
static uint8_t g_read_bit;
static uint8_t g_read_byte;
static uint8_t g_master_ack_pending;
static uint8_t g_i2c_phase;
static uint8_t g_current_reg;
static uint8_t g_who_am_i_value;
static uint8_t g_force_bus_failure;
static uint8_t g_fail_reset_every_attempt;
static uint8_t g_fail_who_read_every_attempt;
static uint8_t g_fail_who_read_after_first_attempt;
static int32_t g_fail_bias_sample_index;
static uint32_t g_next_bias_fail_ack;
static uint32_t g_bias_fail_stride;
static uint32_t g_fail_ack_index;
static uint32_t g_ack_index;
static uint32_t g_reset_write_count;
static uint8_t g_wrong_address_seen;

enum {
    I2C_EXPECT_ADDRESS = 0U,
    I2C_EXPECT_REGISTER = 1U,
    I2C_EXPECT_VALUE = 2U,
    I2C_TRANSACTION_DONE = 3U
};

static void reset_i2c_decoder(void)
{
    g_scl_level = 1U;
    g_sda_level = 1U;
    g_sda_input = 0U;
    g_tx_byte = 0U;
    g_tx_bits = 0U;
    g_tx_ready = 0U;
    g_ack_phase = 0U;
    g_ack_should_fail = 0U;
    g_read_phase = 0U;
    g_read_bit = 0U;
    g_read_byte = 0U;
    g_master_ack_pending = 0U;
    g_i2c_phase = I2C_EXPECT_ADDRESS;
    g_current_reg = 0U;
    g_ack_index = 0U;
    g_reset_write_count = 0U;
    g_wrong_address_seen = 0U;
}

void RCC_APB2PeriphClockCmd(uint32_t peripheral, FunctionalState state)
{
    (void)peripheral;
    (void)state;
}

void GPIO_Init(GPIO_TypeDef *gpio, GPIO_InitTypeDef *config)
{
    (void)gpio;
    if (config != 0 && config->GPIO_Mode == GPIO_Mode_IPU) {
        g_sda_input = 1U;
    } else if (config != 0 && config->GPIO_Mode == GPIO_Mode_Out_OD) {
        g_sda_input = 0U;
    }
}

static void process_transmitted_byte(void)
{
    if (g_i2c_phase == I2C_EXPECT_ADDRESS) {
        if (g_tx_byte == ((MPU6050_ADDR << 1) | 1U)) {
            g_i2c_phase = I2C_TRANSACTION_DONE;
            g_read_byte = 0U;
            g_read_bit = 0U;
        } else {
            if (g_tx_byte != (MPU6050_ADDR << 1)) {
                g_wrong_address_seen = 1U;
            }
            g_i2c_phase = I2C_EXPECT_REGISTER;
        }
        return;
    }

    if (g_i2c_phase == I2C_EXPECT_REGISTER) {
        g_current_reg = g_tx_byte;
        g_i2c_phase = I2C_EXPECT_VALUE;
        return;
    }

    if (g_i2c_phase == I2C_EXPECT_VALUE) {
        if (g_current_reg == MPU6050_PWR_MGMT_1 && g_tx_byte == 0x80U) {
            g_reset_write_count++;
        }
        g_i2c_phase = I2C_TRANSACTION_DONE;
    }
}

static uint8_t should_fail_ack(uint32_t ack_index)
{
    if (g_force_bus_failure) return 1U;
    if (g_fail_ack_index != 0U && ack_index == g_fail_ack_index) {
        g_fail_ack_index = 0U;
        return 1U;
    }
    if (g_fail_reset_every_attempt &&
        ack_index >= 4U &&
        ((ack_index - 4U) % 6U) == 0U) {
        return 1U;
    }
    if (g_fail_who_read_every_attempt &&
        ack_index >= 1U && ((ack_index - 1U) % 3U) == 0U) {
        return 1U;
    }
    if (g_fail_who_read_after_first_attempt &&
        g_current_reg == MPU6050_WHO_AM_I &&
        ack_index >= 6U && (ack_index % 3U) == 0U) {
        return 1U;
    }
    if (g_fail_bias_sample_index >= 0 &&
        ack_index == g_next_bias_fail_ack) {
        g_next_bias_fail_ack += g_bias_fail_stride;
        return 1U;
    }
    return 0U;
}

void GPIO_SetBits(GPIO_TypeDef *gpio, uint16_t pin)
{
    if (gpio != GPIOB) return;
    if (pin == GPIO_Pin_11) {
        if (g_scl_level && !g_sda_level) {
            /* STOP: release SDA while SCL is high. */
            g_i2c_phase = I2C_EXPECT_ADDRESS;
            g_tx_bits = 0U;
            g_tx_ready = 0U;
            g_read_phase = 0U;
            g_master_ack_pending = 0U;
        }
        g_sda_level = 1U;
        return;
    }
    if (pin == GPIO_Pin_10) {
        if (!g_scl_level) {
            g_scl_level = 1U;
            if (g_master_ack_pending) {
                g_master_ack_pending = 0U;
            } else if (g_sda_input) {
                if (g_tx_ready) {
                    g_ack_phase = 1U;
                    g_ack_index++;
                    g_ack_should_fail = should_fail_ack(g_ack_index);
                } else if (g_i2c_phase == I2C_TRANSACTION_DONE ||
                           g_i2c_phase == I2C_EXPECT_ADDRESS) {
                    g_read_phase = 1U;
                }
            } else if (g_tx_bits < 8U) {
                g_tx_byte = (uint8_t)(g_tx_byte << 1);
                if (g_sda_level) g_tx_byte |= 1U;
                g_tx_bits++;
                if (g_tx_bits == 8U) g_tx_ready = 1U;
            }
        }
    }
}

void GPIO_ResetBits(GPIO_TypeDef *gpio, uint16_t pin)
{
    if (gpio != GPIOB) return;
    if (pin == GPIO_Pin_11) {
        if (g_scl_level && g_sda_level) {
            /* START: SDA falls while SCL is high. */
            g_i2c_phase = I2C_EXPECT_ADDRESS;
            g_tx_byte = 0U;
            g_tx_bits = 0U;
            g_tx_ready = 0U;
            g_read_phase = 0U;
            g_master_ack_pending = 0U;
        }
        g_sda_level = 0U;
        return;
    }
    if (pin == GPIO_Pin_10) {
        if (g_scl_level) {
            g_scl_level = 0U;
            if (g_ack_phase) {
                g_ack_phase = 0U;
                g_ack_should_fail = 0U;
                process_transmitted_byte();
                g_tx_byte = 0U;
                g_tx_bits = 0U;
                g_tx_ready = 0U;
            }
            g_read_phase = 0U;
        }
    }
}

static uint8_t read_response_bit(void)
{
    uint8_t response = 0U;
    if (g_current_reg == MPU6050_WHO_AM_I) response = g_who_am_i_value;
    if (g_read_bit == 0U) g_read_byte++;
    if (g_read_bit >= 8U) return 0U;
    return (uint8_t)((response >> (7U - g_read_bit)) & 1U);
}

uint8_t GPIO_ReadInputDataBit(GPIO_TypeDef *gpio, uint16_t pin)
{
    uint8_t value = 0U;
    (void)gpio;
    (void)pin;

    if (g_ack_phase) {
        return g_ack_should_fail ? 1U : 0U;
    }
    if (g_read_phase) {
        value = read_response_bit();
        g_read_bit++;
        if (g_read_bit == 8U) {
            g_read_bit = 0U;
            g_master_ack_pending = 1U;
        }
    }
    return value;
}

void Delay_ms(uint32_t ms)
{
    (void)ms;
}

static void reset_bus(uint8_t bus_ok, uint8_t who_am_i_ok)
{
    reset_i2c_decoder();
    g_force_bus_failure = bus_ok ? 0U : 1U;
    g_who_am_i_value = who_am_i_ok ? 0x68U : 0x00U;
    g_fail_ack_index = 0U;
    g_fail_reset_every_attempt = 0U;
    g_fail_who_read_every_attempt = 0U;
    g_fail_who_read_after_first_attempt = 0U;
    g_fail_bias_sample_index = -1;
    g_next_bias_fail_ack = 0U;
    g_bias_fail_stride = 0U;
}

static void fail_next_transaction_at(uint32_t ack_index)
{
    g_fail_ack_index = ack_index;
}

static void fail_reset_on_every_attempt(void)
{
    g_fail_reset_every_attempt = 1U;
}

static void fail_who_read_on_every_attempt(void)
{
    g_fail_who_read_every_attempt = 1U;
}

static void fail_who_read_after_first_attempt(void)
{
    g_fail_who_read_after_first_attempt = 1U;
}

static void fail_who_am_i_value(uint8_t value)
{
    g_who_am_i_value = value;
}

static void fail_bias_sample(uint8_t sample_index)
{
    g_fail_bias_sample_index = sample_index;
    g_next_bias_fail_ack = 22U + ((uint32_t)sample_index * 3U);
    g_bias_fail_stride = 24U + ((uint32_t)sample_index * 3U);
}

static int test_full_valid_cycle_and_dt_gate(void)
{
    uint8_t flags;

    reset_bus(1U, 1U);
    MPU6050_Init();
    flags = MPU6050_GetValidityFlags();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_OK);
    CHECK((flags & (MPU6050_VALIDITY_INIT | MPU6050_VALIDITY_BIAS)) ==
          (MPU6050_VALIDITY_INIT | MPU6050_VALIDITY_BIAS));
    CHECK((flags & (MPU6050_VALIDITY_READ | MPU6050_VALIDITY_UPDATED)) == 0U);

    MPU6050_SetDtClamped(0U);
    MPU6050_ReadAll();
    CHECK((MPU6050_GetValidityFlags() & MPU6050_VALIDITY_READ) != 0U);
    MPU6050_UpdateYaw(0.005f);
    flags = MPU6050_GetValidityFlags();
    CHECK((flags & MPU6050_VALIDITY_UPDATED) != 0U);
    CHECK((flags & MPU6050_VALIDITY_FUSION_REQUIRED) ==
          MPU6050_VALIDITY_FUSION_REQUIRED);
    CHECK((flags & MPU6050_VALIDITY_DT_CLAMPED) == 0U);
    CHECK(MPU6050_ValidityAllowsFusion(flags));

    MPU6050_SetDtClamped(1U);
    flags = MPU6050_GetValidityFlags();
    CHECK((flags & MPU6050_VALIDITY_DT_CLAMPED) != 0U);
    CHECK(!MPU6050_ValidityAllowsFusion(flags));
    return 0;
}

static int test_initialization_failure_is_sticky(void)
{
    uint8_t flags;

    reset_bus(1U, 1U);
    fail_reset_on_every_attempt();
    MPU6050_Init();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_RESET_WRITE);
    CHECK(g_reset_write_count == 4U);
    CHECK((MPU6050_GetValidityFlags() & MPU6050_VALIDITY_INIT) == 0U);

    /* A later readable bus must not promote a failed boot to initialized. */
    reset_bus(1U, 1U);
    MPU6050_ReadAll();
    MPU6050_UpdateYaw(0.005f);
    flags = MPU6050_GetValidityFlags();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_RESET_WRITE);
    CHECK((flags & MPU6050_VALIDITY_INIT) == 0U);
    CHECK(!MPU6050_ValidityAllowsFusion(flags));
    return 0;
}

static int test_transient_init_failure_recovers_within_retry_budget(void)
{
    reset_bus(1U, 1U);
    fail_next_transaction_at(4U); /* first reset write, after WHO_AM_I */
    MPU6050_Init();
    CHECK(g_reset_write_count == 2U);
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_OK);
    CHECK((MPU6050_GetValidityFlags() & (MPU6050_VALIDITY_INIT |
                                         MPU6050_VALIDITY_BIAS)) ==
          (MPU6050_VALIDITY_INIT | MPU6050_VALIDITY_BIAS));
    CHECK(g_wrong_address_seen == 0U);
    return 0;
}

static int test_persistent_init_failure_is_bounded_and_sticky(void)
{
    uint8_t flags;

    reset_bus(1U, 1U);
    fail_reset_on_every_attempt();
    MPU6050_Init();
    CHECK(g_reset_write_count == 4U);
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_RESET_WRITE);
    flags = MPU6050_GetValidityFlags();
    CHECK((flags & (MPU6050_VALIDITY_INIT | MPU6050_VALIDITY_BIAS)) == 0U);

    reset_bus(1U, 1U);
    MPU6050_ReadAll();
    MPU6050_UpdateYaw(0.005f);
    flags = MPU6050_GetValidityFlags();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_RESET_WRITE);
    CHECK(!MPU6050_ValidityAllowsFusion(flags));
    return 0;
}

static int test_who_am_i_read_and_mismatch_have_distinct_statuses(void)
{
    reset_bus(1U, 1U);
    fail_who_read_on_every_attempt();
    MPU6050_Init();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_WHO_AM_I_READ);
    CHECK(g_reset_write_count == 0U);
    CHECK(g_wrong_address_seen == 0U);

    reset_bus(1U, 1U);
    fail_who_am_i_value(0x71U);
    MPU6050_Init();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_WHO_AM_I_MISMATCH);
    CHECK(g_reset_write_count == 0U);
    CHECK(g_wrong_address_seen == 0U);
    return 0;
}

static int test_unknown_identity_is_fail_closed(void)
{
    reset_bus(1U, 1U);
    fail_who_am_i_value(0x71U);
    MPU6050_Init();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_WHO_AM_I_MISMATCH);
    CHECK(MPU6050_GetObservedID() == 0x71U);
    CHECK(g_reset_write_count == 0U);
    return 0;
}

static int test_mpu6500_identity_can_complete_shared_sequence(void)
{
    uint8_t flags;

    reset_bus(1U, 1U);
    fail_who_am_i_value(0x70U);
    MPU6050_Init();
    flags = MPU6050_GetValidityFlags();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_OK);
    CHECK(MPU6050_GetObservedID() == 0x70U);
    CHECK(g_reset_write_count == 4U);
    CHECK((flags & (MPU6050_VALIDITY_INIT | MPU6050_VALIDITY_BIAS)) ==
          (MPU6050_VALIDITY_INIT | MPU6050_VALIDITY_BIAS));
    return 0;
}

static int test_who_am_i_value_is_retained_for_hardware_diagnosis(void)
{
    reset_bus(1U, 1U);
    fail_who_am_i_value(0x71U);
    MPU6050_Init();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_WHO_AM_I_MISMATCH);
    CHECK(MPU6050_GetObservedID() == 0x71U);

    reset_bus(1U, 1U);
    fail_who_read_on_every_attempt();
    MPU6050_Init();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_WHO_AM_I_READ);
    CHECK(MPU6050_GetObservedID() == 0U);
    return 0;
}

static int test_who_am_i_id_matches_final_attempt(void)
{
    reset_bus(1U, 1U);
    fail_who_am_i_value(0x70U);
    fail_who_read_after_first_attempt();
    MPU6050_Init();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_WHO_AM_I_READ);
    CHECK(MPU6050_GetObservedID() == 0U);
    return 0;
}

static int test_bias_read_failure_is_attributed(void)
{
    reset_bus(1U, 1U);
    fail_bias_sample(0U);
    MPU6050_Init();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_BIAS_READ);
    CHECK(g_reset_write_count == 4U);
    CHECK((MPU6050_GetValidityFlags() & MPU6050_VALIDITY_INIT) == 0U);
    return 0;
}

static int test_runtime_read_failure_does_not_rewrite_boot_status(void)
{
    uint8_t flags;

    reset_bus(1U, 1U);
    MPU6050_Init();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_OK);
    fail_next_transaction_at(g_ack_index + 1U);
    MPU6050_ReadAll();
    MPU6050_UpdateYaw(0.005f);
    flags = MPU6050_GetValidityFlags();
    CHECK(MPU6050_GetInitStatus() == TEST_INIT_STATUS_OK);
    CHECK((flags & (MPU6050_VALIDITY_INIT | MPU6050_VALIDITY_BIAS)) ==
          (MPU6050_VALIDITY_INIT | MPU6050_VALIDITY_BIAS));
    CHECK((flags & (MPU6050_VALIDITY_READ | MPU6050_VALIDITY_UPDATED)) == 0U);
    return 0;
}

int main(void)
{
    if (test_full_valid_cycle_and_dt_gate()) return 1;
    if (test_initialization_failure_is_sticky()) return 1;
    if (test_transient_init_failure_recovers_within_retry_budget()) return 1;
    if (test_persistent_init_failure_is_bounded_and_sticky()) return 1;
    if (test_who_am_i_read_and_mismatch_have_distinct_statuses()) return 1;
    if (test_unknown_identity_is_fail_closed()) return 1;
    if (test_mpu6500_identity_can_complete_shared_sequence()) return 1;
    if (test_who_am_i_value_is_retained_for_hardware_diagnosis()) return 1;
    if (test_who_am_i_id_matches_final_attempt()) return 1;
    if (test_bias_read_failure_is_attributed()) return 1;
    if (test_runtime_read_failure_does_not_rewrite_boot_status()) return 1;
    puts("PASS test_mpu6050_validity");
    return 0;
}
