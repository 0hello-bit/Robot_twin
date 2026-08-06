# MPU6050 Pose Participation Design

Date: 2026-08-06
Status: DESIGN_APPROVED_PENDING_USER_SPEC_REVIEW

## Purpose

Make the existing MPU6050 measurement participate in the robot pose data
chain while preserving the camera AprilTag pose as the global reference. The
feature is for synchronized observation and digital-twin data; it must not
change motor control, line-following decisions, or safety stops in this
increment.

## Current Boundary

The current firmware already performs these actions:

- `MPU6050_Init()` is called during boot.
- The running loop reads the device and integrates Z-axis gyro rate into
  `mpu_data.yaw`.
- The binary telemetry frame carries the integrated yaw as a signed integer
  scaled by 100. The wire value is degrees, even though some historical host
  names use `yaw_rad`.

The current host path does not use that measurement for pose estimation:

- `capture_sync_run.py` converts the wire degree value to radians and stores
  it in the telemetry record.
- `PoseTracker` computes `V1Pose` from AprilTag corners and homography only.
- No camera/IMU yaw fusion or IMU validity gate exists.

The current MPU yaw is relative gyro integration. It has a static Z-bias
calibration but no absolute heading reference, magnetometer correction, or
camera correction. It must not be treated as absolute global heading.

## Goals

1. Make IMU unit, validity, and sample timing explicit in the telemetry
   contract.
2. Keep legacy 24-byte telemetry payloads readable as camera-only/IMU-unknown
   records.
3. Produce separate raw camera pose, raw IMU orientation, and fused yaw
   evidence.
4. Use camera pose as the global correction and IMU delta yaw for short-term
   propagation between camera observations.
5. Fail closed to camera-only output when IMU validity, timing, or gap limits
   are not satisfied.
6. Keep the existing B3 camera/telemetry synchronization gate unchanged in the
   first implementation. Fusion evidence is additive and cannot turn a B3
   FAIL into a PASS.

## Non-goals

- Do not use IMU yaw, gyro rate, or fused yaw to alter line-following control.
- Do not use IMU yaw to reverse or compensate the sensor-to-motor direction
  mapping.
- Do not claim absolute heading accuracy or eliminate gyro drift.
- Do not replace the AprilTag x/y position with dead reckoning.
- Do not add a new TCP client, parser, heartbeat loop, or session lifecycle.
- Do not perform a hardware run or flash as part of the offline implementation.

## Chosen Architecture

### 1. Firmware telemetry extension

Reuse the existing binary telemetry frame and batch path. Extend the current
24-byte payload to 26 bytes:

| Payload offset | Field | Encoding |
| --- | --- | --- |
| 0..19 | Existing sensors, signed PWM, error, PID output, tick | unchanged |
| 20..23 | `imu_yaw_deg_x100` | signed little-endian int32 |
| 24 | `imu_validity` | uint8 bit flags |
| 25 | reserved | uint8, encoded as zero |

The frame length becomes 31 bytes including the existing 5-byte binary frame
header/checksum. The latest-five batching policy remains in place; its buffer
and maximum CIPSEND payload are increased only as required by the new fixed
frame size and tested as one change.

Validity bits:

- bit 0: initialization and WHO_AM_I configuration completed;
- bit 1: static Z-bias calibration completed;
- bit 2: the most recent 14-byte sensor read succeeded;
- bit 3: the yaw sample was updated in the current control cycle;
- bit 4: the yaw integration `dt` was clamped;
- bits 5..7: reserved and zero.

`ready` must not become true merely because a later read succeeds after an
initialization failure. The firmware keeps initialization/calibration state
separate from per-read freshness and encodes both in `imu_validity`.

The existing wire yaw remains a relative degree value. No sign inversion or
absolute-heading claim is introduced by this schema.

### 2. Host telemetry model

The host decoder accepts both payload lengths:

- 24-byte legacy payload: `imu_validity=0`, IMU use is disabled and the record
  is labeled legacy/unknown;
- 26-byte current payload: decode `imu_yaw_deg_x100` and validity flags.

