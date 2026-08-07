# MPU6050 initialization repair offline handoff

Date: 2026-08-06 Asia/Shanghai
Task: bounded, diagnosable MPU6050 initialization and existing telemetry
status propagation
Status: OFFLINE VERIFIED; FLASH VERIFIED; ELEVATED START COMPLETED; MPU INIT FAILED ON HARDWARE

## Scope

This handoff makes MPU6050 initialization finite, retryable, fail-closed, and
observable through the existing telemetry path. It does not change PID,
line-following direction, motor output, speed limits, turn logic, safety stops,
transport ownership, framing, or capture lifecycle.

The existing software-I2C driver and existing 31-byte wire frame are reused.
The existing 26-byte payload remains in place:

- payload byte 24: `imu_validity`
- payload byte 25 / complete wire byte 29: `imu_init_status`

Legacy 24-byte payloads remain accepted and report
`imu_init_status_known=false`.

## Changed files

- `firmware/stm32_line_follower/Hardware/mpu6050.h`
- `firmware/stm32_line_follower/Hardware/mpu6050.c`
- `firmware/stm32_line_follower/User/main.c`
- `simulation/digital_twin/real_world/frame_parser.py`
- `simulation/digital_twin/v1_twin/v1_twin_schema.py`
- `simulation/digital_twin/v1_twin/v1_twin_pose_fusion.py`
- `tools/camera_toolchain/capture_sync_run.py`
- `simulation/digital_twin/tests/test_mpu6050_validity.c`
- `simulation/digital_twin/tests/test_frame_parser_health.py`
- `simulation/digital_twin/tests/test_v1_twin_schema.py`
- `simulation/digital_twin/tests/test_v1_twin_pose_fusion.py`
- `simulation/digital_twin/tests/test_capture_sync_cleanup.py`
- `simulation/digital_twin/tests/mpu_stubs/Delay.h`
- `simulation/digital_twin/tests/mpu_stubs/stm32f10x.h`

No parallel TCP client, telemetry parser, protocol, ACK registry, or capture
session was introduced.

## Firmware contract

`MPU6050_Init` performs one complete initialization attempt and at most three
additional complete retries, for a maximum of four attempts. The address is
fixed at `0x68`; `0x69` is never probed automatically. A failed initialization
leaves the validity flags clear and cannot be promoted by a later readable
sample.

Status values:

| Code | Meaning |
| --- | --- |
| `0x00` | initialization successful |
| `0x01` | not attempted |
| `0x10` | reset register write failed |
| `0x11` | wake register write failed |
| `0x12` | sample-rate register write failed |
| `0x13` | filter configuration write failed |
| `0x14` | gyro configuration write failed |
| `0x15` | accelerometer configuration write failed |
| `0x20` | WHO_AM_I read transaction failed |
| `0x21` | WHO_AM_I value mismatched |
| `0x30` | bias sample read failed |

Successful fusion still requires the existing `INIT | BIAS | READ | UPDATED`
validity conditions with `DT_CLAMPED` clear. A nonzero boot status is rejected
by the existing fusion path with an auditable failure reason.

## TDD evidence

The Host C failure-injection tests and the Python parser/schema/fusion tests
were written and observed failing before the production implementation. The
production changes then made the bounded retry, status decoding, schema
round-trip, and fail-closed fusion tests pass.

## Fresh verification

All relative-path commands below were run from the canonical digital-twin
workspace root unless stated otherwise.

```text
py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
-> 671 passed, 5 skipped in 26.77s

py -3.11 -m compileall -q simulation/digital_twin tools
-> exit 0

git diff --check
-> exit 0; Git emitted only existing LF/CRLF conversion warnings
```

Host C used MSVC through the existing x64 environment setup:

```text
call "D:\vs2022\VC\Auxiliary\Build\vcvars64.bat"
cl /nologo /TC /W4 /WX /source-charset:utf-8 ...
```

Outputs are under
`.embeddedskills/build/2026-08-06-mpu6050-init-repair/hostc/`:

- `test_mpu6050_validity.c` with the real `Hardware/mpu6050.c` and existing
  MPU stubs: compile and run exit 0, `PASS test_mpu6050_validity`.
- `test_telemetry_batch.c` with the real `User/telemetry_batch.c`: compile and
  run exit 0, `telemetry_batch: all tests passed`.
