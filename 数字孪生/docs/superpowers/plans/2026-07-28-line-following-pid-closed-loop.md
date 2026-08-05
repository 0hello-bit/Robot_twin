# 巡线 PID 自主优化闭环 - V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在固定赛道上完成一次可回滚、可复现、以巡线误差优先的 PID 参数自动优化闭环。

**Architecture:** STM32 保持实时巡线并只接受受限运行时参数包；电脑端通过现有 ESP TCP 遥测桥实现双向命令、数据记录和活动编排；新 v1_twin 数字孪生模块负责候选参数预筛选与置信度（通过 G1-G8 可信门后启用）。优化器产生有限候选，AI 只调用这些确定性工具和生成依据报告，不直接输出 PWM、修改源码或触发烧录。

**Tech Stack:** STM32F103C8 / Keil C，ESP-01S TCP，Python 3.7+，现有 `simulation/digital_twin`，asyncio WebSocket/TCP bridge，React/TypeScript/Vite。

## Global Constraints

- 首版仅优化巡线控制的 `Kp`、`Ki`、`Kd` 和允许速度上限；不实现轮速 PID。
- 固定使用用户现有赛道；每活动最多 12 个候选、每参数包最多 5 次运行。
- 接受候选必须满足：完成率不低于基线、平均误差降低至少 15%、最大误差和出线次数不增加、平均完成时间缩短至少 5%、5 次有效运行均无安全停止。
- 自动模式必须由固件强制参数范围、单次变化范围、通信超时、连续出线、运行超时和人工急停保护。
- 参数部署是运行时命令；禁止通过 `KeilBridge.build_flash` 进行自动改源码或烧录。
- 当前工作区没有 `.git`；执行期间不得擅自 `git init`。每个任务改动后在任务报告列出文件和测试结果，未来进入 Git 仓库后再按任务粒度提交。

---

## Planned File Structure

