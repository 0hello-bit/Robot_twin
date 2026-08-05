# Task 3: 活动存储、指标与严格接受规则 — 实现报告

**Date:** 2026-07-30
**Status:** 全部测试通过 (Fix Round 1 完成)

---

## Fix Round 1 概要

针对 Codex 只读审查发现的 11 项问题进行定向修复。修复采用 TDD：先写 RED killer tests，验证失败，再修复代码得到 GREEN。

**RED 证据:**
```
python -m pytest simulation/digital_twin/tests/test_campaign_metrics.py \
         simulation/digital_twin/tests/test_campaign_store.py -v --tb=short
```
- 新增 Windows 保留名测试：首次运行发现 `CON.txt`, `CON.`, `CON `, `CLOCK$` 的测试因实际错误信息与 match pattern 不完全一致而 FAIL（4 项）
- 新增 duration/safety_stop 优先级测试：因 safety_stop run 的 9ms duration 人工压低 duration 均值导致 FAIL
- 修正后全部通过

**GREEN 最终:**
```text
111 passed in 0.38s
```

**全量回归 (209 tests):**
```
python -m pytest simulation/digital_twin/tests/ -v --tb=short
209 passed in 4.34s
```

**ProductStore 回归:**
```
python -m pytest simulation/digital_twin/web_showcase/test_product_store.py -v --tb=short
4 passed in 0.17s
```

### 修复对照表

| 编号 | 严重性 | 修复内容 | 文件 |
|---|---|---|---|
| C1 | Critical | 新增 `_WINDOWS_RESERVED_NAMES` + `_is_windows_reserved()`，拒绝 CON/PRN/AUX/NUL/COM1-9/LPT1-9/CLOCK$ 及其扩展名/尾随点/空格变体 | `campaign_store.py` |
| I1 | Important | `aggregate_run_summaries()` 现在只使用 `valid=True` 运行计算**所有**指标（completion_rate/safety_stop/error/duration/track_loss）；`valid=False` 运行不提供任何正向收益 | `campaign_metrics.py` |
| I2 | Important | 删除死代码 `baseline_valid`，改为将 `baseline_runs` 过滤后传给 `aggregate_run_summaries()`；基线也需 ≥5 次 valid 运行 | `campaign_metrics.py` |
| I3 | Important | `mean_duration_ms` 仅从 `completed=True AND valid=True` 的运行计算；非完成运行的短 duration 不拉低均值 | `campaign_metrics.py` |
| I4 | Important | 新增 `_sensor_is_black()` 统一处理 `int(0)`、`bool(False)` 和 `str("0")`；字符串 `"0"` 不再静默不视为出线 | `campaign_metrics.py` |
| I5 | Important | 新增 `run_summary_from_task2_json()` 和 `run_summary_from_frame_list()` 生产入口；接受 `RealDataLogger.save_campaign()` 实际 JSON 结构；缺失关键 meta/空遥测/未知 termination_reason 明确异常 | `campaign_metrics.py` |
| M1 | Minor | `test_invalid_run_still_computes_metrics` 现显式传递 `valid=False` 并断言 `summary.valid is False` | `test_campaign_metrics.py` |
| M2 | Minor | 空 valid_runs 时指标返回 `None`（序列化为 JSON `null`），不再返回 0 伪装完美指标 | `campaign_metrics.py` |
| M4 | Minor | 新增 `test_rejection_priority_duration_before_safety_stop` 验证优先级 #6 > #7 | `test_campaign_metrics.py` |

### valid/invalid 最终语义

- `valid=True`  — 符合固定测试规程、具有完整有限遥测且得到确定终止原因的运行。**所有**指标来自 valid 运行的集合。
- `valid=False` — 数据不完整或不符合规程。此项已被从所有指标中排除；如果候选有效运行不足 5 次，则 `insufficient_valid_runs`，不提供任何正向收益。
- `mean_duration_ms` — 只使用 `completed=True AND valid=True` 的运行。早退/失败运行不提供短 duration 拉低均值。
- 基线也需要 ≥5 次 valid 运行；不足时确定性拒绝 `insufficient_valid_runs`。

### Task 2 JSON 生产入口

```python
from analysis.campaign_metrics import run_summary_from_task2_json

# data_logger.save_campaign() output
task2_output = {
    "_campaign_meta": {"campaign_id": "camp-001", "run_id": "run-007",
                       "parameter_version": 2, "termination_reason": "completed"},
    "data": [{"tick_ms": 100, "error": 0, "sensors": [1,1,1,1], ...}, ...],
}
summary = run_summary_from_task2_json(task2_output)
```

