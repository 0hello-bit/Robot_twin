# Robot Twin AI Project Memory

This file is binding project context for every agent taking over work in the
canonical workspace. Read it before implementing or extending any task.

## Core Invariant: Reuse Before Rebuild

The project already contains validated pieces from Task 1-3 and Task 4B. An
agent must inspect the existing implementation and tests before writing new
code. Existing behavior is a reusable project asset, not an invitation to
create a parallel implementation.

This is the project's "stand on existing shoulders" principle: reusable
assets include not only source code, but also validated protocols, experiment
results, failure records, safety constraints, and rollback boundaries. A new
task must move the verified frontier forward instead of recreating completed
work.

The following are explicitly protected from duplication:

- ESP-01S TCP transport and connection lifecycle.
- P/R/A/S command and status frames, XOR checksum, parsing, and validation.
- H heartbeat and the runtime lease safety behavior.
- Runtime wheel-speed control through the bounded `speed_max` parameter ramp.
- Campaign/version-correlated ACK handling.
- START/RUNNING, STOP/STOPPED, rollback, line-loss, timeout, and motion-inhibit
  safety behavior.
- Binary telemetry, health-frame, and mixed ASCII/binary stream parsing.
- Raw I/O logging, run identity, camera/session cleanup, and evidence output.

If an interface is insufficient, first write down the concrete evidence gap.
Only a minimal, tested adapter inside the existing boundary is allowed. Do not
silently replace an existing path with a new TCP client, parser, ACK registry,
heartbeat loop, or session lifecycle.

Reuse is not blind copying. The agent must verify version, interface,
configuration, and hardware-identity compatibility before using an existing
asset. Once compatibility is confirmed, direct invocation is preferred over
reimplementation; effort should go to the new experiment, diagnostic, or
validation that the task is meant to add.

## Canonical Existing Assets

- `tools/shakedown_toolchain/ground_shakedown.py` is the canonical bounded
  hardware Smoke entrypoint for V1-B B2. It owns the single-owner session and
  already performs the accepted speed ramp, ACK gates, START/RUNNING gate,
  200 ms H heartbeat, terminal STOP/STOPPED gate, raw evidence, and cleanup.
- `tools/shakedown_toolchain/transport_soak.py` provides the existing
  `SocketTransport`, `RawIoLogger`, mixed-stream support, health summary, and
  `HeartbeatCommand`. The B2 path reuses it; do not add another H encoder.
- `simulation/digital_twin/real_world/runtime_protocol.py` is the shared
  source for `ParameterCommand`, `RunCommand`, frame/checksum rules, ACK/status
  parsing, and bounded parameter validation.
- `simulation/digital_twin/real_world/frame_parser.py` and
  `stream_demuxer.py` are the existing binary and mixed-stream decoders.
- `firmware/stm32_line_follower/User/esp_runtime_transport.c/.h` and
  `esp_tx_coordinator.c/.h` are the firmware-side ESP transport and send
  arbitration boundary.
- `firmware/stm32_line_follower/User/twin_control_protocol.c/.h` is the
  firmware-side runtime parameter, heartbeat lease, rollback, line-loss, and
  motion-inhibit source of truth.
- `simulation/digital_twin/web_showcase/live_wifi_bridge.py` and its
  `AckRegistry` are existing UI bridge assets. They must not be started or
  cloned for B2.
- `tools/camera_toolchain/capture_sync_run.py` is an existing synchronized
  capture path for the later B3 data gate. It must not be repurposed into a
  second B2 control lifecycle.

## Agent Handoff Rule

One agent owns one bounded task. The agent must report actual changed files,
commands and results, VERIFIED/INFERENCE/INSUFFICIENT EVIDENCE, exact hardware
actions, raw evidence paths and the next interface, then stop. A passing fake
or unit test is not real-car evidence. Never claim a real run, flashed
firmware, or hardware improvement without the corresponding raw evidence.

## Candidate R&D issue: raised-track line loss (2026-08-07)

