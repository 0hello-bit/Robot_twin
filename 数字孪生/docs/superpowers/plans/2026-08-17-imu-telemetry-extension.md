# TCP 六轴 IMU Telemetry 扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不启用 UDP、不改变运动控制的前提下，让正式 TCP-only 固件发送 42 字节六轴 IMU telemetry，并让 PC 采集链路保留可用于 A/B 的原始字段。

**Architecture:** 保留现有 `0x01` 二进制 telemetry 类型，以 payload 长度兼容 24/26/42 三种版本。固件在现有遥测生成点快照 MPU6050 六轴值和 telemetry `sample_seq`，PC 解析器按长度解码并将可选字段传入 `V1TelemetryFrame`；PC 接收时间继续由采集端记录，不进入 MCU 帧。

**Tech Stack:** STM32 C/Keil MDK Target 1, TCP ESP-01S CIPSEND, Python 3, pytest, host GCC tests, SHA-256 artifact verification, Git/GitHub.

## Global Constraints

- 只使用 TCP；正式固件源码不得新增 UDP 路径。
- 42 字节 payload 的整帧为 47 字节；CIPSEND 248 字节上限下每批最多 5 帧。
- 六轴字段是 MPU6050 原始 `int16` 寄存器值，不把原始计数伪装成 SI 单位。
- 旧 24/26 字节 telemetry 和旧 JSON 必须继续可解析；旧数据的 raw 字段保持未知。
- 不修改 PID、电机输出、心跳租约、停止保护或烧录流程。
- 不执行烧录；只有在构建、哈希、目标和安全状态核对完成后等待用户单独授权。
- 工作区已有脏改动，所有暂存必须使用明确文件列表，不得使用全量 `git add .`。
- 当前已提交基线保留在 `codex/camera-capture-analysis-decoupling`；实现从该基线建立 `codex/imu-telemetry-extension`，推送目标为 `origin` 的实现分支，不强推、不直接改 `master`。
- 遵循 TDD：每个生产行为先有一个会因功能缺失而失败的测试，再写最小实现并重新验证。

---

### Task 1: Extend Binary Telemetry Decoder

**Files:**
- Modify: `simulation/digital_twin/tests/test_frame_parser_health.py`
- Modify: `simulation/digital_twin/real_world/frame_parser.py`

**Interfaces:**
- Consumes: existing `FrameParser`, `decode_telemetry`, 24/26-byte payloads.
- Produces: `PAYLOAD_LEN_TELEMETRY_EXTENDED = 42`, decoded `imu_ax_raw`, `imu_ay_raw`, `imu_az_raw`, `imu_gx_raw`, `imu_gy_raw`, `imu_gz_raw`, `sample_seq`, and `imu_raw_known`.

- [ ] **Step 1: Add the failing 42-byte decoder tests.**

  Add a test payload with positive and negative raw `int16` values, a large unsigned `sample_seq`, current yaw/status fields, and three concatenated extended frames. Assert the decoded dict contains the exact signed values, `sample_seq`, and `imu_raw_known is True`.

- [ ] **Step 2: Run the decoder tests and verify the expected failure.**

  Run:

  ```powershell
  python -m pytest simulation/digital_twin/tests/test_frame_parser_health.py -q
  ```

  Expected failure: the 42-byte payload is rejected or the new raw keys are absent. Existing 24/26-byte tests must still execute so a test setup error is not mistaken for the feature failure.

- [ ] **Step 3: Implement length-aware extended decoding.**

  Add the 42-byte constant and decode offsets 26..41 as little-endian signed six-axis fields plus unsigned `sample_seq`. Keep 24/26 behavior unchanged and return `None`/`False` for raw fields on legacy lengths.

- [ ] **Step 4: Run the focused decoder suite and inspect the result.**

  Run the same pytest command. Expected result: all decoder, legacy compatibility, checksum, and concatenated-frame tests pass with zero failures.

- [ ] **Step 5: Commit the decoder slice.**

  ```powershell
  git add -- simulation/digital_twin/real_world/frame_parser.py simulation/digital_twin/tests/test_frame_parser_health.py
  git commit -m "feat: decode extended six-axis telemetry"
  ```

### Task 2: Persist IMU Fields Through the PC Capture Schema

**Files:**
- Create: `simulation/digital_twin/tests/test_imu_telemetry_schema.py`
- Modify: `simulation/digital_twin/v1_twin/v1_twin_schema.py`
- Modify: `tools/camera_toolchain/capture_sync_run.py`

**Interfaces:**
- Consumes: Task 1 decoded dict and existing `V1TelemetryFrame` construction in `on_telemetry`.
- Produces: optional raw IMU fields, optional `sample_seq`, and `imu_raw_known` in `V1TelemetryFrame`, JSONL, and `raw_telemetry.json`.