| 路径 | 责任 |
|---|---|
| `程序/3. 麦轮巡线小车/User/twin_control_protocol.h` | 运行时参数、启动、停止、基线恢复命令与确认帧的 C 数据结构、范围和函数声明。 |
| `程序/3. 麦轮巡线小车/User/twin_control_protocol.c` | 无动态内存的命令解析、校验、参数暂存/应用、确认编码和超时状态机。 |
| `程序/3. 麦轮巡线小车/User/main.c` | 将现有宏常量替换为受保护的运行时参数，解析 ESP 的 `+IPD` 负载，发送扩展遥测和运行结果。 |
| `程序/3. 麦轮巡线小车/project.uvprojx` | 把新增 `twin_control_protocol.c` 纳入实际巡线目标。 |
| `simulation/digital_twin/real_world/runtime_protocol.py` | PC 端参数包、ACK、运行控制和扩展遥测的严格编解码与验证。 |
| `simulation/digital_twin/real_world/campaign_store.py` | 活动、运行、候选、遥测索引和不可变结果的原子持久化。 |
| `simulation/digital_twin/analysis/campaign_metrics.py` | 从原始遥测计算误差、出线、完成时间和接受判定。 |
| `simulation/digital_twin/web_showcase/live_wifi_bridge.py` | 在既有 TCP 接收循环中加入受队列保护的下行命令和 `campaign_*` WebSocket 命令。 |
| `simulation/digital_twin/web_showcase/product_store.py` | 为活动报告增加稳定的保存和查询入口。 |
| `simulation/digital_twin/web_showcase/src/product/App.tsx` | 展示活动状态、候选理由、指标、回滚原因和人工停止入口。 |
| `simulation/digital_twin/tests/test_runtime_protocol.py` | 协议的边界、校验、未知字段和确认测试。 |
| `simulation/digital_twin/tests/test_campaign_metrics.py` | 量化指标和严格接受门槛测试。 |
| `simulation/digital_twin/web_showcase/test_live_wifi_mock.py` | 扩展为验证下行命令只在已确认连接中发送、断线即拒绝。 |
| `simulation/digital_twin/v1_twin/v1_twin_schema.py` | 所有数据结构 (V1Pose, V1SyncFrame, etc.) |
| `simulation/digital_twin/v1_twin/v1_twin_errors.py` | 领域错误类型 |
| `simulation/digital_twin/v1_twin/v1_twin_isolation.py` | 旧模型隔离检查器 |
| `simulation/digital_twin/v1_twin/v1_twin_camera.py` | CameraSource 抽象和实现 |
| `simulation/digital_twin/v1_twin/v1_twin_calibration.py` | 相机标定 + Homography |
| `simulation/digital_twin/v1_twin/v1_twin_track_map.py` | 赛道地图 (mask/centerline/width) |
| `simulation/digital_twin/v1_twin/v1_twin_pose_tracker.py` | AprilTag 位姿跟踪 |
| `simulation/digital_twin/v1_twin/v1_twin_sync.py` | 时间同步器 |
| `simulation/digital_twin/v1_twin/v1_twin_dataset.py` | 同步数据集 |
| `simulation/digital_twin/v1_twin/v1_twin_controller.py` | 固件等价控制器 |
| `simulation/digital_twin/v1_twin/v1_twin_virtual_sensor.py` | 虚拟四路传感器 |
| `simulation/digital_twin/v1_twin/v1_twin_plant.py` | 车辆行为模型 |
| `simulation/digital_twin/v1_twin/v1_twin_identification.py` | 系统辨识 |
| `simulation/digital_twin/v1_twin/v1_twin_calibration_set.py` | 校准/holdout 分离 |
| `simulation/digital_twin/v1_twin/v1_twin_model_registry.py` | 模型版本注册 |
| `simulation/digital_twin/v1_twin/v1_twin_validator.py` | 综合验证器 (G1-G8) |
| `simulation/digital_twin/v1_twin/v1_twin_runner.py` | 孪生运行器 |
| `simulation/digital_twin/v1_twin/v1_twin_candidate_generator.py` | 候选生成器 |
| `simulation/digital_twin/v1_twin/v1_twin_ranker.py` | 候选排序器 |
| `simulation/digital_twin/v1_twin/v1_twin_orchestrator.py` | Campaign 编排器（FakeTransport 可测试）|
| `simulation/digital_twin/tests/test_v1_twin_schema.py` | schema 序列化测试 |
| `simulation/digital_twin/tests/test_v1_twin_isolation.py` | 旧模型隔离检查测试 |
| `simulation/digital_twin/tests/test_v1_twin_camera.py` | CameraSource 抽象测试 |
| `simulation/digital_twin/tests/test_v1_twin_calibration.py` | Homography 标定测试 |
| `simulation/digital_twin/tests/test_v1_twin_track_map.py` | 赛道地图测试 |
| `simulation/digital_twin/tests/test_v1_twin_pose_tracker.py` | 位姿检测测试 |
| `simulation/digital_twin/tests/test_v1_twin_sync.py` | 时间同步测试 |
| `simulation/digital_twin/tests/test_v1_twin_dataset.py` | 数据集不可变测试 |
| `simulation/digital_twin/tests/test_v1_twin_controller.py` | PID 固件一致性测试 |
| `simulation/digital_twin/tests/test_v1_twin_virtual_sensor.py` | 虚拟传感器测试 |
| `simulation/digital_twin/tests/test_v1_twin_plant.py` | 车辆模型测试 |
| `simulation/digital_twin/tests/test_v1_twin_identification.py` | 系统辨识测试 |
| `simulation/digital_twin/tests/test_v1_twin_calibration_set.py` | 校准集隔离测试 |
| `simulation/digital_twin/tests/test_v1_twin_model_registry.py` | 模型注册测试 |
| `simulation/digital_twin/tests/test_v1_twin_validator.py` | G1-G8 验证门测试 |
| `simulation/digital_twin/tests/test_v1_twin_candidate_generator.py` | 候选生成边界测试 |
| `simulation/digital_twin/tests/test_v1_twin_orchestrator.py` | 编排器 FakeTransport 测试 |
| `docs/runbooks/line-following-pid-campaign.md` | 真机活动前检查、人工急停、结果采集和异常处理规程。 |

### Task 1: 建立运行时参数协议与固件安全边界

**Files:**
- Create: `程序/3. 麦轮巡线小车/User/twin_control_protocol.h`
- Create: `程序/3. 麦轮巡线小车/User/twin_control_protocol.c`
- Modify: `程序/3. 麦轮巡线小车/User/main.c:12-266, 309-521`
- Modify: `程序/3. 麦轮巡线小车/project.uvprojx`
- Create: `simulation/digital_twin/tests/test_runtime_protocol.py`

**Interfaces:**
- Consumes: ASCII 行协议 `P,<campaign_id>,<version>,<kp>,<ki>,<kd>,<speed_max>,<checksum>`、`R,<campaign_id>,<run_id>,START>`、`R,<campaign_id>,<run_id>,STOP>`、`R,<campaign_id>,<run_id>,RESTORE_BASELINE>`。
- Produces: `A,<campaign_id>,<version>,APPLIED|REJECTED,<reason>,<checksum>` 和扩展状态帧 `S,<campaign_id>,<run_id>,<state>,<reason>,<tick_ms>`。
- Defines: `TwinControlParams`、`TwinControlResult`、`twin_control_receive_byte()`、`twin_control_apply_pending()`、`twin_control_encode_ack()`。

