# Fusion Timestamp Repair Handoff

Date: 2026-08-07 Asia/Shanghai
Task: repair host-side timestamp handling for synchronized camera/telemetry fusion
Status: OFFLINE_VERIFIED_REAL_REPLAY_PENDING_HARDWARE_RERUN

## Root cause

`build_synchronized_dataset()` already aligns telemetry using `tick_ms` and
`ClockSync`. `build_fusion_records()` then called `V1PoseFusion.update()`
without the aligned timestamp, and `V1PoseFusion` used raw `pc_recv_ns`.
Because ESP01S telemetry arrives in batches, adjacent telemetry frames often
share one PC receive timestamp. The real run at
`simulation/digital_twin/logs/c260807104516439/` had 342 frames, 270 equal
consecutive `pc_recv_ns` deltas, and the old fusion result reported 33
`non_monotonic_timestamp` fallbacks.

## Changed files

- `simulation/digital_twin/v1_twin/v1_twin_pose_fusion.py`
  - accepts an explicit aligned `timestamp_ns` without mutating telemetry;
  - keeps `raw_pc_recv_ns` in each fusion record;
  - uses the explicit timestamp for monotonicity and gap checks.
- `tools/camera_toolchain/capture_sync_run.py`
  - passes the fitted `ClockSync` to fusion;
  - skips repeated `tick_ms` associations while retaining all raw sync data.
- `simulation/digital_twin/tests/test_v1_twin_pose_fusion.py`
  - regression for batched receive timestamps.
- `simulation/digital_twin/tests/test_capture_sync_cleanup.py`
  - regression for aligned time, raw timestamp preservation, and duplicate
    telemetry association.

## Offline verification

- RED tests failed before the implementation with the expected missing
  `timestamp_ns`/clock argument errors.
- Focused fusion/capture tests: `39 passed`.
- Full Python regression: `702 passed, 5 skipped`.
- `py -3.11 -m compileall -q simulation/digital_twin tools`: exit `0`.
- Replaying the immutable real run with the repaired code produced:
  - 54 unique fusion records from 57 sync matches;
  - 46 `USED_IMU`, 8 `CAMERA_ONLY`;
  - 0 `non_monotonic_timestamp`;
  - 8 `imu_gap_exceeded`;
  - strictly monotonic aligned fusion timestamps;
  - raw `pc_recv_ns` preserved.

## Evidence boundary

The existing `fusion.jsonl` and `imu_evidence.json` were not overwritten.
They remain evidence from the old implementation. The repaired numbers above
are offline replay only. They do not prove new hardware behavior, IMU
calibration, camera/IMU physical synchronization, or controller improvement.

## Next interface

Stop before hardware. The next action is a separately authorized
`capture_sync_run.py` session with the camera over the fixed track and the car
powered under the user's safety supervision. No firmware rebuild or flash is
required for this host-side repair. After that run, inspect fresh raw files,
status events, sync gate, and repaired fusion evidence independently.