Status: OBSERVED / UNVERIFIED. During a real-car run, the user observed that
the car generally followed the existing line-following logic, but the front
line sensors sometimes failed to detect the black line when the track surface
was raised or uneven. This is a candidate for a future AI-driven iteration,
not yet an attributed sensor fault or a proven algorithm defect.

The later closed-loop task must first reproduce the failure on a fixed track
condition and preserve a baseline run. AI may then propose one constrained
hardware or algorithm change, screen it offline where possible, deploy it to
the real car through the existing safety/flash process, and compare matched
runs using at least: no-line-loss outcome and speed. The cause must remain
classified as VERIFIED, INFERENCE, or INSUFFICIENT EVIDENCE; do not assume a
sensor replacement is necessary before collecting geometry, sensor, and motion
evidence.

## MPU6050 control boundary (2026-08-07)

- The latest authorized elevated-wheel evidence reported
  `imu_init_status=0x00` and valid sample flags, so initialization/read/update
  status is verified for that run. All observed yaw values were `0.0` degrees;
  dynamic yaw response, sign, scale, drift, and control benefit remain
  `INSUFFICIENT EVIDENCE`.
- `simulation/digital_twin/v1_twin/v1_twin_pose_fusion.py` is the existing
  camera-anchored fusion path. `v1_twin_imu_control.py` adds only an offline
  control shadow and evidence summary; it must not be described as firmware
  control or real-car improvement.
- The shadow path may change a bounded hypothetical turn only when IMU
  validity, initialization, freshness, and fused yaw are all eligible. Any
  unknown, failed, stale, or `DT_CLAMPED` sample must fail closed to the
  baseline turn.
- `imu_evidence.json` is additive evidence beside `fusion.jsonl`. Synthetic
  records are always `INSUFFICIENT_EVIDENCE`; a `REAL_SYNC` summary being
  `VERIFIED` means only that its structural prerequisites were met, not that
  the IMU or digital twin is accurate.
- Before changing real firmware control, run a bounded elevated-wheel
  rotation observation that verifies non-zero yaw response and axis sign.

## MPU6050 dynamic yaw observation (2026-08-07)

- The authorized 10-second elevated-wheel run is preserved at
  `logs/imu_yaw_rotation/soak_20260807_173821/`. It used the existing
  `transport_soak.py --run` path and confirmed START/RUNNING and STOP/STOPPED.
- Raw telemetry had 371 frames, `imu_init_status=0x00` throughout, validity
  `0x0F/0x1F`, and yaw changed from `0.00` to `11.68` degrees during the
  user's manual right rotation. This verifies dynamic output response.
- Positive sensor yaw is only consistent with the manual right rotation until
  the board mounting and coordinate convention are explicitly calibrated.
  Do not treat it as a verified control sign or scale.
- The soak's main-loop nonblocking gate failed independently; do not use that
  transport result to erase or promote the IMU yaw evidence. Do not modify
  firmware control until a known-angle sign/scale check and a baseline exist.

## No wheel encoder boundary (2026-08-07)

- The current car has no wheel encoder feedback in the active hardware and
  firmware path. The active motor driver produces PWM outputs only; telemetry
  `m1..m4` are commanded motor values, not measured RPM.
- Camera pose derivatives may provide external whole-car planar speed and yaw
  rate for digital-twin calibration. They must be labeled
  `CAMERA_POSE_DERIVATIVE` and must not be called wheel speed or motor speed.
- The offline observer is
  `simulation/digital_twin/v1_twin/v1_twin_motion_observer.py`. It is a
  fail-closed finite-difference utility and has no firmware or hardware side
  effect.

## Camera motion evidence adapter (2026-08-07)

- `simulation/digital_twin/v1_twin/v1_twin_motion_evidence.py` summarizes
  the existing `CAMERA_POSE_DERIVATIVE` records and carries only the existing
  IMU evidence overlap fields; it does not infer IMU sign, scale, bias, or
  drift.
