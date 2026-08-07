/* Host C test for the 0x02 health diagnostic frame encoder.
 *
 * TDD (firmware health baseline, Task 1):
 *   - RED: health_frame.h/.c absent -> cl cannot open source file, non-zero exit.
 *   - GREEN: health_frame_encode() output equals the 111-byte golden vector
 *     (golden_health_0x02.hex), checksum 0xCD.
 *
 * Cross-language lock (Task 11): the golden byte sequence below is the same
 * one referenced by simulation/digital_twin/tests/test_frame_parser_health.py.
 * If a golden hex file path is passed as argv[1], the test also reads it and
 * asserts it matches both the encode output and the hardcoded golden, so a
 * drift in either side is caught.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "health_frame.h"

#define CHECK(expression) do { \
    if (!(expression)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expression); \
        return 1; \
    } \
} while (0)

/* The golden 111-byte frame: AA 55 02 6A + 106B payload + XOR checksum CD.
   Byte-for-byte identical to golden_health_0x02.hex. */
static const uint8_t k_golden[HEALTH_FRAME_TOTAL_LEN] = {
    0xAA, 0x55, 0x02, 0x6A,
    0x01, 0x01, 0x08, 0x01, 0x01, 0x02, 0x03, 0x00, 0x0A, 0x00, 0xC8, 0x00,
    0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x40, 0x42, 0x0F, 0x00, 0x40, 0xE2, 0x01, 0x00, 0x06, 0x00,
    0xF4, 0x01, 0x64, 0x00, 0x05, 0x00, 0x5F, 0x00, 0x5A, 0x00, 0x05, 0x00, 0x6E, 0x00, 0x69, 0x00,
    0x64, 0x00, 0x01, 0x00, 0x02, 0x00, 0x01, 0x00, 0x01, 0x00, 0x64, 0x00, 0x00, 0x00, 0xF4, 0x01,
    0x00, 0x00, 0x05, 0x00, 0x04, 0x00, 0x5F, 0x00, 0x02, 0x00, 0x02, 0x00, 0x01, 0x00, 0x00, 0x00,
    0x10, 0x27, 0x00, 0x00, 0x88, 0x13, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40, 0x00,
    0x30, 0x00, 0x0C, 0x00, 0x02, 0x00, 0x0A, 0x00, 0x09, 0x00, 0x01, 0x00, 0x2D, 0x00,
    0xCD
};

/* The fixed snapshot matching the golden vector (firmware health baseline
   Task 1 golden snapshot; health_* values = accounting state as of the last
   classified attempt, Round 3 item 3). */
static void set_fixed_snapshot(HealthSnapshot *snap)
{
    memset(snap, 0, sizeof(*snap));
    snap->fw_schema_version       = 1U;
    snap->fw_build_id             = 1U;
    snap->reset_cause             = 0x08U;
    snap->motion_state            = 1U;
    snap->lease_active            = 1U;
    snap->heartbeat_last_reason   = 2U;
    snap->heartbeat_timeout_count = 3U;
    snap->heartbeat_count         = 10U;
    snap->heartbeat_age_ms        = 200U;
    snap->connection_generation   = 1U;
    snap->snapshot_tick_ms        = 1000000U;
    snap->loop_seq                = 123456U;
    snap->loop_last_gap_ms        = 6U;
    snap->loop_max_gap_ms         = 500U;
    snap->telemetry_generated     = 100U;
    snap->telemetry_overwritten   = 5U;
    snap->telemetry_tx_started    = 95U;
    snap->telemetry_tx_ok         = 90U;
    snap->telemetry_tx_failed     = 5U;
    snap->cipsend_started         = 110U;
    snap->cipsend_completed       = 105U;
    snap->cipsend_ok              = 100U;
    snap->cipsend_error           = 1U;
    snap->cipsend_prompt_timeout  = 2U;
    snap->cipsend_sendok_timeout  = 1U;
    snap->cipsend_closed          = 1U;
    snap->cipsend_last_duration_ms = 100U;
    snap->cipsend_max_duration_ms = 500U;
    snap->ack_started             = 5U;
    snap->status_started          = 4U;
    snap->telemetry_started       = 95U;
    snap->diag_health_started     = 2U;
    snap->status_retry            = 2U;
    snap->ack_retry               = 1U;
    snap->boundary_aborts         = 0U;
    snap->uart_rx_bytes           = 10000U;
    snap->uart_tx_bytes           = 5000U;
    snap->uart_rx_overflow        = 0U;
    snap->uart_tx_overflow        = 0U;
    snap->uart_ore_events         = 0U;
    snap->uart_rx_high_water      = 64U;
    snap->uart_tx_high_water      = 48U;
    snap->health_generated        = 12U;
    snap->health_dropped          = 2U;
    snap->health_started          = 10U;
    snap->health_ok               = 9U;
    snap->health_failed           = 1U;
    snap->health_last_duration_ms = 45U;
}

/* Read a space-separated hex file into out (up to capacity bytes).
   Returns the number of bytes read, or 0 on failure. */
