# Task 4B-4 最终离线验收报告

> **生成时间**: 2026-08-01
> **代理**: DeepSeek V4 Pro Offline Wrap-up Agent
> **权威入口**: 本文件为 Task 4B-4 离线验收的单一权威入口。硬件 Gate 执行手册见
>   `task4b4_hardware_gate_runbook.md`，用户操作要求见 `USER_ACTION_REQUIRED.md`。

---

## 1. 最终状态

**`SOFTWARE ACCEPTED / HARDWARE GATE READY`**

Task 4B-4 离线工作已全部完成，可以安全进入硬件 Gate。本文件为离线验收的最终记录。

**不得标 COMPLETE** — 尚未通过真机同步 Gate（coverage ≥95% / 全量 p95 ≤33.3ms），
也未经硬件恢复测试（USART 移位寄存器残留 + ESP AT parser 恢复行为）。

---

## 2. 实际修改范围

### 修复阶段总览

| 阶段 | 描述 | 来源 handoff § | 修改文件数 |
|---|---|---|---|
| A | 异步 CIPSEND / 真实时钟 / PC 契约 / 同步 Gate | §2–§6 | ~18 |
| B | Codex review remediation（C4100 / 代次泄漏 / 清理） | §13 | ~12 |
| C | TX Boundary Coordinator（统一连接边界） | §15 | ~10 |
| D | CLOSED-Path Evidence Fix（etc_handle_terminal 提取） | §16 | 4+hostc sync |

### 修改文件清单

**固件（C，Keil Target 1）**

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `User/main.c` | MODIFIED | 三相 ESP service、TX coordinator 集成、discard_tx_ring_cb |
| `User/stm32f10x_it.c` | MODIFIED | USART1 ISR 增加 TXE 中断排空 TX ring |
| `User/cipsend_tx.c/.h` | NEW+MODIFIED | 非阻塞 CIPSEND TX 状态机；feed_byte ERROR/busy/CLOSED；deadline_stale；W4 C4100 fix |
| `User/cipsend_transaction.c` | MODIFIED | WAIT_PROMPT 路由 srp_feed 检测错误行 |
| `User/tx_frame_queue.c/.h` | NEW | 连接代次 + ACK/STATUS 重试缓冲（纯逻辑） |
| `User/esp_tx_coordinator.c/.h` | NEW+MODIFIED | TX 边界 coordinator；etc_handle_terminal 架构提取 |
| `User/esp_runtime_transport.c/.h` | MODIFIED | 连接代次；AT 行累积过滤 `>` fix |
| `System/mono_time.c/.h` | NEW | TIM3 1kHz → 32 位单调毫秒 |
| `System/mono_time_core.c/.h` | NEW | 纯时间逻辑（回绕安全），Host 可测 |
| `project.uvprojx` | MODIFIED | 新增 System/User 组文件 |

**PC（Python）**

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `v1_twin_schema.py` | MODIFIED | 有符号 PWM + yaw_rad |
| `v1_twin_dataset.py` | MODIFIED | 共同区间 coverage / 全量 p95 / gate |
| `v1_twin_sync.py` | MODIFIED | fit_batched 批次均值 + fit_residuals |
| `v1_twin_pose_tracker.py` | MODIFIED | track() 显式 t_pc_ns 参数 |
| `v1_twin_capture.py` | NEW | 离线可测的采集辅助 |
| `.embeddedskills/build/v1_task4b4/capture_sync_run.py` | MODIFIED | 尺寸核对 / 立即打戳 / fit_batched / run_id fail-closed / 统一清理 |

**测试**

| 文件 | 变更类型 | 测试数 |
|---|---|---|
| `test_v1_twin_schema.py` | MODIFIED | 30 |
| `test_v1_twin_sync.py` | MODIFIED | 8 |
| `test_v1_twin_dataset.py` | MODIFIED | 21 |
| `test_v1_twin_capture.py` | NEW | 6 |
| `test_capture_sync_cleanup.py` | NEW | 5 |
| `test_cipsend_tx.c` | MODIFIED | 14→16 |
| `test_mono_time_core.c` | NEW | 6 |
| `test_tx_frame_queue.c` | NEW | 10 |
| `test_esp_transport_gen.c` | NEW | 5 |
| `test_tx_generation_integration.c` | NEW | 3 |
| `test_coordinator_boundary.c` | NEW | 17 |