- `tools/camera_toolchain/capture_sync_run.py` now writes additive
  `camera_motion.jsonl` and `motion_evidence.json` through the existing
  `write_capture_artifacts()` function. It does not create a second camera,
  TCP, heartbeat, parser, or session lifecycle.
- `motion_evidence.json` is `VERIFIED` only when its source is `REAL_SYNC`,
  the existing sync gate is `PASS`, and at least one valid camera-motion
  interval exists. A failed or missing sync verdict remains
  `INSUFFICIENT_EVIDENCE`.
- Motion records carry explicit units: timestamp `ns`, delta position `mm`,
  velocity `mm/s`, and yaw rate `rad/s`. They remain external whole-car
  observations, never wheel RPM or motor speed.
- Offline verification on 2026-08-07: focused observer/evidence/capture tests
  `41 passed`; the full Python regression `699 passed, 5 skipped`; compileall
  exited `0`; `git diff --check` had no whitespace errors. No camera, TCP,
  ST-Link, firmware, START, STOP, reset, or motor action occurred.
- The next interface is one explicitly authorized synchronized camera + TCP +
  MPU6050 run. It may establish real body-level motion evidence, but cannot by
  itself establish wheel RPM, IMU calibration, or a control improvement.

## Fusion timestamp repair (2026-08-07)

- `V1PoseFusion` must not use raw `pc_recv_ns` as the sensor timeline when
  telemetry is delivered in TCP batches. The canonical synchronized path must
  pass `ClockSync.tick_to_pc_ns(tick_ms)` explicitly and preserve raw
  `pc_recv_ns` for audit.
- `tools/camera_toolchain/capture_sync_run.py::build_fusion_records()` skips
  repeated `tick_ms` matches so one MCU observation is not applied twice when
  neighboring camera poses select the same telemetry frame.
- The repaired path is offline-verified against
  `simulation/digital_twin/logs/c260807104516439/`: 54 unique fusion records,
  46 used IMU, 8 camera-only, zero non-monotonic timestamp fallbacks, and 8
  explicit long-gap fallbacks. These numbers are replay results; they are not
  fresh hardware evidence.
- Never overwrite the original real-run artifacts when replaying a parser or
  fusion change. A fresh `capture_sync_run.py` run is required before claiming
  the repaired artifacts are physically observed.

## Real sync rerun after timestamp repair (2026-08-07)

- Authorized run: `simulation/digital_twin/logs/c260807112623168/`.
- Existing capture lifecycle completed normally: `RUNNING`, commanded
  `STOP/STOPPED`, socket close, camera release, and reader cleanup.
- Camera read 169 frames but generated only 35 poses (20.7% detection ratio);
  pose gaps reached 1.125 s. Telemetry had 343 frames and 8 tick gaps over
  100 ms.
- Sync gate failed at coverage `88.6%` and p95 `48.0 ms` versus `33.3 ms`.
  `motion_evidence.json` is therefore `INSUFFICIENT_EVIDENCE`.
- The repaired timestamp path did work on real data: fresh fusion evidence
  reported zero `non_monotonic_timestamp` fallbacks, with 17 used IMU records,
  13 camera-only records, and 13 explicit long-gap fallbacks. This is a
  structural fusion result, not a verified motion or performance result.
- Do not attribute the sparse pose stream to a specific camera, visibility, or
  tracker cause without further evidence. Before another hardware capture,
  inspect camera placement/marker visibility and offline capture throughput.

## UART TX backpressure and AprilTag diagnostics (2026-08-07)

- In real run `simulation/digital_twin/logs/c260807133939203/`,
  `uart_tx_overflow` rose `0 -> 15` and TX high-water reached 128, while
  telemetry overwrite, telemetry TX failure, CIPSEND error, RX overflow, and
  ORE stayed zero. The active 248-byte telemetry burst exceeded the old
  128-byte UART ring. The transaction retains its send position on sink
  rejection, so classify this as verified capacity pressure, not verified
  wire corruption.