- [ ] **Step 1: Add schema and capture propagation tests.**

  Create tests that construct a frame with six raw values and `sample_seq`, round-trip it through `to_dict`/`from_dict`, and assert legacy dicts without the new keys still load with `None`/`False`. Add a source-level assertion that the binary capture callback passes every decoded raw field into `V1TelemetryFrame`.

- [ ] **Step 2: Run the new schema tests and verify the expected failure.**

  Run:

  ```powershell
  python -m pytest simulation/digital_twin/tests/test_imu_telemetry_schema.py -q
  ```

  Expected failure: `V1TelemetryFrame` does not accept the new constructor fields and `capture_sync_run.py` does not propagate them.

- [ ] **Step 3: Add validated optional schema fields.**

  Bump the schema minor version from `1.1.0` to `1.2.0`. Add optional signed `int16` raw fields, optional unsigned `sample_seq`, and boolean `imu_raw_known`; validate ranges when values are present; include them in `to_dict` and `from_dict`; keep old JSON defaults unknown.

- [ ] **Step 4: Propagate fields at the binary telemetry boundary.**

  In `capture_sync_run.py`, pass the six raw values, `sample_seq`, and `imu_raw_known` from `decode_telemetry` into `V1TelemetryFrame`. Keep `pc_recv_ns`, yaw metadata, and legacy evidence semantics unchanged.

- [ ] **Step 5: Run schema, capture, and existing model tests.**

  ```powershell
  python -m pytest simulation/digital_twin/tests/test_imu_telemetry_schema.py simulation/digital_twin/tests/test_v1_twin_sync.py -q
  ```

  Expected result: all targeted tests pass, including legacy JSON loading and serialization round-trip.

- [ ] **Step 6: Commit the PC schema slice.**

  ```powershell
  git add -- simulation/digital_twin/v1_twin/v1_twin_schema.py tools/camera_toolchain/capture_sync_run.py simulation/digital_twin/tests/test_imu_telemetry_schema.py
  git commit -m "feat: persist raw IMU telemetry in capture schema"
  ```

### Task 3: Extend Firmware Wire Frame and Batch Capacity

**Files:**
- Modify: `firmware/stm32_line_follower/User/main.c`
- Modify: `firmware/stm32_line_follower/User/telemetry_batch.h`
- Modify: `simulation/digital_twin/tests/test_telemetry_batch.c`
- Modify: `simulation/digital_twin/tests/test_telemetry_delivery.c`
- Modify: `simulation/digital_twin/tests/test_telemetry_queue_contract.py`

**Interfaces:**
- Consumes: `mpu_data.ax/ay/az/gx/gy/gz`, `MPU6050_GetValidityFlags`, existing telemetry calls, and the 248-byte CIPSEND bound.
- Produces: 47-byte production frames with a monotonic telemetry `sample_seq`; all normal, line-loss, and hard-stop telemetry calls use the same snapshot layout.

- [ ] **Step 1: Update C and source-contract tests to the desired wire contract.**

  Assert `TELEMETRY_BATCH_FRAME_SIZE == 47U`, `TELEMETRY_BATCH_SEND_MAX_FRAMES == 5U`, `TELEMETRY_BATCH_MAX_BYTES == 752U`, and `TELEMETRY_BATCH_SEND_MAX_BYTES == 235U`. Add source-contract assertions for the six raw fields, sequence field, payload length 42, offsets 26..41, and all three telemetry call paths.

- [ ] **Step 2: Run host C and source-contract tests to verify the expected failure.**

  Run the existing host test build and focused Python contract test:

  ```powershell
  gcc -std=c99 -Wall -Wextra -Werror -Ifirmware/stm32_line_follower/User simulation/digital_twin/tests/test_telemetry_batch.c firmware/stm32_line_follower/User/telemetry_batch.c -o .scratch/telemetry_batch_test.exe
  .scratch/telemetry_batch_test.exe
  python -m pytest simulation/digital_twin/tests/test_telemetry_queue_contract.py -q
  ```

  Expected failure: current constants remain 31/8 and the production source lacks the extended fields. Record any unrelated pre-existing failure separately.

- [ ] **Step 3: Update queue constants and frame-size comments.**

  Change only the telemetry frame and CIPSEND capacity constants in `telemetry_batch.h`. Keep the pending queue at 16 frames and keep `CIPSEND_TX_MAX_DATA == 248U`.

- [ ] **Step 4: Extend the production frame encoder.**

  In `main.c`, extend `build_telemetry_frame` and `Telemetry_Queue` with six `int16_t` raw values and `uint32_t sample_seq`. Set payload length to 42, write the new values at the approved offsets, include every payload byte in the existing XOR, and increment the sequence once per queued telemetry sample. Pass one consistent `mpu_data` snapshot through normal, line-loss, and hard-stop call sites.

