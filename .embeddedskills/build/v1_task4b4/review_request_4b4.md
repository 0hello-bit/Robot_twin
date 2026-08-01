# Task 4B-4 问题总结（供审核 agent 复核）

**日期**: 2026-08-01
**作者**: 执行代理
**目的**: 总结 Task 4B-4（相机与遥测时间同步）真机验证中遇到的困难、当前进度与证据，请审核 agent 复核。

---

## 1. 任务目标（纲领 §6e）

实现 PC monotonic 时钟与 MCU tick 的对齐，生成 synchronized run dataset（pose + telemetry 对齐）。
自动验收 gate: 匹配覆盖率 ≥95%、p95 时间差 ≤ max(相机周期 33.3ms, 遥测周期 20ms) = 33.3ms。
真机验证需要一次真车短距离运行（安全防护）。

---

## 2. 已完成部分（软件层，测试全 GREEN）

### 2.1 文件位置

| 模块 | 路径 | 状态 |
|---|---|---|
| **ClockSync**（tick→PC ns 线性映射 + tick 回绕展开 + 批感知拟合） | `simulation/digital_twin/v1_twin/v1_twin_sync.py` | ✅ 完成 |
| **SynchronizedRunDataset**（pose+telemetry 时间戳对齐、覆盖率、p95、不可变） | `simulation/digital_twin/v1_twin/v1_twin_dataset.py` | ✅ 完成 |
| **PoseTracker**（AprilTag 位姿，4B-3 产物，本任务修复时钟） | `simulation/digital_twin/v1_twin/v1_twin_pose_tracker.py` | ✅ 完成 |
| 测试 | `simulation/digital_twin/tests/test_v1_twin_sync.py`、`test_v1_twin_dataset.py` 等 | ✅ 92/92 GREEN |
| 同步采集脚本 | `.embeddedskills/build/v1_task4b4/capture_sync_run.py` | ✅ 完成 |
| 采集数据 | `.embeddedskills/build/v1_task4b4/raw_telemetry.json`、`raw_poses.json`、`sync_report.json` | 已保存 |

### 2.2 本任务修复的问题（软件层）

1. **位姿时钟 bug（已修复）**：PoseTracker 默认用 `time.perf_counter_ns()`，与遥测 `time.monotonic_ns()` 是**不同时钟**。本机实测两时钟 **epoch 相差 16.946s** → 位姿/遥测时间错位 → 同步覆盖率 0%。已改为 `time.monotonic_ns()`（V1Pose schema 文档规定 "PC monotonic clock"）。
2. **pwm 负值（已修复）**：固件 `m1-m4` 是 int16 可负（反转时），V1TelemetryFrame schema 要求非负。采集时钳位到 0。
3. **遥测读取时序（已修复）**：原主循环批量读 socket 导致 pc_recv_ns 聚类失真。改为**后台 reader 线程**逐帧打时间戳。
4. **STOP 安全（已修复）**：采集结束用 try/finally 确保总是发送 STOP（第一次 12s 采集因 pwm bug 崩溃，未发 STOP，小车没制动——用户观察到"不制动"）。

### 2.3 软件层测试结果

```
pytest: 92 passed (schema/isolation/camera/calibration/track_map/pose_tracker/sync/dataset)
ClockSync: tick 回绕展开、线性回归、批感知拟合 均 GREEN
SynchronizedRunDataset: 时间戳对齐（非下标）、覆盖率、p95、不可变 均 GREEN
```

---

## 3. 真机验证遇到的困难（核心问题）

### 3.1 问题一：遥测投递被 ESP01S 的 CIPSEND 同步阻塞拖慢

**现象**（证据：10 秒连续读测试 + 采集数据）：
- 遥测 75 帧，MCU tick 从 1141965 → 1143445（**跨度仅 1480ms**），但**墙钟过了 9.72s**。
- PC 接收间隔 ~125ms（中位），tick 间隔恒为 20ms（MCU 侧 50Hz 正常）。
- 即：**20ms 的 tick 需要 ~130ms 墙钟**（20ms 控制循环 + ~110ms CIPSEND 阻塞）。

**根因（固件源码确认）**：
`程序/3. 麦轮巡线小车/User/main.c`
- `Telemetry_Send()`（第 200 行）→ `ESP_SendCIPSEND()`（第 248 行）→ `ESP_DoCIPSENDTransaction()`（第 140 行）是**同步阻塞**的：
  - Phase 1: 等 `'>'` 提示，最多 **CIPSEND_PROMPT_TIMEOUT_MS=200ms**（第 108 行）
  - Phase 2: 发完等 `SEND OK`，最多 **CIPSEND_SENDOK_TIMEOUT_MS=500ms**（第 109 行）
  - 每帧用 `Delay_ms(1)` 轮询 → **每发一帧遥测主循环被阻塞 ~110ms**
