#include <stdint.h>
#include <stdio.h>

#include "imu_diagnostic.h"
#include "health_stats.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

int main(void)
{
    ImuDiagnosticSnapshot snapshot;
    uint8_t frame[IMU_DIAGNOSTIC_FRAME_SIZE];
    uint8_t checksum;
    uint8_t i;

    snapshot.observed_id = 0x70U;
    snapshot.init_status = 0x21U;
    snapshot.validity_flags = 0x04U;
    snapshot.hardware_observed_id = 0x68U;

    CHECK(imu_diagnostic_encode(frame, &snapshot) ==
          IMU_DIAGNOSTIC_FRAME_SIZE);
    CHECK(frame[0] == 0xAAU && frame[1] == 0x55U);
    CHECK(frame[2] == IMU_DIAGNOSTIC_TYPE);
    CHECK(frame[3] == IMU_DIAGNOSTIC_PAYLOAD_LEN);
    CHECK(frame[4] == 0x70U);
    CHECK(frame[5] == 0x21U);
    CHECK(frame[6] == 0x04U);
    CHECK(frame[7] == 0x68U);

    checksum = IMU_DIAGNOSTIC_TYPE ^ IMU_DIAGNOSTIC_PAYLOAD_LEN;
    for (i = 0U; i < IMU_DIAGNOSTIC_PAYLOAD_LEN; i++) {
        checksum ^= frame[4U + i];
    }
    CHECK(frame[8] == checksum);

    CHECK(imu_diagnostic_delivery_confirmed(
              CIPSEND_TX_TAG_IMU_DIAGNOSTIC, CTS_RESULT_OK) == 1U);
    CHECK(imu_diagnostic_delivery_confirmed(
              CIPSEND_TX_TAG_IMU_DIAGNOSTIC, CTS_RESULT_ERROR) == 0U);
    CHECK(imu_diagnostic_delivery_confirmed(
              CIPSEND_TX_TAG_DIAG, CTS_RESULT_OK) == 0U);
    CHECK(imu_diagnostic_delivery_confirmed(
              CIPSEND_TX_TAG_DIAG_HEALTH, CTS_RESULT_OK) == 0U);

    puts("PASS test_imu_diagnostic");
    return 0;
}
