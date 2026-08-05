#ifndef MOTOR_REGISTER_DIAG_H
#define MOTOR_REGISTER_DIAG_H

/*============================================================================
 * motor_register_diag.h — Motor-register diagnostic frame encoder
 *
 * Pure encoder — no hardware dependencies, compiles with ARMCC5 and MSVC.
 * Encodes a diagnostic binary frame (type 0x7E) that captures TIM2/TIM4
 * peripheral register snapshots.
 *
 * Frame format:
 *   Header:   AA 55
 *   Type:     0x7E  (reserved diagnostic; not 0x01 telemetry or 0x02 status)
 *   Length:   24
 *   Payload:  12 × uint16 little-endian, in order:
 *               TIM2_CR1, TIM2_ARR, TIM2_CCR1, TIM2_CCR2,
 *               TIM2_CCR3, TIM2_CCR4, TIM4_CR1, TIM4_ARR,
 *               TIM4_CCR1, TIM4_CCR2, TIM4_CCR3, TIM4_CCR4
 *   Checksum: XOR over Type, Length, and Payload
 * Total frame size: 2 + 1 + 1 + 24 + 1 = 29 bytes
 *============================================================================*/

#include <stdint.h>

#define MOTOR_REG_DIAG_TYPE      0x7E
#define MOTOR_REG_DIAG_LEN       24
#define MOTOR_REG_DIAG_FRAME_SIZE 29U

/* Register snapshot: 12 uint16 registers exactly as they appear in
   the diagnostic payload (index 0 = TIM2_CR1, ..., index 11 = TIM4_CCR4). */
typedef struct {
    uint16_t regs[12];
} MotorRegSnapshot;

/* Encode a diagnostic frame into buffer (must be >= MOTOR_REG_DIAG_FRAME_SIZE).
   Returns total frame length (29 bytes). */
uint8_t motor_reg_diag_encode(uint8_t *buffer, const MotorRegSnapshot *snapshot);

#endif /* MOTOR_REGISTER_DIAG_H */