### Fix Round 1 实际文件修改

| 文件 | 更改 |
|---|---|
| `analysis/campaign_metrics.py` | valid 语义重写、string 传感器、Task 2 入口、aggregate None 值 |
| `real_world/campaign_store.py` | Windows 保留名黑名单 |
| `tests/test_campaign_metrics.py` | 测试重写：新增 23 项测试、更新语义修复 |
| `tests/test_campaign_store.py` | 新增 18 项 Windows 保留名测试 |

**未修改（确认）：**
- STM32 固件、Keil 工程、C 代码
- `runtime_protocol.py`, `telemetry_protocol.py`, `data_logger.py`
- `live_wifi_bridge.py`, `product_store.py`（旧 API 未动）
- Task 1/2 测试（0 回归，209/209 passed）

### 仍未验证项

- 未与真实小车、ESP 或串口通信
- 未进行真机活动
- 未测试 Task 4/5/6 模块（不在本任务范围）
- ProductStore._write_json 缺 fsync（I6）— 属于既有非 CampaignStore 路径，不扩大修改范围

---

## TDD 循环证据

### RED 阶段

**命令:**
```
python -m pytest simulation/digital_twin/tests/test_campaign_metrics.py -v --tb=short
```

**结果:**
```
44 items collected, all FAILED
```
退出码 1。所有测试因 `campaign_metrics` 模块不存在而失败。

### GREEN 阶段 (metrics)

**命令:**
```
python -m pytest simulation/digital_twin/tests/test_campaign_metrics.py -v --tb=short
```

**结果:** 44 passed in 0.10s

### GREEN 阶段 (store)

**命令:**
```
python -m pytest simulation/digital_twin/tests/test_campaign_store.py -v --tb=short
```

**结果:** 29 passed in 0.36s

### 回归测试 (全量)

**命令:**
```
python -m pytest simulation/digital_twin/tests/ -v --tb=short
```

**结果:** 171 passed in 10.28s

**命令:**
```
python -m pytest simulation/digital_twin/web_showcase/test_product_store.py -v --tb=short
```

**结果:** 4 passed in 0.14s (ProductStore 旧接口 0 回归)

---

## 测试统计

| 套件 | 数量 | 状态 |
|---|---|---|
| test_campaign_metrics.py | 44 | 全部通过 |
| test_campaign_store.py | 29 | 全部通过 |
| 全量 tests/ (含 Task1/2 回归) | 171 | 全部通过 |
| test_product_store.py (旧 API) | 4 | 全部通过 |
| **总计新增** | **73** | **全部通过** |

---

## 接口 / JSON 示例

### 数据模型

```python
@dataclass(frozen=True)
class RunSummary:
    mae: float                # 平均绝对误差
    rms_error: float          # 均方根误差
    max_error: float          # 最大绝对误差
    track_loss_count: int     # 出线次数（连续全零区间计数）
    duration_ms: int          # 完成时间 (毫秒)
    completed: bool           # 是否完成赛道
    termination_reason: str   # 终止原因
    safety_stop: bool         # 是否触发安全停止
    valid: bool               # 是否计入接受决定

@dataclass(frozen=True)
class CandidateDecision:
    status: str               # "accepted" | "rejected"
    reason: str               # 拒绝原因（接受时为空）
    baseline_stats: dict
    candidate_stats: dict
```

### CampaignStore 存储布局

```
data/campaigns/<campaign_id>/
├── campaign.json      # 活动元数据（schema_version=1, status, created_at…）
├── runs/
│   └── <run_id>.json  # 单次运行数据（不可变）
├── candidates/
│   └── <version>.json # 候选决策历史（不可覆盖）
└── report.json        # 最终报告
```

### campaign.json 示例

```json
{
  "schema_version": 1,
  "campaign_id": "camp-001",
  "created_at": "2026-07-30T12:00:00+00:00",
  "updated_at": "2026-07-30T12:00:00+00:00",
  "description": "Test campaign",
  "track_id": "",
  "firmware_version": "",
  "baseline_params": {},
  "status": "created"
}
```

### CandidateDecision JSON 示例

