# Camera Motion Evidence Adapter Design

Date: 2026-08-07
Status: design approved by user; implementation pending review
Scope: offline evidence preparation before the next authorized real-car run

## Purpose

The active car has no wheel encoders. The next step is therefore to make the
existing synchronized camera and TCP capture produce an auditable whole-car
motion observation. This supports digital-twin calibration without claiming
wheel RPM, per-wheel speed, or motor-side feedback.

## Evidence boundary

The system has one onboard IMU, one external camera pose source, and a TCP
transport. The camera is not an IMU and TCP is not a motion sensor.

The following are separate claims:

- `VERIFIED`: finite-difference math, schema validation, and fail-closed
  handling on offline data.
- `VERIFIED` after a qualifying run: raw camera pose and telemetry were
  captured, structurally synchronized, and the resulting motion records were
  generated.
- `INFERENCE`: camera-derived planar speed is a useful external body-motion
  reference for a no-encoder car.
- `INSUFFICIENT_EVIDENCE`: wheel RPM, per-wheel speed, slip, calibrated IMU
  sign/scale/drift, or any control improvement until dedicated real evidence
  exists.

## Reuse and data flow

The adapter must reuse the existing `capture_sync_run.py` lifecycle,
`V1Pose`, `V1TelemetryFrame`, synchronization gate, raw logging, and existing
IMU evidence summary. It must not add a TCP client, heartbeat sender, parser,
ACK registry, camera tracker, or second capture lifecycle.

The offline flow is:

1. Read the existing synchronized pose/telemetry records.
2. Pass the ordered calibrated `V1Pose` stream to
   `estimate_camera_motion()`.
3. Serialize camera-derived motion records as an additive artifact.
4. Compare valid camera yaw-rate records with valid IMU yaw changes only as
   an evidence report; do not fuse them into firmware control.
5. Preserve all raw inputs and mark invalid intervals explicitly.

## Artifacts

For each capture run, add:

- `camera_motion.jsonl`: one immutable observer record per input pose,
  labeled `CAMERA_POSE_DERIVATIVE`, using `mm`, `s`, and `rad` units.
- `motion_evidence.json`: counts, valid/invalid interval counts, time span,
  speed/yaw-rate summary statistics, IMU-overlap counts, and evidence status.

The report must state that speed and yaw rate are external whole-car camera
derivatives. It must not use names such as `motor_speed`, `wheel_rpm`, or
`encoder_velocity`.

The report may summarize overlap with IMU yaw, but it must not silently infer
an IMU sign, scale, bias, or calibration from an arbitrary run. Those values
remain configuration or future calibration outputs.

## Failure behavior

The adapter is fail-closed:

- the first pose has no derivative;
- non-monotonic timestamps produce no derivative;
- gaps above the observer bound produce no derivative and reset the
  predecessor;
- malformed or incompatible records fail the offline command rather than
  producing partial fabricated motion values;
- synthetic input is labeled `INSUFFICIENT_EVIDENCE` and can never become
  real synchronization evidence merely because the report is structurally
  valid.

Existing synchronization and cleanup behavior remains authoritative. A
failed synchronization gate must remain failed even if camera-motion math
passes.

## Testing

Add tests before implementation for:

- additive artifact creation from valid pose and telemetry records;
- camera-motion records retaining units and source labels;
- valid/invalid interval counts and summary statistics;
- IMU-overlap reporting without changing the IMU sign or scale;
- fail-closed propagation of timestamp gaps and insufficient evidence;
- no second transport or capture lifecycle.

Run the focused tests, the complete Python regression, compileall, and
`git diff --check`. No test may open a camera, socket, debugger, or motor
control path.

## Next hardware gate

After offline implementation and verification, stop and request explicit
authorization for one synchronized camera + TCP + MPU6050 run. The user must
place the camera over the fixed track and confirm the car's physical safety
boundary. The run may produce whole-car motion evidence; it cannot establish
wheel RPM or authorize firmware control changes by itself.

## Non-goals

- no Kalman filter in this change;
- no firmware control change;
- no encoder emulation;
- no motor-speed claim from PWM;
- no B3 threshold relaxation;
- no real hardware action during offline implementation.
