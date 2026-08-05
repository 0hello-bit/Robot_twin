# Task 4A: Digital Twin Credibility Read-Only Audit Report

**Date:** 2026-07-30
**Audited by:** Robot Twin AI V1
**Scope:** `simulation/digital_twin/` — all credibility-relevant modules
**Status:** Read-only audit; no production code, firmware, tests, configs, JSON data, or Keil project modified.

---

## 1. Executive Conclusion

### NOT READY — 当前数字孪生不可用于筛选真车 PID

**核心判断：数字孪生与真车 STM32 固件之间不存在已验证的校准/对齐关系，现有标定报告均为合成数据且有数据泄漏，不能作为 PID 预筛选依据。**

| 维度 | 结论 | 关键证据 |
|------|------|----------|
| 标定有效性 | ❌ 无效 | calibration_report.json 标记 invalidated，误差恶化 -13.4% |
| 验证可信度 | ❌ 数据泄漏 | real_error == sim_error，PID 相关性 1.0 为假象 |
| 模型参数匹配真车 | ❌ 量级不符 | 固件 Kp 范围 20~50，孪生默认 Kp=0.6 (差 58×) |
| 真车数据存在 | ❌ 不存在 | 无 hil_session.json，无遥测 JSONL，无 campaign 数据 |
| 物理模型标定 | ❌ 合成数据 | motor_model: R²=1.0 RMSE=0；latency: total=0ms |
| 可指导 PID 优化 | ❌ optimizer 范围错误 | 搜索 Kp 1~20，固件边界 20~50；完全不对齐 |

---

## 2. Evidence Matrix

| # | 结论 | 证据文件 | 行号 | 证据类型 | 可信等级 |
|---|------|----------|------|----------|----------|
| E1 | validation 中 real_error == sim_error | `analysis/closed_loop_validator.py` | L197 | 代码分析 | ✅ 已核实 |
| E1b | PID 相关性 1.0 由 data leak 导致 | `data/validation_report.json` | `pid_trend.correlation=1.0` | 文件内容 | ✅ 已核实 |
| E2 | calibration 报告标记 invalidated | `data/calibration_report.json` | `status: "invalidated_legacy_result"` | 文件内容 | ✅ 已核实 |
| E3 | calibration 失败（误差恶化） | `data/calibration_report.json` | `improvement_pct: -13.4` | 文件内容 | ✅ 已核实 |
| E4 | motor_model 完美拟合不可能 | `calibration/models/motor_model.json` | `r_squared: 1.0, rmse: 0.0` | 文件内容 | ✅ 已核实 |
| E5 | latency_model total=0ms 不可能 | `calibration/models/latency_model.json` | `total_latency_ms: 0` | 文件内容 | ✅ 已核实 |
| E6 | 固件 Kp 35.0 vs 孪生 Kp 0.6 | `程序/main.c` vs `config.py` | `#define PID_KP 35.0f` vs `DEFAULT_KP = 0.6` | 对比分析 | ✅ 已核实 |
| E7 | 固件 Kd 10.0 vs 孪生 Kd 0.15 | `程序/main.c` vs `config.py` | `#define PID_KD 10.0f` vs `DEFAULT_KD = 0.15` | 对比分析 | ✅ 已核实 |
| E8 | optimizer 搜索范围与固件边界不对齐 | `control_sandbox/pid_optimizer.py` vs `twin_control_protocol.h` | Kp_range=(1,20) 但固件 Kp 20~50 | 对比分析 | ✅ 已核实 |
| E9 | 无真车遥测数据文件 | `data/` 目录扫描 | 仅有 calib/valid report 与 product 文件 | 目录审计 | ✅ 已核实 |
| E10 | 验证时间戳在标定之前 | `data/validation_report.json` vs `calibration_report.json` | 1780059993 < 1780060851 | 时间戳对比 | ✅ 已核实 |
| E11 | 孪生传感器几何未确认 | `config.py` vs `main.c` | 孪生 SENSOR_OFFSETS=[-15,-5,5,15]，固件未找到对应定义 | 代码分析 | ⚠️ 证据不足 |
| E12 | train_ppo.py/rl_env 与 V1 PID 无直接关系 | `rl_env/car_env.py` | RL 训练用，非 V1 PID 优化功能 | 代码分析 | ✅ 已核实 |