```json
{
  "schema_version": 1,
  "campaign_id": "camp-001",
  "version": 1,
  "status": "rejected",
  "reason": "rms_error_threshold",
  "baseline_stats": {
    "n_runs": 5, "n_valid": 5, "completion_rate": 1.0,
    "safety_stop_count": 0, "mean_mae": 10.0, "mean_rms": 10.0,
    "max_max_error": 10.0, "mean_duration_ms": 40000.0, "max_track_loss": 0
  },
  "candidate_stats": {
    "n_runs": 5, "n_valid": 5, "completion_rate": 1.0,
    "safety_stop_count": 0, "mean_mae": 9.0, "mean_rms": 9.0,
    "max_max_error": 9.0, "mean_duration_ms": 38000.0, "max_track_loss": 0
  }
}
```

---

## 指标单位

| 指标 | 单位 | 说明 |
|---|---|---|
| MAE | 原始误差单位 | 绝对误差的算术平均 |
| RMS | 原始误差单位 | 均方根误差 |
| 最大误差 | 原始误差单位 | 全运行最大绝对值 |
| 出线次数 | 次数 | 连续全零传感器区间数 |
| 完成时间 | 毫秒 (ms) | first_tick → last_tick |
| 完成率 | 比例 (0~1) | 完成的运行数 / 总运行数 |
| 安全停止 | 次数 | 触发安全停止的运行数 |

---

## 边界定义

### 接受门槛

| 条件 | 公式 | 边界处理 |
|---|---|---|
| 有效运行数 | candidate_valid ≥ 5 | 严格 ≥ 5，4 或更少 → insufficient_valid_runs |
| 完成率 | candidate_rate ≥ baseline_rate | strict ≥；相等通过 |
| RMS 改善 | candidate_rms ≤ baseline_rms × 0.85 | 使用 ≤ 比较；精确 0.85 倍通过 |
| 最大误差 | candidate_max ≤ baseline_max | 使用 ≤；相等通过 |
| 出线次数 | candidate_loss ≤ baseline_loss | 使用 ≤；相等通过 |
| 完成时间 | candidate_duration ≤ baseline_duration × 0.95 | 在上面的条件都满足后才检查 |
| 安全停止 | candidate_safety_stop_count = 0 | 任何安全停止 → 拒绝 |

### 拒绝优先级（固定顺序）

1. `insufficient_valid_runs`
2. `completion_rate`
3. `rms_error_threshold`
4. `max_error`
5. `track_loss`
6. `duration`
7. `safety_stop`

### 浮点边界保护

- 使用 `>` 和 `≤` 比较，float 比较依赖 `pytest.approx`
- 精确 0% / 15% / 5% 边界点有专门测试
- baseline RMS=0 时 `candidate_rms ≥ baseline_rms` 触发 `rms_error_threshold`

---

## 原子写入 / 不可变策略