static int read_hex_file(const char *path, uint8_t *out, int capacity)
{
    FILE *f;
    int count = 0;
    unsigned int value;
    f = fopen(path, "r");
    if (f == 0) return 0;
    while (count < capacity && fscanf(f, " %x", &value) == 1) {
        out[count++] = (uint8_t)(value & 0xFFU);
    }
    fclose(f);
    return count;
}

static int bytes_equal(const uint8_t *a, const uint8_t *b, int n)
{
    int i;
    for (i = 0; i < n; i++) if (a[i] != b[i]) return 0;
    return 1;
}

/* ---- P0-1: RCC->CSR reset-cause → protocol u8 mapping ----
   Authoritative STM32F1 CSR (stm32f10x.h §RCC_CSR): reset flags live in
   the HIGH byte; the low bits are LSI status (LSION/LSIRDY) and must be
   ignored.  Mapping preserves each flag's bit position in the high byte
   with only RMVF (bit24) cleared: (csr >> 24) & 0xFC.
   PIN(b26)->0x04 POR(b27)->0x08 SFT(b28)->0x10 IWDG(b29)->0x20
   WWDG(b30)->0x40 LPWR(b31)->0x80  RMVF(b24)->0x00.
   (Codex implementation review Round 2: the previous test locked
   PIN=bit24/RMVF=bit31, so the earlier 17/17 acceptance could not prove
   this mapping.) */
static int test_reset_cause_from_csr(void)
{
    CHECK(health_reset_cause_from_csr(0x08000000U) == 0x08U);  /* PORRSTF  */
    CHECK(health_reset_cause_from_csr(0x20000000U) == 0x20U);  /* IWDGRSTF */
    CHECK(health_reset_cause_from_csr(0x04000000U) == 0x04U);  /* PINRSTF  */
    CHECK(health_reset_cause_from_csr(0x10000000U) == 0x10U);  /* SFTRSTF  */
    CHECK(health_reset_cause_from_csr(0x40000000U) == 0x40U);  /* WWDGRSTF */
    CHECK(health_reset_cause_from_csr(0x80000000U) == 0x80U);  /* LPWRRSTF */
    /* RMVF (bit24) is a write-to-clear control bit, never a reset cause. */
    CHECK(health_reset_cause_from_csr(0x01000000U) == 0x00U);
    /* Reserved bit25 (not a reset flag on this part) masks to 0. */
    CHECK(health_reset_cause_from_csr(0x02000000U) == 0x00U);
    /* PIN + POR combo (bits 26|27) -> 0x04 | 0x08 = 0x0C */
    CHECK(health_reset_cause_from_csr(0x0C000000U) == 0x0CU);
    /* Low-only 0x1F (LSI status bits) must map to 0, not leak through. */
    CHECK(health_reset_cause_from_csr(0x0000001FU) == 0x00U);
    /* No flags set -> 0. */
    CHECK(health_reset_cause_from_csr(0x00000000U) == 0x00U);
    return 0;
}

/* The IMU diagnostic image must be distinguishable from the previously
   flashed throughput-remediation image during the next hardware gate. */
static int test_imu_diagnostic_build_id(void)
{
    CHECK(FW_BUILD_ID == 3U);
    return 0;
}

static int test_encode_matches_golden(const char *hex_path)
{
    HealthSnapshot snap;
    uint8_t buf[HEALTH_FRAME_TOTAL_LEN];
    uint8_t from_file[HEALTH_FRAME_TOTAL_LEN];
    int n;

    set_fixed_snapshot(&snap);
    CHECK(health_frame_encode(buf, &snap) == HEALTH_FRAME_TOTAL_LEN);

    CHECK(bytes_equal(buf, k_golden, HEALTH_FRAME_TOTAL_LEN));

    /* Frame skeleton + checksum spot checks. */
    CHECK(buf[0] == 0xAA && buf[1] == 0x55 && buf[2] == HEALTH_FRAME_TYPE);
    CHECK(buf[3] == HEALTH_FRAME_PAYLOAD_LEN);
    {
        /* Golden checksum 0xCD (independent recomputation). */
        uint8_t cs = HEALTH_FRAME_TYPE ^ HEALTH_FRAME_PAYLOAD_LEN;
        int i;
        for (i = 0; i < HEALTH_FRAME_PAYLOAD_LEN; i++) cs ^= buf[4 + i];
        CHECK(cs == 0xCD);
    }

    /* Cross-language golden file lock: if a hex path is supplied, the file
       must agree with both the hardcoded golden and the encoder output. */
    if (hex_path != 0 && hex_path[0] != '\0') {
        n = read_hex_file(hex_path, from_file, HEALTH_FRAME_TOTAL_LEN);
        CHECK(n == HEALTH_FRAME_TOTAL_LEN);
        CHECK(bytes_equal(from_file, k_golden, HEALTH_FRAME_TOTAL_LEN));
        CHECK(bytes_equal(from_file, buf, HEALTH_FRAME_TOTAL_LEN));
    }

    puts("PASS test_health_frame");
    return 0;
}

int main(int argc, char **argv)
{
    const char *hex_path = (argc > 1) ? argv[1] : "";
    if (test_reset_cause_from_csr()) return 1;
    if (test_imu_diagnostic_build_id()) return 1;
    return test_encode_matches_golden(hex_path);
}
