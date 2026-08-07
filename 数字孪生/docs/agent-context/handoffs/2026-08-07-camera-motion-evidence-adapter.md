# Camera Motion Evidence Adapter Handoff

Date: 2026-08-07 Asia/Shanghai
Task: offline camera-derived whole-car motion evidence integration
Status: OFFLINE_VERIFIED_REAL_SYNC_PENDING

## Scope completed

The active car has no wheel encoder feedback. This task adds an auditable
whole-car camera-motion artifact to the existing synchronized capture writer.
It does not estimate wheel RPM, per-wheel speed, slip, or motor-side speed; it
does not feed firmware control.

## Changed files

- `simulation/digital_twin/v1_twin/v1_twin_motion_evidence.py`
  adds the immutable `V1CameraMotionEvidence` report and
  `build_camera_motion_evidence()`.
- `simulation/digital_twin/v1_twin/v1_twin_motion_observer.py`
  adds explicit units to `V1CameraMotion.to_dict()`.
- `tools/camera_toolchain/capture_sync_run.py`
  writes `camera_motion.jsonl` and `motion_evidence.json` through the
  existing `write_capture_artifacts()` path and passes the existing sync gate
  verdict.
- `simulation/digital_twin/tests/test_v1_twin_motion_evidence.py`
  covers report statistics and evidence gates.
- `simulation/digital_twin/tests/test_capture_sync_cleanup.py`
  covers additive artifacts and failed-real-sync downgrade behavior.
- `docs/agent-context/PROJECT_MEMORY.md`
  and `docs/agent-context/CURRENT_STATUS.md` record the new boundary.

## Artifact contract

- `camera_motion.jsonl` contains one `V1CameraMotion` record per input pose,
  including `source=CAMERA_POSE_DERIVATIVE` and explicit units.
- `motion_evidence.json` contains valid/invalid counts, time span, planar
  speed statistics, yaw-rate statistics, and the existing IMU overlap fields.
- `VERIFIED` requires `source=REAL_SYNC`, `sync_gate_verdict=PASS`, and at
  least one valid camera-motion interval.
- A failed or missing synchronization verdict remains
  `INSUFFICIENT_EVIDENCE`, even when the finite-difference math is valid.

## Verification

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_motion_observer.py simulation/digital_twin/tests/test_v1_twin_motion_evidence.py simulation/digital_twin/tests/test_capture_sync_cleanup.py
-> 41 passed

py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
-> 699 passed, 5 skipped

py -3.11 -m compileall -q simulation/digital_twin tools
-> exit 0

git diff --check
-> exit 0; existing LF/CRLF conversion warnings only
```

No camera, TCP, ST-Link, firmware, START, STOP, reset, or motor action was
performed for this task.

## Evidence classification

### VERIFIED

- The report math, unit serialization, additive artifact writing, and
  failed-sync fail-closed rule are verified offline.
- Existing capture ownership and cleanup code remains the only runtime path.

### INFERENCE

- A qualifying real synchronized camera pose stream can provide an external
  body-level speed/yaw reference for future no-encoder twin calibration.

### INSUFFICIENT EVIDENCE

- No real synchronized camera + TCP + MPU6050 artifact exists yet.
- Wheel RPM, per-wheel speed, slip, IMU sign/scale/drift, calibrated
  vehicle-frame direction, and control improvement remain unverified.

## Next interface

Stop here and request explicit authorization before running
`tools/camera_toolchain/capture_sync_run.py`. The user must place the camera
over the fixed track and confirm the physical safety boundary. The resulting
run may establish whole-car motion evidence only; it does not authorize a
firmware control change.