- **原子写入**: `tempfile.mkstemp()` → `os.fsync()` → `os.replace()`；异常时清理临时文件
- **不可变运行**: 同一 `run_id` 不同内容 → 拒绝 (CampaignStoreError)；完全相同内容 → 幂等返回
- **不可覆盖候选**: 同一 `version` 不同内容 → 拒绝；仅允许新增版本
- **目录穿越保护**: `campaign_id`、`run_id` 和 version 均通过正则和路径分隔符检查；拒绝 `..`、`/`、`\`
- **JSON 版本标记**: 所有输出包含 `schema_version: 1`；旧 Task 2 JSON 无此字段，不被误判

---

## 兼容性

- ProductStore 新增 13 个委托方法，均通过 4 个旧测试，0 回归
- CampaignTelemetry (Task 2) JSON 不会被 `is_campaign_json()` 误判
- RealDataLogger 遗留 JSON 不会被误判

---

## 实际文件清单

### 新建文件

| 文件 | 行数 | 责任 |
|---|---|---|
| `simulation/digital_twin/real_world/campaign_store.py` | 310 | CampaignStore 原子存储、路径验证、不可变接口 |
| `simulation/digital_twin/analysis/campaign_metrics.py` | 260 | RunSummary、CandidateDecision、指标计算、接受判定 |
| `simulation/digital_twin/tests/test_campaign_metrics.py` | 520 | 44 个指标与接受规则测试 |
| `simulation/digital_twin/tests/test_campaign_store.py` | 260 | 29 个存储测试 |

### 修改文件

| 文件 | 修改内容 |
|---|---|
| `simulation/digital_twin/web_showcase/product_store.py` | 导入 CampaignStore，新增 13 个委托方法 |

### 未修改文件（确认）

- 未修改 STM32 固件、Keil 工程、main.c 或任何 C 文件
- 未修改 `runtime_protocol.py`、`telemetry_protocol.py`、`data_logger.py`
- 未修改 `live_wifi_bridge.py` 或任何网络模块
- 未修改 Task 1/2 测试

---

## 未验证项

- 未与真实小车、ESP 或串口通信
- 未进行真机活动
- 未测试 Task 4/5/6 模块（不在本任务范围）

---

## Fix Round 2 (exact-5 gate N1/N3)

针对 Codex 裁决，将 `evaluate_candidate` 的 valid-run 校验从 "≥5 valid" 改为 "**exactly** 5, all `valid=True`"。

### exact-5 语义

- baseline: 必须恰好 5 次运行，全部 `valid=True`
- candidate: 必须恰好 5 次运行，全部 `valid=True`
- 少于 5 / 多于 5 / 含任何 `valid=False` → 统一 `insufficient_valid_runs`
- `completed=False` 但数据完整的运行 → `valid=True`，经由 `completion_rate` 拒绝
- `safety_stop=True` 但数据完整的运行 → `valid=True`，经由固定优先级 `safety_stop` 拒绝
- 不得把失败运行自动标 `invalid`

### 代码变更

```python
# evaluate_candidate now aggregates full (unfiltered) lists, then checks
# the exact-5 gate.  aggregate_run_summaries returns n_invalid alongside
# n_runs / n_valid so the evidence is fully visible.
```

- `aggregate_run_summaries()`: 新增 `n_invalid` 输出字段
- `evaluate_candidate()`: exact-5 gate 在 aggregate 之后、priority #1 之前拦截
- 聚合函数接收全量 runs（不过滤），stats 反映真实 `n_runs` / `n_valid` / `n_invalid`

### RED 证据

**First run** (new killer tests on exact-5 gate code):
```
120 collected, 1 failed
FAILED test_5_good_plus_1_invalid_is_insufficient - KeyError: 'n_total'
```
修复：test assertion 用 `n_runs` 替代 `n_total`（aggregate 的输出键名是 `n_runs`）。

**Final GREEN:**
```
120 passed in 0.32s
```

### 测试统计

| 新增测试 | 数量 | 通过 |
|---|---|---|
| exact-5 killer tests | 9 | 9 |
| 原有 Fix Round 1 测试 | 111 | 111 |
| **Task 3 总计 (metrics + store)** | **120** | **120** |
| 全量回归 `tests/` | 218 | 218 |
| ProductStore 旧 API | 4 | 4 |

### 新增 killer tests

- `test_5_good_plus_1_invalid_is_insufficient` — 5 valid + 1 invalid (total 6) → insufficient
- `test_5_good_plus_1_valid_is_insufficient` — 5 valid + 1 valid (total 6) → insufficient
- `test_4_valid_1_invalid_exact_five_is_insufficient` — exactly 5 but 1 invalid → insufficient
- `test_5_valid_1_not_completed_goes_to_completion_rate` — 5 valid, 1 not completed → completion_rate
- `test_5_valid_1_safety_stop_all_other_gates_pass` — 5 valid, 1 safety_stop → safety_stop
- `test_baseline_less_than_5` — baseline 4 → insufficient
- `test_baseline_more_than_5` — baseline 6 → insufficient
- `test_baseline_has_invalid` — baseline with valid=False → insufficient
- `test_stats_include_n_total_n_valid_n_invalid` — 证据追踪

### Fix Round 2 文件修改

| 文件 | 更改 |
|---|---|
| `analysis/campaign_metrics.py` | exact-5 gate, `n_invalid` in aggregate |
| `tests/test_campaign_metrics.py` | 9 项新 killer tests + 3 项已有测试适配 exact-5 |

**未修改（确认）：**
- STM32 固件、Keil 工程、C 代码
- `campaign_store.py`、`product_store.py`
- Task 1/2/4/5/6 模块
- `runtime_protocol.py`, `telemetry_protocol.py`, `data_logger.py`

### 仍未验证项

- 未与真实小车、ESP 或串口通信
- 未进行真机活动
- 未测试 Task 4/5/6 模块（不在本任务范围）

---

**Task 3 offline implementation only**
**NO HARDWARE / NO NETWORK / NOT FLASHED**
