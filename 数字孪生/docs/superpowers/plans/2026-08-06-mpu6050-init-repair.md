# MPU6050 Initialization Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MPU6050 initialization finite, retryable, fail-closed, and diagnosable through the existing 26-byte telemetry payload without changing vehicle control behavior.

**Architecture:** Keep the existing software-I2C driver and public initialization/read APIs. Add a bounded whole-sequence initialization attempt that returns an internal stage code, expose that code through the existing reserved telemetry payload byte, and carry it through the existing parser/schema/fusion path. Host fusion will require both the existing current-cycle validity bits and an explicit successful initialization status.

**Tech Stack:** STM32F10x C firmware, ARMCC/Keil MDK Target 1, MSVC Host C contract tests, Python 3.11, pytest, existing `FrameParser`, `V1TelemetryFrame`, `V1PoseFusion`, and capture pipeline.

## Global Constraints

- Preserve `MPU6050_ADDR=0x68`; never probe `0x69` automatically.
- The first initialization attempt may be followed by at most three retries, for at most four complete attempts total.
- Preserve the 26-byte telemetry payload and 31-byte complete wire frame; payload byte 25 / wire byte 29 is the only new status location.
- Keep `INIT | BIAS | READ | UPDATED` and `DT_CLAMPED` semantics unchanged; `0x04` must never become full validity.
- Do not change PID, motor mapping, line-loss behavior, speed limits, turn logic, safety stops, or the existing capture lifecycle.
- Reuse the current telemetry parser, schema, capture forwarding, session storage, and fusion module; no parallel protocol or transport path.
- Follow TDD for every production behavior: write a failing test, observe the expected failure, implement the smallest change, then rerun focused and regression tests.
- Do not flash, reset, send START/STOP, connect to the car, or run motor motion in this plan.
- Keep `VERIFIED`, `INFERENCE`, and `INSUFFICIENT EVIDENCE` separate in the final handoff.
- Do not commit or clean the dirty shared worktree; all unrelated changes belong to the user or other agents.

---

### Task 1: Add RED Contracts for Initialization Status and Telemetry

**Files:**
- Modify: `simulation/digital_twin/tests/test_mpu6050_validity.c`
- Modify: `simulation/digital_twin/tests/test_frame_parser_health.py`
- Modify: `simulation/digital_twin/tests/test_v1_twin_schema.py`
- Modify: `simulation/digital_twin/tests/test_v1_twin_pose_fusion.py`

**Interfaces:**
- Consumes: current `MPU6050_Init`, `MPU6050_ReadAll`, validity flags, 24/26-byte telemetry decoder, and `V1TelemetryFrame`.
- Produces: executable RED tests for `MPU6050_GetInitStatus`, named failure codes, retry bounds, 26-byte status decoding, schema round-trip, and fusion rejection of a nonzero init status.

- [x] **Step 1: Extend the Host C stub with deterministic failure injection**

  Keep the existing GPIO/Delay stubs and add only test-side controls for a
  selected I2C transaction or bias sample. The stub must be able to model:

  ```c
  reset_bus(1U, 1U);
  fail_next_transaction_at(1U);  /* first write fails */
  fail_who_am_i_value(0x70U);     /* completed read, wrong identity */
  fail_bias_sample(3U);           /* fourth 6-byte bias read fails */
  ```

  Count attempted reset writes and WHO_AM_I/bias transactions in the test
  harness so the retry ceiling is observable without adding production test
  hooks.

- [x] **Step 2: Write the failing firmware behavior tests**

  Add focused tests with these names and assertions:

  ```c
  test_transient_init_failure_recovers_within_retry_budget
  test_persistent_init_failure_is_bounded_and_sticky
  test_who_am_i_read_and_mismatch_have_distinct_statuses
  test_bias_read_failure_is_attributed
  test_runtime_read_failure_does_not_rewrite_boot_status
  ```

  The tests must assert the named status values, `INIT|BIAS` only after full
  success, no promotion by a later readable `ReadAll()`, and no fusion
  eligibility after persistent initialization failure. The first run must
  fail because the status accessor/stage behavior is absent or because the
  current implementation stops after the first failure; do not weaken the
  assertions to fit current behavior.

