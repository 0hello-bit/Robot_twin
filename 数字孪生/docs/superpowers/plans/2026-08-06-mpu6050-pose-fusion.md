# MPU6050 Pose Fusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline-verifiable, camera-anchored MPU6050 yaw observation path without changing line-following control, safety behavior, or the existing B3 synchronization gate.

**Architecture:** Extend the existing binary telemetry frame from a 24-byte payload to a 26-byte payload while keeping the decoder backward compatible with 24-byte records. Keep raw camera pose and raw telemetry untouched, then run a pure host fusion state machine that uses camera yaw as the global anchor and valid IMU yaw deltas only for short gaps. Write additive fusion evidence beside the existing raw artifacts; never use fused output to change motor commands or turn a failed gate into a pass.

**Tech Stack:** STM32F10x C firmware, Keil MDK, host C contract tests, Python 3.11, pytest, existing `FrameParser`, `ClockSync`, `V1TelemetryFrame`, and `capture_sync_run.py`.

## Global Constraints

- Read and obey `docs/agent-context/PROJECT_MEMORY.md`; reuse the existing ESP transport, binary parser, batch queue, clock sync, capture lifecycle, and cleanup.
- Do not add a TCP client, heartbeat loop, parser, ACK registry, or session lifecycle.
- Do not use IMU yaw, gyro rate, or fused yaw in line-following control, motor mapping, or safety stops.
- Preserve 24-byte telemetry decoding as IMU-unknown legacy evidence.
- Preserve the existing B3 thresholds and raw `pose.jsonl` / `telemetry.jsonl` files.
- Do not flash firmware, send START/STOP, connect to the car, or claim physical MPU validity in this plan.
- Keep `VERIFIED`, `INFERENCE`, and `INSUFFICIENT EVIDENCE` separate in the handoff.
- Every production change follows RED test, minimal GREEN implementation, and regression verification.

---

### Task 1: Versioned IMU Telemetry Decoder and Model

**Files:**
- Modify: `simulation/digital_twin/real_world/frame_parser.py`
- Modify: `simulation/digital_twin/v1_twin/v1_twin_schema.py`
- Test: `simulation/digital_twin/tests/test_frame_parser_health.py`
- Test: `simulation/digital_twin/tests/test_v1_twin_schema.py`

**Interfaces:**
- Consumes: existing 24-byte telemetry payloads and new 26-byte payloads.
- Produces: `decode_telemetry()` fields `imu_yaw_deg_x100`, `imu_validity`, and `imu_validity_known`; `V1TelemetryFrame.imu_yaw_rad`, `imu_validity`, and `imu_validity_known` while retaining the existing `yaw_rad` constructor and JSON field for compatibility.

- [x] **Step 1: Write the failing decoder/model tests**

  Add tests that build an old payload with a signed yaw value and assert it is
  decoded as legacy/unknown, and build a 26-byte payload with
  `imu_yaw_deg_x100=-1234`, validity `0x0F`, and reserved byte zero and assert
  the exact raw value and flags. Add a model test that serializes and restores
  the new fields without changing positional construction used by existing
  tests.

