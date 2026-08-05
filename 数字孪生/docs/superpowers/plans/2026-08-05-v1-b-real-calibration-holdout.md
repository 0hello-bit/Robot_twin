# Robot Twin AI V1-B 真实校准与 Holdout 计划书

> **For agentic workers:** 本计划采用单 agent、顺序任务和强制停点。每个任务完成后必须提交 handoff，等待 Codex 独立验收；不得把 agent 自报结果当作通过依据。

**Goal:** 在不修改小车核心算法和硬件的前提下，用真实小车的同步观测数据校准当前数字孪生，并用完全隔离的 holdout 数据验证它是否足以支持下一阶段的候选筛选。

**Architecture:** 当前小车、相机和现有遥测组成真实观测端；`capture_sync_run.py` 生成带 run ID 的不可覆盖原始数据；`V1Identification` 只使用 calibration 数据拟合；`V1ModelRegistry` 冻结带版本和哈希的模型；holdout 由独立验证器重新加载模型并生成预测报告。V1-B 不生成 AI 候选，不修改固件源码，不设计 PCB。

**Tech Stack:** Python 3.11、现有 `simulation/digital_twin/v1_twin` 接口、`tools/camera_toolchain` 采集工具、pytest、当前 STM32 固件运行时参数协议；真实采集仅在用户当次明确授权后进行。

## Global Constraints

- 正式工作区固定为 `C:\Users\24668\Desktop\stm32小车\数字孪生`；所有新文件、输出和测试都在此目录内。
- V1-B 的最终状态只能是 `TWIN_USABLE` 或 `INSUFFICIENT_EVIDENCE`；V1-B 阶段不得写成真实数字孪生 `READY`。
- 没有用户对具体采集动作的当次授权时，不连接相机、TCP、串口、ST-Link，不烧录，不复位，不发送 `START`，不驱动车轮。
- 硬件采集只能使用已经审核的固件和受限运行时参数；不得在 V1-B 中修改 `main.c`、控制算法、通信协议、安全停机逻辑或 PCB。
- 人工可以执行上电、打板、装配、相机摆放和安全停机；人工不得替 agent 调参、修改候选代码、修复候选固件或主观选择候选胜者。
- 原始数据目录使用新的唯一 `run_id`，不覆盖已有目录；原始文件、manifest、哈希和报告分离保存。
- 所有结论必须分为 `VERIFIED`、`INFERENCE`、`INSUFFICIENT EVIDENCE`。mock、截图、编译成功和路径存在不能当作真机证据。
- 一个 agent 只执行一个明确任务。到达计划中的 `AGENT STOP` 后必须停止，不能自行进入下一个 Gate。
- V1-B 不是 V1-C。V1-B 通过后，只能说数字孪生通过了真实数据校准与 holdout 验证；只有 V1-C 的真实 A/B/C 改进才能证明 AI 参与了一轮真实机器人研发迭代。

---

## 1. 先把问题说清楚

### 1.1 V1-B 要证明什么

V1-A 已经证明了离线软件链路：

```text
初始状态 + 赛道 + PID 候选
    -> controller
    -> plant
    -> virtual sensor
    -> predictor
    -> evaluator
```

V1-B 要证明的是这条链路不再只依赖 synthetic plant，而是能够由当前小车的真实观测数据约束，并在没有参与拟合的真实数据上进行检查。最小有效证据包括：

1. 相机、遥测和运行参数能够以同一 `run_id` 可靠关联；
2. calibration 与 holdout 严格隔离，模型拟合没有读取 holdout；
3. 真实模型可以被版本化、重新加载和确定性复现；
4. holdout 报告同时给出预测误差、失败样本和数据覆盖范围；
5. 对目标场景的证据边界明确：模型在哪些速度、曲率和传感器条件下有效，哪些条件仍然没有证据。

### 1.2 V1-B 不证明什么

- 不证明 AI 已经自主修改核心算法；
- 不证明 AI 已经设计出可用 PCB；
- 不证明当前数字孪生能够一次性预测所有高速急弯行为；
- 不证明真实小车已经完成性能提升；
- 不证明相机、MPU6050 或编码器一定有用。