### 未触碰文件（SHA-256 与 baseline 一致）

`User/cipsend_transaction.{c,h}`（除 MODIFIED 版本外）、`User/uart_ring.{c,h}`、
`System/Delay.c`。PID 参数、电机方向公式、线损策略代码段未修改。

**禁止触碰范围命中: 0**（`closed_path_scope_review.json` 复核）。

---

## 3. Codex 独立验收结果

Codex 在 2026-08-01 独立复验当前代码，结果如下：

| 复验项 | 结果 | 证据文件 |
|---|---|---|
| 全量 Python（336 tests，Python 3.11） | **336 passed, exit=0** | `full_pytest_remediation.log` |
| Host C 12 套件（MSVC /W4 /WX） | **12/12 PASS, exit=0** | `host_c_tests_fresh.log` |
| Keil Target 1 Rebuild-only | **0 Error(s), 0 Warning(s)**，AXF 生成，未烧录 | `keil_rebuild_closed_path.log` |
| scope_review 哈希 | 一致 | `closed_path_scope_review.json` |

Codex 确认 handoff §13 的 3 个缺口（C4100 / 连接代次 / START 清理）均已修复。
Codex 确认 handoff §15 的 TX Boundary Coordinator 6 个根因已修复。
Codex 确认 handoff §16 的 CLOSED-Path Evidence Fix：`etc_handle_terminal` 已提取，
`test_closed_terminal_discards_all` 真实 path 测试已新增并 PASS。

---

## 4. DeepSeek（本轮离线收尾代理）结果

### 4.1 事实核对

- ✅ handoff §14–§16 与当前代码（closed_path_scope_review.json 哈希）、最新独立结果为一致。
- ✅ Python 全量: **336 passed**（Python 3.11）。handoff §15 的 "294 passed / Python 3.7" 中 6 个失败为 `math.dist` 预存问题（Python 3.7 不支持 `math.dist`），与本次修改无关。**统一证据为 336 passed / Python 3.11。**
- ✅ Host C: **12/12 suites, /W4 /WX, exit=0**，含 coordinator_boundary 17 测试。
- ✅ Keil Rebuild-only: **0 Error(s), 0 Warning(s)**，Code=20144。
- ⚪ CLOSED-path RED 证据保留参见 §5（RED 证据限制）。

### 4.2 离线预检（preflight）

- 预检脚本: `.embeddedskills/build/v1_task4b4_fix/preflight.py`
- 结果: **READY**（详见 §7 及 preflight 输出）
- 未打开摄像头、socket、串口、ST-Link；未发送 START/STOP。

---

## 5. 证据等级与禁止过度声明

### ✅ VERIFIED SOFTWARE（离线证据充分）

| 项 | 验证方式 | 证据路径 |
|---|---|---|
| Python 全量 336 passed | pytest（Python 3.11）| `full_pytest_remediation.log` |
| Host C 12/12 PASS（/W4 /WX）| MSVC 编译+运行 | `host_c_tests_fresh.log` |
| Keil Rebuild 0 Error/0 Warning | UV4 -r | `keil_rebuild_closed_path.log` |
| scope_review 哈希一致 | SHA-256 复核 | `closed_path_scope_review.json` |
| cipsend_tx 16 测试（含 C4100 fix）| MSVC /W4 /WX | `host_c_tests_fresh.log` |
| tx_frame_queue 10 测试 | MSVC /W4 /WX | `host_c_tests_fresh.log` |
| coordinator_boundary 17 测试（含 CLOSED path）| MSVC /W4 /WX | `host_c_tests_fresh.log` |
| capture 清理 5 测试 | pytest 离线 fake socket/camera | `full_pytest_remediation.log` |
| TX ring discard 幂等/回绕安全 | Host C 测试 | `host_c_tests_fresh.log` |

