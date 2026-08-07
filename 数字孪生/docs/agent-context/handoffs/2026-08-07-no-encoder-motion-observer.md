# No-Encoder Motion Observer Handoff

Date: 2026-08-07 Asia/Shanghai
Task: offline camera-derived whole-car motion observation
Status: OFFLINE VERIFIED; REAL MOTION EVIDENCE PENDING

## Scope

The active car has no wheel encoder feedback. This task adds a small offline
observer that derives whole-car planar velocity, planar speed, and yaw rate
from the existing calibrated camera `V1Pose` stream. It does not estimate four
wheel speeds, does not claim motor RPM, and does not feed firmware control.

## Changed files

- `simulation/digital_twin/v1_twin/v1_twin_motion_observer.py`
  implements `estimate_camera_motion()` and immutable `V1CameraMotion` records.
- `simulation/digital_twin/tests/test_v1_twin_motion_observer.py`
  covers valid differences, first-sample rejection, timestamp/gap rejection,
  shortest-angle yaw rate, immutability, and input validation.
- `docs/agent-context/PROJECT_MEMORY.md`
  records the no-encoder boundary and naming rule.
- `docs/agent-context/CURRENT_STATUS.md`
  records the offline acceptance boundary.

## Contract

`estimate_camera_motion(poses, max_gap_ns=100_000_000)` consumes calibrated
`V1Pose` values and returns a tuple of `V1CameraMotion`. Valid records use the
world-frame units `mm`, `s`, and `rad`; invalid intervals are labeled
`INSUFFICIENT_EVIDENCE` with no fabricated derivatives. Every record carries
`source=CAMERA_POSE_DERIVATIVE`.

## Verification

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_motion_observer.py
-> 6 passed

py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_motion_observer.py simulation/digital_twin/tests/test_v1_twin_pose_fusion.py simulation/digital_twin/tests/test_v1_twin_imu_control.py
-> 22 passed

py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
-> 691 passed, 5 skipped

py -3.11 -m compileall -q simulation/digital_twin tools
-> exit 0

git diff --check
-> exit 0; only the repository's existing LF/CRLF conversion warnings were emitted.
```

No camera, TCP, ST-Link, firmware, START, STOP, reset, or motor action was
performed for this task.

## Evidence boundary

### VERIFIED

- The observer math and fail-closed timestamp behavior pass offline tests.
- The observer is structurally compatible with the existing `V1Pose` contract
  and does not create a second camera or capture path.

### INFERENCE

- A valid real synchronized pose stream can provide a useful body-level speed
  reference for digital-twin calibration even without wheel encoders.

### INSUFFICIENT EVIDENCE

- Real camera-derived speed and yaw rate have not been computed from a passed
  synchronized run.
- No wheel RPM, per-wheel velocity, camera/IMU sign-scale calibration, B3 pass,
  or high-speed control improvement is established.

## Next interface

The next hardware action is a user-authorized synchronized camera + TCP
telemetry run after the existing B3 synchronization/setup boundary is ready.
It must compare camera motion derivatives with IMU yaw and preserve the
existing raw evidence; it must not be described as encoder feedback.