### 1.3 一个必须避免的逻辑错误

只采集一条 baseline 轨迹，再用这条轨迹拟合模型，只能说明模型可以解释已经观察到的行为，不能说明模型可以判断候选 B 是否优于 A。为此，V1-B 的数据协议必须包含至少两种预先声明的受限输入或运行状态，例如 baseline 与一个受限运行时参数扰动；holdout 必须包含没有参与拟合的运行条件。具体参数值必须在采集前写入 acceptance profile，不得采集后按结果改值。

如果没有受限激励数据，V1-B 最多只能接受为 `CALIBRATION_DATA_READY`，不能接受为 `TWIN_USABLE_FOR_CANDIDATE_SCREENING`。

---

## 2. 当前接口和目录边界

agent 必须先复用现有接口，不得重新造一套平行数字孪生：

- `simulation/digital_twin/v1_twin/v1_twin_schema.py`：遥测、姿态和单位约定；
- `simulation/digital_twin/v1_twin/v1_twin_capture.py`：run ID 输出目录和采集输入校验；
- `simulation/digital_twin/v1_twin/v1_twin_calibration_set.py`：calibration/holdout 集合隔离；
- `simulation/digital_twin/v1_twin/v1_twin_identification.py`：真实数据拟合入口；
- `simulation/digital_twin/v1_twin/v1_twin_model_registry.py`：模型版本和证据注册；
- `simulation/digital_twin/v1_twin/v1_twin_validator.py`：候选和证据门禁；
- `tools/camera_toolchain/capture_sync_run.py`：同步采集入口；
- `simulation/digital_twin/tests/`：现有离线回归测试。

新增文件只有在现有接口不能表达 V1-B 约束时才允许添加，并且必须保持 `v1_twin_*` 命名、可独立测试和可追溯。不能为了计划书而预先创建 UI、MCP、第二台机器人或 PCB 工具链。

建议的真实数据目录：

```text
simulation/digital_twin/data/product/sessions/v1_b/{run_id}/
    session_manifest.json
    camera_frames/                 # 原始帧或明确的帧索引
    telemetry.jsonl                # 原始遥测，不覆盖
    pose.jsonl                     # 相机/地面位姿
    sync_report.json               # 同步门禁结果
    hashes.json                    # 原始文件哈希
    derived/                       # 可重建派生数据
```

`derived/` 可以删除后重建；原始文件和 `session_manifest.json` 不得被派生流程覆盖。

---

## 3. V1-B 数据契约

### 3.1 Run 类型

每个 run 的 manifest 必须明确标记以下一种类型：

- `SMOKE`：相机、通信和安全停机的短验证，不进入模型拟合；
- `CALIBRATION`：允许用于参数拟合，必须记录输入 profile 和覆盖范围；
- `HOLDOUT`：在模型版本冻结前不得参与拟合、调参、阈值选择或候选排序；
- `EXCITATION`：预先声明的受限输入变化，用于识别速度、转向和延迟响应；它必须明确归入 calibration 或 holdout，不得同时属于两者。

### 3.2 每个 run 必须记录的元数据

```json
{
  "run_id": "v1b-20260805-001",
  "run_type": "CALIBRATION",
  "robot_id": "stm32-line-follower-01",
  "track_id": "string",
  "track_map_version": "string",
  "firmware_sha256": "64-hex-string",
  "controller_version": "string",
  "input_profile_id": "string",
  "camera_config_hash": "64-hex-string",
  "calibration_set_id": "string",
  "holdout_set_id": null,
  "started_at_utc": "RFC3339-string",
  "duration_s": 0.0,
  "authorization_reference": "string",
  "raw_files": [],
  "status": "CAPTURED"
}
```

上面的字段不是让 agent 填假值。所有尖括号字段在真实运行前必须有实际值；缺失时 run 必须进入 `INSUFFICIENT_EVIDENCE`，不得被模型读取。

每条样本必须统一单位并记录来源：