### 数据泄漏详细分析

**`analysis/closed_loop_validator.py` `validate_open_loop()` 方法（L121-207）：**

```python
# L196-197: 仿真轨迹直接复制真实 error！
'error': rec.get('error', 0),   # ← 这里 rec 是真实数据
```

然后在 `get_mismatch_heatmap()`（L219-235）：
```python
'real_error': r.get('error', 0),
'sim_error': s.get('error', 0),  # s.error == r.error（因为从同一来源复制）
```

结果：`validation_report.json` 中 100 个 heatmap 点的 `real_error == sim_error` 完全一致，且 `pid_trend.correlation = 1.0` 是虚假的。

---

## 3. Module Classification Table

| 模块 | 路径 | 入口/类 | 输入 | 输出 | 分类 | 说明 |
|------|------|---------|------|------|------|------|
| PlantModel | `control_sandbox/plant_model.py` | PlantModel.step() | PWM, dt | sensors, state | **2-需适配** | 物理模型基础好，但默认参数未标定 |
| PID Controller | `simulator/pid.py` | PIDController.compute() | error, dt | output | **2-需适配** | 算法合理，但 scale 与固件不同 |
| 控制器仿真 | `control_sandbox/controller_emulator.py` | SimpleController/AdvancedController | sensors | PWM | **2-需适配** | STM32 行为复制，但未经真机验证 |
| 标定循环 | `calibration/calibration_loop.py` | CalibrationLoop.calibrate() | real_records | params | **1-可复用** | 架构正确，但缺少真车数据 |
| 模型更新器 | `calibration/model_updater.py` | ModelUpdater.calibrate() | params, callback | result | **1-可复用** | EMA 阻尼、梯度裁剪完善 |
| DTW 匹配器 | `calibration/trajectory_matcher.py` | DTWMatcher.align() | real, sim | distance | **1-可复用** | DTW 算法可独立使用 |
| 闭环验证器 | `analysis/closed_loop_validator.py` | ClosedLoopValidator.validate_open_loop() | real_data | report | **3-仅演示** | 存在数据泄漏，需修复 |
| 模型误差评估 | `analysis/model_error.py` | ModelErrorEvaluator.evaluate() | real, sim | trust_score | **1-可复用** | 评分方法合理 |
| 模型置信度 | `analysis/model_confidence.py` | ModelConfidence.evaluate() | errors, stability | score | **1-可复用** | 多维评分合理 |
| 行为匹配 | `behavior_match/behavior_matcher.py` | BehaviorMatcher.compare() | sim_log, real_log | match_score | **1-可复用** | 5 维对比完善 |
| PID 优化器 | `control_sandbox/pid_optimizer.py` | PidOptimizer.grid_search() | Kp/Kd/Ki 范围 | best_params | **2-需适配** | 搜索范围与固件边界不匹配 |
| A/B 测试 | `analysis/ab_test_runner.py` | ABTestRunner.run() | params_a/b, real_data | winner | **1-可复用** | 方法合理 |
| campaign 指标 | `analysis/campaign_metrics.py` | evaluate_candidate() | baseline/candidate runs | CandidateDecision | **1-可复用** | strict exact-5 规则完善 |
| campaign 存储 | `real_world/campaign_store.py` | CampaignStore | campaign data | JSON 文件 | **1-可复用** | 原子写入、不可变设计 |
| 运行时协议 | `real_world/runtime_protocol.py` | ParameterCommand | PID params | ASCII 帧 | **1-可复用** | 与固件边界一致 |
| WiFi 桥 | `real_world/wifi_bridge.py` | WifiBridge | TCP bytes | telemetry | **1-可复用** | 框架完整 |
| PPO 训练 | `train_ppo.py` | CurriculumPPOTrainer | env | model | **4-无关** | RL 训练，非 V1 PID 功能 |
| 3D 仿真 | `main_3d.py` | — | — | — | **3-仅演示** | 可视化用途，不参与 PID 优化 |
| 行为标定模型 JSON | `calibration/models/*.json` | — | — | param dict | **3-仅演示** | 合成数据，R²=1.0，不可信 |

### 分类说明

