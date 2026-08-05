## Handoff — Task 4B-0

### Task ID / Status
- **Task:** 4B-0 — 数据契约、测试夹具与旧模型隔离
- **Status:** COMPLETE ✅（自动验收 gate 全部 PASS）
- **上下文:** 4B-D 返工 v2 完成后，用户明确指示"开始4b-0"，视为对进入 Phase B 的授权（4B-D 正式重新验收仍待用户/独立验证者执行）。

### Changed files

| 操作 | 路径 | 说明 |
|------|------|------|
| NEW | `simulation/digital_twin/v1_twin/__init__.py` (7 行) | v1_twin 命名空间包 |
| NEW | `simulation/digital_twin/v1_twin/v1_twin_errors.py` (20 行) | 领域错误类型：V1TwinError / V1SchemaError / V1CalibrationHoldoutOverlapError / V1IsolationError |
| NEW | `simulation/digital_twin/v1_twin/v1_twin_schema.py` (482 行) | 数据契约：V1Pose / V1TelemetryFrame / V1SyncFrame / V1SensorModelConfig / V1TrackMap / V1CalibrationSet / V1HoldoutSet / V1ModelVersion + JSON 序列化 + assert_disjoint |
| NEW | `simulation/digital_twin/v1_twin/v1_twin_isolation.py` (134 行) | 旧模型隔离检查器（源码静态扫描主门 + sys.modules 诊断） |
| NEW | `simulation/digital_twin/tests/test_v1_twin_schema.py` (297 行) | schema 序列化/不可变/单位校验/隔离测试 |
| NEW | `simulation/digital_twin/tests/test_v1_twin_isolation.py` (131 行) | 隔离检查器测试 |
| — | 既有生产源码、测试、固件、Keil 工程、配置、模型 JSON、数据文件 | **未修改** |

新建文件 sha256（供 §21 回滚审计）：
- `__init__.py`: `30fdcff3…`
- `v1_twin_errors.py`: `3e249299…`
- `v1_twin_schema.py`: `e6bdf098…`
- `v1_twin_isolation.py`: `fc1bbf60…`
- `test_v1_twin_schema.py`: `0ddb9bc0…`
- `test_v1_twin_isolation.py`: `ada7a6f7…`

### Commands

```bash
"<PYTHON_INTERPRETER>" -m pytest simulation/digital_twin/tests/test_v1_twin_schema.py -v
"<PYTHON_INTERPRETER>" -m pytest simulation/digital_twin/tests/test_v1_twin_isolation.py -v
# 冲突/回归验证（与遗留 config 导入测试 + Task 3 测试同进程）:
"<PYTHON_INTERPRETER>" -m pytest simulation/digital_twin/tests/test_v1_twin_schema.py simulation/digital_twin/tests/test_v1_twin_isolation.py simulation/digital_twin/tests/test_config.py simulation/digital_twin/tests/test_sensor.py simulation/digital_twin/tests/test_campaign_metrics.py simulation/digital_twin/tests/test_campaign_store.py simulation/digital_twin/tests/test_runtime_protocol.py
```

### Exact results and exit codes

```
# TDD RED→GREEN
Step1 (schema 测试, 实现前):  ModuleNotFoundError: No module named 'v1_twin'   (RED)
Step2 (schema 实现后):        25 passed in 0.07s                              (GREEN)
Step3 (隔离测试, 实现前):     ImportError: cannot import name 'v1_twin_isolation' (RED)
Step4 (隔离实现后):           9 passed in 0.09s                                (GREEN)

# 自动验收 gate (§6a)
pytest test_v1_twin_schema.py -v        -> 25 passed
pytest test_v1_twin_isolation.py -v     -> 9 passed
两者同跑                              -> 34 passed in 0.10s

# 冲突/回归（同进程，含遗留 config 导入）
34 + test_config + test_sensor + test_campaign_metrics + test_campaign_store + test_runtime_protocol
    -> 195 passed in 0.69s
exit=0
```

> **TDD 过程中修正的测试断言（非实现缺陷）:** `test_scan_imports_detects_each_legacy_prefix` 初版用字典短名（如 `closed_loop_validator`）做 `startswith` 前缀断言，而实际违规模块路径是 `analysis.closed_loop_validator`（含父包前缀）。实现正确检测了全部违规；修正测试为校验完整违规模块路径后全绿。

### Artifact/log/report paths
- `.embeddedskills/build/v1_task4b0/handoff.md` — 本文件

### Verified facts
- ✅ **[VERIFIED SOFTWARE]** — `test_v1_twin_schema.py` 25/25 PASS：JSON 往返（8 类型）、frozen 不可变、单位/字段校验（mm/rad/ns/ms）、sensors 0/1 二进制、calibration↔holdout run_id 交集检查、schema_version 恒序列化
- ✅ **[VERIFIED SOFTWARE]** — `test_v1_twin_isolation.py` 9/9 PASS：源码静态扫描检出全部旧路径、v1_twin 包源码零旧路径引用（`scan_package_source() == {}`）、sys.modules 运行期诊断
- ✅ **[VERIFIED SOFTWARE]** — 195 项同进程回归全过（含遗留 `config` 导入测试），无回归、无命名空间冲突
- ✅ **[VERIFIED SOFTWARE]** — v1_twin 四个源文件经隔离主门扫描，不 import 任何 `control_sandbox` / `analysis.closed_loop_validator` / `calibration.sim_replay_calibrator` / `config`

### Inferences
- 🔶 隔离检查器以**源码静态扫描**为确定性主门（AST 解析，不依赖 pytest 会话状态）；sys.modules 扫描为运行期诊断。原因：既有测试（test_config/test_sensor 等）会在同进程导入遗留 `config`，纯 sys.modules 检查在全集回归中会产生误报。

### Unverified items
- ⚪ **4B-0 人工验收 gate 未满足** — 需用户确认 schema 字段和单位满足需求（纲领 §6a）
- ⚪ 未在真车/摄像头/固件上验证任何数据 — 本任务纯离线（⚪）
- ⚪ 单元约定（传感器 0/1 阈值）最终以固件 `main.c` 的 `SENSOR_THRESHOLD` 为权威，尚未在 4B-5 中与固件逐行核对

### Scope review
- 未修改任何既有生产源代码、测试、配置、固件、Keil 工程、模型 JSON 或真实数据 ✓
- 仅新建 v1_twin 命名空间内 4 个源文件 + 2 个测试文件（均在 §6a 允许新建清单内）✓
- 未连接摄像头、小车、串口或网络设备 ✓
- 未烧录、未复位、未发送电机命令 ✓
- 未安装软件或修改系统环境 ✓
- 未 git init ✓

### Hardware actions performed
- ❌ 无

### Safety/rollback state
- 无硬件安全隐患
- 本任务为纯新建文件；回滚 = 删除 handoff Changed files 所列 6 个文件（§21 规程：操作前核对哈希，默认保留失败产物于 `.embeddedskills/build/`）

### Next prerequisites
- **下一 Task: 4B-1（摄像头实时输入 Gate 0）** — 🔴 需要硬件（摄像头实时流）
- ⬜ 4B-0 自动验收 gate 已 PASS；人工验收 gate（用户确认 schema 字段/单位）待用户执行
- ⬜ 4B-1 前置：4B-0 完成 + 用户提供 USB/RTSP 摄像头实时流 + 连续 10 分钟验证（fps ≥ 20, drop ≤ 5%, 时间戳单调）

---

*Task 4B-0 COMPLETE. 等待用户确认人工验收 gate 后由用户指示进入 4B-1。*