- 时间：单调 PC 纳秒和 MCU tick，禁止把 wall-clock 当同步时钟；
- PWM：保留符号，明确量纲和量程；
- 位姿：米/毫米、弧度，坐标系和相机到地面的变换版本必须明确；
- yaw：若来自 MPU6050 且尚未独立验证，标记为 exploratory，不得伪装成 VERIFIED；
- 速度：没有编码器或其他直接测量时，不得把 PWM 当作速度事实。

### 3.3 数据泄漏规则

以下任一情况都使该次 V1-B 直接 `INSUFFICIENT EVIDENCE`：

- calibration 与 holdout 的 `run_id`、原始文件哈希或样本时间段重叠；
- 用 holdout 选择模型参数、阈值、输入 profile 或候选；
- 在模型冻结后修改 holdout 原始数据；
- manifest 中固件、赛道、相机或参数 profile 版本缺失；
- 把同一条长录制切成两段后伪装成独立 calibration 和 holdout，而没有预先声明切分规则。

---

## 4. Gate 总表与独立验收点

| Gate | 名称 | agent 交付物 | agent 必须停止的位置 | Codex 独立验收条件 |
|---|---|---|---|---|
| B0 | Scope Freeze | 本计划的任务分解、数据契约、受限激励 profile 草案、禁止项清单 | 不得扩张到 V1-C、V2、V3 或平台化 | 检查范围是否仍为 V1-B；检查没有 UI/MCP/第二车/PCB 扩张 |
| B1 | Offline Ready | 数据 manifest/validator、离线测试、采集工具 preflight、handoff | 不连接设备，不运行相机，不执行 `START` | 独立运行测试和编译；检查无外部旧路径、无硬件副作用、状态不写 READY |
| B2 | Hardware Safety Smoke | 相机探测、已授权固件核验、抬轮短运行、最终 STOP 证据 | 不得自行进入地面采集 | 复核固件哈希、相机实际模式、ACK/STOP 原始证据和安全条件；用户再次授权后才能继续 |
| B3 | Sync Gate | 新的 `SMOKE/CALIBRATION/HOLDOUT` 原始 run 及 `sync_report.json` | 同步 Gate 不通过时停止，不采集更多数据掩盖失败 | 从原始数据重算 coverage、p95、时间单调性、清理结果，不信任 agent 报告数字 |
| B4 | Dataset Freeze | calibration/holdout manifest、哈希清单、覆盖矩阵、不可变数据目录 | 数据冻结后不得修改 raw 或偷偷重分组 | 独立检查 ID/哈希隔离、目标高速急弯覆盖、输入 profile 覆盖和单位一致性 |
| B5 | Twin Validation | calibration fit、冻结 model registry、holdout 预测报告、失败样本报告 | holdout 读入前必须冻结模型；报告不通过则停止 | 独立从 raw+model hash 重跑；检查拟合未读 holdout、结果可复现、门限无事后调整 |
| B6 | V1-B Decision | `TWIN_USABLE` 或 `INSUFFICIENT_EVIDENCE` handoff | 不得直接开始 V1-C | Codex 给出最终 verdict；只有 `TWIN_USABLE` 才能写 V1-C 任务 |

任何 Gate 被拒绝时，agent 只能修复对应 Gate 的问题并重新提交，不能跳到后续 Gate。

---

## 5. 详细任务计划

### Task B1：离线数据契约与 preflight

**Files:**

- Inspect: `simulation/digital_twin/v1_twin/v1_twin_schema.py`
- Inspect: `simulation/digital_twin/v1_twin/v1_twin_capture.py`
- Inspect: `simulation/digital_twin/v1_twin/v1_twin_calibration_set.py`
- Inspect: `simulation/digital_twin/v1_twin/v1_twin_identification.py`
- Inspect: `simulation/digital_twin/v1_twin/v1_twin_model_registry.py`
- Inspect: `tools/camera_toolchain/capture_sync_run.py`
- Create or modify only the smallest required validator/schema module under `simulation/digital_twin/v1_twin/`
- Test: `simulation/digital_twin/tests/test_v1_b_*.py` or the existing nearest test module
- Create: `docs/agent-context/handoffs/2026-08-05-v1-b-offline-preflight.md`

**Required work:**