- [x] **Step 2: Run only the new tests and verify RED**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_frame_parser_health.py simulation/digital_twin/tests/test_v1_twin_schema.py
  ```

  Expected: the new assertions fail because the decoder/model has no explicit
  IMU validity and raw-degree fields yet.

- [x] **Step 3: Implement the smallest compatible decoder/model change**

  Keep `PAYLOAD_LEN_TELEMETRY` as the legacy minimum, add a current payload
  length constant of 26, decode the existing yaw bytes as the raw degree value,
  and set `imu_validity_known=False` for 24-byte payloads. For 26-byte payloads
  decode byte 24 as flags and require byte 25 to remain reserved zero in the
  contract test. Keep the existing `yaw` return field and `yaw_rad` model field
  so old capture and dataset code remains readable. Add the explicit
  `imu_yaw_rad` property/serialized field as the normalized radians value and
  make fusion eligibility depend on the validity-known flag, not on a numeric
  zero/nonzero yaw.

- [x] **Step 4: Run the focused tests and verify GREEN**

  Run the same pytest command. Expected: all selected tests pass with no new
  warnings.

---

### Task 2: Firmware IMU Validity and 26-Byte Telemetry Contract

**Files:**
- Modify: `firmware/stm32_line_follower/Hardware/mpu6050.h`
- Modify: `firmware/stm32_line_follower/Hardware/mpu6050.c`
- Modify: `firmware/stm32_line_follower/User/main.c`
- Modify: `firmware/stm32_line_follower/User/telemetry_batch.h`
- Modify: `firmware/stm32_line_follower/User/cipsend_tx.h`
- Test: `simulation/digital_twin/tests/test_telemetry_batch.c`
- Test: `simulation/digital_twin/tests/test_cipsend_tx.c`
- Create: `simulation/digital_twin/tests/test_mpu6050_validity.c`

**Interfaces:**
- Consumes: existing `MPU6050_Init`, `MPU6050_ReadAll`, `MPU6050_UpdateYaw`,
  `Telemetry_Queue`, and latest-five batch path.
- Produces: `MPU6050_GetValidityFlags()`, `MPU6050_SetDtClamped()`, a 31-byte
  wire frame (5-byte frame envelope plus 26-byte payload), and a 155-byte
  latest-five batch/CIPSEND capacity.

- [x] **Step 1: Write failing firmware contract tests**

  Extend the batch test to use `TELEMETRY_BATCH_FRAME_SIZE == 31`, assert five
  frames occupy `155` bytes, and assert the sixth append drops only the oldest.
  Extend the CIPSEND test to accept a 155-byte droppable payload and reject a
  payload larger than the new bound. Add a pure validity test for the required
  bits: initialization, bias, successful read, and current-cycle yaw update;
  `dt_clamped` must be observable and must prevent a fully-valid fusion sample.

- [x] **Step 2: Compile/run the focused tests and verify RED**

  Run the existing host-C compile recipes recorded in the current acceptance
  artifacts, plus the new validity test. Expected: the tests fail on the old
  29-byte batch size, 145-byte CIPSEND limit, and missing validity interface;
  compilation or path failures are not an acceptable RED result.

- [x] **Step 3: Add separate firmware state for initialization, bias, read, update, and dt clamp**

  Keep `ready` as the per-read gate used by the current integration path, but
  add immutable-for-the-run initialization/bias state and per-cycle read/update
  flags. Initialization failure must leave bit 0 clear forever for that boot;
  a later successful read must not promote it. `MPU6050_GetValidityFlags()`
  returns bits 0..4 exactly as specified by the design, and
  `MPU6050_SetDtClamped()` is called by `main.c` after the existing dt clamp
  decision. No sign or scale change is allowed.

- [x] **Step 4: Extend the existing frame and batch path without creating a parallel path**

  Change the telemetry payload length to 26, encode the relative yaw in signed
  degree-times-100 at offsets 20..23, validity at offset 24, and reserved zero
  at offset 25. Set the batch frame size to 31 and the latest-five capacity to
  155. Raise `CIPSEND_TX_MAX_DATA` only to 155 so the new batch fits while the
  existing health frame and priority arbitration remain unchanged. Update all
  existing `Telemetry_Queue` call sites, including line-loss and zero-output
  paths, to carry the current yaw and validity bits.

- [x] **Step 5: Run focused host-C tests and verify GREEN**

  Re-run the tests from Step 2. Expected: all pass, with the existing checksum,
  ACK/STATUS priority, batch overwrite, and safety tests unchanged.

- [x] **Step 6: Rebuild the locked Keil target without flashing**

  Enumerate `Target 1`, rebuild the canonical `project.uvprojx`, record the
  AXF hash and `0 Error(s), 0 Warning(s)`, and do not invoke a flash command.

---

### Task 3: Pure Camera-Anchored Yaw Fusion State Machine

**Files:**
- Create: `simulation/digital_twin/v1_twin/v1_twin_pose_fusion.py`
- Create: `simulation/digital_twin/tests/test_v1_twin_pose_fusion.py`

**Interfaces:**
- Consumes: `V1Pose`, `V1TelemetryFrame`, and a configuration containing
  `imu_sign`, `correction_gain`, and `max_imu_gap_ns`.
- Produces: immutable `V1PoseFusionRecord` with raw camera yaw, raw IMU yaw,
  propagated yaw, fused yaw, optional camera x/y, quality, fallback reason,
  validity flags, timestamp, and gap.

- [x] **Step 1: Write the failing fusion tests**

  Cover these independent behaviors: first valid camera/IMU pair anchors to
  camera yaw; a known IMU delta propagates through a camera gap; a bounded
  camera correction removes part of a known drift; invalid/stale IMU falls
  back to camera-only and never fabricates x/y; angular wraparound uses the
  shortest residual; non-monotonic timestamps and excessive gaps produce
  `INSUFFICIENT_EVIDENCE` or camera-only output according to whether a camera
  pose is present.

- [x] **Step 2: Run the fusion tests and verify RED**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_pose_fusion.py
  ```

  Expected: import/API failures because the pure fusion module does not exist.