- [ ] **Step 1: 写出 PC 端协议失败测试**

在 `test_runtime_protocol.py` 中先写入以下测试，覆盖首版命令不可变字段和拒绝路径：

```python
def test_parameter_packet_round_trip_and_checksum():
    packet = ParameterCommand("camp-001", 3, 35.0, 0.0, 10.0, 680)
    assert parse_command(packet.encode()) == packet

def test_parameter_packet_rejects_out_of_range_speed():
    with pytest.raises(ProtocolError, match="speed_max"):
        ParameterCommand("camp-001", 3, 35.0, 0.0, 10.0, 900).encode()

def test_ack_requires_matching_campaign_and_version():
    ack = parse_ack("A,camp-001,3,APPLIED,OK,1F\n")
    assert ack.campaign_id == "camp-001"
    assert ack.version == 3
```

- [ ] **Step 2: 运行协议测试，确认它在模块不存在时失败**

Run: `python -m pytest simulation/digital_twin/tests/test_runtime_protocol.py -v`

Expected: FAIL，错误指出 `runtime_protocol` 尚不存在。

- [ ] **Step 3: 实现纯 Python 协议参考实现**

创建 `simulation/digital_twin/real_world/runtime_protocol.py`。使用 `@dataclass(frozen=True)` 定义 `ParameterCommand`、`RunCommand`、`ParameterAck`、`RunStatus`；校验 `campaign_id` 为 ASCII 字母数字加 `-`、版本为正整数、`kp/kd` 为有限数、`ki >= 0`、速度在固件声明的范围内。校验和为从首字节到最后一个逗号前的 ASCII 字节 XOR 两位十六进制值。

```python
def xor_checksum(body: str) -> str:
    value = 0
    for byte in body.encode("ascii"):
        value ^= byte
    return f"{value:02X}"

def frame(body: str) -> str:
    return f"{body},{xor_checksum(body)}\n"
```

- [ ] **Step 4: 运行协议测试，确认 Python 参考实现通过**

Run: `python -m pytest simulation/digital_twin/tests/test_runtime_protocol.py -v`

Expected: PASS。

- [ ] **Step 5: 实现与参考实现一致的 C 协议模块**

在 `twin_control_protocol.h` 声明固定长度字段和安全范围；在 `.c` 中采用逐字节行缓冲，拒绝超长行、字段数不正确、校验和错误、活动或版本非法、浮点数非有限、参数越界和单次速度变化越界。解析成功只设置 `pending_params`；`twin_control_apply_pending()` 必须在主循环安全点原子替换当前参数并返回 APPLIED ACK。STOP、超时和 RESTORE_BASELINE 必须将四路电机目标置零并恢复基线参数。

```c
typedef struct {
    float kp;
    float ki;
    float kd;
    int16_t speed_max;
    uint32_t version;
    char campaign_id[17];
} TwinControlParams;

bool twin_control_apply_pending(TwinControlParams *active,
                                const TwinControlParams *baseline,
                                TwinControlResult *result);
```

- [ ] **Step 6: 将巡线控制改为读取活动参数且保留安全停机**

在 `main.c` 中保留当前宏值作为 `baseline_params` 初始值；控制循环改为读取 `active_params.kp`、`active_params.ki`、`active_params.kd` 和 `active_params.speed_max`。每轮调用 ESP 接收解析、`twin_control_apply_pending()` 和安全状态检查。不要调用 `KeilBridge`，不要从 PC 触发编译或烧录。

- [ ] **Step 7: 在 Keil 工程中加入新模块并进行构建验证**

把 `twin_control_protocol.c` 加入 `project.uvprojx` 的实际巡线 Target；使用 Keil skill 先列出 Target，再仅构建该 Target。构建成功要求 `0 Error(s)`；不执行下载。

Run: `python C:\Users\24668\.codex\skills\keil\scripts\keil_project.py targets --project "C:\Users\24668\Desktop\stm32小车\程序\3. 麦轮巡线小车\project.uvprojx" --json`

Expected: 返回实际巡线 Target 名称；再用该名称执行构建，结果 `errors=0`。

- [ ] **Step 8: 记录任务检查点**

在任务报告中列出新增 C 模块、Keil Target、构建日志路径、Python 协议测试结果和未进行烧录的事实。

### Task 2: 扩展双向遥测与电脑端可靠传输