- Offline remediation raises `UART_RING_SIZE` to 256 and adds a test that
  accepts `CIPSEND_TX_MAX_DATA` without overflow. Native Host C execution was
  unavailable in the current environment; do not use old prebuilt binaries as
  evidence for the new source. Keil and Python verification are recorded in
  `docs/agent-context/handoffs/2026-08-07-uart-tx-apriltag-diagnostics.md`.
- `PoseTracker` now records rejected AprilTag candidates per scale and
  distinguishes `candidates_rejected` from `no_markers` in the existing
  `frame_index.jsonl`. This is diagnostic evidence, not a continuous-tracking
  fix. The latest run retained no images, so visibility, blur, occlusion, and
  detector failure remain unclassified.

## B3 failure-frame diagnostic boundary (2026-08-07)

- The canonical `tools/camera_toolchain/capture_sync_run.py` now retains a
  bounded set of representative failed-frame JPEG thumbnails in each new
  run's `failed_frames/` directory. It saves at most 12 images, records the
  relative path in `frame_index.jsonl`, and writes counts/errors to
  `failure_frame_summary.json`.
- Sampling is deterministic: first occurrence per failure reason, then every
  30th occurrence until the cap. This is for root-cause attribution only; it
  does not change the AprilTag detector, calibration, sync gate, firmware, or
  control behavior.
- A future agent must use this existing capture path and inspect the retained
  images before changing detector parameters, camera resolution, or
  calibration. Do not create a second camera/TCP/session lifecycle.
- Offline status after this change: `708 passed, 5 skipped`, compileall `0`.
  No new hardware evidence exists, and B3 remains blocked until an authorized
  rerun produces interpretable failure-frame evidence.

## B3 camera-height rerun (2026-08-08)

- Authorized run `simulation/digital_twin/logs/c260808033248336/` used the
  existing capture path after the operator raised the camera. It used
  `1280x720/MJPG/30 fps`, completed START/RUNNING and commanded STOP/STOPPED,
  and did not flash firmware.
- The run produced 389 readable frames, 154 poses, and 631 telemetry frames.
  Detection ratio was `39.59%`; all 235 failures were
  `candidates_rejected`; eight representative failure thumbnails were saved.
  The fixed sync gate passed at 100% coverage and `15.36 ms` p95 time error.
- The prior run had 28/206 poses (`13.59%`), so the increased pose count is
  verified and the camera-height contribution is an inference, not isolated
  causal proof.
- The strict offline B3 observation analyzer rejected this run because frames
  380 and 381 have an equal camera timestamp. Do not rewrite the raw artifact
  or silently ignore the duplicate. Detection p95 was `64.75 ms` and the
  maximum pose gap was 28 frame records, so observation readiness remains
  blocked even apart from the timestamp evidence issue.
- The next agent must audit the timestamp contract offline before selecting one
  constrained detector/camera/calibration experiment. Do not bundle changes or
  claim continuous AprilTag tracking from this run.

## B3 timestamp clock repair (2026-08-08)

- The equal camera timestamp in `c260808033248336` was traced to Windows
  Python `time.monotonic_ns()` using `GetTickCount64()` at approximately
  `15.625 ms` resolution. It was not evidence of a frame-order reversal.
- The canonical capture path now uses shared `capture_pc_clock_ns()` backed by
  high-resolution `perf_counter_ns()` for camera timestamps, telemetry
  `pc_recv_ns`, and health `pc_recv_ns`. Timeout and heartbeat scheduling stay
  on their existing clocks.
- TDD RED/GREEN was verified. Capture tests are `33 passed`; the full Python
  regression is `729 passed, 5 skipped`; compileall is clean. The old raw run
  remains unchanged and cannot be retroactively promoted.
- The next action requires explicit hardware authorization for a fresh run;
  verify timestamp ordering first, then replay the observation gate. Do not
  claim that the detector or B3 readiness is fixed from this offline change.