- [ ] **Step 5: Update C queue tests for five-frame batches and rerun them.**

  Change only assertions that encode the new constants or five-frame send prefix; retain tests for pending order, overwrite behavior, failed-send retention, and connection clearing. Compile and run both `test_telemetry_batch.c` and `test_telemetry_delivery.c` with `-Wall -Wextra -Werror`.

- [ ] **Step 6: Run the firmware source contract and focused queue suite.**

  ```powershell
  python -m pytest simulation/digital_twin/tests/test_telemetry_queue_contract.py -q
  gcc -std=c99 -Wall -Wextra -Werror -Ifirmware/stm32_line_follower/User simulation/digital_twin/tests/test_telemetry_batch.c firmware/stm32_line_follower/User/telemetry_batch.c -o .scratch/telemetry_batch_test.exe
  .scratch/telemetry_batch_test.exe
  gcc -std=c99 -Wall -Wextra -Werror -Ifirmware/stm32_line_follower/User simulation/digital_twin/tests/test_telemetry_delivery.c firmware/stm32_line_follower/User/telemetry_batch.c firmware/stm32_line_follower/User/telemetry_delivery.c -o .scratch/telemetry_delivery_test.exe
  .scratch/telemetry_delivery_test.exe
  ```

  Expected result: both host binaries report all tests passed and the source contract reports zero failures.

- [ ] **Step 7: Commit the firmware slice.**

  ```powershell
  git add -- firmware/stm32_line_follower/User/main.c firmware/stm32_line_follower/User/telemetry_batch.h simulation/digital_twin/tests/test_telemetry_batch.c simulation/digital_twin/tests/test_telemetry_delivery.c simulation/digital_twin/tests/test_telemetry_queue_contract.py
  git commit -m "feat: transmit raw MPU6050 telemetry over TCP"
  ```

### Task 4: Cross-Layer Verification and Release Checkpoint

**Files:**
- Inspect only: `firmware/stm32_line_follower/project.uvprojx`
- Create/modify only if needed: `.embeddedskills/build/2026-08-17-imu-telemetry-extension/`

**Interfaces:**
- Consumes: the three task commits and the configured Keil `Target 1` project.
- Produces: reproducible test output, Keil build log, HEX/AXF SHA-256 hashes, and a reviewable Git checkpoint. No hardware side effect.

- [ ] **Step 1: Run the complete focused software suite.**

  ```powershell
  python -m pytest simulation/digital_twin/tests/test_frame_parser_health.py simulation/digital_twin/tests/test_imu_telemetry_schema.py simulation/digital_twin/tests/test_v1_twin_sync.py simulation/digital_twin/tests/test_telemetry_queue_contract.py -q
  ```

  Report failures by file and distinguish new regressions from pre-existing dirty-worktree failures.

- [ ] **Step 2: Re-scan the Keil project and Target.**

  ```powershell
  python C:\Users\24668\.codex\skills\keil\scripts\keil_project.py targets --project firmware/stm32_line_follower/project.uvprojx --json
  ```

  Confirm exactly `Target 1` before building.

- [ ] **Step 3: Build with Keil without flashing.**

  ```powershell
  python C:\Users\24668\.codex\skills\keil\scripts\keil_build.py build --uv4 F:\keil\UV4\UV4.exe --project firmware/stm32_line_follower/project.uvprojx --target "Target 1" --log-dir .embeddedskills/build/2026-08-17-imu-telemetry-extension --json
  ```

  Require exit status 0 and zero compiler errors. Do not call `flash`.

- [ ] **Step 4: Hash and inspect artifacts.**

  Parse the structured build result and hash the exact artifact paths it reports:

  ```powershell
  $build = python C:\Users\24668\.codex\skills\keil\scripts\keil_build.py build --uv4 F:\keil\UV4\UV4.exe --project firmware/stm32_line_follower/project.uvprojx --target "Target 1" --log-dir .embeddedskills/build/2026-08-17-imu-telemetry-extension --json | ConvertFrom-Json
  Get-FileHash -Algorithm SHA256 -LiteralPath $build.details.flash_file
  Get-FileHash -Algorithm SHA256 -LiteralPath $build.details.debug_file
  ```

  Record exact paths and hashes in the final report; artifact hashes are build evidence, not proof of a flashed board.

- [ ] **Step 5: Request an independent read-only review.**

  Review the final diff and task requirements for protocol offsets, signedness, queue capacity, backward compatibility, safety behavior, missing tests, and accidental UDP/hardware actions. Resolve all Critical/Important findings before push.

- [ ] **Step 6: Verify the staged scope and push the feature branch.**

  ```powershell
  git status --short
  git diff --check origin/master..HEAD
  git push -u origin codex/imu-telemetry-extension
  ```

  The push contains the committed baseline history plus this feature's design, plan, implementation, and verification records; unrelated working-tree changes remain unstaged and local.