**Files:**
- Modify: `程序/3. 麦轮巡线小车/User/main.c:87-218, 331-521`
- Modify: `simulation/digital_twin/real_world/telemetry_protocol.py`
- Modify: `simulation/digital_twin/real_world/data_logger.py`
- Modify: `simulation/digital_twin/web_showcase/live_wifi_bridge.py:313-517, 1650-1753`
- Modify: `simulation/digital_twin/web_showcase/test_live_wifi_mock.py`
- Test: `simulation/digital_twin/tests/test_runtime_protocol.py`

**Interfaces:**
- Consumes: Task 1 的 `P`、`R` 命令与 ACK；既有 `AA 55` 二进制遥测帧。
- Produces: 含 `campaign_id`、`run_id`、运行状态、终止原因、参数版本的 PC 端 `CampaignTelemetry`。
- Defines: `LiveWifiBridge.send_runtime_command(command: str) -> Awaitable[None]` 和 `LiveWifiBridge.wait_for_ack(campaign_id: str, version: int, timeout_s: float) -> ParameterAck`。

- [ ] **Step 1: 写出断线与 ACK 匹配失败测试**

在 `test_live_wifi_mock.py` 加入：未连接时 `send_runtime_command()` 抛出 `RuntimeCommandError("wifi not connected")`；收到活动 ID 或版本不匹配的 ACK 时 `wait_for_ack()` 超时；匹配 ACK 时返回 `ParameterAck`。

- [ ] **Step 2: 运行桥接测试，确认新增方法尚不存在**

Run: `python -m pytest simulation/digital_twin/web_showcase/test_live_wifi_mock.py simulation/digital_twin/tests/test_runtime_protocol.py -v`

Expected: FAIL，指出 `send_runtime_command` 或 `wait_for_ack` 不存在。

- [ ] **Step 3: 让 ESP 固件解析 TCP 下行负载并发送可区分的运行状态**

扩展 `ESP_ProcessByte()` 以识别 `+IPD,<id>,<length>:` 前缀，并将随后精确 `length` 字节逐字节送入 `twin_control_receive_byte()`；不得把 AT 状态行误当控制命令。遥测保留既有 24 字节数据帧，并新增 ASCII `S`、`A` 状态/确认帧经同一 TCP client 发送。每次参数应用、拒绝、停止、恢复基线、出线或运行超时必须发送一次状态。

- [ ] **Step 4: 实现 PC 端双向发送队列和 ACK 注册表**

在 `LiveWifiBridge` 保存当前 TCP `StreamWriter`、`asyncio.Lock` 和以 `(campaign_id, version)` 为键的 `Future` 注册表。`_wifi_loop()` 连接后设置 writer，断线前清空 writer 并以连接错误完成所有等待中的 Future；发送路径必须 `writer.write(command.encode("ascii"))` 后 `await writer.drain()`。将来自 STM32 的 ASCII 状态帧交给 `runtime_protocol.parse_ack()` / `parse_status()`，二进制遥测继续走现有 `FrameParser`。

- [ ] **Step 5: 扩展通用遥测模型和记录器**

在 `telemetry_protocol.py` 新增 `CampaignTelemetry`，字段为 `campaign_id`、`run_id`、`parameter_version`、`termination_reason` 和既有传感器/误差/PWM/tick。`RealDataLogger.start()` 接收活动、运行和参数版本，`save()` 将这些字段与原始帧一起写入 JSON；旧 JSON 文件仍可加载，缺少新字段时标记为 `legacy`。

- [ ] **Step 6: 运行桥接、协议和既有模拟遥测测试**

Run: `python -m pytest simulation/digital_twin/web_showcase/test_live_wifi_mock.py simulation/digital_twin/tests/test_runtime_protocol.py simulation/digital_twin/web_showcase/test_product_store.py -v`

Expected: PASS；mock 遥测回归测试不依赖真实 ESP。

- [ ] **Step 7: 记录任务检查点**

记录协议版本、ACK 超时值、向下兼容策略、所有模拟测试结果，以及没有向真实小车发送命令的事实。

### Task 3: 建立活动存储、指标与严格接受规则

**Files:**
- Create: `simulation/digital_twin/real_world/campaign_store.py`
- Create: `simulation/digital_twin/analysis/campaign_metrics.py`
- Create: `simulation/digital_twin/tests/test_campaign_metrics.py`
- Modify: `simulation/digital_twin/web_showcase/product_store.py:269-386`

**Interfaces:**
- Consumes: Task 2 的单次运行 JSON 及 `ParameterCommand`。
- Produces: `Campaign`, `RunSummary`, `CandidateDecision` 和稳定的活动报告 JSON。
- Defines: `CampaignStore.create_campaign()`, `CampaignStore.save_run()`, `CampaignStore.save_decision()`，`evaluate_candidate(baseline_runs, candidate_runs) -> CandidateDecision`。

