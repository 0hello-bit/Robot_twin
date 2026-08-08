# B3 camera-height rerun handoff

Date: 2026-08-08
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `REAL_CAPTURE_COMPLETED_OBSERVATION_STILL_BLOCKED`

## Objective

Repeat the bounded synchronized run after the operator raised the camera,
covering the car's start-to-finish motion as far as the fixed-duration capture
can observe it. This was a camera-setup experiment only. No firmware, detector,
calibration, or control code was changed.

## Run and raw evidence

- Run ID: `c260808033248336`
- Raw directory: `simulation/digital_twin/logs/c260808033248336/`
- Command: `py -3.11 tools/camera_toolchain/capture_sync_run.py --host 192.168.110.236 --port 8888 --camera 1 --duration 20 --wait-timeout 30 --calibration-manifest simulation/digital_twin/data/product/calibration_profiles/c960_r3_exploratory_v1/manifest.json --out simulation/digital_twin/logs`
- Camera: actual `1280x720`, `MJPG`, `30.00003 fps`
- Firmware action: no flash; the existing device image was used.
- Lifecycle: `START/RUNNING -> 20 s capture -> STOP/STOPPED`; heartbeat, socket,
  camera, and reader cleanup all completed.
- The stop reason was the commanded `STOP`; no `LINE_LOST` event ended this run.

## Verified results

- `sync_report.json` reports `verdict=PASS` and `sync_gate_verdict=PASS`.
- Synchronization coverage was `100.0%`; p95 pose/telemetry difference was
  `15.36 ms` against the `33.3 ms` bound.
- The raw session contains 389 readable camera records, 154 pose records, and
  631 telemetry records.
- 235 camera records failed detection. Every failure was
  `candidates_rejected`; there were no read failures, `no_markers`, or
  `target_tag_not_found` records.
- Eight bounded failed-frame thumbnails were saved under `failed_frames/` with
  zero save errors. The thumbnails show the car and marker in many failed
  frames, including turns and near-frame-edge positions.
- Direct raw recheck gives a pose detection ratio of `39.59%`, detector p95 of
  `64.75 ms`, and a maximum pose-run gap of 28 camera records. These values
  remain below the observation screening profile (`>=95%`, `<=33.3 ms`, and
  `<=2` frame periods).

## Timestamp evidence boundary

The read-only B3 observation analyzer did not publish a formal gate report for
this run because `frame_index.jsonl` contains one equal adjacent timestamp:

- frame 380: `t_pc_ns=1690493078000000`
- frame 381: `t_pc_ns=1690493078000000`

The raw artifacts were not edited and the duplicate was not silently removed.
Therefore the formal observation-gate status for this run is
`INSUFFICIENT_EVIDENCE`, not `PASS`. The direct detection statistics above are
valid diagnostic counts, but they do not override the strict evidence gate.

## Comparison with the previous run

The prior run `c260808033006893` recorded 28 poses in 206 readable frames
(`13.59%`). The raised-camera run recorded 154 poses in 389 readable frames
(`39.59%`). The absolute increase is `25.99 percentage points` and the ratio
is approximately `2.91x`.

## Evidence classification

### VERIFIED

- The raised-camera run completed the existing real capture lifecycle and
  passed the fixed synchronization sub-gate.
- The new run has substantially more retained pose observations than the
  immediately preceding run.
- The remaining detector failure label is consistently
  `candidates_rejected`, with representative failed images retained.

### INFERENCE

- Camera height and the resulting field of view likely improved observation
  availability. This is supported by the paired run comparison, but it is not
  an isolated causal experiment because the runs were not identical repeats.
- The failed images are more compatible with a visibility/scale/pose or motion
  interaction than with the car being absent from every failed frame. The exact
  detector cause is still unverified.

### INSUFFICIENT EVIDENCE

- Continuous AprilTag observation is not verified; `39.59%` remains far below
  the screening threshold.
- The formal observation gate cannot classify this run until the duplicate
  timestamp evidence issue is resolved or explicitly handled by a reviewed
  contract change.
- No machine-readable finish event exists, so “start to finish” is not an
  independently verified event even though the 20-second trajectory covers
  the visible track path.
- No detector parameter, calibration, firmware, or vehicle-control change has
  been validated.

## Next interface

Keep B3 blocked. First perform an offline audit and minimal regression for the
equal camera timestamp without rewriting this raw run. Then use the retained
failed frames to choose exactly one constrained observation experiment. Do not
change detector parameters and camera calibration in the same experiment.
