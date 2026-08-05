/*============================================================================
 * test_motor_register_diag.c — Host C tests for motor-register diagnostic frame
 *
 * This is the TDD RED test: it validates the pure encoder before any
 * hardware integration.  The encoder takes register snapshots and produces
 * binary AA55 frames with XOR checksum.
 *============================================================================*/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "motor_register_diag.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static int test_header(void)
{
    MotorRegSnapshot snap;
    uint8_t buf[MOTOR_REG_DIAG_FRAME_SIZE];
    memset(&snap, 0, sizeof(snap));
    memset(buf, 0xEE, sizeof(buf));

    uint8_t len = motor_reg_diag_encode(buf, &snap);
    CHECK(len == MOTOR_REG_DIAG_FRAME_SIZE);
    CHECK(buf[0] == 0xAA);
    CHECK(buf[1] == 0x55);
    CHECK(buf[2] == MOTOR_REG_DIAG_TYPE);
    CHECK(buf[3] == MOTOR_REG_DIAG_LEN);
    return 0;
}

static int test_all_zeros(void)
{
    MotorRegSnapshot snap;
    uint8_t buf[MOTOR_REG_DIAG_FRAME_SIZE];
    memset(&snap, 0, sizeof(snap));

    motor_reg_diag_encode(buf, &snap);

    /* All-zero payload: checksum = TYPE ^ LEN = 0x7E ^ 24 = 0x7E ^ 0x18 = 0x66 */
    uint16_t i;
    for (i = 4; i < 28; i++) CHECK(buf[i] == 0x00);
    CHECK(buf[28] == (uint8_t)(MOTOR_REG_DIAG_TYPE ^ MOTOR_REG_DIAG_LEN));
    return 0;
}

static int test_deterministic_values(void)
{
    MotorRegSnapshot snap;
    uint8_t buf[MOTOR_REG_DIAG_FRAME_SIZE];
    uint8_t expected_payload[24];
    uint8_t cs;
    uint16_t i;

    /* Assign deterministic values: each register = index + 1 */
    for (i = 0; i < 12; i++) {
        snap.regs[i] = (uint16_t)(i + 1);
    }

    motor_reg_diag_encode(buf, &snap);

    /* Build expected payload: each uint16 in little-endian */
    for (i = 0; i < 12; i++) {
        uint16_t val = (uint16_t)(i + 1);
        expected_payload[i * 2]     = (uint8_t)(val & 0xFF);
        expected_payload[i * 2 + 1] = (uint8_t)((val >> 8) & 0xFF);
    }

    CHECK(memcmp(buf + 4, expected_payload, 24) == 0);

    /* Verify checksum */
    cs = MOTOR_REG_DIAG_TYPE ^ MOTOR_REG_DIAG_LEN;
    for (i = 0; i < 24; i++) cs ^= expected_payload[i];
    CHECK(buf[28] == cs);
    return 0;
}

static int test_little_endian(void)
{
    MotorRegSnapshot snap;
    uint8_t buf[MOTOR_REG_DIAG_FRAME_SIZE];

    memset(&snap, 0, sizeof(snap));
    /* Test a value > 255 to verify LE encoding */
    snap.regs[0] = 0xABCD;
    snap.regs[1] = 0x0102;
    snap.regs[11] = 0xF0F0;

    motor_reg_diag_encode(buf, &snap);

    /* regs[0] = 0xABCD -> payload bytes 4,5 = 0xCD, 0xAB */
    CHECK(buf[4]  == 0xCD);
    CHECK(buf[5]  == 0xAB);

    /* regs[1] = 0x0102 -> payload bytes 6,7 = 0x02, 0x01 */
    CHECK(buf[6]  == 0x02);
    CHECK(buf[7]  == 0x01);

    /* regs[11] = 0xF0F0 -> payload bytes 26,27 = 0xF0, 0xF0 */
    CHECK(buf[26] == 0xF0);
    CHECK(buf[27] == 0xF0);

    /* Verify checksum */
    uint8_t cs = MOTOR_REG_DIAG_TYPE ^ MOTOR_REG_DIAG_LEN;
    uint16_t i;
    for (i = 4; i < 28; i++) cs ^= buf[i];
    CHECK(buf[28] == cs);
    return 0;
}

