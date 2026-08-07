# Real Sync Rerun After Timestamp Repair

Date: 2026-08-07 Asia/Shanghai
Task: validate the host timestamp repair on a fresh real-car synchronized capture
Status: REAL_CAPTURE_COMPLETED_SYNC_GATE_FAILED

## Hardware action

The user explicitly authorized control and camera with the car powered. The
existing `capture_sync_run.py` path ran one bounded 10-second session. It sent
START, maintained the existing heartbeat, sent STOP, confirmed STOPPED, closed
the TCP socket, released the camera, and joined the reader. No firmware was
rebuilt or flashed.

Evidence directory:

`simulation/digital_twin/logs/c260807112623168/`

## VERIFIED

- Camera mode was `1280x720 / MJPG`.
- The runtime lifecycle completed normally; status events were INIT,
  RUNNING/START, and STOPPED/STOP.
- The repaired fusion code produced fresh evidence with zero
  `non_monotonic_timestamp` fallbacks. This confirms the host-side timestamp
  repair is active on real batched telemetry.
- Fresh fusion summary: 30 unique records, 17 `USED_IMU`, 13 `CAMERA_ONLY`,
  and 13 explicit `imu_gap_exceeded` fallbacks.

## INSUFFICIENT EVIDENCE

- Only 35 camera poses were detected from 169 successfully read frames.
  Detection ratio was 20.7%; pose gaps reached 1.125 seconds.
- Telemetry had 343 frames and 8 MCU tick gaps over 100 ms.
- Sync gate was `FAIL`: coverage `88.6%`, p95 time difference `48.0 ms`,
  tolerance `33.3 ms`.
- `motion_evidence.json` is `INSUFFICIENT_EVIDENCE` because the real sync gate
  failed. No camera-derived motion, IMU calibration, or vehicle improvement
  claim is allowed from this run.

## INFERENCE

The timestamp bug is no longer the dominant observed failure in this run. The
remaining gate failure is consistent with sparse marker pose detection and
telemetry gaps, but the cause could be camera placement/visibility, tracker
throughput, or runtime delivery. The current evidence does not distinguish
those causes.

## Next interface

Keep the car powered off. Before the next separately authorized hardware run,
inspect camera/marker visibility and decide whether to improve offline capture
throughput. No firmware flash is indicated by this result.