1. **可复用** — 代码质量好，架构正确，只需数据接入即可用于 V1
2. **需适配后复用** — 核心逻辑合理但参数/接口需与固件对齐
3. **仅演示/Mock/无关** — 合成数据、可视化或非 V1 用途
4. **无法确认** — 缺乏足够信息判断

---

## 4. End-to-End Data Flow (当前实际状态)

```
[真车 STM32]  →  (ESP TCP)  →  [real_world/wifi_bridge]  →  [data_logger]
    ↓ 不存在                                                                   ↓ 不存在
[真车遥测 JSON]  ─── 不存在 ──→  [calibration/SimReplayCalibrator]  ──合成──→  [calibration_report.json]
                                                                                        ↓ invalidated
[合成数据替代]  ──────────────→  [calibration/models/*.json]  ──R²=1.0──→  [PlantModel 默认参数]
                                                                                        ↓
[analysis/closed_loop_validator]  ──data leak──→  [validation_report.json]
                                                                                        ↓ trust_score=57.8 (虚假)
[control_sandbox/pid_optimizer]  ──范围错误──→  [候选人筛选]  ──不可用──→  [真车 PID]
```

**关键断裂点：**
1. ❌ 真车 → PC 遥测数据链路从未产生过持久化文件
2. ❌ calibration 使用了不存在真车的合成数据，且失败
3. ❌ validation 存在 data leak，trust_score 无效
4. ❌ optimizer 搜索范围与固件边界不对齐（Kp: 孪生 1~20 vs 固件 20~50）

---

## 5. Calibration/Validation 真实性审计

### 5.1 calibration_report.json 审计

| 字段 | 值 | 真实性判断 |
|------|-----|-----------|
| `status` | `invalidated_legacy_result` | **✅ 诚实标记不可用** |
| `successful` | `false` | **✅ 诚实标记失败** |
| `improvement_pct` | -13.4 | **✅ 误差恶化，符合代码逻辑** |
| `iterations` | 2 | **⚠️ 仅 2 次迭代，不正常** |
| `steering_tau` change | 0.05→0.5 (+900%) | **⚠️ 剧烈变化，不稳定** |
| `n_records` | 200 | **❓ 无对应数据文件** |

### 5.2 validation_report.json 审计

| 字段 | 值 | 真实性判断 |
|------|-----|-----------|
| `method` | `open_loop` | **✅ 使用简单运动学模型** |
| `trust_score` | 57.8 | **❌ 因 data leak 部分无效** |
| `pid_trend.correlation` | 1.0 | **❌ 完美相关，data leak 导致** |
| `pid_trend.direction_match_pct` | 100.0 | **❌ 同上** |
| `sensor_match.match_pct` | 50.0 | **⚠️ 50%=随机猜测（孪生输出固定 [1,1,1,1]）** |
| `trajectory.rmse` | 40.045 | **❓ 无法验证无真值数据** |
| `real_error` == `sim_error` | 全部 100 点 | **❌ 确认 data leak** |

### 5.3 模型文件审计

| 文件 | 可疑字段 | 判断 |
|------|---------|------|
| `motor_model.json` | R²=1.0, RMSE=0.0, n_samples=1000 | **❌ 真实数据不可能** |
| `steering_model.json` | K=0.121, td=0, tau=0, fit_quality=0 | **⚠️ tau=0 不合理** |
| `latency_model.json` | total_latency_ms=0, jitter_ms=255 | **❌ total=0 不可能；jitter>total 矛盾** |

### 5.4 时间戳异常

```
validation_report.json timestamp:   1780059993 → 2026-05-29 13:06:33
calibration_report.json timestamp:  1780060851 → 2026-05-29 13:20:51
motor_model.json timestamp:         1780059993
steering_model.json timestamp:      1780059993
latency_model.json timestamp:       1780059993
```

**验证（1780059993）在标定（1780060851）之前运行** — 逻辑顺序错误。模型文件的 timestamp=1780059993 与 validation 相同，说明它们是在同一次运行中产生的（非独立获取）。

---

## 6. Key Blockers (按 Critical / Important / Minor 排序)

### 🔴 Critical