- [ ] **Step 1: 写出接受和拒绝的指标测试**

```python
def test_candidate_is_accepted_only_when_all_thresholds_pass():
    baseline = five_runs(rms=10, maximum=20, loss=0, duration=40, completed=True)
    candidate = five_runs(rms=8.0, maximum=20, loss=0, duration=37.5, completed=True)
    assert evaluate_candidate(baseline, candidate).status == "accepted"

def test_faster_candidate_is_rejected_when_error_does_not_improve_15_percent():
    baseline = five_runs(rms=10, maximum=20, loss=0, duration=40, completed=True)
    candidate = five_runs(rms=9.0, maximum=20, loss=0, duration=35, completed=True)
    assert evaluate_candidate(baseline, candidate).reason == "rms_error_threshold"
```

- [ ] **Step 2: 运行指标测试，确认模块尚不存在**

Run: `python -m pytest simulation/digital_twin/tests/test_campaign_metrics.py -v`

Expected: FAIL，指出 `campaign_metrics` 不存在。

- [ ] **Step 3: 实现确定性指标计算和接受判定**

`campaign_metrics.py` 必须从原始误差序列计算 RMS、最大绝对误差、全零传感器帧导致的出线次数、完成时间、完成率和安全停止计数。接受判断按全体 5 次有效候选运行的聚合值进行，按以下固定顺序返回首个拒绝原因：`insufficient_valid_runs`、`completion_rate`、`rms_error_threshold`、`max_error`、`track_loss`、`duration`、`safety_stop`。

```python
def evaluate_candidate(baseline_runs: Sequence[RunSummary],
                       candidate_runs: Sequence[RunSummary]) -> CandidateDecision:
    ...
```

- [ ] **Step 4: 实现不可变活动存储**

`CampaignStore` 以 `data/campaigns/<campaign_id>/` 保存 `campaign.json`、每个 `runs/<run_id>.json`、`candidates/<version>.json` 和 `report.json`。使用临时文件加 `os.replace()` 原子写入；拒绝的候选和失败运行只能新增状态，不能覆盖原始遥测。`ProductStore` 添加仅委托 `CampaignStore` 的列表、读取和报告保存方法。

- [ ] **Step 5: 运行指标与存储测试**

Run: `python -m pytest simulation/digital_twin/tests/test_campaign_metrics.py simulation/digital_twin/web_showcase/test_product_store.py -v`

Expected: PASS；写入后的运行 JSON 能重新读取且拒绝原因保持不变。

- [ ] **Step 6: 记录任务检查点**

记录数据目录结构、指标单位、接受阈值及 5 次有效运行规则。

### Phase A: 计划同步 (Task 4B-D)

**状态: 已完成** — 本文件与 spec/design 的 Task 4 章节已更新。

**修改内容:**
- 废弃旧 Task 4 "复用数字孪生做候选预筛选"（含 `sim_candidate_filter.py`、`campaign_optimizer.py`）
- 文件结构新增 `simulation/digital_twin/v1_twin/` 命名空间全部文件
- 替换为 Phase B (4B-0~8) + Phase C (4C) 子任务序列

---

### Phase B: Task 4B — 最小可信二维数字孪生 (4B-0 → 4B-8)

所有新代码放入 `simulation/digital_twin/v1_twin/`，测试放在 `simulation/digital_twin/tests/`，文件名前缀 `v1_twin_` / `test_v1_twin_`。

#### 4B-0: 数据契约、测试夹具与旧模型隔离

| 字段 | 值 |
|------|-----|
| **文件** | `v1_twin_schema.py`, `v1_twin_errors.py`, `v1_twin_isolation.py`, `test_v1_twin_schema.py`, `test_v1_twin_isolation.py` |
| **输出** | V1Pose, V1TelemetryFrame, V1SyncFrame, V1SensorModelConfig, V1TrackMap, V1CalibrationSet, V1HoldoutSet, V1ModelVersion |
| **Gate** | `pytest test_v1_twin_schema.py -v` + `test_v1_twin_isolation.py -v` 全部通过 |
| **硬件** | ⚪ 纯离线 |

#### 4B-1: 摄像头实时输入 Gate 0

| 字段 | 值 |
|------|-----|
| **文件** | `v1_twin_camera.py`, `test_v1_twin_camera.py` |
| **输出** | CameraSource 抽象 + 连续 10 分钟验证脚本 |
| **Gate** | fps ≥ 20, drop ≤ 5%, 时间戳严格单调 |
| **硬件** | 🔴 需要摄像头实时流 |

#### 4B-2: 相机标定与赛道坐标

