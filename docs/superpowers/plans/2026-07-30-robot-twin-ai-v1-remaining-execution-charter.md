# Robot Twin AI V1 — 剩余任务总执行纲领

**REQUIRED SUB-SKILL:** `using-superpowers` · `writing-plans` · `brainstorming` · `verification-before-completion`

**日期:** 2026-07-30  
**状态:** 正式生效，废弃旧 Task 4 计划  
**版本:** 1.0  
**剩余执行单元总数:** 16（4B-D, 4B-0~8, 4C, 5A, 5B, 6, 7, 8）

---

## 目次

1. [目标与架构](#1-目标与架构)
2. [如何使用本纲领](#2-如何使用本纲领)
3. [事实状态表](#3-事实状态表)
4. [依赖关系与禁止跳转](#4-依赖关系与禁止跳转)
5. [Phase A — 计划同步 (Task 4B-D)](#5-phase-a--计划同步-task-4b-d)
6. [Phase B — Task 4B: 最小可信二维数字孪生](#6-phase-b--task-4b-最小可信二维数字孪生)
   - [4B-0: 数据契约与测试夹具](#6b-task-4b-0-数据契约测试夹具与旧模型隔离)
   - [4B-1: 摄像头实时输入 Gate 0](#6c-task-4b-1-摄像头实时输入-gate-0)
   - [4B-2: 相机标定与赛道坐标](#6d-task-4b-2-相机标定与赛道坐标)
   - [4B-3: 车顶标记二维位姿跟踪](#6e-task-4b-3-车顶标记二维位姿跟踪)
   - [4B-4: 相机与遥测时间同步](#6f-task-4b-4-相机与遥测时间同步)
   - [4B-5: 固件等价控制器与虚拟四路传感器](#6g-task-4b-5-固件等价控制器与虚拟四路传感器)
   - [4B-6: 四 PWM→vx/vy/omega 车辆行为模型](#6h-task-4b-6-四-pwmvxvyomega-车辆行为模型)
   - [4B-7: 校准集/holdout 隔离与模型拟合](#6i-task-4b-7-校准集holdout-隔离模型拟合与失效保护)
   - [4B-8: 模型未见安全 PID 组验证与 READY 门](#6j-task-4b-8-模型未见安全-pid-组验证与-ready-门)
7. [Phase C — Task 4C: 候选生成与预筛选](#7-phase-c--task-4c-受固件范围步进限制的确定性候选生成)
8. [Phase D — Task 5: 真机活动闭环](#8-phase-d--task-5-真机活动闭环)
9. [Phase E — Task 6: 证据只读与安全控制 UI](#9-phase-e--task-6-证据只读与安全控制-ui)
10. [Phase F — V1 完成后](#10-phase-f--v1-完成后)
11. [数字孪生命名空间与目录设计](#11-数字孪生命名空间与目录设计)
12. [数据与模型设计硬约束](#12-数据与模型设计硬约束)
13. [硬件安全矩阵](#13-硬件安全矩阵)
14. [证据等级](#14-证据等级)
15. [Handoff 模板](#15-handoff-模板)
16. [用户 ↔ Claude Code 通信模板](#16-用户--claude-code-通信模板)
17. [代理工作纪律](#17-代理工作纪律)
18. [旧计划迁移说明](#18-旧计划迁移说明)
19. [最终完成定义](#19-最终完成定义)
20. [自检清单](#20-自检清单)
21. [回滚规程](#21-回滚规程)

---

## 1. 目标与架构

### Goal

在固定真实赛道上，通过有界运行次数的 PID 参数寻找更准确、更稳定、不退化时更快的巡线方案。安全与完成率不能退化，RMS error 至少下降 15%，最大误差和出线次数不增加，满足前述条件后平均完成时间至少缩短 5%。

### Architecture

```
┌────────────────────────────────────────────────────────┐
│                  AI Agent (Claude Code / DeepSeek)     │
│  责任: 编排活动、解释候选、调用确定性工具、输出报告    │
└──────────────────────┬─────────────────────────────────┘
                       │ 只调用确定性 API，不输出裸 PWM
                       ▼
┌────────────────────────────────────────────────────────┐
│               PC 端闭环服务 (Python 3.11)               │
│  Campaign Orchestrator · CampaignStore · Metrics       │
│  Candidate Generator · Model Ranker · Report           │
├──────────────────┬──────────────────┬──────────────────┤
│  摄像头接入       │  时间同步模块     │  WiFi/ESP TCP    │
│  (USB/RTSP)       │  (PC sync)       │  桥接层          │
└────────┬─────────┴────────┬─────────┴────────┬─────────┘
         │                   │                   │
         ▼                   ▼                   ▼
    俯视相机            (monotonic clock)    ESP-01S TCP
    (位置/速度/姿态真值)                        ↓
                                           STM32F103C8
                                           (实时巡线控制)
```

### Tech Stack

| 层 | 技术 |
|---|---|
| 固件 | STM32F103C8 / Keil C (ARMCC V5.06) |
| 通信 | ESP-01S TCP, AT+CIPSEND, +IPD, P/R/A/S ASCII 协议 + AA55 二进制遥测 |
| PC 后端 | Python 3.11 (绝对路径: `C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe`) |
| 摄像头接入 | OpenCV (USB / RTSP 流) |
| 位姿跟踪 | AprilTag 36h11 (tag36h11) 或等效二维码标记 |
| 模型 | 轻量混合模型: 几何传感器 + 固件等价控制器 + 低参数车辆模型 + 残差 |
| 验证 | pytest, Host C (MSVC), cross-language 测试 |
| UI (Task 6) | React/TypeScript/Vite（运行证据只读；仅 STOP/恢复基线属于受保护写操作） |

### Global Constraints

1. **首版只优化巡线 PID 的 Kp、Ki、Kd 和速度上限。** 不实现轮速 PID、姿态 PID、在线强化学习。
2. **固定使用用户现有赛道。** 每活动最多 12 个候选，每参数包恰好 5 次有效运行 (exact-5)。
3. **接受候选必须同时满足:** 有效完成率不低于基线、RMS error 降低 ≥15%、最大误差和出线次数不增加、平均完成时间缩短 ≥5%、5 次有效运行均无安全停止。
4. **安全性:** 固件强制参数范围、单次变化幅度、通信超时、连续出线、运行超时和人工急停保护。
5. **参数部署是运行时命令，禁止自动改源码或烧录。** 不得调用 `KeilBridge.build_flash`。
6. **工作区不是 Git 仓库。** 严禁 `git init`，严禁编造 commit。
7. **V1 不自动修改控制源代码、不自动烧录、不发送裸电机命令。**
8. **当前无已验证编码器；禁止声称已完成轮速 PID 或已获得真实轮速反馈。**

---

## 2. 如何使用本纲领

> **适用对象:** 新开的 Claude Code / DeepSeek 会话，可能没有任何聊天历史。

### 核心原则: 一任务一代理

```
新会话打开本文件
  │
  ├── 读取全部 §1–§4 了解全局状态和依赖
  ├── 根据当前进度，确定要执行的唯一 Task 编号
  ├── 只读取该 Task 的完整卡片 (§5–§10 中对应条目)
  ├── 读取该 Task 的前置报告 (路径在卡片中指明)
  ├── 执行该 Task
  ├── 完成后输出 handoff (§15 模板)
  └── 停止。等待用户或独立验证者明确 PASS 后再进入下一 Task。
```

### 禁止行为

- ❌ 不得自动跳过或连跑多个 Task。
- ❌ 不得自我验收代替独立验收。
- ❌ 不得声称完成度高于实际证据等级。
- ❌ 不得连接硬件、烧录、复位或发送电机命令（除非 Task 卡片明确授权且用户当场确认）。
- ❌ 不得 `git init` 或编造 commit。
- ❌ 不得修改生产源代码、测试、配置、固件、Keil 工程、模型 JSON 或真实数据（除非 Task 卡片明确列出"允许修改"的文件）。
- ❌ 不得把离线测试当作硬件证据。

### 任务完成后必须做什么

1. 输出完整 handoff（§15 模板）。
2. 明确列出：
   - 哪些是 **VERIFIED SOFTWARE**（通过了什么测试）
   - 哪些是 **VERIFIED HARDWARE**（真实硬件上观察到了什么）
   - 哪些是 **INFERENCE**（代码分析推断但未实测）
   - 哪些是 **INSUFFICIENT EVIDENCE**（无法验证）
3. 明确列出下一 Task 的进入条件，并注明是否已满足。

---

## 3. 事实状态表

| 任务 | 状态 | 证据边界 | 核心证据路径 |
|------|------|----------|-------------|
| **Task 1** | ✅ 完成 | 离线代码 + 构建 + 跨语言测试 + 变异测试 + ASan + Keil 构建 + 范围审查 | `docs/superpowers/task1-final-acceptance.md` — 全部 8 个 Gate PASS |
| **Task 2A** | ✅ 完成 | 离线代码 + 测试 + Keil 构建 | 92 项测试全通过，Keil 0 Error/0 Warning |
| **Task 2B** | ✅ 完成 | 🔴 **硬件证据:** 真车运动确认 | 电机寄存器诊断显示 TIM2/TIM4 CEN=1, CCR=399, 443。2s、3s、连续 3 次约 3s 窗口有真实运动和停止确认。5s 窗口 35 telemetry + 1 diag。**这只证明通信、运动窗口和遥测链路，不证明巡线闭环或 PID 优化完成。** |
| **Task 3** | ✅ 完成 | 离线代码 + 测试 (Python 3.11) | 120 项 (metrics + store) + 218 全量回归 + ProductStore 4 pass。exact-5 语义。 |
| **Task 4A** | ✅ 完成 | 只读审计，无代码修改 | 旧数字孪生 NOT READY。calibration_report invalidated，closed_loop_validator 数据泄漏，PID 量级与固件不一致 (Kp: 孪生 0.6 vs 固件 35.0)。 |
| **旧 Task 4** | ❌ 已废弃 | — | "直接复用现有数字孪生做候选筛选"被 Task 4A 否定。任何代理不得继续实现 `sim_candidate_filter.py` / `campaign_optimizer.py` 旧方案。 |
| **旧 spec/plan** | ❌ 需更新 | — | Task 4 章节需在 4B-D (Phase A) 中重写。 |
| **Task 4B** | ⬜ 未开始 | — | 见 §6 |
| **Task 4C** | ⬜ 未开始 | 阻塞: 4B-8 READY | 见 §7 |
| **Task 5** | ⬜ 未开始 | 阻塞: 4C 完成 | 见 §8 |
| **Task 6** | ⬜ 未开始 | 阻塞: 5A 完成 | 见 §9 |
| **Task 7** | ⬜ 未开始 | 阻塞: V1 全部完成 | 见 §10 |
| **Task 8** | ⬜ 未开始 | 阻塞: Task 7 完成 + 第二台机器人 | 见 §10 |

### 证据等级标注

- ✅ **VERIFIED SOFTWARE** — 自动化测试通过，可重现
- 🔴 **VERIFIED HARDWARE** — 真实硬件上执行并观察到结果
- 🔶 **INFERENCE** — 代码/日志分析推断，未直接测量
- ⚪ **INSUFFICIENT EVIDENCE** — 无法验证

---

## 4. 依赖关系与禁止跳转

```
Phase A: 4B-D (计划同步)
  │ 完成后更新旧 spec/plan
  ▼
Phase B: 4B-0 → 4B-1 → 4B-2 → 4B-3 → 4B-4 → 4B-5 → 4B-6 → 4B-7 → 4B-8
  │                                           ▲
  │       4B-1 (Camera Gate 0) 失败时          │
  │       允许更换 USB/RTSP/手机串流方式        │
  │       但不允许伪造实时输入                   │
  ▼
4B-8 READY? ───→ NO ──→ 停止，标记 INCOMPLETE，返回报告
  │ YES
  ▼
Phase C: Task 4C (候选生成与预筛选)
  │
  ▼
Phase D: Task 5A (纯离线 Campaign Orchestrator)
  │         ↓
  │    Task 5B (固定赛道真机闭环活动)
  ▼
Phase E: Task 6 (证据只读 + 受保护安全控制 UI)
  │
  ▼
Phase F: Task 7 (可迁移核心) → Task 8 (第二台机器人验证)
```

### 硬性禁止跳转规则

1. **4B-8 未 READY → 不得开始 Task 4C。** 模型可信门未通过时，任何候选生成和预筛选都是盲目的。
2. **4B-1 (Camera Gate 0) 失败 → 允许更换 USB/RTSP/手机串流方式，但不允许伪造实时输入。** 如果没有可用摄像头实时流，Task 4B 整体失败。
3. **Task 5B (真机活动) 之前必须通过 5A (纯离线) 全部测试。** 不允许用真机调试编排状态机。
4. **Task 6 (UI) 必须在 5A 之后**，因为 UI 读取的是 CampaignStore 和 Orchestrator 状态。5B 不是 UI 开发的前提；运行证据保持只读，唯一允许的写操作是带二次确认的 STOP/恢复基线安全控制。
5. **Task 7/8 在 V1 全部闭环完成之前不得开始。** 不得为了架构迁移阻塞 V1 验收。

---

## 5. Phase A — 计划同步 (Task 4B-D)

| 字段 | 值 |
|------|-----|
| **目标** | 完成最小可信二维数字孪生正式设计，并更新旧 spec/plan 的 Task 4 章节 |
| **为什么现在做** | 旧 spec/plan (2026-07-28) 的 Task 4 方案已被 Task 4A 否定。必须先把计划更新到与当前状态一致，后续代理才能准确执行。 |
| **前置条件** | ✅ Task 4A 审计报告完成 (`.embeddedskills/build/task4a-digital-twin-audit/report.md`) |
| **允许读取的文件** | 工作区全部可读 |
| **允许修改的文件** | `docs/superpowers/specs/2026-07-28-line-following-pid-closed-loop-design.md` 中 Task 4 相关章节<br>`docs/superpowers/plans/2026-07-28-line-following-pid-closed-loop.md` 中旧 Task 4 条目 |
| **禁止触碰的范围** | 所有生产源代码、测试、配置、固件、Keil 工程、模型 JSON、数据文件 |
| **Consumes** | Task 4A 审计报告、本纲领中的 Phase B/C 设计 |
| **Produces** | 更新后的 spec `§4` (数字模型) 和 plan Task 4 章节 |
| **TDD 步骤** | 不适用于纯设计文档更新 |
| **离线/硬件属性** | ⚪ 纯离线设计，不涉及硬件 |
| **自动验收 gate** | 无自动 gate |
| **人工验收 gate** | 用户确认 spec/plan 的 Task 4 章节已正确反映新设计 |
| **失败和回滚** | 用户可要求恢复到旧版本（本纲领和原文件时间戳可追溯）。参考 §21 回滚规程。 |
| **输出报告路径** | `.embeddedskills/build/v1_task4bd/handoff.md` — 必须输出独立 handoff，涵盖更新前后对比和用户确认记录 |
| **下一 Task 进入条件** | 用户确认 plan 章节更新完成 |

---

## 6. Phase B — Task 4B: 最小可信二维数字孪生

> **⚠️ STOP 条件:** 在任何 4B 子任务开始前，代理必须先读取本纲领全文和 Task 4A 审计报告。禁止在任何子任务中修改生产代码、旧孪生模型、或连接硬件（除非子任务卡片明确授权）。

### 命名空间

所有新代码放入: `simulation/digital_twin/v1_twin/`

命名约定:
- Python: `v1_twin_*.py`
- 测试: `test_v1_twin_*.py`
- 数据: `data/v1_twin/` 目录下

旧路径 (`simulation/digital_twin/control_sandbox/`、旧 calibration models、旧 validation report) 默认隔离，不得在新代码中默认导入。

---

### 6a. Task 4B-0: 数据契约、测试夹具与旧模型隔离

| 字段 | 值 |
|------|-----|
| **目标** | 定义 Phase B 所有数据结构的不可变 schema，实现序列化/反序列化，编写测试夹具，建立旧模型隔离检查 |
| **为什么现在做** | 所有后续 4B 子任务依赖统一的坐标系、单位、时间格式和数据容器。先定义契约再实现。 |
| **前置条件** | ✅ 本纲领已生效 |
| **允许读取的文件** | 工作区全部可读，特别是 Task 3 的 `RunSummary`、`CandidateDecision`、`campaign_store.py`、`runtime_protocol.py` 中的数据结构 |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/__init__.py`<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_schema.py` (所有数据结构)<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_errors.py` (领域错误类型)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_schema.py`<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_isolation.py` (旧模型隔离检查器)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_isolation.py` |
| **禁止触碰的范围** | 所有旧 `simulation/digital_twin/` 下的源文件 (除上述新建外)、固件、Keil 工程、配置、模型 JSON、数据 JSON |
| **Consumes** | 无 |
| **Produces** | `V1Pose` (x_mm, y_mm, yaw_rad, confidence, t_pc_ns)<br>`V1TelemetryFrame` (sensors[4], error, pid_output, pwm[4], tick_ms)<br>`V1SyncFrame` (pose, telemetry, sync_quality)<br>`V1SensorModelConfig` (四传感器相对车体偏移 mm)<br>`V1TrackMap` (二值 mask / centerline / width)<br>`V1CalibrationSet` / `V1HoldoutSet` (按 run_id 隔离)<br>`V1ModelVersion` (model_name, version, schema_version) |
| **TDD 步骤** | 1. 写 schema 序列化测试 (RED: 模块不存在)<br>2. 实现不可变 dataclass + JSON 序列化 (GREEN)<br>3. 写旧模型隔离检查测试 (RED: 隔离检查器不存在)<br>4. 实现隔离检查器，确保旧路径不在 v1_twin 的 sys.modules 中 (GREEN) |
| **离线/硬件属性** | ⚪ 纯离线 |
| **自动验收 gate** | `pytest simulation/digital_twin/tests/test_v1_twin_schema.py -v` 全部通过<br>`pytest simulation/digital_twin/tests/test_v1_twin_isolation.py -v` 全部通过 |
| **人工验收 gate** | 用户确认 schema 字段和单位满足需求 |
| **失败和回滚** | 按 §21 回滚规程处理本 Task 在 handoff 中列明的新建文件。默认保留失败产物和日志供审计。 |
| **输出报告路径** | `.embeddedskills/build/v1_task4b0/` |
| **下一 Task 进入条件** | ⬜ 4B-0 全部测试通过 |

### 数据空间硬约束

| 量 | 内部单位 | 序列化单位 | 说明 |
|---|---|---|---|
| 位置 | mm | mm | 地面二维坐标，原点由标定确定 |
| 角度 | rad | rad | 内部连续 rad，不转 degree 存储 |
| PC 时间 | ns | ns | `time.monotonic_ns()` |
| MCU tick | ms | ms | 固件 `g_loop_count * LOOP_DELAY_MS` |
| 误差 | 原始误差单位 | — | 与固件 `error` 定义一致 |
| 传感器 | 0/1 | 0/1 | 权威定义见 §12 第六项 |

---

### 6b. Task 4B-1: 摄像头实时输入 Gate 0

| 字段 | 值 |
|------|-----|
| **目标** | 验证俯视摄像头实时流可用性: 连续 10 分钟、有效帧率 ≥20 fps、drop ≤5%、时间戳严格单调 |
| **为什么现在做** | 摄像头是整个数字孪生的外部真值来源。如果实时流不可用，后续所有工作都无法进行。必须先验证。 |
| **前置条件** | ✅ 4B-0 完成 |
| **允许读取的文件** | 4B-0 schema |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_camera.py` (CameraSource 抽象和实现)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_camera.py` |
| **禁止触碰的范围** | 所有其他生产源代码、固件、Keil 工程、模型 |
| **Consumes** | USB 或 RTSP 摄像头实时流 (用户提供) |
| **Produces** | `CameraSource.start()` / `stop()` / `read()` → (frame, timestamp_ns, ok)<br>Gate 0 验证脚本 |
| **TDD 步骤** | 1. 写 CameraSource 抽象测试 (RED)<br>2. 实现 OpenCV 读取 + 时间戳 + 帧率统计 (GREEN)<br>3. 写 Gate 0 验证脚本 (连续 10min 录制 + 统计) |
| **离线/硬件属性** | 🔴 **需要硬件:** 必须连接摄像头运行验证 |
| **自动验收 gate** | 连续 10 分钟录制脚本自动输出: `fps >= 20`, `drop_rate <= 5%`, `timestamps_monotonic = True` |
| **人工验收 gate** | 用户确认摄像头画面正确覆盖赛道区域 |
| **失败和回滚** | **Gate 0 失败时**，允许更换 USB/RTSP/手机串流方式；如果所有方式都失败，Task 4B 标记 INCOMPLETE，返回报告说明原因。回滚按 §21 规程处理本 Task 创建的文件。 |
| **输出报告路径** | `.embeddedskills/build/v1_task4b1/` |
| **下一 Task 进入条件** | ⬜ Gate 0 PASS |

---

### 6c. Task 4B-2: 相机标定与赛道坐标

| 字段 | 值 |
|------|-----|
| **目标** | 完成相机内参标定（畸变校正）和俯视变换 (homography)，建立赛道地面二维坐标系，提取赛道中心线/宽度/边界 |
| **为什么现在做** | 必须在记录轨迹之前完成标定，否则像素坐标无物理意义。必须在模型拟合之前知道赛道几何。 |
| **前置条件** | ✅ 4B-1 Gate 0 PASS |
| **允许读取的文件** | 4B-0 schema, 4B-1 camera module |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_calibration.py` (相机标定 + homography)<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_track_map.py` (赛道地图: mask/centerline/width)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_calibration.py`<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_track_map.py` |
| **禁止触碰的范围** | 所有其他生产源代码、固件、Keil 工程、旧孪生模型 |
| **Consumes** | 棋盘格或已知尺寸标定板图片；赛道俯视图像 |
| **Produces** | `CameraCalibration` (内参矩阵、畸变系数、标定重投影误差)<br>`HomographyTransform` (像素↔地面 mm)<br>`TrackMap` (二值 mask / centerline 点列 / 宽度 / 边界)<br>`TrackMap.validate()` |
| **TDD 步骤** | 1. 写 homography 正反变换测试 (RED)<br>2. 实现标定流程 (GREEN)<br>3. 写赛道地图提取算法测试 |
| **离线/硬件属性** | 🔴 **需要硬件:** 必须连接摄像头拍摄标定板图片和赛道俯视图 |
| **自动验收 gate** | 重投影误差 p95 ≤ max(2 pixel, 5% 的真实黑线宽度折算像素) |
| **人工验收 gate** | 用户确认赛道地图与真实赛道一致 (可叠加显示) |
| **失败和回滚** | 标定失败可重拍标定板；homography 失败可调整标定点。 |
| **输出报告路径** | `.embeddedskills/build/v1_task4b2/` |
| **下一 Task 进入条件** | ⬜ 标定验收通过 |

---

### 6d. Task 4B-3: 车顶标记二维位姿跟踪

| 字段 | 值 |
|------|-----|
| **目标** | 检测车顶 AprilTag (或等效二维码)，输出每帧的 x/y/yaw_rad/confidence |
| **为什么现在做** | 这是从摄像头原始像素到车辆位姿的转换层，是后续所有模型拟合和时间同步的基础。 |
| **前置条件** | ✅ 4B-2 (标定完成，已知像素↔mm 映射) |
| **允许读取的文件** | 4B-0 schema, 4B-2 calibration |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_pose_tracker.py` (AprilTag 检测 + homography 投影)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_pose_tracker.py` |
| **禁止触碰的范围** | 所有其他生产源代码、固件、Keil 工程、旧孪生模型 |
| **Consumes** | 摄像头帧、CameraCalibration、HomographyTransform、AprilTag 库 (pupil_apriltags / apriltag / OpenCV ArUco，实施时择一并锁版本) |
| **Produces** | `PoseTracker.track(frame) → V1Pose(x_mm, y_mm, yaw_rad, confidence)` |
| **TDD 步骤** | 1. 写 tag 检测纯测试 (使用静态图片，RED)<br>2. 实现检测逻辑 (GREEN)<br>3. 写 homography 投影测试 |
| **离线/硬件属性** | 🔴 **需要硬件:** 需要摄像头拍摄车顶标记的静态照片 |
| **自动验收 gate** | 静态测试: 有效检测率 ≥95% (连续 100 帧人工已知位置)<br>静态抖动: x/y p95 抖动 ≤5% 黑线宽度, yaw p95 抖动 ≤2 degrees |
| **人工验收 gate** | 用户确认标记固定在车顶且无遮挡 |
| **失败和回滚** | 标签检测失败: 更换标签类型/尺寸/打印质量；运动模糊: 调节曝光时间 |
| **输出报告路径** | `.embeddedskills/build/v1_task4b3/` |
| **下一 Task 进入条件** | ⬜ 静态位姿验收通过 |

---

### 6e. Task 4B-4: 相机与遥测时间同步

| 字段 | 值 |
|------|-----|
| **目标** | 实现 PC monotonic 时钟与 MCU tick 的对齐，生成 synchronized run dataset |
| **为什么现在做** | 不同步的数据点无法用于模型拟合。这是将摄像头轨迹与遥测关联的关键。 |
| **前置条件** | ✅ 4B-1, 4B-3 (摄像头可以采集位姿) |
| **允许读取的文件** | 4B-0 schema, 4B-1 camera, 4B-3 tracker |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_sync.py` (时间同步器)<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_dataset.py` (同步数据集)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_sync.py`<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_dataset.py` |
| **禁止触碰的范围** | 所有其他生产源代码、固件、Keil 工程、旧孪生模型 |
| **Consumes** | 摄像头帧 (timestamp_ns)，遥测帧 (tick_ms, pc_recv_ns) |
| **Produces** | `ClockSync` (MCU tick → PC ns 映射: 线性回归或 PTP 样同步)<br>`SynchronizedRunDataset` (pose + telemetry 对齐列表, sync_quality 字段)<br>**不可变规则:** 原始视频帧、原始遥测、原始位姿观测不可覆盖。派生同步数据集可重算且必带 schema/model version。 |
| **TDD 步骤** | 1. 写 tick unwrap 测试 (RED)<br>2. 写 linear regression sync 测试 (RED)<br>3. 实现 sync 逻辑 (GREEN)<br>4. 写 dataset 不可变性测试 |
| **离线/硬件属性** | 🔴 **需要硬件:** 需要一次真车运行（短距离，安全防护）产生遥测+摄像头数据 |
| **自动验收 gate** | 匹配覆盖率 ≥95%<br>p95 时间差 ≤ max(一帧相机周期, 一帧遥测周期) |
| **人工验收 gate** | 用户确认数据集字段完整，未发生按数组下标硬拼 (验证: 同步使用 t_pc_monotonic_ns 关联) |
| **失败和回滚** | 同步失败: 调整时钟模型阶数，检查 MCU tick 单调性 |
| **输出报告路径** | `.embeddedskills/build/v1_task4b4/` |
| **下一 Task 进入条件** | ⬜ 同步验收通过 |

---

### 6f. Task 4B-5: 固件等价控制器与虚拟四路传感器

| 字段 | 值 |
|------|-----|
| **目标** | 实现与 STM32 固件控制公式完全一致的控制器仿真，以及基于车体位姿和赛道地图的虚拟四路传感器仿真 |
| **为什么现在做** | 需要"植入"孪生的控制器和传感器与固件一致，模型预测才可比较。 |
| **前置条件** | ✅ 4B-2 (赛道地图)、4B-3 (位姿跟踪)、4B-4 (同步数据集) |
| **允许读取的文件** | 4B-0 schema, 固件 `main.c` 中的 PID 公式和误差计算, `程序/3. 麦轮巡线小车/User/main.c:624-655` |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_controller.py` (与固件一致的 PID + 输出限幅)<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_virtual_sensor.py` (四传感器几何模型)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_controller.py`<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_virtual_sensor.py` |
| **禁止触碰的范围** | 固件 `main.c` 本身、Keil 工程、其他所有生产文件 |
| **Consumes** | 固件 PID 公式 (P*error + I*累积 + D*微分 + 限幅)、误差计算公式 (离散加权误差)<br>赛道地图 (TrackMap)、传感器相对车体偏移 (SensorModelConfig) |
| **Produces** | `V1Controller` — 输入 (error, dt) → pid_output (与 main.c L624 公式逐行对比验证)<br>`V1VirtualSensor` — 输入 (pose_mm, track_map) → sensors[4], error<br>`V1Controller.validate_against_firmware()` — 批量输入/输出对比固件 C 代码 |
| **TDD 步骤** | 1. 写 PID 输出与固件一致性测试 (RED)<br>2. 实现 `V1Controller`，与固件宏值公式逐行对齐 (GREEN)<br>3. 写虚拟传感器测试：已知位姿 → 期望传感器状态 (RED)<br>4. 实现 `V1VirtualSensor` (GREEN) |
| **离线/硬件属性** | ⚪ 纯离线 (基于现有固件中已读取的公式) |
| **自动验收 gate** | `test_v1_twin_controller.py` — Kp/Ki/Kd 多组合下输出与固件 C 代码计算结果完全一致<br>`test_v1_twin_virtual_sensor.py` — 传感器状态正确反映位姿与赛道关系 |
| **人工验收 gate** | 无 |
| **失败和回滚** | 重读固件 PID 公式确保正确 |
| **输出报告路径** | `.embeddedskills/build/v1_task4b5/` |
| **下一 Task 进入条件** | ⬜ 全部测试通过 |

---

### 6g. Task 4B-6: 四 PWM→vx/vy/omega 车辆行为模型

| 字段 | 值 |
|------|-----|
| **目标** | 从同步数据集辨识四路独立 PWM 到车体速度 (vx, vy, omega) 的映射，建立低参数车辆行为模型 |
| **为什么现在做** | 麦轮底盘四轮独立 PWM，不能简化为两轮差速。需要从真实数据辨识参数。 |
| **前置条件** | ✅ 4B-4 (同步数据集)、4B-5 (控制器和虚拟传感器, 用于生成仿真输入) |
| **允许读取的文件** | 4B-0 schema, 4B-5 controller/virtual sensor, Task 4A 审计报告中关于旧 plant_model 的分析 |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_plant.py` (车辆行为模型)<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_identification.py` (系统辨识)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_plant.py`<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_identification.py` |
| **禁止触碰的范围** | 所有其他生产源代码、旧孪生模型文件；禁止裸 PWM 命令，只能使用受限运行时 PID 参数产生的自然 PWM 激励 |
| **Consumes** | 同步数据集 (pose, telemetry)、固件 PWM 输出、相机真值位姿 |
| **Produces** | `V1Plant` — 输入 (pwm[4], dt) → (vx, vy, omega)<br>`V1Plant.identify()` — 从同步数据集辨识参数<br>`V1Plant.predict()` — 积分预测轨迹<br>模型参数最少化，避免当前数据量下不可辨识<br>**数据覆盖矩阵** — 每路 PWM 取值范围直方图、四路组合覆盖热图、转向/直行/停止状态占比 |
| **校准数据要求** | 使用 baseline + 至少 3 个安全 probe PID 组，每组恰好 5 次有效运行。数据不足时标记 INSUFFICIENT EVIDENCE 而不是 PASS。 |
| **TDD 步骤** | 1. 写模型结构测试 (RED)<br>2. 实现最小参数模型 (偏置/线性 + 死区 + 延迟) (GREEN)<br>3. 写辨识算法测试 (RED)<br>4. 实现辨识 (GREEN)<br>5. 写数据覆盖分析测试 (RED)<br>6. 实现覆盖矩阵 (GREEN) |
| **离线/硬件属性** | 🔶 **混合硬件+离线:** 需用户在场且明确授权下，用受限 PID 参数产生自然 PWM 激励采集真车数据；采集完成后离线拟合。每次数据采集对应一次 START/STOP 运行，用户逐次授权。 |
| **自动验收 gate** | **本 Task 不设 holdout 轨迹验证**（轨迹验证在 4B-8）。本 Task 只验证：<br>1. 合成已知参数恢复测试: 用已知参数生成仿真数据，辨识算法能恢复原参数（容差 ±5%）<br>2. 数值稳定性: 不同初始值导致相同收敛结果<br>3. 参数可辨识性诊断: Fisher information / 条件数报告<br>4. 数据覆盖矩阵: 每路 PWM 覆盖 ≥60% 范围、四路组合无全零列 |
| **人工验收 gate** | 用户确认激励数据采集过程安全、数据覆盖矩阵充足 |
| **失败和回滚** | 辨识不收敛、数据覆盖不足 → 增加激励运行、减少模型参数、增加正则化。参考 §21 回滚规程处理已创建文件。 |
| **输出报告路径** | `.embeddedskills/build/v1_task4b6/` |
| **下一 Task 进入条件** | ⬜ 行为模型辨识通过且数据覆盖充足 |

---

### 6h. Task 4B-7: 校准集/holdout 隔离、模型拟合与失效保护

| 字段 | 值 |
|------|-----|
| **目标** | 消费 4B-6 的真实辨识数据，固化 calibration run_id 清单，完成模型拟合、冻结、版本化和失效保护 |
| **为什么现在做** | 同一数据不可既训练又验收。最终 holdout 必须在模型冻结后使用全新 PID 组采集；不允许从已参与辨识的数据中挑选最终 holdout，也不允许先看 holdout 再调整模型。 |
| **前置条件** | ✅ 4B-5, ✅ 4B-6 (必须已使用真实辨识数据完成辨识) |
| **允许读取的文件** | 4B-0 schema, 4B-6 产生的数据和覆盖矩阵 |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_calibration_set.py` (校准/验证集分离)<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_model_registry.py` (模型版本注册)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_calibration_set.py`<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_model_registry.py` |
| **禁止触碰的范围** | 所有其他生产源代码、旧孪生数据文件 |
| **Consumes** | 4B-6 真实辨识数据 (baseline + probe PID 组同步数据集)、各子模型 (controller, virtual_sensor, plant) |
| **Produces** | 1. 不可变 `calibration_run_ids` 与参数版本清单<br>2. 冻结后的模型选择、超参数、停止条件和模型哈希<br>3. 空的最终 holdout 注册表；只允许 4B-8 在模型冻结后追加全新 PID 组的 run_id<br>4. `ModelRegistry` — 保存模型参数 + schema_version + model_version + 拟合时间戳<br>5. 拟合日志和收敛证据 |
| **TDD 步骤** | 1. 写 calibration 清单不可变测试 (RED)<br>2. 实现清单与交集硬检查 (GREEN)<br>3. 写模型冻结/拟合测试 (RED)<br>4. 实现拟合 + 注册表 (GREEN)<br>5. 写“冻结前不得登记最终 holdout、冻结后不得修改模型”测试并通过 |
| **离线/硬件属性** | ⚪ 纯离线（消费 4B-6 已采集数据） |
| **自动验收 gate** | **程序硬检查:** calibration 与最终 holdout 的 run_id 交集必须为空；模型冻结后任何参数、代码版本或停止条件变化都使原 holdout 资格失效。<br>拟合收敛日志完整。 |
| **人工验收 gate** | 确认模型选择、超参数和停止条件已冻结，且尚未查看或采集最终 holdout 结果 |
| **失败和回滚** | 参考 §21 回滚规程。隔离失败 → 修正分离器逻辑。 |
| **输出报告路径** | `.embeddedskills/build/v1_task4b7/` |
| **下一 Task 进入条件** | ⬜ 全部测试通过 |

---

### 6i. Task 4B-8: 模型未见安全 PID 组验证与 READY 门

| 字段 | 值 |
|------|-----|
| **目标** | 用模型未见过的安全 PID 参数组验证模型预测的排序正确性。通过所有门后宣布 READY，否则 NOT READY。 |
| **为什么现在做** | 这是数字孪生从"实验性模型"变为"可用于候选预筛选"的唯一标准。不通过则 Task 4C 不得开始。 |
| **前置条件** | ✅ **4B-0 至 4B-7 全部 PASS**<br>G1-G4 证据仍有效（若 4B-1~4B-4 完成后间隔过久需重检）<br>模型、超参数、停止条件和 calibration run_id 已冻结并记录哈希<br>🔴 用户本次明确授权采集最终 holdout；旧授权不可沿用 |
| **允许读取的文件** | 所有 v1_twin 模块 |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_validator.py` (综合验证器)<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_runner.py` (孪生运行器)<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_validator.py`<br>**仅新增真实证据:** `data/v1_twin/holdout/<model_version>/...` 与 `.embeddedskills/build/v1_task4b8/...`；不得覆盖 calibration 或既有 raw run |
| **禁止触碰的范围** | 所有其他生产源代码、旧孪生模型、固件 |
| **Consumes** | 全部冻结后的 v1_twin 模型与 calibration 清单；本 Task 在冻结后采集至少 5 个模型从未见过的安全 PID 组，每组恰好 5 次完整运行（总计至少 25 次最终 holdout）。若运行意外出现 line_loss/safety_stop，完整数据仍可标 valid=True 用于 danger recall，不得删除失败运行。 |
| **Produces** | `V1TwinValidator` 统一接入各验证门<br>`V1TwinRunner.run(params, track_map) → predicted run`<br>`VALIDATION_REPORT` — 所有门的结果 + 综合结论 READY / NOT READY |

### 可信门阈值表

| ID | 门名称 | 公式 | 通过标准 | 单位/说明 |
|----|--------|------|---------|----------|
| G1 | 摄像头实时流 | 连续 10min, `有效帧率`, `drop率` | fps ≥ 20, drop ≤ 5%, 时间戳严格单调 | 来自 4B-1 |
| G2 | 相机标定 | 重投影误差 p95 | ≤ max(2 pixel, 5% 黑线宽度像素) | 来自 4B-2 |
| G3 | 静态位姿 | 有效检测率, x/y yaw 抖动 | 有效率 ≥ 95%, x/y p95 ≤ 5% 黑线宽度, yaw p95 ≤ 2 deg | 来自 4B-3 |
| G4 | 时间同步 | 匹配覆盖率, p95 时间差 | 覆盖率 ≥ 95%, 时间差 ≤ max(1帧相机周期, 1帧遥测周期) | 来自 4B-4 |
| G5 | 传感器模型 | holdout macro-F1 | ≥ 0.90 | 任何 0/1 语义倒置测试必须 fail |
| G6 | 轨迹模型 | holdout 横向误差 p95 | ≤ 0.5 × 黑线宽度 | 完成/出线终止类别全对 |
| G7 | 指标预测 | holdout RMS 相对误差, 最大误差, 完成时间 | RMS ≤ 15%, 最大误差 ≤ 15%, 完成时间 ≤ 10% | — |
| G8 | PID 排序 | Spearman rank, danger recall | ≥ 5 组模型未见安全 PID, Spearman ≥ 0.70, danger recall = 100% | 所有真车出线/safety stop 的组必须被模型判为不合格 |

> **G8 danger recall 说明:** 如果 ≥5 个验证 PID 组中有 N 个在真车测试中触发了 line loss 或 safety stop，模型必须将这 N 个全部判为不合格（danger recall = N/N = 100%）。少判 1 个 → G8 失败。

### 关键规则

- 任何一门失败 → 模型 **NOT READY** → Task 4C 不得开始。
- 阈值写明确单位、样本数和计算方法。
- G1-G4 可在 4B-1~4B-4 完成后预检，G5-G8 需要模型集成。
- 如果样本不足以统计显著，状态为 **INSUFFICIENT EVIDENCE** 而不是 PASS。

| 离线/硬件属性 | 🔴 **需要硬件:** 真车运行 ≥5 个安全 PID 组的验证数据 |
| **自动验收 gate** | 验证报告自动输出每项 G1-G8 的 PASS/FAIL/INSUFFICIENT EVIDENCE |
| **人工验收 gate** | 用户确认验证过程正确、数据独立 |
| **失败和回滚** | NOT READY → 返回模型拟合报告，指出具体失败门，不推进 Task 4C。回滚按 §21 规程处理。 |
| **输出报告路径** | `.embeddedskills/build/v1_task4b8/` |
| **下一 Task 进入条件** | ⬜ **4B-8 综合结论 = READY** |

---

## 7. Phase C — Task 4C: 受固件范围/步进限制的确定性候选生成

> **⚠️ STOP 条件:** 4B-8 必须报告 READY。不得在任何 4B 子任务未完成时开始 4C。

| 字段 | 值 |
|------|-----|
| **目标** | 在固件声明的 Kp/Ki/Kd/speed_max 边界内，以确定性算法生成不超过 12 个候选 PID 参数包，经模型预筛选后输出排序列表 |
| **为什么现在做** | 只有在数字孪生通过可信门后，其预筛选才有意义。 |
| **前置条件** | 🔴 **4B-8 READY** |
| **允许读取的文件** | 所有 v1_twin 模块、`twin_control_protocol.h` 中的参数边界 (`TWIN_CONTROL_KP_MIN/MAX` 等) |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_candidate_generator.py`<br>**新建:** `simulation/digital_twin/v1_twin/v1_twin_ranker.py`<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_candidate_generator.py` |
| **禁止触碰的范围** | 旧 `sim_candidate_filter.py` 和 `campaign_optimizer.py`（已废弃）|
| **Consumes** | 固件参数边界、模型 (controller+virtual_sensor+plant)、最近基线运行 |
| **Produces** | `CandidateGenerator.propose(baseline_params, firmware_bounds) → list[CandidateProposal]`<br>每个 `CandidateProposal` 包含 params, model_prediction, confidence, rationale |
| **TDD 步骤** | 1. 写候选生成边界测试 (RED)<br>2. 实现确定性生成 (GREEN)<br>3. 写模型预筛选测试 (RED)<br>4. 实现排序 + 置信度 (GREEN) |
| **离线/硬件属性** | ⚪ 纯离线 |
| **自动验收 gate** | 候选数 ≤ 12，所有候选在固件边界内，去重后全部唯一 |
| **人工验收 gate** | 无 (但用户可检查候选 rationale) |
| **失败和回滚** | 按 §21 回滚规程处理本 Task 创建的文件。默认保留失败产物和日志供审计。 |
| **输出报告路径** | `.embeddedskills/build/v1_task4c/` |
| **下一 Task 进入条件** | ⬜ 候选生成测试全部通过 |

---

## 8. Phase D — Task 5: 真机活动闭环

### 8a. Task 5A: 纯离线、FakeTransport 的可回滚 Campaign Orchestrator

| 字段 | 值 |
|------|-----|
| **目标** | 实现活动编排状态机: baseline → calibrate → simulate → deploy → run → evaluate → accept/reject/rollback，全部通过 FakeTransport 测试 |
| **前置条件** | ✅ Task 3 (CampaignStore, Metrics), ✅ Task 4C (候选生成) |
| **允许修改的文件** | **新建:** `simulation/digital_twin/v1_twin/v1_twin_orchestrator.py`<br>**新建:** `simulation/digital_twin/tests/test_v1_twin_orchestrator.py` |
| **禁止触碰的范围** | 固件、Keil 工程、实时传输层 |
| **Consumes** | CampaignStore, CampaignMetrics, CandidateGenerator, V1TwinRunner |
| **Produces** | `V1CampaignOrchestrator` — 状态序列 + 回滚 + 报告 |
| **离线/硬件属性** | ⚪ 纯离线 (FakeTransport 模拟全部通信) |
| **自动验收 gate** | FakeTransport 测试覆盖: 成功候选、ACK 超时回滚、出线回滚、人工停止 |
| **下一 Task 进入条件** | ⬜ 全部 Orchestrator 测试通过 |

### 8b. Task 5B: 固定赛道真机闭环活动

| 字段 | 值 |
|------|-----|
| **目标** | 在固定赛道上运行实际活动: baseline 5 次 → 候选生成 → 模型预筛选 → 部署 → 真车运行 → 评价 → 接受/回滚 |
| **前置条件** | 🔴 **4B-8 READY**<br>✅ Task 4C PASS<br>✅ Task 5A PASS<br>🔴 **用户本次明确硬件授权**（旧授权不可沿用，用户必须当次确认赛道净空、急停可用、供电正常） |
| **允许新增的文件** | `data/v1_twin/campaigns/<campaign_id>/...` — 不可变真实运行数据<br>`.embeddedskills/build/v1_task5b/...` — 活动报告和日志<br>不得覆盖已有 raw run 数据 |
| **硬件需求** | 🔴 **用户必须在场。** 赛道净空、急停可用、一次一个动作。每次部署需用户逐次授权。 |
| **安全规则** | 见 §13 硬件安全矩阵 — Track Run 行 |
| **Task 完成 gate** | 一个真机 campaign 按 exact-5 规则完整结束；每个候选均有接受或拒绝结论；任何拒绝、超时、出线或人工停止均留下完整证据并恢复基线。全部候选被拒绝时，只能证明编排和回滚闭环完成。 |
| **V1 成功 gate** | 至少一个候选经真机 exact-5 验证后被接受，并满足：RMS error 下降 ≥15%；或在 RMS error 不退化、最大误差不退化且无安全事件时，完成时间缩短 ≥5%。若无候选满足，Task 5B 可标 `COMPLETE / NO_ACCEPTED_CANDIDATE`，但 **V1 不得标记完成**；应回到 4C 生成下一批候选，不能降低门槛。 |

---

## 9. Phase E — Task 6: 证据只读与安全控制 UI

| 字段 | 值 |
|------|-----|
| **目标** | 对活动状态、运行结果和模型置信度提供不可编辑的证据视图；仅提供带二次确认的 STOP/恢复基线安全控制，不提供其他写操作 |
| **为什么现在做** | 没有 UI 时只能通过终端和 JSON 查看活动结果。UI 提供状态概览和人工安全干预入口。 |
| **前置条件** | ✅ 5A (Orchestrator 完成, 有数据可展示) |
| **允许修改的文件** | **建议修改:** `simulation/digital_twin/web_showcase/src/product/App.tsx` — 活动卡片和状态面板<br>**建议修改:** `simulation/digital_twin/web_showcase/src/types.ts` — 活动类型定义<br>**建议修改:** `simulation/digital_twin/web_showcase/src/product.css` — 活动组件样式<br>**建议新增:** 对应前端测试 (TypeScript)<br>**建议修改:** `simulation/digital_twin/web_showcase/test_product_store.py` — 活动报告存储回归测试<br>**建议新建:** `docs/runbooks/line-following-pid-campaign.md` — 真机运行规程 |
| **禁止触碰的范围** | ❌ 不提供任意 PID 直下发或自动烧录 UI<br>❌ 不提供参数数值输入框 |
| **功能范围** | 活动列表、候选 rationale、运行 replay、模型置信度、stop/restore baseline 入口（需二次确认对话框）、可追溯报告 |
| **TDD 步骤** | 1. 写活动状态序列化测试和 UI 显示测试 (RED)<br>2. 运行现有 typecheck 确认新增类型失败<br>3. 实现只读证据面板和停止入口 (GREEN)<br>4. 编写真机运行规程文档<br>5. 全量回归测试 |
| **离线/硬件属性** | ⚪ 离线可开发，部署时需连接真车数据 |
| **自动验收 gate** | TypeScript typecheck 通过<br>前端测试通过<br>`test_product_store.py` 回归 PASS |
| **人工验收 gate** | 只读证据验证: 活动报告可查看但不能编辑<br>停止按钮显示二次确认对话框文案"停止并恢复基线参数"<br>确认无任意 PID 数值输入框或烧录按钮 |
| **输出报告路径** | `.embeddedskills/build/v1_task6/` |
| **下一 Task 进入条件** | ⬜ Task 6 验收通过 |

---

## 10. Phase F — V1 完成后

### Task 7: 可迁移核心封装

| 字段 | 值 |
|------|-----|
| **目标** | 将设备无关接口、适配器、数据契约和安全策略封装为可迁移核心 |
| **前置条件** | ✅ V1 全部闭环完成 (Task 1-6 全部验收) |
| **评估** | MCP / skill / Python package 的最小组合 |

### Task 8: 第二台机器人验证

| 字段 | 值 |
|------|-----|
| **目标** | 在第二种机器人/控制器上验证迁移性 |
| **前置条件** | ✅ Task 7 完成 |
| **核心规则** | 没有第二台机器人证据前，不得声称平台通用 |

---

## 11. 数字孪生命名空间与目录设计

### 建议基准目录

```
simulation/digital_twin/v1_twin/
├── __init__.py
├── v1_twin_schema.py           # 所有数据结构 (V1Pose, V1SyncFrame, etc.)
├── v1_twin_errors.py           # 领域错误类型
├── v1_twin_isolation.py        # 旧模型隔离检查器
├── v1_twin_camera.py           # CameraSource 抽象和实现
├── v1_twin_calibration.py      # 相机标定 + Homography
├── v1_twin_track_map.py        # 赛道地图 (mask/centerline/width)
├── v1_twin_pose_tracker.py     # AprilTag 位姿跟踪
├── v1_twin_sync.py             # 时间同步器 (PC monotonic ns ↔ MCU tick)
├── v1_twin_dataset.py          # 同步数据集 (不可变原始, 可重算派生)
├── v1_twin_controller.py       # 固件等价控制器
├── v1_twin_virtual_sensor.py   # 虚拟四路传感器
├── v1_twin_plant.py            # 车辆行为模型
├── v1_twin_identification.py   # 系统辨识
├── v1_twin_calibration_set.py  # 校准/holdout 分离
├── v1_twin_model_registry.py   # 模型版本注册
├── v1_twin_validator.py        # 综合验证器 (G1-G8)
├── v1_twin_runner.py           # 孪生运行器
├── v1_twin_candidate_generator.py  # 候选生成器
├── v1_twin_ranker.py           # 候选排序器
└── v1_twin_orchestrator.py     # Campaign 编排器
```

### 测试目录

```
simulation/digital_twin/tests/
├── test_v1_twin_schema.py
├── test_v1_twin_isolation.py
├── test_v1_twin_camera.py
├── test_v1_twin_calibration.py
├── test_v1_twin_track_map.py
├── test_v1_twin_pose_tracker.py
├── test_v1_twin_sync.py
├── test_v1_twin_dataset.py
├── test_v1_twin_controller.py
├── test_v1_twin_virtual_sensor.py
├── test_v1_twin_plant.py
├── test_v1_twin_identification.py
├── test_v1_twin_calibration_set.py
├── test_v1_twin_model_registry.py
├── test_v1_twin_validator.py
├── test_v1_twin_candidate_generator.py
└── test_v1_twin_orchestrator.py
```

### 隔离规则

| 操作 | 路径 | 理由 |
|------|------|------|
| **保留 (已验证可复用)** | `real_world/runtime_protocol.py` | 与固件边界一致 |
| **保留** | `real_world/campaign_store.py` | 原子写入不可变存储 |
| **保留** | `analysis/campaign_metrics.py` | strict exact-5 规则 |
| **保留** | `analysis/model_confidence.py` | 多维评分可复用 |
| **保留** | `calibration/trajectory_matcher.py` | DTW 对齐可复用 |
| **保留** | `calibration/model_updater.py` | EMA 阻尼 + 梯度裁剪合理 |
| **隔离 (旧模型)** | `control_sandbox/plant_model.py` | 参数需置零/标记未校准 |
| **隔离** | `analysis/closed_loop_validator.py` | data leak 修复前不可用 |
| **隔离** | `calibration/models/*.json` | 全部合成数据, 标记不可用 |
| **隔离** | `control_sandbox/pid_optimizer.py` | 搜索范围与固件不对齐 |
| **隔离** | `config.py` PID 默认值 | 与固件不匹配 (Kp=0.6 vs 35) |

---

## 12. 数据与模型设计硬约束

1. **空间单位 mm，角度内部单位 rad，时间 PC monotonic ns / MCU tick ms。** 所有序列化必须带单位注释。
2. **原始视频帧、原始遥测、原始位姿观测不可覆盖。** 派生同步数据和模型可重算且必须带 schema/model version。
3. **校准集与 holdout 按 run_id 完全隔离。** 程序硬检查：两集合 run_id 交集为空则通过。
4. **禁止按数组下标拼合相机和遥测。** 同步必须通过独立时间戳关联（pc_ns ↔ mcu_tick_ms）。
5. **黑白传感器 0/1 语义只允许有一个权威定义。** 固件 `main.c` 中 `SENSOR_THRESHOLD` 是唯一来源。V1 虚拟传感器必须与之一致。
6. **物理/行为模型和 2D UI 渲染完全分离。** UI 是观察层，不参与 PID 优化逻辑。

---

## 13. 硬件安全矩阵

| 模式 | 允许的连接 | 禁止事项 | 用户在场要求 |
|------|-----------|---------|-------------|
| **Offline** | 无 | 不连接任何硬件、不烧录 | — |
| **Camera-only** | 仅连接摄像头 | 小车断电、不运行电机 | 可不在场 |
| **Static car** | 小车可断电放置标定 | 不运行电机（可上电用于 ST-Link 读取寄存器，电机不供电） | 建议在场 |
| **Track run** | 全系统上电连接 | 赛道净空、急停可用、一次一个动作、禁止后台无人值守运行电机 | **必须全程在场** |

### 授权规则

- 所有硬件动作都需要用户当次明确授权。
- 旧授权不可无限沿用。每个新会话必须重新确认。
- 禁止后台无人值守运行电机。

---

## 14. 证据等级

| 等级 | 定义 | 示例 |
|------|------|------|
| **VERIFIED SOFTWARE** | 自动化测试通过，在 CI 或本地可完全重现 | `pytest ... -v` 全部 PASS |
| **VERIFIED HARDWARE** | 在真实硬件上执行并观察到可重复结果 | 真车运动确认、TIM 寄存器捕获、遥测窗口验证 |
| **INFERENCE** | 代码/日志/设计分析推论，未在目标环境实测 | 代码审查发现数据泄漏路径、公式对比发现不匹配 |
| **INSUFFICIENT EVIDENCE** | 无法在当前条件下验证 | 无真车数据文件、无编码器反馈、无第二台机器人 |

### 禁止行为

- ❌ 不得用截图、文件名、构建产物或 mock 代替真机证据。
- ❌ 不得把 VERIFIED SOFTWARE 等同于 VERIFIED HARDWARE。
- ❌ 不得声称 INSUFFICIENT EVIDENCE 的项目为已验证。

---

## 15. Handoff 模板

每个 Task 完成后必须输出以下 handoff（外层使用四反引号，内部代码块使用三反引号）：

````markdown
## Handoff — Task <ID>

### Task ID / Status
- **Task:** <Task 4B-3 / etc.>
- **Status:** COMPLETE / BLOCKED / INCOMPLETE

### Changed files
- NEW: `path/to/file.py` (N lines)
- MODIFIED: `path/to/file.py` (简述修改)
- DELETED: —

### Commands
```bash
python -m pytest path/to/tests.py -v
```
```bash
<其他命令>
```

### Exact results and exit codes
```
<测试输出摘要>
exit=0
```

### Artifact/log/report paths
- `.embeddedskills/build/v1_task4b3/`

### Verified facts
- ✅ [VERIFIED SOFTWARE] 位姿检测测试 12/12 PASS
- 🔴 [VERIFIED HARDWARE] — (或无)

### Inferences
- 🔶 基于代码分析推断...

### Unverified items
- ⚪ 未在真车上验证位姿抖动

### Scope review
- 未修改固件、Keil 工程、旧孪生模型

### Hardware actions performed
- ❌ 无 / 或列出具体授权操作

### Safety/rollback state
- 无硬件安全隐患 / 或具体状态

### Next prerequisites
- ⬜ 需要 4B-4 时间同步完成 (当前未开始)
````


---

## 16. 用户 ↔ Claude Code 通信模板

### A. 新会话首次消息模板（只读纲领，不自动执行）

```
请读取 `C:\Users\24668\Desktop\stm32小车\docs\superpowers\plans\2026-07-30-robot-twin-ai-v1-remaining-execution-charter.md`
报告当前 Task 进度和下一 Task 编号。
然后停止。等待用户明确指示后，再执行下一 Task。
工作区不是 Git 仓库，严禁 git init。
```

### B. 执行某个 Task 的消息模板（用户写 Task ID 后才执行）

```
用户指定执行 Task <ID>。
请读取 `C:\Users\24668\Desktop\stm32小车\docs\superpowers\plans\2026-07-30-robot-twin-ai-v1-remaining-execution-charter.md`
跳到 §<Task 章节> 的 <Task ID> 卡片。
读取前置报告：<路径>
执行此 Task。完成后输出完整 handoff。
不跳转到下一 Task，停止并等待用户确认 PASS。
```

### C. 上下文被清空后的恢复消息模板（只报告状态，等待用户决定）

```
上一会话完成了 <Task ID>，handoff 在 <路径>。
请读取该 handoff 和纲领文件，报告当前恢复的状态。
然后停止。等待用户指定是否执行下一 Task。
```

### D. 只读验收消息模板

```
请读取 `C:\Users\24668\Desktop\stm32小车\docs\superpowers\plans\2026-07-30-robot-twin-ai-v1-remaining-execution-charter.md`
跳到 <Task ID> 的人工验收 gate。
读取输出报告 <路径>，验证是否满足所有通过标准。
输出 PASS / FAIL / INSUFFICIENT EVIDENCE。
不修改任何文件。
```

### E. 硬件任务授权消息模板

```
正在执行 <Task ID>，需要以下硬件操作：
- <操作1：连接摄像头>
- <操作2：小车断电放置>
- <操作3：一次 START/STOP 运行>

请确认：赛道净空、急停可用、供电正常。
我将：一次只做一个动作，完成后立即停止。
是否继续？
```

---

## 17. 代理工作纪律

1. **使用 Python 3.11 绝对路径:** `C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe`
2. **使用 Edit 工具修改文件。** 不运行破坏性命令。
3. **工作区文件属于用户。** 不删除或覆盖未授权文件。
4. **不运行 `git init`。**
5. **大规模实现前先读本纲领和当前 Task 的前置报告。**
6. **新功能/修复必须 TDD:** RED (failing test) → GREEN (implementation) → regression。
7. **声称完成前必须 fresh verification。** 不得复用之前会话的测试结果。
8. **不得自我验收替代独立验收。** 输出 handoff 后停止。
9. **遇到阻塞只能标 BLOCKED/INCOMPLETE，不降低门栅。**

---

## 18. 旧计划迁移说明

### 保留的章节

原 `design.md` 和 `plan.md` 中以下内容保留:
- §1 目标与边界 (不变)
- §2 成功定义 (exact-5 + 15%/5% 门槛不变)
- §3 固定测试规程 (不变)
- §4.1 STM32 固件职责 (不变)
- §7 安全与故障处理 (不变)
- §8 首次验收演示 (不变)
- §9 非目标 (不变)
- Task 1/2/3 章节 (已完成)

### 废弃的 Task 4 内容

- 原 plan.md Task 4 "复用数字孪生做候选预筛选和有界搜索" — **完全废弃**
- `sim_candidate_filter.py` — 不再实现
- `campaign_optimizer.py` (旧版本) — 不再实现
- 所有引用旧数字孪生作为 PID 预筛选依据的内容

### 需更新的章节

| 原文件 | 章节 | 更新内容 |
|--------|------|---------|
| `specs/2026-07-28-line-following-pid-closed-loop-design.md` | §4.3 数字模型 | 改为依赖新 v1_twin |
| `specs/2026-07-28-line-following-pid-closed-loop-design.md` | §4.4 优化器与 AI | 明确使用新候选生成器 |
| `plans/2026-07-28-line-following-pid-closed-loop.md` | Task 4 → Phase B/C | 拆分为 4B-0~8 + 4C |
| `plans/2026-07-28-line-following-pid-closed-loop.md` | 文件结构 | 移除旧 Task 4 文件，加入 v1_twin 文件 |
| `plans/2026-07-28-line-following-pid-closed-loop.md` | Task 5/6 | 更新依赖为依赖新 4B/4C |

### (Phase A 中执行)

---

## 19. 最终完成定义

### V1 技术闭环完成

```
Task 1  ✅ 安全参数协议 + 固件边界
   +
Task 2  ✅ 双向通信 + 硬件链路验证
   +
Task 3  ✅ 存储 + 指标 + exact-5
   +
Task 4  ⬜ 最小可信二维数字孪生 (4B) + 候选生成 (4C)
   +
Task 5  ⬜ 真机活动闭环 (5A + 5B)
   +
Task 6  ⬜ 证据只读 + 受保护安全控制 UI + 报告
   =
V1 完成
```

### 不等于

V1 技术闭环完成 **不等于** 最终 Robot Twin AI 平台完成。

### 终极目标 (V1 范围外)

- AI 参与硬件理解、缺陷诊断、设计改良、算法改进
- 仿真 ↔ 实机验证和知识沉淀
- 跨机器人可迁移平台 (Task 7/8)

### V1 证明了什么

**在固定赛道、受限 PID 参数范围内，AI 编排的闭环可以找到经过真车验证的更优参数。**

---

## 20. 自检清单

- [x] 无未决占位符；所有阈值均为可执行公式或明确的实测输入
- [x] 不引用不存在的函数而不定义接口
- [x] 文件路径一致 (使用 `simulation/digital_twin/v1_twin/` 命名空间)
- [x] Task 依赖无环 (4B-0→1→2→3→4→5→6→7→8→4C→5A→5B→6)
- [x] 所有硬件动作有授权门 (§13 安全矩阵)
- [x] 所有完成声明有证据类型 (§14 证据等级)
- [x] 文档对上下文为零的新代理可独立理解 (§2 使用说明 + §16 模板)
- [x] 明确禁止跳转规则 (§4)
- [x] 旧计划迁移路径清晰 (§18)
- [x] 每个 Task 有明确 STOP 条件、硬件需求、回滚路径
- [x] 每个 Task 有自动和人工验收 gate
- [x] Handoff 模板标准化 (§15)
- [ ] **待用户确认:** 摄像头具体型号/接口 (USB/RTSP)、标定板尺寸、车顶标记类型
- [ ] **待用户确认:** 旧 spec/plan 的 Task 4 章节更新 (Phase A) 是否在此纲领后立即执行

---

## 21. 回滚规程

> **背景:** 工作区不是 Git 仓库，无 commit 可 revert。文件可能已被用户独立修改。本规程适用于任何 Task 失败后需要撤销变更的场景。

### 通用原则

1. **只处理本 Task 在 handoff 中列明的新建/修改文件。** 不得触及 handoff 范围外的文件。
2. **删除/覆盖前核对路径和哈希。** 使用 `sha256sum` (Linux) 或 `certutil -hashfile` (Windows) 记录当前文件哈希，与 handoff 中的哈希比对一致后再操作。
3. **取得用户授权。** 任何删除或覆盖操作必须经用户当场确认。
4. **默认保留失败产物和日志供审计。** 除非用户明确要求清理，失败产物保留在 `.embeddedskills/build/` 下。
5. **可恢复的回滚优先。** 将文件移入 `.embeddedskills/rollback/<task_id>/` 临时目录而不是直接删除，以便事后审查。

### 步骤

```text
1. 读取本 Task 的 handoff → 获取 Changed files 清单
2. 对每个文件，读取当前内容并与 handoff 中描述比对
3. 若文件已被用户修改（与 handoff 不匹配）：
   - 停止，报告差异，等待用户决定
4. 若文件与 handoff 一致：
   - 询问用户是否移除/覆盖
   - 获确认后，移入 rollback 目录或删除
5. 更新 handoff 状态为 ROLLED BACK，注明已保留的日志路径
```

---

*文档结束。如有冲突以本纲领最新版本为准。*