- `test_cipsend_tx.c` with the real CIPSEND modules: compile and run exit 0,
  `PASS test_cipsend_tx`.

Keil verification used the canonical project and UV4 executable:

```text
py -3.11 C:\Users\24668\.codex\skills\keil\scripts\keil_project.py targets \
  --project "firmware\stm32_line_follower\project.uvprojx" --json
-> exactly one target: Target 1

py -3.11 C:\Users\24668\.codex\skills\keil\scripts\keil_build.py rebuild \
  --uv4 F:\keil\UV4\UV4.exe \
  --project "firmware\stm32_line_follower\project.uvprojx" \
  --target "Target 1" \
  --log-dir ".embeddedskills\build\2026-08-06-mpu6050-init-repair\keil" --json
-> exit 0; 0 Error(s), 0 Warning(s)
```

Build metrics are Code=24020, RO-data=460, RW-data=156, ZI-data=3052.
The current AXF is
`firmware/stm32_line_follower/Objects/Project.axf` with SHA-256
`DEF9E50B261B5D289DA3ABF8A0F905B1864D7756EE749DC5B0AA3F6F46CC58C8`.
The build log is
`.embeddedskills/build/2026-08-06-mpu6050-init-repair/keil/project-Target 1-rebuild.log`.

After explicit user authorization, the exact AXF above was flashed with Keil
Target 1 through the connected ST-Link:

```text
py -3.11 C:\Users\24668\.codex\skills\keil\scripts\keil_build.py flash \
  --uv4 F:\keil\UV4\UV4.exe \
  --project "firmware\stm32_line_follower\project.uvprojx" \
  --target "Target 1" \
  --log-dir ".embeddedskills\build\2026-08-06-mpu6050-init-repair\keil" --json
-> exit 0; flash succeeded
```

The flash log is
`.embeddedskills/build/2026-08-06-mpu6050-init-repair/keil/project-Target 1-flash.log`.
It records `Erase Done`, `Programming Done`, `Verify OK`, and
`Application running`. A post-flash hash check still reports
`DEF9E50B261B5D289DA3ABF8A0F905B1864D7756EE749DC5B0AA3F6F46CC58C8`.

## Passive static observation

At 22:37 on 2026-08-06, the existing `transport_soak.py` passive mode was
run for five seconds against the configured ESP-01S endpoint. The passive
mode sent no command frames.

Evidence directory:
`logs/v1_mpu6050_static/soak_20260806_223705/`

- `raw_io.json`: 6 RX events, 594 RX bytes, 0 TX events, 0 TX bytes.
- `raw_health.json`: 5 health frames; all report `fw_build_id=2`,
  `motion_state=0`, `lease_active=0`, `telemetry_generated=0`, and
  `telemetry_tx_ok=0`.
- `raw_telemetry.json`: 0 telemetry frames.
- `transport_report.json`: passive mode, handshake `N/A`, exit code 3 because
  cadence and nonblocking evidence are insufficient with zero telemetry.

This is evidence that the TCP observation path reached the flashed firmware
and that the firmware was still motion-inhibited. It is not evidence of an
MPU initialization failure. The current firmware intentionally does not
generate telemetry while motion is inhibited; the IMU validity and boot
status cannot be checked in this passive state.

## Authorized elevated-wheel runtime observation

After the passive observation, the user separately authorized only a bounded
elevated-wheel `START -> telemetry collection -> STOP` session. No ground
motion was authorized or used.

Command:

```text
py -3.11 tools/shakedown_toolchain/ground_shakedown.py --host 192.168.110.236 --port 8888 --duration 0.5 --run-kind elevated-wheels --out-root logs --execute
```

Evidence directory:
`logs/v1_ground_shakedown_260806224756564/`

The command returned `SHAKEDOWN_PASS`. The run used the flashed AXF with
SHA-256
`DEF9E50B261B5D289DA3ABF8A0F905B1864D7756EE749DC5B0AA3F6F46CC58C8`.

### VERIFIED real-hardware control evidence

- The report has `control_verdict=PASS`, `stop_confirmed=true`,
  `rollback_requested=true`, and proven quiescence.
- All five bounded speed updates (`580, 480, 380, 280, 260`) received one
  correlated `APPLIED/APPLIED` ACK each.
- The same campaign/run observed `START/RUNNING`, two heartbeats, terminal
  `STOP/STOPPED`, and completed transport close.