1. Run the existing complete V1-A test baseline before changing anything.
2. Map every V1-B manifest field to an existing schema or a minimal new field.
3. Add tests that reject missing run IDs, duplicate IDs, calibration/holdout overlap, non-monotonic timestamps, mixed units, missing firmware hash, and raw-file overwrite.
4. Add tests that accept a valid synthetic calibration/holdout pair without touching hardware.
5. Add or repair a no-device preflight that checks imports, `--help`, syntax, output-directory isolation and dependency paths.
6. Record the exact acceptance profile for the first hardware campaign, including the two or more input profiles, target speed/curve coverage, and numeric holdout thresholds. Thresholds must be justified from the existing measurement-noise/nominal-model evidence and frozen before hardware capture; Codex must approve them before B2.

**Required verification:**

```powershell
py -3.11 -m pytest -q simulation\digital_twin\tests
py -3.11 -m compileall -q simulation\digital_twin tools
```

**B1 acceptance:** all existing tests pass; new validator tests pass; no command opens a camera, network socket, serial port or debugger; no active source contains the old parent-workspace path; no real run is reported as captured.

**AGENT STOP:** 提交 changed files、命令结果、未验证项和下一接口后停止。只有 Codex 完成 B1 独立验收，才允许进入 B2。

### Task B2：安全硬件 Smoke

本任务只有在用户给出包含具体设备、时长和动作的当次授权后才能执行。B1 未通过时不得执行。

**Required execution order:**

1. 复核当前 canonical firmware artifact 和 SHA-256；历史 handoff 中的路径或哈希不能自动视为当前固件证据。
2. 只连接 C960，相机先于小车验证；确认实际模式为 `MJPG / 1280x720 / 30 fps`，不能只记录请求值。
3. wheels elevated，用户在电源旁。当前已审核的安全 ramp 是 `speed_max=260`，运行时更新顺序为 `680 -> 580 -> 480 -> 380 -> 280 -> 260`；每个更新必须收到对应的 `APPLIED/APPLIED` ACK。若当前固件不支持该协议或版本不一致，立即停止，不得自行改写数值。
4. 只发送一次短时 `START`，不自动重试；必须记录最终相关的 `STOPPED/STOP`。
5. 保存原始通信、相机模式、ACK、STOP 和资源清理证据；任何异常立即停止并保留失败证据。

**B2 acceptance:** 相机实际模式正确；固件哈希和运行时版本可追溯；每个 ACK 关联正确；未发生未授权地面运动；STOP 确认且资源各清理一次。B2 通过不等于同步 Gate 通过，也不等于可以开始高速运行。

**AGENT STOP:** B2 结束后必须等待 Codex 对原始证据的独立验收和用户对下一次地面采集的全新授权。

### Task B3：同步采集与数据完整性

**Required fixed thresholds:**

- camera/telemetry common coverage `>= 95%`；
- all-frame nearest-neighbor time-difference `p95 <= 33.3 ms`；
- camera and telemetry timestamps monotonic；
- pose/telemetry set non-empty；
- actual camera mode `MJPG / 1280x720 / 30 fps`；
- final STOP status and one-time resource cleanup present。

这些是同步数据门槛，不是模型准确度门槛。若遥测仍接近 10 Hz，导致 p95 或 coverage 不达标，结论为 `FAIL` 或 `INSUFFICIENT_EVIDENCE`，不得靠增加报告文字通过。

**Required verification:**

- agent 运行唯一 run ID 目录；
- agent 不覆盖旧目录；
- agent 生成 `sync_report.json` 后停止；
- Codex 从 raw `telemetry.jsonl`、`pose.jsonl` 和帧索引重新计算 coverage/p95，不只读取 `sync_report.json`。

### Task B4：Calibration/Holdout 数据冻结

第一轮 V1-B campaign 的最小数据量是 **5 条可用 run：3 条 calibration、2 条 holdout**。每条 run 必须覆盖固定赛道中的直道、普通弯和目标高速急弯区域；整个集合必须覆盖至少两个预先声明的输入 profile 或速度区间。若 5 条 run 不能覆盖这些区域，数量增加也不能自动通过，必须记录为 `INSUFFICIENT EVIDENCE` 并重新设计采集范围。

