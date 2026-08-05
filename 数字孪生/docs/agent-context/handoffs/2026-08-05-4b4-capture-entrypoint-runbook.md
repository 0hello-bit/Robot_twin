# 4B-4 Capture Entrypoint Runbook

Date: 2026-08-05

Status: `SOFTWARE_ONLY_READY; HARDWARE_GATE_PENDING`

This document records the offline-prepared procedure for a future Task 4B-4
capture. It is not hardware authorization. The camera, TCP link, firmware,
serial port, debugger, and motors must remain untouched until a separate,
immediate user authorization is given.

## Offline-verified entrypoint

`.embeddedskills/build/v1_task4b4/capture_sync_run.py` now opens the requested
camera through `.embeddedskills/tools/camera_toolchain/camera_common.py` with:

- DirectShow index `1` (the current C960 index; re-probe after hot-plug)
- FourCC `MJPG`
- Frame size `1280x720`
- Requested frame rate `30.0 fps`

The common camera helper validates the actual FPS and FourCC. The capture
entrypoint additionally fails closed unless the actual size is exactly
`1280x720`, releasing the camera on a size mismatch.

Offline checks completed:

- `test_capture_sync_cleanup.py`: `13 passed`
- Related capture, dataset, sync, pose, and camera-common test counts are
  recorded in the current acceptance handoff; all passed.
- Python compilation of the entrypoint and common camera helper: passed

The entrypoint now records the actual camera mode and complete session cleanup
actions in `sync_report.json`. Connection failures release the opened camera,
and START/no-telemetry/collection/insufficient-data failures publish a
structured non-passing report instead of only printing to stdout.

These results prove software behavior only. They do not prove that index `1`
still names the C960 after the next hot-plug, nor do they prove a 30 fps stream
on the next run.

## Preconditions for a future hardware run

1. Obtain a fresh authorization that names the exact run and duration.
2. Keep the user beside the motor-power switch; keep the track clear.
3. Re-run `probe_camera.py` and confirm that index `1` is the C960. Do not
   silently fall back to the laptop camera or another index.
4. Confirm the camera opens as `MJPG / 1280x720 / 30 fps` before connecting to
   the car.
5. Use a new timestamped output directory. Never overwrite an older evidence
   directory.
6. Start with the wheels elevated. A ground run requires a separate fresh
   authorization after reviewing the elevated-wheel evidence.

## Bounded execution order

1. Use only the already accepted firmware artifact and verify its recorded
   hash before any flashing step.
2. Send the bounded parameter sequence and require a correlated
   `APPLIED/APPLIED` acknowledgement for every step.
3. Send exactly one `START`; do not retry it automatically.
4. Collect the requested short window while recording camera poses and raw
   telemetry. The session must attempt `STOP` on every exit path after START.
5. Require correlated `STOPPED/STOP` before treating the run as controlled.
6. If STOP is not confirmed, motion is unexpected, the camera is unavailable,
   or the operator says stop, cut motor power immediately and preserve the
   evidence as a failure or insufficient-evidence result.

## 4B-4 acceptance gate

The formal synchronization gate is not passed by a successful software run
alone. The new evidence must show:

- camera and telemetry samples overlap for at least `95%` of captured poses;
- all-frame nearest-neighbor time-difference `p95 <= 33.3 ms`;
- monotonic timestamps and a non-empty pose/telemetry set;
- the actual camera mode recorded as `MJPG / 1280x720 / 30 fps`;
- final STOP status and clean resource cleanup.

The known risk remains: the firmware telemetry path has historically been near
10 Hz while the original gate assumption was 30 fps. If the new run still
shows sparse telemetry, mark 4B-4 as `FAIL` or `INSUFFICIENT_EVIDENCE` and do
not claim that the synchronization gate is complete. MPU6050 yaw remains
exploratory until its validity and calibration are independently established.

## Evidence and handoff

After a future run, review the new run directory without modifying it. Record
the camera probe result, actual mode, run identity, sample counts, coverage,
p95 time difference, telemetry interval diagnostics, STOP result, and the
verdict. Link that evidence from the current gate ledger. A ground run is
vehicle data collection; it does not by itself complete the global 2 mm mapping
gate or make the Robot Twin AI V1 ready.
