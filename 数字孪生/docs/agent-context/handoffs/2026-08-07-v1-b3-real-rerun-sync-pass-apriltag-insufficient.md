# V1-B B3 Real Rerun Handoff

Date: 2026-08-07 Asia/Shanghai
Run: `c260807144501519`
Status: `SYNC_GATE_PASS_CAMERA_DETECTION_INSUFFICIENT`

## Scope

One authorized synchronized camera/TCP run was executed with the canonical
`tools/camera_toolchain/capture_sync_run.py` entrypoint. No source or firmware
change was made during the run.

## Evidence

Raw evidence is preserved at:

`simulation/digital_twin/logs/c260807144501519/`

The directory contains `sync_report.json`, `raw_io.json`, `raw_health.json`,
`pose.jsonl`, `telemetry.jsonl`, `frame_index.jsonl`, `fusion.jsonl`, and
`camera_motion.jsonl`.

## VERIFIED

- The lifecycle completed `START -> 12 s capture -> STOP`.
- `RUNNING` and matching `STOPPED/STOP` were observed.
- Socket, camera, reader, and cleanup gates completed without errors.
- Camera mode was `1280x720`, `MJPG`, approximately 30 fps.
- Firmware identity was `fw_build_id=3`, schema version 1.
- Fixed B3 sync gate: coverage `100.0%`, p95 time difference `15.4 ms`,
  threshold `<=33.3 ms`, verdict `PASS`.
- During the health observation, `uart_tx_overflow`,
  `telemetry_overwritten`, `telemetry_tx_failed`, and `cipsend_error` all
  remained zero.
- All 381 telemetry frames reported `imu_init_status=0x00`; validity was
  known in all frames.
- AprilTag diagnostics recorded 193 camera frames, 21 pose frames, 172
  `candidates_rejected` frames, a 10.9% detection ratio, and a 2.75 s longest
  valid-pose gap.

## INFERENCE

- The UART ring/telemetry remediation is consistent with removal of the
  previously observed capacity-pressure symptom in this run.
- The remaining data limitation is the sparse AprilTag pose stream. The exact
  reason for candidate rejection is not yet proven.

## INSUFFICIENT EVIDENCE

- The sync PASS does not mean continuous camera tracking; only 21 of 193
  camera frames yielded a pose.
- The run does not establish calibration quality, digital-twin accuracy, wheel
  speed, line-loss reduction, or high-speed sharp-turn improvement.
- The IMU and camera-motion reports are structural real-sync summaries only;
  they do not establish IMU calibration or control benefit.

## Next interface

Keep the car powered off. Audit the existing AprilTag `PoseTracker` rejection
path and calibration/geometry assumptions offline using `frame_index.jsonl`.
Do not add a parallel detector or start another hardware run until that audit
produces a constrained next test. Preserve the fixed B3 sync thresholds and
also track detection ratio and longest pose gap.