要求：

- calibration 与 holdout 在采集前声明，不按结果重分组；
- holdout 的 `run_id` 和原始哈希在模型拟合前冻结；
- 原始数据保存为只读证据，派生数据放在 `derived/`；
- 不诱导危险丢线；自然出现的丢线、抖动和超时必须保留，若没有失败样本，必须明确写出“丢线分类证据不足”；
- MPU6050 和编码器只有在其数据实际进入模型并通过单位/时间验证时才纳入主证据，否则标记为 exploratory 或不纳入；
- 当前 camera + signed PWM + 已验证遥测优先，不能因为传感器存在就增加采集范围。

**B4 acceptance:** manifest 完整，哈希可重算，calibration/holdout 无重叠，目标域覆盖可见，输入 profile 预先声明，raw 数据未被 fit 脚本修改。

**AGENT STOP:** 数据冻结后停止。Codex 独立验收通过前，任何 agent 不得运行 calibration fit 或读取 holdout 选择参数。

### Task B5：模型拟合与 Holdout 验证

**Required order:**

1. 从 calibration manifest 加载数据，确认 holdout 不在输入集合中。
2. 通过 `V1Identification` 拟合当前 plant/传感器/延迟参数；所有参数使用明确量纲和版本。
3. 通过 `V1ModelRegistry` 保存模型、代码版本、数据哈希、fit 配置和生成时间。
4. 冻结 model registry 后，单独加载 holdout，生成轨迹、姿态、时间、完成/丢线状态预测。
5. 输出 mean/p95/max、失败样本、输入覆盖和不确定性/证据等级；禁止只输出一个综合分数。
6. 在同一冻结模型上重复运行，序列化输出必须一致；任何随机过程必须记录种子。

**Model acceptance:**

- calibration fit 成功且所有参数有限、量纲正确、版本可追溯；
- holdout 未参与 fit、阈值选择或模型版本选择；
- holdout 预测结果可由 Codex 从 raw+model hash 独立重建；
- holdout 误差必须使用 B1 之前冻结的 acceptance profile 判断，不能在看到结果后修改门槛；
- 校准模型必须相对于未校准 nominal model 在预先声明的主要输出上有明确改善，改善幅度和输出维度写入 acceptance profile；
- 如果 holdout 没有丢线样本，只能宣称轨迹/状态预测通过，不能宣称丢线预测能力已验证；
- 不能用模型拟合误差直接替代真机 B/C 性能提升证据。

### Task B6：V1-B 最终决策与 V1-C handoff

只有同时满足以下条件才能写 `TWIN_USABLE`：

1. B2 安全证据通过；
2. B3 同步 Gate 通过；
3. B4 数据冻结通过；
4. B5 holdout 独立重跑通过；
5. 模型适用域、失败样本和未验证项完整记录；
6. Codex 独立复核没有发现数据泄漏、单位错误、旧路径或硬件证据越界。

否则状态必须是 `INSUFFICIENT_EVIDENCE`，并明确缺口。不得用“模型能跑”“测试通过”替代真实校准或 holdout 证据。

V1-B 通过后，V1-C 才能开始设计真实 A/B/C 候选循环：每轮至少两个候选、数字孪生输出排序和淘汰理由、固定测试条件、B/C 重复运行、C 不丢线且比 B 更快。V1-B 不允许另一个 agent 自行开始 V1-C。

---

## 6. 给另一个 agent 的第一阶段目标提示词

下面的提示词用于启动 V1-B，当前只执行 B1 离线准备，不执行任何硬件动作：