| # | 阻塞项 | 影响 | 证据 |
|---|--------|------|------|
| B1 | **无真车校准数据** | 无法执行任何 sim2real 校准 | 目录审计无遥测 JSON |
| B2 | **Validation data leak**（real_error→sim_error） | PID 趋势完美相关是假象 | closed_loop_validator.py:197 |
| B3 | **Firmware PID scale vs 孪生不匹配**（Kp 58×差） | 孪生优化结果完全不能用于真车 | main.c PID_KP=35 vs config.py DEFAULT_KP=0.6 |
| B4 | **优化器搜索范围与固件边界不对齐** | 搜索候选全部在固件范围之外 | pid_optimizer.py Kp 1~20 vs 固件 20~50 |

### 🟠 Important

| # | 阻塞项 | 影响 | 证据 |
|---|--------|------|------|
| B5 | 标定模型文件为合成数据 | R²=1.0 (motor), latency=0ms | motor_model.json, latency_model.json |
| B6 | 时间戳异常（validation 在 calibration 前） | 数据生成流程不严谨 | 相差 ~14min |
| B7 | 孪生传感器几何未与固件验证 | 传感器位置/间距影响误差计算 | config.py vs main.c 无可比定义 |
| B8 | 孪生使用连续位置误差，固件用离散加权误差 | 误差模型不同导致 PID 行为不同 | control_fitness.py vs main.c L653-655 |

### 🟡 Minor

| # | 阻塞项 | 影响 | 证据 |
|---|--------|------|------|
| B9 | rl_env/train_ppo.py 非 V1 PID 用途 | 代码存在但不会用于 PID 优化 | car_env.py control_mode='rl' |
| B10 | 无单元测试覆盖 calibration_report 生成 | 无法验证报告正确性 | 仅有 test_calibration_safety.py |
| B11 | 3D 扫描/相机仿真非 V1 需求 | V1 不需要 | 设计规格 §9 非目标 |

---

## 7. Task 4B 数据采集与校准输入清单

### 7.1 俯视相机系统最低要求

| 项目 | 要求 | 当前状态 |
|------|------|---------|
| 赛道坐标系 | 俯视相机标定后建立世界坐标 | `tracking/` 模块已实现 homography 标定 |
| 相机标定 | 4 点标定 + 畸变校正 | `calibrate_floor.py` 已实现，需实地操作 |
| 车体标记 | AprilTag 36h11 贴于车顶 | `generate_apriltag.py` 已实现 |
| 时间同步 | PC 时间戳对齐遥测与视觉 | 需在 capture 循环中统一时间源 |
| 起始姿态 | 每次运行记录初始位置/角度 | 需新增逻辑 |
| 轨迹采样率 | ≥30fps（30ms 周期匹配固件） | tracking 默认 30fps，可配置 |

### 7.2 小车遥测最低要求

| 字段 | 来源 | Task 2B 状态 |
|------|------|-------------|
| campaign_id | PC 生成 | ✅ runtime_protocol.py 已实现 |
| run_id | PC 生成 | ✅ runtime_protocol.py 已实现 |
| parameter_version | PC 生成 | ✅ runtime_protocol.py 已实现 |
| Kp / Ki / Kd | 固件回传确认值 | ✅ runtime_protocol + twin_control_protocol 已实现 |
| 速度上限 | 固件回传确认值 | ✅ runtime_protocol + twin_control_protocol 已实现 |
| 四路传感器 (S0~S3) | 固件实时遥测 | ✅ frame_parser decode_telemetry 已实现 |
| error | 固件计算 | ✅ frame_parser payload byte 16-17 |
| PID output | 固件计算 | ✅ frame_parser payload byte 18-19 |
| 四路 PWM (M1~M4) | 固件实时遥测 | ✅ frame_parser payload byte 8-15 |
| tick_ms | 固件运行时间 | ✅ frame_parser payload byte 20-21 |
| 终止原因 | 固件 S 帧 | ✅ runtime_protocol RunStatus |

### 7.3 Task 2B 数据链缺失/不可靠字段

| 字段 | 问题 | 影响等级 |
|------|------|---------|
| **car_x, car_y** | 蓝牙/BLE 帧无位置；需俯视相机补充 | 🔴 Critical |
| **car_angle** | 蓝牙/BLE 帧有 yaw(int32/100)，精度待验证 | 🟠 Important |
| **赛道版本 ID** | 需人工/流程保证每次记录 | 🟡 Minor |
| **电池电压** | BLE status 帧有 battery_mv，需验证剩余电量影响 | 🟡 Minor |