The internal model exposes an explicit `imu_yaw_rad` value for new code while
retaining compatibility for historical JSON records that contain `yaw_rad`.
The value is converted exactly once from wire degrees to radians. Report
metadata must call the raw wire unit `degrees` and the normalized model unit
`radians`; neither name may be used ambiguously.

### 3. Camera-anchored yaw fusion

Add a small pure host module, separate from `PoseTracker`, with one explicit
state machine:

1. A first synchronized camera pose and valid IMU sample establish the yaw
   anchor. The fused yaw equals the camera yaw at this point.
2. For each later synchronized sample, propagate the previous fused yaw by the
   unwrapped IMU yaw delta, applying an explicit configurable sign.
3. When a valid camera pose is available, apply a bounded complementary
   correction toward the camera yaw. The correction gain is configuration,
   not an automatically tuned hardware claim.
4. If the IMU validity flags are incomplete, the sample is stale, timestamps
   are non-monotonic, or the IMU gap exceeds the configured limit, emit a
   camera-only result and record the fallback reason.
5. The camera remains the only source of x/y. A camera-missing interval may
   produce an orientation-only prediction record, but it must not fabricate a
   complete `V1Pose` position.

The output is a separate fusion record containing:

- camera pose timestamp and yaw when present;
- raw IMU yaw and validity flags;
- propagated yaw, corrected/fused yaw, and the configured sign/gain;
- `USED_IMU`, `CAMERA_ONLY`, or `INSUFFICIENT_EVIDENCE` quality;
- fallback reason and IMU gap.

The existing camera `pose.jsonl` and telemetry `telemetry.jsonl` remain raw
inputs and are never overwritten by fused output. A new fusion artifact is
written beside them.

## Timing and Coordinate Contract

- MCU `tick_ms` is mapped to PC monotonic time by the existing `ClockSync`.
- Camera frame timestamps continue to be captured immediately after
  `cap.read()` succeeds.
- All yaw calculations use radians internally and wrap angular residuals to
  `[-pi, pi)`.
- The IMU sign is a named configuration value. It is not silently inferred
  from a single run.
- The first implementation uses camera x/y and camera global yaw as the
  authoritative pose reference; IMU is a relative short-term orientation
  contributor only.

## Failure and Evidence Rules

- Missing IMU validity is not converted into a valid zero yaw.
- Legacy telemetry remains usable for the existing camera-only B3 gate.
- Fused output is never allowed to improve a gate by replacing raw metrics.
- A successful parser/build/test is offline evidence only; it is not evidence
  that the MPU6050 is physically connected or correctly oriented.
- Hardware evidence must separately verify initialization, sign, scale,
  drift, sample freshness, and camera/IMU timing before any future control use
  is considered.

## Tests and Acceptance

The implementation is accepted offline only when all of the following exist:

1. A failing test proves a 26-byte telemetry payload decodes the IMU flags and
   degree value, while a 24-byte legacy payload remains IMU-unknown.
2. A failing test proves a first valid camera/IMU pair anchors fused yaw to
   camera yaw.
3. A failing test proves a known IMU delta propagates yaw during a camera gap.
4. A failing test proves camera correction removes a known bounded drift.
5. A failing test proves invalid/stale IMU data falls back to camera-only and
   never fabricates x/y.
6. A failing test covers angular wraparound and non-monotonic timestamps.
7. Existing telemetry, parser, capture cleanup, B2, and B3 regression tests
   remain green.
8. Offline artifacts explicitly distinguish `VERIFIED`, `INFERENCE`, and
   `INSUFFICIENT EVIDENCE`.

The later hardware acceptance is a separate authorized gate: build and flash
the tested image, verify IMU validity on the real car, perform a bounded
stationary/turn sign test, and then collect a synchronized run. It must not
change the line-following controller during this feature.

## Review Boundary

This document authorizes planning, not implementation. The next step is a
TDD implementation plan with disjoint firmware, decoder/model, fusion, and
report/test tasks. Production code must not be written until that plan is
reviewed and executed through the required failing-test-first cycle.