- [x] **Step 3: Write the failing Python protocol/schema/fusion tests**

  Extend the existing current-frame test with a nonzero payload byte 25 and
  assert:

  ```python
  decoded["imu_init_status"] == 0x21
  decoded["imu_init_status_known"] is True
  ```

  Assert a legacy 24-byte payload has `imu_init_status_known is False`. Add a
  `V1TelemetryFrame` JSON round-trip with `imu_init_status=0x21` and
  `imu_init_status_known=True`. Add a fusion test with validity `0x0F` and
  init status `0x21`; it must return `CAMERA_ONLY` with
  `fallback_reason == "imu_init_failed"`.

- [x] **Step 4: Run only the new/affected tests and record RED**

  Run the existing Host C recipe from the offline handoff and:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_frame_parser_health.py simulation/digital_twin/tests/test_v1_twin_schema.py simulation/digital_twin/tests/test_v1_twin_pose_fusion.py
  ```

  The Python assertions must fail because payload byte 25 is not decoded and
  fusion does not yet check initialization status. The C test may fail to link
  only on the newly declared accessor; that missing symbol is the expected
  feature RED, not a path or toolchain failure. Record the exact failure before
  writing production changes.

---

### Task 2: Implement Bounded MPU6050 Initialization and Stage Status

**Files:**
- Modify: `firmware/stm32_line_follower/Hardware/mpu6050.h`
- Modify: `firmware/stm32_line_follower/Hardware/mpu6050.c`
- Test: `simulation/digital_twin/tests/test_mpu6050_validity.c`

**Interfaces:**
- Consumes: existing software-I2C register accessors, `MPU6050_Data`, and validity flags.
- Produces: `MPU6050_GetInitStatus()` and stable constants for `OK`, `NOT_ATTEMPTED`, each configuration write, WHO_AM_I read/mismatch, and bias read failure.

- [x] **Step 1: Add the stable status constants and accessor contract**

  Add these exact values to `mpu6050.h`:

  ```c
  #define MPU6050_INIT_STATUS_OK                 0x00U
  #define MPU6050_INIT_STATUS_NOT_ATTEMPTED      0x01U
  #define MPU6050_INIT_STATUS_RESET_WRITE       0x10U
  #define MPU6050_INIT_STATUS_WAKE_WRITE        0x11U
  #define MPU6050_INIT_STATUS_SAMPLE_RATE_WRITE 0x12U
  #define MPU6050_INIT_STATUS_CONFIG_WRITE      0x13U
  #define MPU6050_INIT_STATUS_GYRO_CONFIG_WRITE 0x14U
  #define MPU6050_INIT_STATUS_ACCEL_CONFIG_WRITE 0x15U
  #define MPU6050_INIT_STATUS_WHO_AM_I_READ     0x20U
  #define MPU6050_INIT_STATUS_WHO_AM_I_MISMATCH 0x21U
  #define MPU6050_INIT_STATUS_BIAS_READ         0x30U
  ```

  Declare `uint8_t MPU6050_GetInitStatus(void);`. Keep the existing validity
  constants and public function signatures unchanged.

- [x] **Step 2: Implement one complete internal initialization attempt**

  Add a private helper that performs the existing sequence in order and
  returns one stage code. Every failed register write returns its matching
  stage code immediately. Read WHO_AM_I through the existing read primitive so
  a transaction failure returns `WHO_AM_I_READ` while a completed value other
  than `0x68` returns `WHO_AM_I_MISMATCH`. Reset the bias sum at the start of
  every attempt and return `BIAS_READ` on any failed sample. Do not add an
  alternate address or modify the existing register values, bias count,
  spacing, yaw scale, sign, or filter.

- [x] **Step 3: Wrap the helper in the finite retry loop**

  In `MPU6050_Init`, initialize flags, `ready`, yaw, bias, and status before
  the first attempt. Run the helper once and then at most three more times
  while it returns a failure code. Use a short fixed delay between attempts.
  On success set `INIT|BIAS`, status `OK`, and return. On exhaustion leave all
  validity bits clear, leave `ready=0`, reset yaw/bias to boot-safe values, and
  retain the final stage code. Do not introduce a timer, interrupt, or
  background retry.

- [x] **Step 4: Run the C RED tests again and make them GREEN**

  Use the existing MSVC command from
  `docs/agent-context/handoffs/2026-08-06-mpu6050-pose-fusion-offline.md` to
  compile `test_mpu6050_validity.c` with the real `Hardware/mpu6050.c` and
  `tests/mpu_stubs`. Expected result is `PASS test_mpu6050_validity`, with
  exact assertions for four total attempts on persistent failure.

- [x] **Step 5: Run the existing Host C regressions**

  Rebuild and run `test_telemetry_batch.c` and `test_cipsend_tx.c` before
  changing telemetry encoding. They must remain green, confirming the new
  status accessor did not change batch or transport ownership.

---

### Task 3: Reuse the Existing Telemetry Byte Without Changing Framing

**Files:**
- Modify: `firmware/stm32_line_follower/User/main.c`
- Modify: `simulation/digital_twin/real_world/frame_parser.py`
- Modify: `simulation/digital_twin/tests/test_frame_parser_health.py`

**Interfaces:**
- Consumes: `MPU6050_GetInitStatus()`, existing `build_telemetry_frame`, and current 24/26-byte decoder.
- Produces: `imu_init_status` and `imu_init_status_known` in decoded telemetry while retaining the current payload and wire lengths.

- [x] **Step 1: Add a framing/layout RED assertion**

  Build a 26-byte payload with `payload[24]=0x0F` and `payload[25]=0x21`,
  encode a complete frame with the existing helper used by the parser tests,
  and assert the parser preserves the 31-byte frame length, checksum validity,
  validity byte, and status byte. The current decoder must fail on the missing
  status field before production edits.

- [x] **Step 2: Encode the boot status at payload byte 25**

  In `build_telemetry_frame`, keep `len=26`, the existing yaw offsets, and the
  existing checksum loop. Replace only the reserved assignment:

  ```c
  s_tele_frame[29] = MPU6050_GetInitStatus();
  ```

  This is complete-frame byte 29, payload byte 25. Do not alter
  `TELEMETRY_BATCH_FRAME_SIZE`, the latest-five queue, `CIPSEND_TX_MAX_DATA`,
  or any Telemetry_Queue caller.

- [x] **Step 3: Decode the status with legacy compatibility**

  Add protocol constants and decode fields in `frame_parser.py`:

  ```python
  d["imu_init_status"] = payload[25] if len(payload) == 26 else 0
  d["imu_init_status_known"] = len(payload) == 26
  ```

  Keep 24-byte payload acceptance and mark its initialization status unknown.
  Keep the existing `yaw`, `imu_yaw_deg_x100`, and validity fields unchanged.

- [x] **Step 4: Run parser and Host C framing tests GREEN**

  Run the focused parser test and both existing C telemetry tests. Verify the
  new byte participates in XOR checksum validation and no frame length or
  batching regression appears.

---

### Task 4: Carry Initialization Status Through Schema and Fusion Gate

**Files:**
- Modify: `simulation/digital_twin/v1_twin/v1_twin_schema.py`
- Modify: `simulation/digital_twin/v1_twin/v1_twin_pose_fusion.py`
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Modify: `simulation/digital_twin/tests/test_v1_twin_schema.py`
- Modify: `simulation/digital_twin/tests/test_v1_twin_pose_fusion.py`
- Modify: `simulation/digital_twin/tests/test_capture_sync_cleanup.py`

**Interfaces:**
- Consumes: parser keys `imu_init_status` and `imu_init_status_known`.
- Produces: backward-compatible `V1TelemetryFrame` fields and fusion records that explain initialization rejection.

- [x] **Step 1: Extend `V1TelemetryFrame` compatibly**

  Add defaulted fields after the existing IMU fields:

  ```python
  imu_init_status: int = 0
  imu_init_status_known: bool = False
  ```

  Validate the status as `uint8` and the known flag as `bool`. Include both in
  `to_dict()` and `from_dict()`. Existing positional construction and old JSON
  without the fields must continue to work.

- [x] **Step 2: Forward the fields in the existing capture callback**

  In the current `V1TelemetryFrame(...)` construction, pass:

  ```python
  imu_init_status=int(d["imu_init_status"]),
  imu_init_status_known=bool(d["imu_init_status_known"]),
  ```

  Do not change socket ownership, frame parsing, clock fitting, artifact
  names, or cleanup behavior.

- [x] **Step 3: Make the existing fusion eligibility check fail closed**

  Keep the existing reason ordering for legacy validity failures, then add:

  ```python
  if not telemetry.imu_init_status_known:
      return "imu_init_status_unknown"
  if telemetry.imu_init_status != MPU6050_INIT_STATUS_OK:
      return "imu_init_failed"
  ```

  Import the shared Python protocol constant from the existing parser module;
  do not create a second fusion implementation or a second telemetry decoder.
  Add the two status fields to `V1PoseFusionRecord` and its serialized evidence
  so a rejected sample remains auditable.

- [x] **Step 4: Run focused Python tests GREEN**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_frame_parser_health.py simulation/digital_twin/tests/test_v1_twin_schema.py simulation/digital_twin/tests/test_v1_twin_pose_fusion.py simulation/digital_twin/tests/test_capture_sync_cleanup.py
  ```

  Confirm legacy samples remain camera-only/insufficient, `0x04` still reports
  `imu_not_fresh`, and a current frame with `0x0F + status 0x21` reports
  `imu_init_failed`.