- `raw_io.json` contains 14 RX events and 10 TX events. Replaying its bytes
  through the existing parser found 14 valid binary frames and zero checksum
  failures/resynchronizations: 12 telemetry frames and two health frames.
- Health evidence reports `fw_build_id=2`, schema `1`, no heartbeat timeout,
  no CIPSEND error, and no UART overflow. The camera recorder exited cleanly
  at `1280x720`, `30/1` FPS; the input log verifies source `MJPG` while the
  Matroska output tag is container-unspecified.

### VERIFIED real-hardware MPU failure

The top-level report's
`imu_evidence_status=UNVERIFIED_NO_VALIDITY_BIT` is incomplete because the
current `_SessionLoop._on_telemetry()` adapter drops the two IMU fields. The
immutable raw bytes were independently decoded with the existing
`decode_telemetry` parser:

- All 12 telemetry frames have `imu_init_status=0x21`, the firmware's
  `WHO_AM_I_MISMATCH` code.
- The first frame has `imu_validity=0x14`; the remaining 11 have `0x04`.
  The required `INIT|BIAS|READ|UPDATED` mask is `0x0F`, so no frame proves
  valid fusion input.
- The first frame has `DT_CLAMPED=0x10`; the later frames do not. `yaw=0.0`
  throughout is consistent with the fail-closed firmware path and is not
  proof that the IMU pose is valid.

This verifies a real-hardware MPU initialization failure. It does not yet
identify whether the physical cause is I2C wiring/power, AD0/addressing, or a
different device response.

### VERIFIED offline evidence adapter repair

- `_SessionLoop._on_telemetry()` now preserves `imu_yaw_deg_x100`,
  `imu_validity`, `imu_validity_known`, `imu_init_status`, and
  `imu_init_status_known` in each report frame.
- `summarize_imu_evidence()` separates `VERIFIED` evidence from
  `INSUFFICIENT_EVIDENCE` and carries a separate `verdict=PASS/FAIL`, so a
  known MPU failure cannot be mistaken for missing data or a passing sensor.
- Replaying the existing raw run through the new offline path gives
  `status=VERIFIED`, `verdict=FAIL`, `imu_init_status=0x21`, validity values
  `0x14/0x04`, and one `DT_CLAMPED` frame. The old immutable report is not
  rewritten; it was generated before this adapter repair.
- The timestamp regression in the existing execute path was fixed with one
  regression test. Focused ground-shakedown tests are `106 passed`; the full
  Python suite is `675 passed, 5 skipped`.

## Evidence boundary

### VERIFIED

- Offline bounded initialization and retry ceiling.
- Distinct initialization stage statuses in the existing telemetry frame.
- Legacy 24-byte parser compatibility.
- Schema round-trip and fail-closed fusion behavior.
- Host C contracts, full current Python regression, compileall, diff check, and
  Keil Target 1 rebuild.
- The verified AXF was flashed after explicit authorization. No START/STOP,
  serial send, camera session, or motor motion was performed.
- The passive TCP observation connected to the flashed `fw_build_id=2` image,
  received five health frames, sent zero bytes, and received zero telemetry
  frames.
- The bounded elevated-wheel session completed the full START/RUNNING and
  STOP/STOPPED control lifecycle with raw evidence, but its IMU fields show a
  `WHO_AM_I` mismatch rather than a valid initialized sensor.

### INFERENCE

- `0x21` proves the firmware received a value from the WHO_AM_I read path and
  rejected it, but the raw session does not identify the physical root cause.

### INSUFFICIENT EVIDENCE

- The physical cause of the WHO_AM_I mismatch, bias quality after repair,
  axis sign/scale, camera/IMU synchronization, and any vehicle improvement.
- Any ground no-line-loss or high-speed sharp-turn result.
- A new hardware report generated after this adapter repair, so the persisted
  report-level IMU summary can be checked without a separate raw-byte reparse.

## Next interface

Stop hardware work at this boundary. The offline evidence adapter is now
repaired. Next inspect physical MPU power, common ground, I2C pull-ups,
SDA/SCL wiring, AD0/address selection, and the actual WHO_AM_I response. Only
after that requires separate explicit authorization for another bounded
elevated-wheel session, with
`imu_validity=0x0F`, `DT_CLAMPED=0`, and `imu_init_status=0x00` as gates before
any ground motion.
