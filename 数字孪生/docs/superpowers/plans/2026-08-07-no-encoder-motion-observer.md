# No-Encoder Motion Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline-only camera-trajectory motion observer so the digital twin can estimate body-plane motion when the car has no wheel encoders.

**Architecture:** Derive finite-difference world-frame velocity, planar speed, and yaw rate from the existing calibrated `V1Pose` sequence. Keep the result explicitly labeled as `CAMERA_POSE_DERIVATIVE`; it is an external vehicle-motion observation, not wheel RPM, and it never feeds firmware control or changes the B3 verdict. Reject the first sample, non-monotonic timestamps, and excessive gaps instead of fabricating values.

**Tech Stack:** Python 3.11, existing `V1Pose`, `wrap_angle_rad`, pytest, current `simulation/digital_twin` package.

## Global Constraints

- Reuse the existing `V1Pose` schema and angle helper; do not create a second camera tracker or capture lifecycle.
- Do not add an encoder, infer four wheel speeds, or call camera-derived speed a measured motor speed.
- Do not modify STM32 firmware, TCP frames, safety behavior, PID control, B3 thresholds, or real hardware state.
- Keep `VERIFIED`, `INFERENCE`, and `INSUFFICIENT_EVIDENCE` distinct.
- Do not perform Git write operations; the canonical workspace is already dirty and repository instructions require separate authorization for Git writes.

---

### Task 1: Define the camera-motion observer contract

**Files:**
- Create: `simulation/digital_twin/v1_twin/v1_twin_motion_observer.py`
- Test: `simulation/digital_twin/tests/test_v1_twin_motion_observer.py`

**Interfaces:**
- Consumes: `Iterable[V1Pose]`, with `x_mm`, `y_mm`, `yaw_rad`, and monotonic PC `t_pc_ns`.
- Produces: `estimate_camera_motion(poses, max_gap_ns=100_000_000) -> tuple[V1CameraMotion, ...]`.
- Each `V1CameraMotion` contains `timestamp_ns`, `dt_s`, `dx_mm`, `dy_mm`, `world_vx_mm_s`, `world_vy_mm_s`, `planar_speed_mm_s`, `yaw_rate_rad_s`, `quality`, and `reason`.

- [x] **Step 1: Write failing tests for valid finite differences**

  Use two `V1Pose` values 100 ms apart with a 100 mm x displacement and a
  `0.2` rad yaw change. Assert the second record reports `1000 mm/s`, a
  `2 rad/s` yaw rate, and the source-independent quality `VALID`.

- [x] **Step 2: Write failing tests for fail-closed boundaries**

  Assert the first pose is `INSUFFICIENT_EVIDENCE`, a repeated timestamp is
  rejected, and a gap larger than `max_gap_ns` returns no velocity or yaw rate.
  Assert angle wraparound uses the shortest yaw delta and that the function
  does not mutate input poses.

- [x] **Step 3: Run the focused tests and verify RED**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_motion_observer.py
  ```

  Expected: collection fails because the new observer module and API do not
  exist yet. A collection error caused by a test typo is not acceptable RED.

### Task 2: Implement the minimal observer

**Files:**
- Modify: `simulation/digital_twin/v1_twin/v1_twin_motion_observer.py`
- Test: `simulation/digital_twin/tests/test_v1_twin_motion_observer.py`

**Interfaces:**
- Reuses: `V1Pose` and `wrap_angle_rad` from the existing V1 twin package.
- Produces: immutable records with explicit optional derivatives and quality.

- [x] **Step 1: Implement input validation and first-sample behavior**

  Validate `max_gap_ns` as a positive integer, accept only `V1Pose` values,
  and emit an immutable first record with `quality=INSUFFICIENT_EVIDENCE` and
  `reason="no_previous_pose"`.

- [x] **Step 2: Implement finite-difference motion**

  For a valid adjacent pair, calculate `dt_s` from `t_pc_ns`, divide `dx_mm`
  and `dy_mm` by `dt_s`, calculate `planar_speed_mm_s` with `hypot`, and use
  `wrap_angle_rad(current.yaw_rad - previous.yaw_rad) / dt_s` for yaw rate.
  Keep all position and velocity values in millimeters and seconds, and do
  not transform into a vehicle body frame until the mounting convention is
  calibrated.

- [x] **Step 3: Implement fail-closed gap and timestamp handling**

  For non-monotonic timestamps or gaps above `max_gap_ns`, return a record
  with `dt_s`, derivatives, and speed set to `None`, preserving the current
  pose timestamp and an explicit reason. Do not use the invalid pose as a
  valid predecessor for the next derivative.

- [x] **Step 4: Run the focused tests and verify GREEN**

  Re-run the focused test command. Expected: all observer tests pass.

### Task 3: Record the no-encoder evidence boundary

**Files:**
- Modify: `docs/agent-context/PROJECT_MEMORY.md`
- Modify: `docs/agent-context/CURRENT_STATUS.md`
- Create: `docs/agent-context/handoffs/2026-08-07-no-encoder-motion-observer.md`

- [x] **Step 1: Record the hardware fact and naming contract**

  State that the current car has no wheel encoder feedback in the active
  hardware/firmware path; telemetry `m1..m4` remains commanded PWM. State that
  camera-derived planar speed is external motion evidence only.

- [x] **Step 2: Run the affected offline verification**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_motion_observer.py simulation/digital_twin/tests/test_v1_twin_pose_fusion.py simulation/digital_twin/tests/test_v1_twin_imu_control.py
  py -3.11 -m compileall -q simulation/digital_twin tools
  git diff --check
  ```

  Record exact results. Do not connect to the car, flash, reset, send START,
  send STOP, or start a camera capture.

- [x] **Step 3: Write the handoff evidence boundary**

  Mark the observer math and tests `VERIFIED`; mark real camera-derived speed,
  camera/IMU synchronization, calibrated body-frame direction, wheel RPM, and
  any control improvement `INSUFFICIENT EVIDENCE`. The next hardware gate is
  a user-authorized synchronized camera + telemetry run, not a motor-speed
  claim.