---

### Task 5: Full Offline Acceptance, Documentation, and Hardware Handoff

**Files:**
- Modify: `docs/superpowers/plans/2026-08-06-mpu6050-init-repair.md`
- Modify: `docs/agent-context/CURRENT_STATUS.md`
- Create: `docs/agent-context/handoffs/2026-08-06-mpu6050-init-repair-offline.md`

**Interfaces:**
- Consumes: green focused tests, existing Python regression, Host C results, and canonical Keil Target 1 build output.
- Produces: evidence-traceable offline/build handoff that stops before any hardware action.

- [x] **Step 1: Run the complete Python regression and syntax checks**

  Run exactly:

  ```powershell
  py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
  py -3.11 -m compileall -q simulation/digital_twin tools
  git diff --check
  ```

  Record exit codes and test counts. Do not treat archived legacy collection
  failures as current regression evidence; report them separately if they
  occur.

- [x] **Step 2: Re-run all affected Host C contracts**

  Compile/run `test_mpu6050_validity.c`, `test_telemetry_batch.c`, and
  `test_cipsend_tx.c` against the real production C modules and existing test
  stubs. Record compiler path, command, exit code, and output directory.

- [x] **Step 3: Rebuild canonical Keil Target 1 without flashing**

  Enumerate Target 1 and rebuild `firmware/stm32_line_follower/project.uvprojx`
  with the established Keil skill command. Record the AXF path/hash and exact
  `0 Error(s), 0 Warning(s)` result. Do not invoke the flash entrypoint.

- [x] **Step 4: Write the evidence handoff**

  The handoff must include changed files, exact commands/results, stage-code
  semantics, raw evidence paths if any, and these boundaries:

  - `VERIFIED`: offline tests, parser/schema/fusion behavior, C contracts, and
    Keil build only;
  - `INFERENCE`: the repair is expected to distinguish transient I2C failure
    from the named initialization boundary;
  - `INSUFFICIENT EVIDENCE`: physical wiring, WHO_AM_I on the real car, bias
    quality, axis sign/scale, valid synchronized capture, and any vehicle
    improvement.

- [x] **Step 5: Stop at the hardware interface**

  Update `CURRENT_STATUS.md` to request a fresh user authorization for flashing
  the verified AXF. The next hardware gate is stationary/elevated-wheel
  telemetry: require `imu_validity` bits `0x0F`, `DT_CLAMPED` clear, and
  `imu_init_status=0x00` before any ground motion. No flash, reset, START,
  STOP, serial send, or motor test is part of this plan.
