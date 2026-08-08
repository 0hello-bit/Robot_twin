# B3 Offline Observation and Timestamp Repair Handoff

Date: 2026-08-08 Asia/Shanghai
Status: `OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED`

## Scope

This handoff covers offline code and replay only. No firmware was built or
flashed, no camera device was opened, and no car command was sent.

## Changes

- `tools/camera_toolchain/capture_sync_run.py` now uses the shared
  `capture_pc_clock_ns()` based on `perf_counter_ns()` for camera frame
  timestamps, telemetry receive timestamps, and health receive timestamps.
  A lock and a last-value guard make emitted values strictly increasing.
  START/STOP timeout and heartbeat scheduling still use their existing clock.
- `v1_twin/v1_twin_pose_tracker.py` first searches a bounded ROI around the
  last successfully decoded target ID 0. The first full-frame search keeps
  `1x/2x/3x`; an ROI miss uses a bounded full-frame `2x` reacquisition probe.
  It never accepts an unknown ID as the target.
- Diagnostics now record search mode, attempted regions, ROI bounds, fallback
  use, rejected-candidate counts, and detection time.

## Offline evidence

- The eight retained failure thumbnails from real run
  `c260808033248336` all show the car and its roof marker. Replaying each
  thumbnail five times with the current default detector decoded ID 0 in 1/8
  images; the other 7/8 remained `candidates_rejected` in every replay.
- Global histogram equalization decoded 2/8 and CLAHE decoded 1/8 on those
  same images. Neither result is strong enough to promote preprocessing into
  the production path.
- A synthetic 40-frame moving-tag sequence decoded 40/40 with both forced
  full-frame and ROI tracking; 39/40 ROI frames used the fast path. A closer
  synthetic 1280x720, 35-pixel-tag sequence decoded 15/15 in both branches;
  local p95 detector time was about 3.96 ms full-frame versus 2.17 ms with
  ROI. These are software benchmarks, not real-car performance evidence.

## Verification

- Pose tracker and capture cleanup tests: `47 passed`.
- B3 observation gate tests: `19 passed`.
- Full Python regression excluding archive: `732 passed, 5 skipped`.
- Python compileall for `simulation/digital_twin` and `tools`: exit 0.
- `git diff --check`: no whitespace errors; only existing LF/CRLF warnings.

## Authorized real rerun

Real run `c260808052942717` used the same canonical capture path, camera
profile, and 20-second boundary. START/RUNNING and STOP/STOPPED completed,
cleanup passed, and no firmware was flashed.

- 370 readable camera frames, 154 poses, and 629 telemetry frames.
- Frame timestamps were strictly increasing: 0 non-increasing pairs.
- The existing synchronization gate passed with 100% coverage and 15.4 ms
  p95 time difference.
- The separate observation gate failed: detection ratio `41.62%`, maximum pose
  gap `58.74531` frame periods, and detector p95 `77.447895 ms`.
- Search modes were `148` ROI frames, `221` ROI-then-full-frame frames, and
  `1` initial full-frame frame. Only five fallback frames recovered a pose;
  all five recovered at full-frame `2x`. The remaining 216 failures were
  `candidates_rejected`.
- The derived observation report is
  `docs/evidence/v1_b3_observation_gate_20260808_rerun_c260808052942717/report.json`.

## Follow-up offline change

The real-run evidence added a constrained fallback budget: ROI misses now use
only full-frame `2x` before returning a miss. Initial acquisition remains
three-scale. TDD RED was observed by requiring the fallback scale list to be
`[1.0, 2.0, 3.0, 2.0]`; the focused test then passed, followed by the full
regression.

Fresh verification after this change is `732 passed, 5 skipped`, compileall
exit 0, and `git diff --check` has no whitespace errors.

## Evidence boundary

`VERIFIED`: the host timestamp source is high-resolution and strictly
increasing in offline tests and in the new real artifact; the tracker has a
bounded ROI path and strict ID validation; the real synchronization gate
passed; the fallback workload and its successful scale were measured.

`INFERENCE`: limiting ROI-miss reacquisition to the observed successful `2x`
probe may reduce detector backlog without changing the target-ID contract.

`INSUFFICIENT EVIDENCE`: the new fallback budget has not yet been validated
on a fresh real run; continuous AprilTag detection, real observation-gate
pass, calibration quality, and any vehicle or digital-twin improvement remain
unverified.

## Next interface

After explicit hardware authorization, run one bounded synchronized capture
with the full marker visible from the first frame. Inspect timestamp
monotonicity, `failure_frame_summary.json`, `frame_index.jsonl`, and the
observation analyzer output. Keep the existing sync thresholds. Do not bundle
equalization, detector-threshold changes, camera resolution changes, or
calibration changes into that rerun.