- 主循环每 `LOOP_DELAY_MS=5`（第 358 行）迭代，遥测每 `TELEMETRY_INTERVAL_MS=20`（第 361 行）。

**后果**：
- 小车**实际一直在跑**（用户确认能沿线跑、丢线能回），但控制循环被 CIPSEND 阻塞拖慢，tick 不按真实时间推进。
- PC 收到的遥测 pc_recv_ns 反映的是"被阻塞的节奏"，不是真实运行节奏 → **pc_recv_ns 无法可靠映射 tick→PC 时间** → 时钟校准失效。

**修复方向（固件层）**：
1. 遥测改 **fire-and-forget**（发 CIPSEND 后不阻塞等 SEND OK）——遥测帧独立、丢帧不影响解析（协议设计本就容忍）。
2. 或降低遥测频率（如每 100ms 一帧）减少阻塞次数。
3. 或缩短 CIPSEND prompt/SEND OK 超时。

### 3.2 问题二：小车运行范围超出相机视野

**现象**：小车沿线跑动时会跑出手机（DroidCam）镜头视野，标签检测不到（一次 12s 采集只采到 2 帧位姿）。
用户可手动保持标签在视野内，但需配合。

**缓解**：采集窗口内用户手动保持标签可见；或重摆相机 + 重建单应（4B-2 的单应依赖相机位置，移动需重建）。

### 3.3 问题三：真机同步覆盖率只有 50%（未达标）

**现象**：修复时钟 bug + reader 线程后重采 6s：位姿 165 帧、遥测 46 帧，**覆盖率 50.3%**（需 ≥95%）、p95 29.7ms ≤ 33.3ms ✅。

**原因**（两层）：
1. **遥测只覆盖 900ms 的 tick**（CIPSEND 阻塞导致 tick 不推进），而位姿采了 5.5s → 大部分位姿没有对应遥测。
2. **ClockSync 斜率失真**（~6.5ms/tick-ms，期望 ~1ms）：因为 pc_recv_ns 反映被阻塞的节奏。已实现 `fit_batched`（按接收批次均值拟合）缓解，但根因是问题一。

**结论**：问题一是核心阻塞——需固件层修复遥测转发阻塞后，pc_recv_ns 才可靠，覆盖率/时钟才能达标。

---

## 4. 当前进度状态

- ✅ 4B-4 软件层（ClockSync + SynchronizedRunDataset + 相关修复）全部完成，测试 92/92 GREEN。
- 🔴 真机验证**被遥测转发阻塞（固件层 CIPSEND）卡住**：覆盖率 50%（需 95%），根因在 `main.c` 的同步 CIPSEND。
- ⏳ 备选方案（未执行）：用**位姿 yaw ↔ 遥测 yaw 交叉相关**校准时钟，绕开不可靠的 pc_recv_ns——可作为固件修复前的临时方案。

---

## 5. 请审核 agent 重点复核的问题

1. **CIPSEND 同步阻塞的判断**是否成立？（`main.c` 140-180 行的 `ESP_DoCIPSENDTransaction` 确实同步阻塞主循环吗？）
2. **遥测改 fire-and-forget 是否安全**？（CIPSEND 不等待 SEND OK，ESP01S 是否会丢帧/乱序？协议容错是否够？）
3. **位姿 yaw ↔ 遥测 yaw 交叉相关校准**是否可行/合理？（两个信号都测小车航向，但约定/漂移不同）
4. **4B-4 gate 是否必须依赖 pc_recv_ns**，还是有更稳健的时钟校准路径？
5. 我是否有遗漏/误判的地方？

---

## 6. 关键证据文件

- 采集数据: `.embeddedskills/build/v1_task4b4/raw_telemetry.json`（44-75 帧，tick/pc_recv）
- 同步报告: `.embeddedskills/build/v1_task4b4/sync_report.json`（覆盖率 50.3%、p95 29.7ms）
- 固件转发逻辑: `程序/3. 麦轮巡线小车/User/main.c`（Telemetry_Send:200, ESP_DoCIPSENDTransaction:140, CIPSEND 超时:108-109, LOOP_DELAY_MS:358, TELEMETRY_INTERVAL_MS:361）
- 遥测解析: `simulation/digital_twin/real_world/frame_parser.py`（decode_telemetry:204）
- 运行命令协议: `simulation/digital_twin/real_world/runtime_protocol.py`（RunCommand:188）
