#ifndef IMU_DIAGNOSTIC_H
#define IMU_DIAGNOSTIC_H

#include <stdint.h>
#include "cipsend_tx.h"

/* Additive diagnostic frame carried by the existing ESP/CIPSEND path. */
#define IMU_DIAGNOSTIC_TYPE        0x7DU
#define IMU_DIAGNOSTIC_PAYLOAD_LEN 4U
#define IMU_DIAGNOSTIC_FRAME_SIZE  9U

typedef struct {
    uint8_t observed_id;
    uint8_t init_status;
    uint8_t validity_flags;
    /* 0 means the independent hardware-I2C2 read failed. */
    uint8_t hardware_observed_id;
} ImuDiagnosticSnapshot;

static inline uint8_t imu_diagnostic_encode(
    uint8_t *buffer, const ImuDiagnosticSnapshot *snapshot)
{
    uint8_t checksum;
    uint8_t i;

    buffer[0] = 0xAAU;
    buffer[1] = 0x55U;
    buffer[2] = IMU_DIAGNOSTIC_TYPE;
    buffer[3] = IMU_DIAGNOSTIC_PAYLOAD_LEN;
    buffer[4] = snapshot->observed_id;
    buffer[5] = snapshot->init_status;
    buffer[6] = snapshot->validity_flags;
    buffer[7] = snapshot->hardware_observed_id;

    checksum = IMU_DIAGNOSTIC_TYPE ^ IMU_DIAGNOSTIC_PAYLOAD_LEN;
    for (i = 0U; i < IMU_DIAGNOSTIC_PAYLOAD_LEN; i++) {
        checksum ^= buffer[4U + i];
    }
    buffer[8] = checksum;
    return IMU_DIAGNOSTIC_FRAME_SIZE;
}

static inline uint8_t imu_diagnostic_delivery_confirmed(
    uint8_t tx_tag, uint8_t tx_result)
{
    return (tx_tag == CIPSEND_TX_TAG_IMU_DIAGNOSTIC &&
            tx_result == CTS_RESULT_OK) ? 1U : 0U;
}

#endif /* IMU_DIAGNOSTIC_H */