static int test_max_values(void)
{
    MotorRegSnapshot snap;
    uint8_t buf[MOTOR_REG_DIAG_FRAME_SIZE];
    uint8_t cs;
    uint16_t i;

    /* All registers at 0xFFFF */
    for (i = 0; i < 12; i++) {
        snap.regs[i] = 0xFFFF;
    }

    motor_reg_diag_encode(buf, &snap);

    /* Payload bytes: every even byte = 0xFF, odd byte = 0xFF */
    for (i = 4; i < 28; i++) CHECK(buf[i] == 0xFF);

    /* XOR of all 0xFF bytes with type^len */
    cs = MOTOR_REG_DIAG_TYPE ^ MOTOR_REG_DIAG_LEN;
    for (i = 0; i < 24; i++) cs ^= 0xFF;
    CHECK(buf[28] == cs);
    return 0;
}

static int test_buffer_not_touched_beyond_frame(void)
{
    MotorRegSnapshot snap;
    uint8_t buf[MOTOR_REG_DIAG_FRAME_SIZE + 4];
    size_t i;

    memset(&snap, 0, sizeof(snap));
    /* Fill with 0xEE sentinel */
    memset(buf, 0xEE, sizeof(buf));

    motor_reg_diag_encode(buf, &snap);

    /* Bytes beyond frame should be untouched */
    for (i = MOTOR_REG_DIAG_FRAME_SIZE; i < sizeof(buf); i++) {
        CHECK(buf[i] == 0xEE);
    }
    return 0;
}

static int test_index_order(void)
{
    MotorRegSnapshot snap;
    uint8_t buf[MOTOR_REG_DIAG_FRAME_SIZE];

    /* Use distinctive values for each field to verify ordering */
    snap.regs[0]  = 0x0001; /* TIM2_CR1 */
    snap.regs[1]  = 0x0002; /* TIM2_ARR */
    snap.regs[2]  = 0x0003; /* TIM2_CCR1 */
    snap.regs[3]  = 0x0004; /* TIM2_CCR2 */
    snap.regs[4]  = 0x0005; /* TIM2_CCR3 */
    snap.regs[5]  = 0x0006; /* TIM2_CCR4 */
    snap.regs[6]  = 0x0007; /* TIM4_CR1 */
    snap.regs[7]  = 0x0008; /* TIM4_ARR */
    snap.regs[8]  = 0x0009; /* TIM4_CCR1 */
    snap.regs[9]  = 0x000A; /* TIM4_CCR2 */
    snap.regs[10] = 0x000B; /* TIM4_CCR3 */
    snap.regs[11] = 0x000C; /* TIM4_CCR4 */

    motor_reg_diag_encode(buf, &snap);

    /* Each uint16 LE at offset 4 + i*2 */
    CHECK(buf[4]  == 0x01 && buf[5]  == 0x00);
    CHECK(buf[6]  == 0x02 && buf[7]  == 0x00);
    CHECK(buf[8]  == 0x03 && buf[9]  == 0x00);
    CHECK(buf[10] == 0x04 && buf[11] == 0x00);
    CHECK(buf[12] == 0x05 && buf[13] == 0x00);
    CHECK(buf[14] == 0x06 && buf[15] == 0x00);
    CHECK(buf[16] == 0x07 && buf[17] == 0x00);
    CHECK(buf[18] == 0x08 && buf[19] == 0x00);
    CHECK(buf[20] == 0x09 && buf[21] == 0x00);
    CHECK(buf[22] == 0x0A && buf[23] == 0x00);
    CHECK(buf[24] == 0x0B && buf[25] == 0x00);
    CHECK(buf[26] == 0x0C && buf[27] == 0x00);
    return 0;
}

int main(void)
{
    int failed = 0;

    failed += test_header();
    failed += test_all_zeros();
    failed += test_deterministic_values();
    failed += test_little_endian();
    failed += test_max_values();
    failed += test_buffer_not_touched_beyond_frame();
    failed += test_index_order();

    if (failed) {
        fprintf(stderr, "%d test(s) FAILED\n", failed);
        return 1;
    }
    printf("All motor_register_diag tests PASSED.\n");
    return 0;
}