- [x] **Step 3: Implement the minimal state machine**

  Use `IMU_VALIDITY_REQUIRED = INIT | BIAS | READ | UPDATED` and reject a
  sample with `DT_CLAMPED`, unknown validity, missing IMU yaw, non-monotonic
  timestamp, or an IMU gap above the configured limit. Anchor on the first
  valid camera/IMU pair. Between camera observations, add
  `imu_sign * wrap(current_imu_yaw - previous_imu_yaw)` to the previous fused
  yaw. When a camera pose is present, apply
  `correction_gain * wrap(camera_yaw - propagated_yaw)` and keep camera x/y as
  the only position source. Return explicit quality and fallback reason for
  every update; do not mutate input frames.

- [x] **Step 4: Run the fusion tests and verify GREEN**

  Run the same pytest command and then the existing schema/dataset tests.
  Expected: all pass and no fused record can contain fabricated x/y when the
  camera pose is absent.

---

### Task 4: Additive Capture Evidence Artifact

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Modify: `simulation/digital_twin/tests/test_capture_sync_cleanup.py`
- Modify: `simulation/digital_twin/tests/test_v1_twin_capture.py`

**Interfaces:**
- Consumes: the existing raw pose/telemetry lists, `ClockSync`, and the pure
  fusion module.
- Produces: `fusion.jsonl` beside `pose.jsonl`, `telemetry.jsonl`,
  `raw_health.json`, and `raw_io.json`; raw files and B3 report fields remain
  byte-for-byte contract-compatible.

- [x] **Step 1: Write failing artifact tests**

  Assert that an offline capture with a valid camera/IMU pair writes one fusion
  record, that a legacy telemetry record writes `CAMERA_ONLY` or
  `INSUFFICIENT_EVIDENCE` rather than a fake IMU result, and that cleanup and
  the unchanged B3 verdict still run when fusion output is additive.

- [x] **Step 2: Run the focused capture tests and verify RED**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_capture_sync_cleanup.py simulation/digital_twin/tests/test_v1_twin_capture.py
  ```

  Expected: the new artifact assertions fail because no fusion artifact is
  emitted.

- [x] **Step 3: Integrate without replacing the existing capture lifecycle**

  After the existing clock fit and synchronized-dataset derivation, generate
  fusion records from the raw streams using the existing nearest-timestamp
  association. Write only the new `fusion.jsonl`; never overwrite or reinterpret
  the raw streams. Record metadata naming the raw wire unit as degrees and the
  normalized model unit as radians. A B3 `FAIL` remains `FAIL` even when fusion
  records exist.

- [x] **Step 4: Run focused tests and verify GREEN**

  Re-run the focused capture tests and inspect the serialized artifact schema.

---

### Task 5: Full Offline Acceptance and Handoff

**Files:**
- Modify: `docs/agent-context/CURRENT_STATUS.md`
- Create: `docs/agent-context/handoffs/2026-08-06-mpu6050-pose-fusion-offline.md`
- Modify: this plan file to mark completed steps only after evidence exists.

- [x] **Step 1: Run the complete Python regression and compileall**

  Run:

  ```powershell
  py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
  py -3.11 -m compileall -q simulation/digital_twin tools
  git diff --check
  ```

- [x] **Step 2: Re-run all affected host-C contracts and Keil rebuild**

  Record exact commands, exit codes, test counts, AXF path/hash, and build
  warnings. Do not flash or connect hardware.

- [x] **Step 3: Write the evidence boundary**

  Mark offline decoder, fusion math, capture artifact, host tests, and Keil
  build as `VERIFIED` only. Mark physical MPU connection, initialization,
  axis sign, scale, drift, and real synchronized improvement as
  `INSUFFICIENT EVIDENCE`. Mark any architectural interpretation of the
  current failed B3 run as `INFERENCE` unless it is directly reproduced from
  raw data.

- [x] **Step 4: Stop at the hardware interface**

  The next action after this plan is a fresh user-authorized hardware gate:
  flash the tested AXF, verify validity flags while stationary, perform a
  bounded elevated-wheel sign test, and only then request a synchronized ground
  run. No hardware action is part of this offline acceptance.