### 7.4 校准集与验证集分离

为防止同一数据既训练又验收，强制：

1. **按时间分离**：前 N 次运行（如 5 次基线）→ 校准集；后 M 次运行（如 3 次）→ 验证集
2. **按运行分离**：calibration 只使用校准集 run_id，verification 只使用验证集 run_id
3. **JSON Schema 约束**：campaign 存储中每个 run 标记 `dataset: "calibration" | "validation" | "test"`
4. **代码硬检查**：`calibrate()` 和 `verify()` 方法应拒绝 overlap。当前 `sim_replay_calibrator.py` 用同一 `self.replay_data` 做 pre/post 验证 → 需修复

### 7.5 模型资格筛选 PID 的可测量门控

| 门控 | 测量方法 | 通过标准 |
|------|---------|---------|
| 轨迹 RMSE | 俯视相机追踪 vs 仿真轨迹 | <10px（标定后） |
| 传感器匹配率 | 真车传感器序列 vs 仿真传感器 | ≥80% |
| PID 趋势相关性 | 真车 error 序列 vs 仿真 error 序列 | ≥0.7 |
| 转向响应一致性 | 角速度 RMSE | <5°/s |
| 模型置信度 | model_confidence.evaluate() | ≥MEDIUM |

**重点：候选排序正确性优先于轨迹动画相似性。** 即使轨迹 RMSE 偏高，只要模型对不同 PID 参数的优劣排序与真车一致，即可用于筛选。

---

## 8. Three Approach Comparison for Task 4B

### 方案 1：修复现有物理模型

| 维度 | 评估 |
|------|------|
| 做法 | 采集真车数据 → 重新校准 PlantModel 参数 → 修复 data leak → 验证 |
| 优点 | 架构已存在（calibration_loop、model_updater、trajectory_matcher）；DTW、EMA 阻尼等高质量组件可直接复用 |
| 缺点 | 需要大量真车运行数据（≥5 runs × 多组 PID）；模型参数多（10 个），调参空间大 |
| 风险 | 模型仍可能不够准（非线性效应难建模）；迭代周期长 |
| **可行性** | ⭐⭐⭐ — 架构好但数据需求大 |

### 方案 2：建立最小数据驱动行为模型 ✅ 推荐

| 维度 | 评估 |
|------|------|
| 做法 | 仅使用真车遥测的 `(sensors, error, PWM)` 建立黑箱映射；不涉及完整运动学；用简单回归/查找表预测 output |
| 优点 | 数据需求少（一组 baseline + 3~5 组候选即可）；与四路离散传感器天然匹配；不需要俯视相机（仅用遥测即可） |
| 缺点 | 无法预测轨迹/位置；仅预测 error 序列和完成时间 |
| 风险 | 对未见过的 PID 参数外推能力有限 |
| **可行性** | ⭐⭐⭐⭐⭐ — 最适应当前条件 |

### 方案 3：混合模型（物理 + 数据驱动）

| 维度 | 评估 |
|------|------|
| 做法 | PlantModel 保留运动学框架，但用真车数据学习残差补偿（error residual model） |
| 优点 | 结合物理约束与数据驱动；资源充足时可逐步提高精度 |
| 缺点 | 复杂度最高；需要同时维护物理参数和 ML 模型；当前条件无编码器、无俯视相机 |
| 风险 | 实施周期最长；两套模型互调困难 |
| **可行性** | ⭐⭐ — 非当下最佳选择 |

### 推荐：方案 2（最小数据驱动）

**理由：**
1. **无编码器** — 无法准确测量速度/加速度，物理模型关键参数无法校准
2. **四路离散传感器** — 天然适合离散 pattern → error 查找表映射
3. **俯视相机可用但非必需** — 方案 2 可以先不依赖相机起步
4. **当前最关键问题** — PID 参数优劣排序，不是轨迹绝对精度
5. **task2b 遥测管道（runtime_protocol.wifi_bridge）已就绪** — 只需接入数据

---

## 9. Task 4B 进入条件和完成判据

### 进入条件（Entry Criteria）

- [ ] 真车完成 ≥5 次基线运行并通过遥测管道记录（`campaign_store`）
- [ ] 固件 `twin_control_protocol` 参数范围已确认与 runtime_protocol 一致
- [ ] 至少 1 组候选 PID 参数已通过固件边界检查
- [ ] PC → ESP → STM32 → PC 闭环通信已验证（Task 2B）

