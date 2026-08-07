# MPU alternate-identity compatibility regression recovery

Date: 2026-08-07 Asia/Shanghai
Status: RECOVERY_FLASHED_PASSIVE_DIAGNOSTIC_VERIFIED

## Verified runtime observation

The compatibility AXF with SHA-256
`FEB4D761F4AF714D1A5BB0D70728A60724374A3542AF040D37D2E2F316553DDB` was
flashed through Keil Target 1 at 12:29:47. After the ESP setup window,
`192.168.110.236` still answered ping but TCP port `8888` actively refused
connections. No MCU bytes or motion commands were sent after the flash.

This is a real regression observation compared with the immediately
preceding Build 3 passive sessions. It does not alone identify whether the MCU
stopped during startup or the ESP server was not re-established.

## Root-cause finding

The only hardware-path change after the preceding observable image was in
`mpu6050.c`: the stable `WHO_AM_I=0x70` response changed from a diagnostic
mismatch to an accepted identity. The driver then executed the MPU6050
reset/configuration sequence and 100-sample gyro bias read. The model-specific
compatibility assumption was not verified on hardware.

## Recovery contract

- Accept only `0x68` in the verified MPU6050 driver.
- Preserve `0x70` as the observed diagnostic ID.
- Reject `0x70` before any reset/configuration write or bias sampling.
- Do not change TCP, PID, motor, telemetry, or control behavior.

The Host C regression asserts that `0x70` produces `init_status=0x21`, retains
`observed_id=0x70`, and performs zero reset writes.

## Offline verification

- Host C `test_mpu6050_validity`: `PASS test_mpu6050_validity`.
- Python regression: `676 passed, 5 skipped`.
- Python compileall: exit 0.
- Keil Target 1 rebuild: `0 Error(s), 0 Warning(s)`.
- Recovery AXF SHA-256:
  `76689F796C4FD1AFDD478352B49A84F21F719301F36FFB339C9CAD17B2786B32`.
- Build log:
  `.embeddedskills/build/2026-08-07-mpu-fail-closed/keil/project-Target 1-rebuild.log`

## Hardware retest

After explicit authorization, the recovery AXF was flashed through Keil
Target 1 at 12:54:36. The first passive retest at 12:55:22 still received
WinError 10061 from `192.168.110.236:8888`; ping remained available. No MCU
bytes or motion commands were sent and no diagnostic frame was received.

This result disproves the stronger hypothesis that accepting `0x70` alone
caused the TCP service failure. A complete car/ESP power cycle is now the next
single hardware variable. Keep the car motion-inhibited and use the existing
passive TCP path only after the power cycle. Do not send `START` until the
service and diagnostic frame are observed.

The Li-ion battery power-cycle retest connected successfully. It recorded 4
RX events / 270 RX bytes and 0 TX events / 0 TX bytes with zero parser errors.
The diagnostic frame was
`AA 55 7D 04 70 21 00 00 28`: observed ID `0x70`, init status `0x21`, and
validity flags `0x00`. Two health frames reported Build 3, motion inhibited,
and no UART or CIPSEND errors. The recovery firmware and passive transport are
therefore verified after power cycling; MPU initialization remains blocked and
no motion test is authorized by this evidence.