### 🔶 INFERENCE（合理推断，未直接观测）

- TIM3 无应用冲突（grep 仅命中库定义；Motor 用 TIM2/TIM4）
- 三相 ESP service 消除旧架构竞态（单线程主循环，无 RTOS）
- CIPSEND 异步化不改变 PID 参数/电机方向/线损策略（main.c 算法段未改动）

### ⚪ INSUFFICIENT EVIDENCE（证据不足，严禁声称通过）

1. **真机同步 Gate**：coverage ≥95% 且全量 p95 ≤33.3ms — 需新鲜真车数据
2. **USART 移位寄存器/DR 残留 ≤2 字节后 ESP AT parser 恢复** — 需逻辑分析仪在 TX pin 捕获
3. **断连/重连真机复验** — 仅 Host C 纯逻辑/集成验证，未验证真车 TCP 场景
4. **DroidCam 实际尺寸 vs 标定核对** — capture_sync_run.py 离线测试用 fake camera，未验证真机
5. **遥测实际到达率与 CIPSEND busy 重试** — 仅离线推理

### RED 证据限制

**本轮 CLOSED-path 补证**（handoff §16）的 RED 证据性质：
- 修改前 `ESP_TX_HandleTerminal` 为 `main.c` 内部 **static** 函数，Host C 测试无法调用
  相同的终态处理逻辑。
- 提取 `etc_handle_terminal` 到 `esp_tx_coordinator.c` 后，main.c 和 Host C 测试调用
  同一生产函数。
- **RED 是结构性必要性论证（"修改前不可测"），而非保存的修改前失败运行**。
  严格 TDD RED 运行证据缺失。
- 其他阶段（A/B/C）的 RED/GREEN 证据保存完整：handoff §4、§13、§15 均有 RED 和
  GREEN 日志文件。

---

## 6. 未执行硬件动作

- ❌ 未连接 TCP/串口/ST-Link
- ❌ 未烧录、未复位、未 flash/download/debug
- ❌ 未运行电机；未发送 START/STOP/PID/PWM
- ❌ 未运行 capture_sync_run.py（会发送 START/STOP）
- ❌ 未打开摄像头
- ❌ ESP、摄像头、小车保持断电

---

## 7. 离线预检（Offline Preflight）

预检脚本: `.embeddedskills/build/v1_task4b4_fix/preflight.py`
运行方式: `py -3.11 preflight.py`（在 `.embeddedskills/build/v1_task4b4_fix/` 下）

预检范围（只读，无硬件访问）:
- 必要文件存在性
- Python 依赖可导入
- 标定/赛道配置可解析
- 输出目录策略 fail-closed
- capture 脚本可 `--help`/语法编译
- Keil 日志和 AXF 路径存在

输出: `READY` 或 `NOT_READY` 及缺失项。不使用 mock 替代真实硬件证据。

详见 `preflight.py`。

---

## 8. 下一步：硬件 Gate

所有离线工作已完成。下一步 **必须用户授权 + 硬件上电**，按以下文件执行：

- **硬件 Gate 执行手册**: `task4b4_hardware_gate_runbook.md`
- **用户需要做什么**: `USER_ACTION_REQUIRED.md`

本代理不执行硬件 Gate，不开始 Task 4B-5。

---

## 9. 证据文件索引

| 文件 | 说明 |
|---|---|
| `handoff.md` | Task 4B-4 完整 handoff（§1–§16） |
| `closed_path_scope_review.json` | CLOSED-path 最终 SHA-256 哈希 |
| `full_pytest_remediation.log` | Python 336 passed |
| `host_c_tests_fresh.log` | Host C 12/12 PASS |
| `keil_rebuild_closed_path.log` | Keil 0 Error/0 Warning |
| `tx_boundary_design_decision.md` | TX coordinator 设计决策 |
| `task4b4_hardware_gate_runbook.md` | 硬件 Gate 执行手册 |
| `USER_ACTION_REQUIRED.md` | 用户操作要求 |
| `preflight.py` | 离线预检脚本 |