| 字段 | 值 |
|------|-----|
| **文件** | `v1_twin_calibration.py`, `v1_twin_track_map.py`, `test_v1_twin_calibration.py`, `test_v1_twin_track_map.py` |
| **输出** | CameraCalibration, HomographyTransform, TrackMap |
| **Gate** | 重投影误差 p95 ≤ max(2 pixel, 5% 黑线宽度像素) |
| **硬件** | 🔴 需要摄像头+标定板 |

#### 4B-3: 车顶标记二维位姿跟踪

| 字段 | 值 |
|------|-----|
| **文件** | `v1_twin_pose_tracker.py`, `test_v1_twin_pose_tracker.py` |
| **输出** | PoseTracker.track(frame) → V1Pose |
| **Gate** | 有效率 ≥ 95%, x/y p95 ≤ 5% 黑线宽度, yaw p95 ≤ 2° |
| **硬件** | 🔴 需要摄像头+车顶标记 |

#### 4B-4: 相机与遥测时间同步

| 字段 | 值 |
|------|-----|
| **文件** | `v1_twin_sync.py`, `v1_twin_dataset.py`, `test_v1_twin_sync.py`, `test_v1_twin_dataset.py` |
| **输出** | ClockSync, SynchronizedRunDataset |
| **Gate** | 匹配覆盖率 ≥ 95%, 时间差 ≤ max(1帧周期) |
| **硬件** | 🔴 需要一次短距离真车运行 |

#### 4B-5: 固件等价控制器与虚拟四路传感器

| 字段 | 值 |
|------|-----|
| **文件** | `v1_twin_controller.py`, `v1_twin_virtual_sensor.py`, `test_v1_twin_controller.py`, `test_v1_twin_virtual_sensor.py` |
| **输出** | V1Controller (PID 公式与固件逐行一致), V1VirtualSensor |
| **Gate** | PID 多组合输出与固件 C 代码完全一致 |
| **硬件** | ⚪ 纯离线 |

#### 4B-6: 四 PWM→vx/vy/omega 车辆行为模型

| 字段 | 值 |
|------|-----|
| **文件** | `v1_twin_plant.py`, `v1_twin_identification.py`, `test_v1_twin_plant.py`, `test_v1_twin_identification.py` |
| **输出** | V1Plant, 系统辨识, 数据覆盖矩阵 |
| **Gate** | 合成已知参数恢复, 参数可辨识性诊断 |
| **硬件** | 🔶 混合: 需真车激励数据采集 + 离线拟合 |

#### 4B-7: 校准集/holdout 隔离、模型拟合与失效保护

| 字段 | 值 |
|------|-----|
| **文件** | `v1_twin_calibration_set.py`, `v1_twin_model_registry.py`, `test_v1_twin_calibration_set.py`, `test_v1_twin_model_registry.py` |
| **输出** | 不可变 calibration_run_ids, 冻结模型 + 哈希, 空 holdout 注册表 |
| **Gate** | run_id 交集为空硬检查, 冻结后修改检测 |
| **硬件** | ⚪ 纯离线（消费 4B-6 已采集数据）|

#### 4B-8: 模型未见安全 PID 组验证与 READY 门

| 字段 | 值 |
|------|-----|
| **文件** | `v1_twin_validator.py`, `v1_twin_runner.py`, `test_v1_twin_validator.py` |
| **输出** | VALIDATION_REPORT (G1-G8), READY / NOT READY |
| **Gate** | G1-G8 全部 PASS |
| **硬件** | 🔴 需要真车运行 ≥5 个安全 PID 组验证数据 |

> **硬性禁止跳转:** 4B-8 未 READY → 不得开始 Task 4C。

---

### Phase C: Task 4C — 受固件范围/步进限制的确定性候选生成

| 字段 | 值 |
|------|-----|
| **前置条件** | 🔴 **4B-8 READY** |
| **文件** | `v1_twin_candidate_generator.py`, `v1_twin_ranker.py`, `test_v1_twin_candidate_generator.py` |
| **输出** | CandidateGenerator.propose() → list[CandidateProposal] |
| **Gate** | 候选数 ≤ 12, 全部在固件边界内, 去重唯一 |
| **硬件** | ⚪ 纯离线 |

> 旧 `sim_candidate_filter.py` 和 `campaign_optimizer.py`（旧版本）不再实现。

### Task 5A: 纯离线、FakeTransport 的可回滚 Campaign Orchestrator

**前置条件:** ✅ Task 3 (CampaignStore, Metrics), ✅ Task 4C (候选生成)

**Files:**
- Create: `simulation/digital_twin/v1_twin/v1_twin_orchestrator.py`
- Create: `simulation/digital_twin/tests/test_v1_twin_orchestrator.py`

