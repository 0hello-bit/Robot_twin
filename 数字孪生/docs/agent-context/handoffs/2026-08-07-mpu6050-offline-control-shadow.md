# MPU6050 offline control-shadow handoff

Date: 2026-08-07 Asia/Shanghai

## Status

OFFLINE VERIFIED; HARDWARE DYNAMIC-YAW GATE PENDING

The latest authorized elevated-wheel run reported `imu_init_status=0x00` and
normal validity `0x0F` (one `0x1F` frame was `DT_CLAMPED`). This verifies the
initialization/read/update status reported by the current firmware in that
run. Yaw was `0.0` degrees in every observed frame, so dynamic response and
axis sign are not verified.

## Changes

- Added `simulation/digital_twin/v1_twin/v1_twin_imu_control.py`.
  - `V1ImuControlShadow` makes a bounded hypothetical turn correction only
    from an eligible `V1PoseFusionRecord`.
  - Invalid, unknown, stale, initialization-failed, or `DT_CLAMPED` samples
    fail closed to the baseline turn.
  - `summarize_imu_evidence()` reports coverage, fallback reasons, timestamp
    monotonicity, and yaw residuals.
- Added `simulation/digital_twin/tests/test_v1_twin_imu_control.py` with seven
  contracts for control influence, fail-closed behavior, bounds,
  determinism, synthetic evidence, real-sync prerequisites, and timestamp
  regression.
- Extended `tools/camera_toolchain/capture_sync_run.py` to write additive
  `imu_evidence.json` beside `fusion.jsonl`; raw pose/telemetry files and the
  synchronization verdict are untouched.
- Extended the capture artifact test to assert that its synthetic fixture is
  explicitly `INSUFFICIENT_EVIDENCE`.

## Verification

- Focused IMU shadow tests: `7 passed`.
- Capture cleanup/artifact tests: `27 passed`.
- Pose-fusion and schema tests: `41 passed`.
- Full current Python regression, excluding the archived legacy tree:
  `685 passed, 5 skipped`.
- `py -3.11 -m compileall -q simulation/digital_twin tools`: exit 0.
- `git diff --check`: exit 0; only existing LF/CRLF conversion warnings.

## Evidence boundary

### VERIFIED

- The latest real run reported successful IMU initialization and valid sample
  flags as described above.
- The offline control-shadow and evidence-summary contracts pass.
- The existing capture path can publish the additive IMU evidence summary.

### INFERENCE

- The shadow path is a suitable interface for later testing whether yaw can
  affect a constrained turn decision.
- Incremental camera/IMU residuals are more meaningful than comparing absolute
  yaw values, because the IMU yaw origin may have an unknown offset.

### INSUFFICIENT EVIDENCE

- Dynamic yaw response, sign, scale, bias, drift, and timing on the physical
  car.
- Any real-car line-loss, speed, or high-speed sharp-turn improvement.
- Any claim that MPU6050 currently changes firmware control; it does not.
- Any digital-twin calibration or AI iteration result.

## Next interface

The car is currently outside this offline task and must remain unpowered until
the next explicit hardware authorization. The next experiment is a bounded
elevated-wheel rotation observation to verify non-zero yaw response and sign.
Do not modify real firmware control before that gate passes.