### Task 4B 执行步骤（不实现，仅规划）

1. **准备**：赛道环境记录，相机标定（如需），电池供电记录
2. **基线采集**：固定 PID 运行 5 次，保存完整遥测
3. **候选生成**：用 bounded grid/random 生成 ≤12 个候选
4. **模型筛选**：用最小行为模型预测各候选评分
5. **真车验证**：部署候选，每参数 ≤5 次运行
6. **接受/拒绝**：按 exact-5 规则判定
7. **报告**：输出可追溯的候选排序和最终结论

### 完成判据（Completion Criteria for Task 4B）

- ✅ 最小行为模型可以正确排序真车 PID 候选（排序正确率 ≥80%）
- ✅ 模型预测的 RMS error 方向（更好/更差）与真车一致
- ✅ 报告明确标注当前置信度等级
- ✅ 使用独立验证集（非校准集数据）评估

### 文件级保留/隔离/重写/新增建议

| 操作 | 路径 | 理由 |
|------|------|------|
| **保留** | `real_world/runtime_protocol.py` | 与固件边界一致，核心协议 |
| **保留** | `real_world/campaign_store.py` | 原子写入不可变存储，设计优秀 |
| **保留** | `analysis/campaign_metrics.py` | strict exact-5 规则完善 |
| **保留** | `analysis/model_confidence.py` | 多维评分合理 |
| **保留** | `calibration/trajectory_matcher.py` | DTW 对齐可复用 |
| **保留** | `calibration/model_updater.py` | EMA 阻尼 + 梯度裁剪合理 |
| **隔离** | `control_sandbox/plant_model.py` | 物理模型框架保留，默认参数需置零/标记未校准 |
| **隔离** | `analysis/closed_loop_validator.py` | data leak 修复前不可用 |
| **隔离** | `calibration/models/*.json` | 全部为合成数据，标记不可用 |
| **重写** | `analysis/closed_loop_validator.py validate_open_loop()` | 需修复 data leak（L197） |
| **重写** | `control_sandbox/pid_optimizer.py` 搜索范围 | 必须对齐 `TWIN_CONTROL_KP_MIN/MAX`（20~50） |
| **重写** | `config.py` PID 默认值 | 必须对齐固件 baseline（Kp=35, Kd=10, Ki=0） |
| **新增** | `analysis/pid_candidate_ranker.py` | 最小行为模型：sensor→error→PWM 映射 |
| **新增** | `calibration/data_splitter.py` | 校准集/验证集分离强制检查 |
| **新增** | `tests/` 覆盖 data_leak 回归 | 防止 real_error/sim_error 再次泄漏 |

---

## 10. Read Files, Run Commands, Results, Unverified Items

### 实际读取的文件

- ✅ `docs/superpowers/specs/2026-07-28-line-following-pid-closed-loop-design.md` — V1 设计规格
- ✅ `docs/superpowers/plans/2026-07-28-line-following-pid-closed-loop.md` — V1 实现计划
- ✅ `simulation/digital_twin/README.md` — 孪生平台概述
- ✅ `simulation/digital_twin/docs/digital_twin.md` — 孪生系统文档
- ✅ `simulation/digital_twin/docs/sim2real.md` — Sim2Real 转移文档
- ✅ `simulation/digital_twin/data/calibration_report.json` — 标定报告
- ✅ `simulation/digital_twin/data/validation_report.json` — 验证报告
- ✅ `simulation/digital_twin/control_sandbox/plant_model.py` — 物理模型
- ✅ `simulation/digital_twin/control_sandbox/pid_optimizer.py` — PID 优化器
- ✅ `simulation/digital_twin/calibration/calibration_loop.py` — 标定循环
- ✅ `simulation/digital_twin/calibration/sim_replay_calibrator.py` — 回放标定器
- ✅ `simulation/digital_twin/calibration/model_updater.py` — 模型更新器
- ✅ `simulation/digital_twin/calibration/trajectory_matcher.py` — DTW 对齐
- ✅ `simulation/digital_twin/analysis/closed_loop_validator.py` — 闭环验证器
- ✅ `simulation/digital_twin/analysis/model_error.py` — 模型误差评估
- ✅ `simulation/digital_twin/analysis/model_confidence.py` — 模型置信度
- ✅ `simulation/digital_twin/analysis/ab_test_runner.py` — A/B 测试
- ✅ `simulation/digital_twin/analysis/campaign_metrics.py` — Campaign 指标
- ✅ `simulation/digital_twin/analysis/control_fitness.py` — 控制适应性
- ✅ `simulation/digital_twin/real_world/runtime_protocol.py` — 运行时协议
- ✅ `simulation/digital_twin/real_world/campaign_store.py` — Campaign 存储
- ✅ `simulation/digital_twin/real_world/wifi_bridge.py` — WiFi 桥
- ✅ `simulation/digital_twin/real_world/frame_parser.py` — 帧解析器
- ✅ `simulation/digital_twin/behavior_match/behavior_matcher.py` — 行为匹配器
- ✅ `simulation/digital_twin/config.py` — 全局配置
- ✅ `程序/3. 麦轮巡线小车/User/main.c` — 固件主控（仅读取宏定义和 PID 部分）
- ✅ `程序/3. 麦轮巡线小车/User/twin_control_protocol.h` — 协议头文件
- ✅ `calibration/models/motor_model.json` — 电机模型
- ✅ `calibration/models/steering_model.json` — 转向模型
- ✅ `calibration/models/latency_model.json` — 延迟模型