```text
你现在执行 Robot Twin AI 项目的 V1-B Task B1：真实校准与 holdout 的离线准备。

正式工作区固定为：
C:\Users\24668\Desktop\stm32小车\数字孪生

你的目标不是做完整 V1-B，也不是做硬件实验。你的唯一目标是把后续真实采集所需的离线数据契约、验证器、preflight 和 acceptance profile 准备好，并在 B1 停止等待 Codex 独立验收。

必须遵守：
1. 先阅读：
   - docs\Robot_Twin_AI_完整计划说明书_v2.7.md
   - docs\agent-context\CURRENT_STATUS.md
   - docs\superpowers\plans\2026-08-05-v1-b-real-calibration-holdout.md
   - 现有 simulation\digital_twin\v1_twin\ 和 tools\camera_toolchain\ 接口。
2. 复用现有 V1Identification、V1ModelRegistry、V1 calibration-set、capture 和 validator；只有现有接口不能表达明确约束时，才添加最小模块。
3. 建立并测试 V1-B manifest、run ID、原始文件哈希、calibration/holdout 隔离、单位和时间戳校验。
4. 建立第一轮 campaign 的 acceptance profile：至少两个预先声明的输入 profile/速度区间，覆盖直道、普通弯和目标高速急弯；把同步门槛和模型门槛写死在 profile 中，禁止采集后改门槛。
5. 为缺失 run ID、重复 ID、calibration/holdout 重叠、非单调时间、单位混用、缺少固件哈希、覆盖旧目录等情况添加离线测试。
6. preflight 只能做导入、--help、语法、路径和 fake 数据检查；不得打开摄像头、socket、串口、ST-Link，不得发送 START/STOP，不得烧录、复位或运行小车。
7. 不修改 STM32 固件源码、控制算法、通信协议、安全停机逻辑、PCB、UI、MCP、第二台机器人。
8. 不把 synthetic 或 fake 测试写成真实校准证据，不把状态写成 READY 或 TWIN_USABLE。

至少运行并记录：
py -3.11 -m pytest -q simulation\digital_twin\tests
py -3.11 -m compileall -q simulation\digital_twin tools

提交 handoff 时必须包含：
- 实际修改/新增文件；
- 每条命令和退出码；
- VERIFIED / INFERENCE / INSUFFICIENT EVIDENCE 分栏；
- 明确写“未连接、未烧录、未复位、未发送 START/STOP”；
- 未完成项及其原因；
- 下一接口是 B2，不得自行执行 B2。

完成 handoff 后立即停止，等待 Codex 独立验收。不要继续推进硬件 Gate。
```

---

## 7. 每次 handoff 的固定格式

agent 不得只回复“完成”或“测试通过”，必须提供：

```text
Task/Gate:
Status: PASS / FAIL / INSUFFICIENT_EVIDENCE

Changed files:
- list each changed path and the reason it changed; write `none` when no file changed

Commands and results:
- list each command, exit code and relevant result; write `none` only when no command was run

VERIFIED:
- list claims supported by current evidence; write `none` when no claim is verified

INFERENCE:
- list reasonable but unproven inferences; write `none` when no inference is made

INSUFFICIENT EVIDENCE:
- list missing evidence; write `none` only when no evidence gap remains

Hardware actions:
- connected / flashed / reset / START / STOP / motion: exact answer

Data evidence:
- list run IDs, hashes and raw report paths; write `none` for an offline-only task

Blocked next interface:
- write the exact next Gate and the reason it is blocked
```

Codex 的独立验收回复必须单独列出：

1. 是否重跑了关键命令；
2. 是否从原始数据重算了关键指标；
3. 是否发现数据泄漏、单位问题、路径问题或证据越界；
4. 通过、拒绝或证据不足的具体原因；
5. 是否允许进入下一 Gate。

---

## 8. 终止条件

以下任一情况出现，立即停止当前任务并将状态写为 `INSUFFICIENT_EVIDENCE`，不得用更多运行次数掩盖：

- 相机实际分辨率、FourCC 或 FPS 与记录不一致；
- 同步 coverage 或 p95 不达门槛；
- STOP 未确认或资源未清理；
- 固件哈希、参数 profile、赛道版本或 run ID 不可追溯；
- calibration/holdout 有任何重叠；
- 拟合脚本读取 holdout；
- holdout 门槛在看到结果后被修改；
- 真实数据和 synthetic 数据无法区分；
- 需要人工替 agent 修改候选代码、参数或 PCB 才能继续；
- agent 试图在未授权情况下访问任何硬件。

该终止不是项目失败，而是防止错误证据进入下一轮。修复后必须从最近一个被拒绝的 Gate 重新开始，并保留原始失败记录。