**Interfaces:**
- Consumes: `CampaignStore`、`CampaignMetrics`、`CandidateGenerator`、`V1TwinRunner`。
- Produces: `V1CampaignOrchestrator` — 状态序列 + 回滚 + 报告。
- Defines: 状态序列 `baseline -> calibrating -> simulating -> deploying -> running -> evaluating -> accepted|rejected|stopped|complete`。

- [ ] **Step 1: 写出成功、通信超时和出线回滚测试**

使用 `FakeTransport`（记录发送命令并按测试注入 ACK/状态）写入以下断言：成功候选被接受；ACK 超时后发送 RESTORE_BASELINE 并进入 `stopped`；任何 `line_lost` 或 `safety_stop` 状态都发送 STOP 和 RESTORE_BASELINE，且不会部署下一候选。

```python
async def test_ack_timeout_restores_baseline():
    orchestrator = make_orchestrator(transport=FakeTransport(ack=None))
    await orchestrator.start()
    assert transport.sent_types == ["P", "R:RESTORE_BASELINE"]
    assert orchestrator.status().state == "stopped"
```

- [ ] **Step 2: 运行状态机测试，确认模块尚不存在**

Run: `python -m pytest simulation/digital_twin/tests/test_v1_twin_orchestrator.py -v`

Expected: FAIL，指出 `v1_twin_orchestrator` 不存在。

- [ ] **Step 3: 实现有限状态机和单候选部署锁**

每次只允许一个 `deployed` 参数版本。`start()` 先创建活动并要求 5 次基线结果；基线完整后调用候选生成、模型筛选和单候选部署。部署前存储候选；ACK 成功后才发送 START；每次运行结束保存原始数据和 RunSummary；5 次候选结果齐全后调用 `evaluate_candidate()`。接受候选时更新报告；拒绝、超时、断线、出线或人工停止时先 STOP 再 RESTORE_BASELINE，再持久化拒绝理由。

- [ ] **Step 4: 运行编排器测试**

Run: `python -m pytest simulation/digital_twin/tests/test_v1_twin_orchestrator.py simulation/digital_twin/tests/test_campaign_metrics.py simulation/digital_twin/tests/test_runtime_protocol.py -v`

Expected: PASS；FakeTransport 测试验证成功、拒绝和回滚路径。

- [ ] **Step 5: 记录任务检查点**

记录状态转换表、超时值、回滚命令顺序和每条端到端测试证据。

### Task 5B: 固定赛道真机闭环活动

**前置条件:**
- 🔴 **4B-8 READY**
- ✅ Task 4C PASS
- ✅ Task 5A PASS
- 🔴 **用户本次明确硬件授权**（旧授权不可沿用，用户必须当次确认赛道净空、急停可用、供电正常）

**Files (允许新增):**
- `data/v1_twin/campaigns/<campaign_id>/...` — 不可变真实运行数据；不得覆盖已有 raw run 数据
- `.embeddedskills/build/v1_task5b/...` — 活动报告和日志

**硬件需求:**
- 🔴 **用户必须在场。** 赛道净空、急停可用、一次一个动作。每次部署需用户逐次授权。
- 安全规则见纲领 §13 硬件安全矩阵 — Track Run 行。

**Task 完成 gate:**
- 一个真机 campaign 按 exact-5 规则完整结束；每个候选均有接受或拒绝结论；
- 任何拒绝、超时、出线或人工停止均留下完整证据并恢复基线；
- 全部候选被拒绝时，只能证明编排和回滚闭环完成，**不能宣称 V1 已找到更优 PID**。

**V1 成功 gate:**
- 至少一个候选经真机 exact-5 验证后被接受，且满足：RMS error 下降 ≥15%；或在 RMS error 不退化、最大误差不退化且无安全事件时，完成时间缩短 ≥5%。
- 若无候选满足，Task 5B 可标 `COMPLETE / NO_ACCEPTED_CANDIDATE`，但 **V1 不得标记完成**；应回到 4C 生成下一批候选，**不得降低门槛**。

- [ ] **Step 1: 真机活动前安全检查**

按纲领 §13 硬件安全矩阵 Track Run 行执行：赛道净空、急停可用、供电正常。通过 §16 模板 E 向用户当次确认并获得明确硬件授权后才允许开始。

- [ ] **Step 2: 基线采集**

以 baseline PID 在固定赛道完成恰好 5 次有效运行 (exact-5)，保存原始遥测至 `data/v1_twin/campaigns/<campaign_id>/`。

- [ ] **Step 3: 候选生成与模型预筛选**

调用 Task 4C 的 `CandidateGenerator` + `V1TwinRunner` 预筛选，输出不超过 12 个候选的排序列表。