### 执行的分析命令

```bash
# 不修改任何文件。所有分析通过读文件 + 代码审查 + 对比分析完成。
```

| 分析 | 方法 | 结果 |
|------|------|------|
| 标定报告真实性 | JSON 内容审计 | invalidated, -13.4%, 不可用 |
| 验证报告真实性 | JSON 内容 + 代码追溯 | data leak: real_error==sim_error |
| 模型文件真实性 | JSON 内容审计 | 合成数据：R²=1.0, latency=0ms |
| 固件 PID vs 孪生 PID | 代码对比 | Kp 58×差, Kd 67×差 |
| optimizer 范围审计 | 代码对比 | 搜索范围 Kp 1~20 vs 固件 20~50 |
| 数据文件存在性 | 目录扫描 | 无真车数据文件 |
| 时间戳审计 | JSON timestamp 对比 | validation(1780059993) < calibration(1780060851) |
| rl_env V1 相关性 | 代码审查 | 不直接相关 |

### 已验证项目

- ✅ `closed_loop_validator.py:197` — data leak 确认（`'error': rec.get('error', 0)`）
- ✅ `validation_report.json` 中 real_error == sim_error — 100 个 heatmap 点全部一致
- ✅ `calibration_report.json` status = `invalidated_legacy_result`
- ✅ `motor_model.json` R²=1.0, RMSE=0.0 — 真实数据不可能
- ✅ 固件 main.c PID_KP=35.0 vs config.py DEFAULT_KP=0.6 — 量级不符
- ✅ `twin_control_protocol.h` Kp 20~50 vs `pid_optimizer.py` kp_range=(1,20) — 范围不匹配
- ✅ 无 `hil_session.json` 或任何真车遥测数据文件
- ✅ 时间戳异常：validation 在 calibration 前

### 未验证项目

- ⚠️ 固件传感器几何（SENSOR_OFFSETS）— 固件 `main.c` 中未找到可比较的宏定义
- ⚠️ 真车实际运行的 baseline PID 值 — 需要连接真车（Task 4A 禁止）
- ⚠️ ESP TCP 遥测实际帧格式 — 需要 ESP 连接确认
- ⚠️ 赛道尺寸和几何 — 需要俯视相机/手动测量

---

## 11. 声明

- ✅ **未修改任何生产源代码**（包括 firmware、Python 模块、测试、配置）
- ✅ **未修改任何校准模型、JSON 数据、JSONL 遥测文件**
- ✅ **未连接小车、ESP、串口、ST-Link、摄像头或任何网络设备**
- ✅ **未执行固件构建、烧录、复位或电机动作**
- ✅ **未安装任何依赖项**
- ✅ **未运行任何仿真或真车测试**（仅进行文件级代码审查和分析）
- ✅ **本报告所有结论均来自文件内容分析和代码审查** — 任何标为"已核实"的证据均可通过重新读取原始文件再现
