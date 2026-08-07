# V1-B B3 offline evidence and telemetry remediation handoff

Date: 2026-08-07 Asia/Shanghai
Status: OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED

## Scope

This handoff records the offline remediation after the real synchronized run
`simulation/digital_twin/logs/c260807115454101/` failed the sync gate. No
firmware was flashed and no hardware run was performed for this remediation.

## Root causes addressed

1. `summarize_imu_evidence()` did not accept the actual synchronization gate,
   and the artifact writer did not pass it. A failed real sync could therefore
   leave `imu_evidence.json` as `VERIFIED`.
2. `PoseTracker` had no per-frame detection diagnostics, so sparse AprilTag
   observations could not be separated into marker visibility and timing
   problems.
3. The firmware generated telemetry every 20 ms while its droppable batch and
   CIPSEND payload were sized for only five frames. The new tested contract is
   an eight-frame, 248-byte batch generated every 30 ms.

## Changed boundary

- `v1_twin_imu_control.py`: explicit non-PASS sync verdict downgrades IMU
  evidence to `INSUFFICIENT_EVIDENCE` with reason `sync_gate_not_pass`.
- `capture_sync_run.py`: passes the real gate to the IMU report and persists
  `attempted_scales`, `matched_scale`, `tag_side_px`, `failure_reason`, and
  `detect_elapsed_ns` in `frame_index.jsonl`.
- `v1_twin_pose_tracker.py`: adds `track_with_diagnostics()` on the existing
  AprilTag detector path; no second detector or capture path was added.
- Firmware: `TELEMETRY_BATCH_MAX_FRAMES=8`,
  `TELEMETRY_BATCH_MAX_BYTES=248`, `CIPSEND_TX_MAX_DATA=248`, and
  `TELEMETRY_INTERVAL_MS=30` with wrap-safe scheduling.
- Host diagnostics use the same 30 ms generation contract.

## Offline verification

- Focused Python regression: `94 passed`.
- Full Python regression with archive excluded: `706 passed, 5 skipped`.
- Python compileall for `simulation/digital_twin` and `tools`: exit `0`.
- MSVC Host C `test_telemetry_batch`: compile and run passed.
- MSVC Host C `test_cipsend_tx`: compile and run passed.
- Keil `Target 1` rebuild: `0 Error(s), 0 Warning(s)`.
- AXF: `firmware/stm32_line_follower/Objects/Project.axf`.
- AXF SHA-256: `22B978BA1BA1DD76354C39A307C3DDCC5AB6504026AC9205F733DD1B6DC5C29A`.
- `git diff --check`: no whitespace errors; existing line-ending warnings only.

## Evidence classification

### VERIFIED

- The evidence downgrade rule, per-frame diagnostics, telemetry capacity
  contract, wrap-safe scheduler, Host C tests, and Keil build are verified
  offline.

### INFERENCE

- The larger batch and slower generation rate may reduce telemetry overwrite
  and improve synchronized coverage under the observed CIPSEND latency.
- Per-frame diagnostics should identify whether the next real failure is
  marker visibility, detector throughput, or telemetry delivery.

### INSUFFICIENT EVIDENCE

- No claim that B3 now passes.
- No claim that the new firmware improves telemetry overwrite or sync coverage
  on the physical car.
- No claim of valid camera/IMU motion evidence, wheel speed, line-loss
  reduction, or high-speed sharp-turn improvement.

## Next hardware interface

Keep the car powered off until explicit flash authorization. Then flash the
recorded AXF through the established Keil/ST-Link path, place the car on the
fixed track with the complete AprilTag visible, and run one bounded
`START -> real motion capture -> STOP` session. The next acceptance must
inspect fresh evidence for:

- synchronization coverage `>= 95%`;
- p95 camera/telemetry time difference `<= 33.3 ms`;
- `telemetry_overwritten` and UART/CIPSEND health counters;
- camera detection ratio and longest pose gap;
- `imu_evidence.json` and `motion_evidence.json` both inheriting the sync gate.

Only a fresh run satisfying the fixed gate may be considered B3 evidence.