- [ ] **Step 4: 部署与真车运行**

每次部署单个候选需用户逐次授权；ACK 成功后发送 START；每参数包最多 5 次有效运行；任何出线、超时、安全停止或人工停止立即 STOP + RESTORE_BASELINE 并保留完整证据。

- [ ] **Step 5: 评价与接受/回滚**

按 Task 3 `evaluate_candidate()` 的 exact-5 规则判定接受或拒绝；拒绝、超时、出线或人工停止均持久化拒绝理由并恢复基线。全部候选处理完后生成活动报告。

- [ ] **Step 6: 记录任务检查点**

记录活动 ID、候选列表、每候选接受/拒绝结论、证据路径，以及"V1 是否标记完成"的判定（必须符合上述 V1 成功 gate）。

### Task 6: 交付活动界面、报告与真机运行规程

**Files:**
- Modify: `simulation/digital_twin/web_showcase/src/product/App.tsx`
- Modify: `simulation/digital_twin/web_showcase/src/types.ts`
- Modify: `simulation/digital_twin/web_showcase/src/product.css`
- Modify: `simulation/digital_twin/web_showcase/test_product_store.py`
- Create: `docs/runbooks/line-following-pid-campaign.md`

**Interfaces:**
- Consumes: `campaign_status` 和 `campaign_report` WebSocket 消息。
- Produces: 只读活动证据面板与唯一的人工 `campaign_stop` 控件；运行规程。
- Defines: TypeScript `CampaignStatus`、`CandidateDecision`、`CampaignReport`。

- [ ] **Step 1: 写出活动状态序列化和 UI 显示测试**

在 `test_product_store.py` 添加活动报告的保存/读取断言；在 TypeScript 测试或最小组件测试中断言 `accepted` 显示基线与候选的 RMS、完成时间和运行次数，`rejected` 显示首个拒绝理由，`stopped` 显示回滚已完成。

- [ ] **Step 2: 运行现有前端类型检查与产品存储测试，确认新增类型失败**

Run: `npm.cmd run typecheck`（目录 `simulation/digital_twin/web_showcase`）以及 `python -m pytest test_product_store.py -v`（同目录）。

Expected: TypeScript 或 Python 测试失败，指出缺少活动状态字段或存储方法。

- [ ] **Step 3: 实现只读证据面板和停止入口**

在 `App.tsx` 添加活动卡片：显示活动 ID、赛道版本、基线与当前候选、模型置信度、当前状态、运行进度、RMS/最大误差/出线/完成时间、接受或拒绝理由。停止按钮只能发送 `campaign_stop`，显示二次确认文案“停止并恢复基线参数”；不提供任意 PID 数值输入框或烧录按钮。

- [ ] **Step 4: 编写真机运行规程**

`line-following-pid-campaign.md` 必须按顺序列出：赛道净空、人工急停验证、供电记录、基线 5 次、模型置信度检查、候选活动启动、异常即停止、报告导出、人工复核接受结果。明确禁止在活动中改赛道、调传感器高度、换电后混合比较，明确禁止使用 Keil 自动烧录。

- [ ] **Step 5: 执行软件验证**

Run: `npm.cmd run test`（目录 `simulation/digital_twin/web_showcase`）

Run: `python -m pytest simulation/digital_twin/tests/test_runtime_protocol.py simulation/digital_twin/tests/test_campaign_metrics.py simulation/digital_twin/tests/test_v1_twin_candidate_generator.py -v`

Expected: 全部 PASS；没有连接真实 ESP 或小车。

- [ ] **Step 6: 记录任务检查点**

记录软件测试输出、界面截图路径、运行规程路径和“尚未进行真机活动”的状态。

## Spec Coverage Review

- 受限 PID 参数、STM32 确认、停止和回滚：Task 1 和 Task 2。
- 原始遥测、活动/运行/版本证据和持久化：Task 2 和 Task 3。
- 固定赛道、5 次重复、12 个候选和量化接受标准：Task 3 和 Task 5。
- 数字模型校准、置信度和候选预筛选：Phase B (4B-0~8) + Phase C (4C)。
- AI/优化器只编排确定性工具、禁止裸参数或烧录：Phase B/C、Task 5 和 Task 6。
- 人工急停、异常停止、报告和真机规程：Task 1、Task 5 和 Task 6。

## Plan Self-Review

- 已覆盖规格的所有目标、数据、验证和非目标；轮速 PID、自动改代码/烧录和单次成绩均未被纳入任务。
- 计划不含未决占位项或延后实现的步骤。
- 主要接口在产生它们的任务中声明，并在后续任务按相同名称使用。
