#include "motor_register_diag.h"

static void put_u16_le(uint8_t *buf, uint16_t value)
{
    buf[0] = (uint8_t)(value & 0xFFU);
    buf[1] = (uint8_t)((value >> 8) & 0xFFU);
}

uint8_t motor_reg_diag_encode(uint8_t *buffer, const MotorRegSnapshot *snapshot)
{
    uint8_t cs;
    uint8_t i;

    /* Header */
    buffer[0] = 0xAA;
    buffer[1] = 0x55;

    /* Type and Length */
    buffer[2] = MOTOR_REG_DIAG_TYPE;
    buffer[3] = MOTOR_REG_DIAG_LEN;

    /* Payload: 12 uint16 LE */
    for (i = 0; i < 12; i++) {
        put_u16_le(buffer + 4 + (uint8_t)(i * 2), snapshot->regs[i]);
    }

    /* XOR checksum over type, length, payload */
    cs = MOTOR_REG_DIAG_TYPE ^ MOTOR_REG_DIAG_LEN;
    for (i = 0; i < MOTOR_REG_DIAG_LEN; i++) {
        cs ^= buffer[4 + i];
    }
    buffer[28] = cs;

    return MOTOR_REG_DIAG_FRAME_SIZE;
}
