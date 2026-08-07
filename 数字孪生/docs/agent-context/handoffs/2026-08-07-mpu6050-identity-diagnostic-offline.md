# MPU6050 identity diagnostic offline handoff

Date: 2026-08-07 Asia/Shanghai
Status: COMPATIBILITY_PATCH_FLASHED; PASSIVE_POSTFIX_OBSERVATION_PENDING

## Verified problem boundary

The immutable run `logs/v1_ground_shakedown_260806224756564/raw_io.json`
contains 12 valid current telemetry payloads. Every payload reports
`imu_init_status=0x21`; the old payload did not contain the raw WHO_AM_I byte.
The current evidence proves a real initialization failure, but does not prove
the physical cause. No claim of MPU6500, AD0, wiring, power, or collision is
made from that status alone.

The fresh passive session at
`logs/v1_mpu6050_identity_260807/soak_20260807_120419/` sent zero bytes and
recorded 13 valid binary frames with zero checksum or resynchronization
failures. Its first binary frame was:

`AA 55 7D 04 70 21 00 00 28`

Therefore the physical car returned a stable readable `WHO_AM_I=0x70`, with
the old firmware still reporting `init_status=0x21` and `validity_flags=0x00`.
Twelve health frames all reported `fw_build_id=3`, `motion_state=0`, and
`lease_active=0`. No START, STOP, heartbeat, or motion command was sent.

An independent recheck after a power cycle at
`logs/v1_mpu6050_identity_recheck_260807/soak_20260807_122531/` sent zero
bytes and decoded 11 valid binary frames with zero checksum or
resynchronization failures. It again reported `0x7D = 70 21 00 00` and ten
health frames with `fw_build_id=3`, `motion_state=0`, and `lease_active=0`.

After the compatibility AXF was flashed, passive attempts at 12:31:31,
12:32:15, and 12:34:11-12:34:19 received `WinError 10061` from
`192.168.110.236:8888`. Ping and ARP verified the ESP host was online, but the
TCP service actively refused connections after the expected ESP setup window.
No MCU bytes were sent and no post-fix IMU frame was received. This blocks
post-fix observation; it does not classify the compatibility initialization.

## Changes in this handoff

- `firmware/stm32_line_follower/Hardware/mpu6050.c/.h`: read WHO_AM_I first,
  keep the raw ID tied to the final initialization attempt, clear it when the
  final WHO_AM_I transaction fails, and expose `MPU6050_GetObservedID()`.
- `firmware/stm32_line_follower/Hardware/mpu6050.c/.h`: explicitly accept
  `0x68` (MPU6050) and `0x70` (MPU6500-class) identities; keep unknown IDs
  fail-closed. The existing common register sequence is unchanged.
- `firmware/stm32_line_follower/User/imu_diagnostic.h`: pure encoder for one
  additive type `0x7D`, 4-byte payload, 9-byte frame, plus the SEND-OK
  delivery predicate.
- `firmware/stm32_line_follower/User/main.c`: send that frame once through the
  existing CIPSEND diagnostic path when a client is available, retain it after
  failed transactions, and clear it only after the distinct IMU diagnostic
  tag receives `SEND OK`; no new transport or control behavior.
- `firmware/stm32_line_follower/User/cipsend_tx.h`: distinct
  `CIPSEND_TX_TAG_IMU_DIAGNOSTIC`.
- `firmware/stm32_line_follower/User/health_frame.h`: `FW_BUILD_ID=3`.
- `simulation/digital_twin/real_world/frame_parser.py`: decode type `0x7D`.
- `simulation/digital_twin/tests/test_mpu6050_validity.c`: raw-ID retention
  and identity-before-write contracts.
- `simulation/digital_twin/tests/test_imu_diagnostic.c` and
  `test_frame_parser_health.py`: frame and parser contracts.
- `firmware/stm32_line_follower/project.uvprojx`: registers the new header.

## Fresh verification

- ARMCC C99 source compilation passed for the changed
  `test_mpu6050_validity.c` and `mpu6050.c`; current Host C runtime execution
  is not claimed because no host C compiler is installed.
- Focused Host C: `PASS test_imu_diagnostic`.
- Host C: `telemetry_batch: all tests passed`.
- Host C: `PASS test_cipsend_tx`.
- Host C: `PASS test_health_frame`.
- Python: `676 passed, 5 skipped` with `--ignore=archive`.
- `py -3.11 -m compileall -q simulation/digital_twin tools`: exit 0.
- `git diff --check`: exit 0; only existing LF/CRLF warnings.
- Keil target enumeration: exactly `Target 1`.
- Keil `Target 1` rebuild from the compatibility source:
  `0 Error(s), 0 Warning(s)`; Code=24284, RO-data=460,
  RW-data=156, ZI-data=3052; exit 0.
- ARMCC C99 source compilation passed for `test_imu_diagnostic.c` and
  `test_mpu6050_validity.c`.
- AXF:
  `firmware/stm32_line_follower/Objects/Project.axf`
- AXF SHA-256:
  `FEB4D761F4AF714D1A5BB0D70728A60724374A3542AF040D37D2E2F316553DDB`
- Keil log:
  `.embeddedskills/build/2026-08-07-mpu6500-compat/keil/project-Target 1-rebuild.log`
- Keil flash log:
  `.embeddedskills/build/2026-08-07-mpu6500-compat/keil/project-Target 1-flash.log`
- After explicit authorization on 2026-08-07 at 12:29:47, this exact
  compatibility AXF was flashed through Keil Target 1 with ST-Link. The flash
  log records `Erase Done`, `Programming Done`, `Verify OK`, and
  `Application running`. No START, STOP, or motion command was sent.

## Evidence classification

### VERIFIED

- The previous real run contains a genuine nonzero WHO_AM_I mismatch status.
- The fresh passive real run verified a stable readable `0x70` responder and
  captured the diagnostic frame with zero TX bytes and zero parser errors.
- The new source records the final-attempt raw ID and emits it through the
  existing transport path.
- The compatibility source explicitly accepts `0x70` and keeps `0x71`
  fail-closed in the C test contract.
- The Python parser contracts execute, the C assertions compile under ARMCC
  C99, and the Keil firmware build passes offline. Current Host C runtime
  execution is intentionally not claimed.
- The exact compatibility AXF was flashed and verified through Keil. This is
  programmer evidence only; post-fix IMU initialization remains unverified.

### INFERENCE

- `0x70` is consistent with an MPU6500-class responder, but the exact module
  marking is not independently verified. The current register sequence uses
  the subset shared by the explicitly accepted identities, so the compatibility
  path is a bounded inference pending post-flash hardware confirmation.

### INSUFFICIENT EVIDENCE

- The post-fix init status and validity flags after this compatibility AXF
  boots on the physical car.
- Physical power, common ground, pull-ups, AD0, SDA/SCL integrity, and bus
  waveform.
- Current Host C runtime execution for the changed test source is not claimed;
  no host C compiler is installed in the current environment and the older
  executable was not reused.
- Valid IMU bias, axis sign/scale, camera synchronization, or any vehicle
  improvement.

## Next interface

First restore the existing TCP service and verify a passive health/diagnostic
connection. Keep the car motion-inhibited and require the new `0x7D` frame to
report `init_status=0x00` before any START or ground motion is considered.
