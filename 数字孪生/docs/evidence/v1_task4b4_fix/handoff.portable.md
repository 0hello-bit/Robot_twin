# Handoff — Task 4B-4 修复（异步 CIPSEND / 真实时钟 / PC 契约 / 同步 Gate）

> **⚠️ 并发执行冲突（必须优先阅读）**: 工作区检测到另一会话并发执行相同的
> Task 4B-4 修复任务。证据与消解见本文件末尾 §11「并发执行冲突披露」。本
> handoff 的结论基于 **2026-08-01 14:55 复核的当前文件状态**（哈希与
> `scope_review.json` 完全一致），但 **Codex 验收前必须重新验证文件哈希并
> 重新运行测试套件**，因为并发会话可能在我之后继续写文件。

> **🔧 Codex review remediation（Task 4B-4B，本修订）**: Codex 对上一版做独立
> 复验后确认 3 个缺口（Host C /W4 /WX 的 C4100、连接代次错误导致旧 critical
> 帧可能发给新客户端、START 后清理不完整）。本修订已修复全部 3 个缺口并通过
> 新鲜离线验证。详见 **§13「Codex review remediation」**。最终状态仍为
> `SOFTWARE FIX COMPLETE / HARDWARE GATE PENDING`。

---

## 1. Task ID / Status

- **Task:** 4B-4 相机与遥测时间同步（修复执行）
- **Status:** `SOFTWARE FIX COMPLETE / HARDWARE GATE PENDING`
  （无新鲜真机数据，**不得标 COMPLETE**）
- **输出目录:** `.embeddedskills/build/v1_task4b4_fix/`

## 2. Changed files（实际修改/新增）

### 固件（C，Keil Target 1）
| 文件 | 状态 | 说明 |
|---|---|---|
| `程序/3. 麦轮巡线小车/User/main.c` | MODIFIED | 移除同步阻塞 CIPSEND；接入非阻塞 TX 状态机、UART TX ring、真实单调时间、latest-wins 遥测槽、yaw dt 边界保护 |
| `程序/3. 麦轮巡线小车/User/stm32f10x_it.c` | MODIFIED | USART1 ISR 增加 TXE 中断排空 TX ring |
| `程序/3. 麦轮巡线小车/project.uvprojx` | MODIFIED | System 组加入 mono_time/mono_time_core；User 组加入 cipsend_tx |
| `程序/3. 麦轮巡线小车/User/cipsend_tx.c/.h` | NEW | 非阻塞但严格串行的 CIPSEND TX 状态机（纯 C，可 Host 测试） |
| `程序/3. 麦轮巡线小车/System/mono_time.c/.h` | NEW | TIM3 1kHz 更新中断 → 32 位单调毫秒（`mono_now_ms`） |
| `程序/3. 麦轮巡线小车/System/mono_time_core.c/.h` | NEW | 纯时间逻辑（回绕安全 elapsed/clamp/deadline），可 Host 测试 |

### PC（Python）
| 文件 | 状态 | 说明 |
|---|---|---|
| `simulation/digital_twin/v1_twin/v1_twin_schema.py` | MODIFIED | `V1TelemetryFrame` 有符号 PWM + `yaw_rad`（legacy=None）；schema 1.1.0 |
| `simulation/digital_twin/v1_twin/v1_twin_dataset.py` | MODIFIED | 共同区间 coverage / 全量 p95 / 诊断指标 / `evaluate_sync_gate`（PASS/FAIL/INSUFFICIENT） |
| `simulation/digital_twin/v1_twin/v1_twin_sync.py` | MODIFIED | `fit_batched` 批次均值追踪 + `fit_residuals` |
| `simulation/digital_twin/v1_twin/v1_twin_pose_tracker.py` | MODIFIED | `track(frame, t_pc_ns=...)` 文档明确：帧读取后立即打 monotonic_ns |
| `.embeddedskills/build/v1_task4b4/capture_sync_run.py` | MODIFIED | 实际帧尺寸核对、`mono_ns` 立即打戳、有符号 PWM、yaw_rad、fit_batched、独立 run_id 目录 fail-closed、诚实 gate |
| `simulation/digital_twin/v1_twin/v1_twin_capture.py` | NEW | 采集辅助（`validate_frame_dimensions` / `resolve_run_output_dir`），离线可测 |

### 测试
| 文件 | 状态 | 说明 |
|---|---|---|
| `simulation/digital_twin/tests/test_v1_twin_schema.py` | MODIFIED | 有符号 PWM、yaw legacy、旧 JSON 兼容 |
| `simulation/digital_twin/tests/test_v1_twin_sync.py` | MODIFIED | 修正 batched 测试（真实批量投递语义）+ fit 非批退化 |
| `simulation/digital_twin/tests/test_v1_twin_dataset.py` | MODIFIED | 共同区间语义、全量 p95、gate PASS/FAIL/INSUFFICIENT、指标 |
| `simulation/digital_twin/tests/test_v1_twin_capture.py` | NEW | capture 辅助 6 测试 |
| `simulation/digital_twin/tests/test_cipsend_tx.c` | NEW | cipsend_tx 状态机 14 个 Host C 测试 |
| `simulation/digital_twin/tests/test_mono_time_core.c` | NEW | mono_time_core 6 个 Host C 测试 |

> 注意：`System/Delay.c`、`User/cipsend_transaction.{c,h}`、`User/uart_ring.{c,h}`
> **未修改**（哈希与基线一致，见 §10 scope review）。`capture_sync_run.py` 已修改
> 但**未运行**（会发送 START）。

## 3. 根因 → 测试 → 修复 映射

### A. 固件：CIPSEND 阻塞主循环（事实 #1/#2）
- **根因**: `ESP_DoCIPSENDTransaction()` 主循环同步轮询 `>`/`SEND OK`，每帧
  `Delay_ms(1)`，遥测每帧阻塞 ~110ms，tick 不按真实时间推进。
- **测试**: `test_cipsend_tx.c`（分段 prompt、分段 SEND OK、ERROR/busy/CLOSED、
  超时、连续事务、禁止重叠、critical 标签、混合 +IPD、sink 拒绝）。
  RED（stub 拒绝 start）→ GREEN（真实实现全部 PASS）。
- **修复**: 新增 `cipsend_tx` 非阻塞状态机；`main.c` 每次主循环由 `ESP_TX_Service`
  推进一小步；同一时间仅一个事务（`cipsend_tx_start` 忙碌即拒）；A/S 重试缓冲
  保留，telemetry latest-wins 单槽；所有 RX 字节同时路由到
  `esp_transport_process_byte` 与 `cipsend_tx_feed_byte`。

### B. 固件：真实单调时钟（事实 #2/#6）
- **根因**: 遥测 tick 与 line-loss/yaw dt 全依赖 `g_loop_count * LOOP_DELAY_MS`，
  阻塞期间不推进。
- **测试**: `test_mono_time_core.c`（回绕安全 elapsed、clamp 零/正常/大间隔、
  deadline、yaw dt 组合）。RED（stub 返回错误）→ GREEN。
- **修复**: TIM3 1kHz 更新中断累加 32 位单调毫秒（`mono_time.c`）；纯逻辑在
  `mono_time_core.c`；`main.c` 中遥测 tick/line-loss/yaw dt 全部改用
  `mono_now_ms()`；yaw dt = 相邻采样真实时间差并 clamp 到 [1,100]ms。
  **TIM3 冲突审查**: `grep -rn "TIM3" --include=*.c --include=*.h` 仅命中库
  定义；应用层 Motor 用 TIM2/TIM4，`System/Timer.c` 的 `Timer_Init()` 未被
  main 调用。TIM3 无冲突（证据见 §9 INFERENCE）。

### C. PC 数据契约与采集（事实 #7/#8/#9/#10/#11）
- **根因**: PWM 负值被钳 0 丢方向；yaw 被丢弃；pose 时间戳在检测结束后生成；
  DroidCam 实际 640x480 而标定 1280x720 未核对；原始数据可被覆盖。
- **测试**: `test_v1_twin_schema.py`（有符号 PWM 往返、yaw legacy=None、旧 JSON
  可加载、yaw NaN 拒绝）；`test_v1_twin_capture.py`（尺寸不符 fail-closed、
  run_id 目录 fail-closed）。
- **修复**: `V1TelemetryFrame.pwm` 允许负值；新增 `yaw_rad`（旧 JSON → None=
  legacy，不伪造）；`capture_sync_run.py` 帧读取成功立即 `time.monotonic_ns()`
  显式传给 `track(t_pc_ns=...)`；启动前读实际 `cap.get(WIDTH/HEIGHT)` 与
  `calib.image_size` 严格核对；写入独立 run_id 目录且目标文件存在即 fail closed。

### D. ClockSync 与同步 Gate（事实 #3/#4/#7）
- **根因**: batched 测试数据不真实（批内 pc 随 tick 递增 → 斜率被批累积偏移
  污染）；coverage 按全部 pose（含单侧缺失段）稀释；p95 先过滤失败样本再算
  （构造性必然，无效 gate）；采集未使用 fit_batched。
- **测试**: `test_v1_twin_sync.py`（真实批量投递：批内接收时间近似相同、源 tick
  递增 → fit_batched 恢复真实速率且拟合线穿过批次均值）；`test_v1_twin_dataset.py`
  （共同区间排除单侧缺失段、p95 含失败样本、gate PASS/FAIL/INSUFFICIENT）。
- **修复**: `fit_batched` 保留并修正（批次均值追踪 + `fit_residuals`），采集策略
  改用 `fit_batched`；`build_synchronized_dataset` 只在共同区间计算 coverage，
  p95 用全部最近距离；新增 `evaluate_sync_gate`（coverage>=95% 且全量
  p95<=33.3ms 才 PASS；数据不足 → INSUFFICIENT EVIDENCE）。

## 4. RED / GREEN 证据

### Host C（新模块，stub RED → 真实 GREEN）
| 测试 | RED 日志 | GREEN 日志 |
|---|---|---|
| `test_cipsend_tx` | `red_cipsend_tx.log`（exit=1，stub 拒绝 start） | `green_cipsend_tx.log`（exit=0，PASS） |
| `test_mono_time_core` | `red_mono_time_core.log`（exit=1，stub 返回错误 elapsed） | `green_mono_time_core.log`（exit=0，PASS） |

### Python（先改测试后实现）
- `test_v1_twin_schema.py`：新增 5 个测试先 RED（`TypeError: unexpected keyword 'yaw_rad'`），实现后 30 passed。
- `test_v1_twin_sync.py`：旧 `test_fit_batched_...` 基线 RED（`2041523 != 1000000`），修正数据后 8 passed。
- `test_v1_twin_dataset.py`：新增共同区间/gate 测试，实现后 21 passed。

### 全量回归
- `pytest tests/ -q` → **331 passed**（基线为 310 passed + 1 failed；修复后净增 20 测试全 GREEN）。
- Host C 全量（`host_c_tests.log`）：send_response_parser / cipsend_transaction /
  uart_ring / ipd_parser / cipsend_tx / mono_time_core **全部 PASS，exit=0**。

## 5. 全部命令、退出码、测试数量

```bash
# 基线（修改前）
python -m pytest tests/ -q          # 310 passed, 1 failed

# Python 全量（修改后）
python -m pytest tests/ -v          # 331 passed, exit=0
python -m pytest tests/ -q > full_pytest.log 2>&1

# Host C（MSVC cl.exe，ASCII hostc 编译区，MSYS2_ARG_CONV_EXCL='*'）
bash build_host_c_tests.sh test_cipsend_tx_red.exe  ...   # RED: exit=1
bash build_host_c_tests.sh test_cipsend_tx_green.exe ...   # GREEN: exit=0
bash build_host_c_tests.sh test_mono_time_red.exe   ...   # RED: exit=1
bash build_host_c_tests.sh test_mono_time_green.exe ...   # GREEN: exit=0
# 回归：hc_srp / hc_cts / hc_ur / hc_ipd 均 exit=0（host_c_tests.log）

# Keil Rebuild Target 1（UV4 无头重建）
"<KEIL_ROOT>/UV4/UV4.exe" -r project.uvprojx -j0 -o keil_rebuild_4b4.log
#   Program Size: Code=19256 RO-data=460 RW-data=116 ZI-data=2524
#   "./Objects/Project.axf" - 0 Error(s), 0 Warning(s).
#   Build Time Elapsed: 00:00:03  （exit=0，0 error / 0 warning）

# 语法检查（不运行）
python -m py_compile capture_sync_run.py   # OK
```

## 6. Artifact / log / report 路径

- `.embeddedskills/build/v1_task4b4_fix/baseline_hashes.json` — 修改前全部目标文件哈希
- `.embeddedskills/build/v1_task4b4_fix/scope_review.json` — 修改/新增/未触碰文件哈希
- `.embeddedskills/build/v1_task4b4_fix/full_pytest.log` — 全量 pytest 日志
- `.embeddedskills/build/v1_task4b4_fix/host_c_tests.log` — Host C 编译运行日志
- `.embeddedskills/build/v1_task4b4_fix/keil_rebuild_4b4.log` — Keil Rebuild 原始日志（0 Error / 0 Warning）
- `.embeddedskills/build/v1_task4b4_fix/red_*.log` / `green_*.log` — 每组 RED/GREEN 日志
- `.embeddedskills/build/v1_task4b4_fix/handoff.md` — 本文件
- `.embeddedskills/build/v1_task4b4_fix/BLOCKED_duplicate_execution.md` — **并发会话**的 BLOCKED 报告（不是我写的）

## 7. Verified facts / Inferences / Unverified

- ✅ **[VERIFIED SOFTWARE]** Python 全量 331 passed（含新增 schema/sync/dataset/capture 测试）。
- ✅ **[VERIFIED SOFTWARE]** Host C：cipsend_tx 14 测试、mono_time_core 6 测试 GREEN；回归套件全 PASS。
- ✅ **[VERIFIED SOFTWARE]** Keil Target 1 Rebuild **0 Error(s), 0 Warning(s)**，AXF 生成（NOT FLASHED）。
- 🔶 **[INFERENCE]** TIM3 未被应用使用（grep 仅命中库定义；Motor 用 TIM2/TIM4），可作为 1kHz 单调时钟源。
- 🔶 **[INFERENCE]** CIPSEND 异步状态机不改变 PID 参数、电机方向公式、线损策略（main.c 算法段未改动，仅替换传输层与计时）。
- ⚪ **[INSUFFICIENT EVIDENCE]** 真机同步 gate（coverage ≥95% / 全量 p95 ≤33.3ms）未验证——需要新鲜真车数据，本任务未授权运行。

## 8. Hardware actions performed

- ❌ **未连接**任何 TCP/串口/ST-Link；**未烧录**；**未复位**；**未运行电机**；
  **未发送** START/STOP/PID/PWM 命令；**未运行** `capture_sync_run.py` 或任何
  真车采集脚本。用户已将轮子架空并保持供电，但本次**未触碰硬件控制路径**。

## 9. Scope review（SHA-256）

- 所有实际修改/新增文件哈希见 `scope_review.json`（2026-08-01 14:55 复核与
  当前文件状态完全一致）。
- 禁止范围命中：**0**。`User/cipsend_transaction.{c,h}`、`User/uart_ring.{c,h}`、
  `System/Delay.c` 哈希与 `baseline_hashes.json` 完全一致（未修改）。
- 未删除任何旧原始数据、旧报告；未修改 PID 参数边界、电机方向公式。
- 未触碰 Task 4B-5 及后续任务文件。

## 10. 下一步安全硬件验证方案（不执行）

1. **编译验证后烧录由用户单独授权**：确认赛道净空、急停可用、供电正常后，
   在**用户在场**下烧录并复位（本次未做）。
2. 短距真车运行（安全防护），采集 telemetry + pose 到新 run_id 目录。
3. 运行更新后的 `capture_sync_run.py`（会发送 START/STOP，需授权）。
4. 用 `evaluate_sync_gate` 输出 PASS/FAIL/INSUFFICIENT；只有新鲜真机数据下
   coverage ≥95% 且全量 p95 ≤33.3ms 才能把 4B-4 从 `HARDWARE GATE PENDING`
   升级为 `COMPLETE`。
5. 若 gate 仍不足：检查 telemetry 实际到达率（期望 50Hz 实时）、CIPSEND 事务
   是否在 ESP busy 时正确等待重试、相机帧尺寸是否与标定一致。

## 11. 并发执行冲突披露（BLOCKED）

**检测到并发会话执行相同 Task 4B-4 修复任务。** 证据：

- `run-claude-task4b4-fix.ps1`（14:28 创建）以 `--name Task4B4-DeepSeek-Fix`
  无头启动另一个 Claude Code，读取相同 prompt（`claude-task4b4-root-cause-fix.txt`）。
- `claude-task4b4-live.jsonl`（19.8 MB，14:43 停止增长）为该会话流式输出。
- `.embeddedskills/build/v1_task4b4_fix/BLOCKED_duplicate_execution.md`（14:43，
  **非本代理创建**）由检测到冲突的另一代理写入：它声称观察到我（或另一会话）
  正在修改目标文件，按「fail closed」停止，未修改任何生产文件。
- 本代理（当前会话）的 Python 文件修改时间 14:35–14:40、固件修改 14:44–14:50，
  与 BLOCKED 报告中「并发改写」时间线吻合——**即 BLOCKED 报告观察到的写入者
  正是本会话**。
- 本代理完成后（14:54–14:55）复核所有目标文件哈希，与 `scope_review.json`
  完全一致；但 `.embeddedskills/build/` 根目录 14:54 出现
  `twin_control_trace_runner.exe/.rsp`（非本代理创建），提示**仍有其他会话在
  共享目录活动**。

**处置**：本代理按「verification-before-completion」基于**当前文件状态**（已复核
哈希）完成并提交 handoff，**不销毁任何一方已产出物**。由于存在并发写可能，
**Codex 验收前必须**：(1) 重新计算所有目标文件 SHA-256 并与 `scope_review.json`
比对；(2) 重新运行 `pytest tests/`、Host C 套件与 Keil Rebuild；(3) 确认
`.embeddedskills/build/v1_task4b4_fix/` 下不存在第二个本任务的 handoff 覆盖。
若并发会话已另行产出权威 handoff，由用户/Codex 指定唯一权威版本并归档另一份。

## 12. 最终结论

- **Task 4B-4（修复）**: `SOFTWARE FIX COMPLETE / HARDWARE GATE PENDING`
- 四组离线修复（A 异步 CIPSEND / B 真实时钟 / C PC 契约 / D 同步 Gate）均完成，
  对应测试 GREEN，Keil 0 error/0 warning。
- **没有新鲜真机数据，不得标 COMPLETE**。真机 gate 需要用户授权下的安全运行，
  且必须先消解 §11 的并发写冲突并复核文件状态。

## 13. Codex review remediation（Task 4B-4B，定向返工）

> 本节记录 Codex 复验后确认的 3 个缺口的定向修复。只修复下列缺口，未重做
> 整个任务；所有 RED/GREEN、全量回归与 Keil Rebuild-only 均为本次**新鲜**离线
> 执行。哈希复核见 `scope_review_remediation.json`；修改前哈希见
> `remediation_before_hashes.json`。

### 13.1 缺口 1 — Host C /W4 /WX 的 C4100

- **Codex 复验**: MSVC /W4 /WX 下 `cipsend_tx_start()` 的 `now_ms` 参数触发
  C4100（未引用形参），/WX 把它升级为错误。
- **测试先行（RED→GREEN）**: `test_cipsend_tx.c` 新增 2 个测试证明公开 API 语义：
  - `test_start_sets_initial_deadline`：`start(now_ms)` 后初始 deadline 必须锚定
    在 `now_ms + CIPSEND_TX_PROMPT_TIMEOUT_MS`。
  - `test_start_stall_timeout`：sink 持续拒绝（TX ring 满）时事务必须超时失败，
    而不是永久卡在 SEND_CMD。
  - RED：对旧实现编译运行，`test_start_sets_initial_deadline` 失败（exit=1）。
- **修复（最清晰，未降级警告）**: `cipsend_tx.c` 在 `cipsend_tx_start()` 用
  `now_ms` 锚定初始 deadline；`tick()` 在 SEND_CMD/SEND_DATA 状态检查该 deadline，
  超时 → FAILED(timeout_abort=1)。`now_ms` 成为真实输入，C4100 消除。
- **GREEN**: `/W4 /WX` 编译运行 `PASS test_cipsend_tx`，exit=0。
- **证据**: `red_cipsend_tx_w4.exe` / `green_cipsend_tx_w4.exe`，
  `red_green_evidence.log`。

### 13.2 缺口 2 — 连接代次错误：旧 critical 帧可能发给新客户端

- **Codex 复验**: main.c 的 `s_retry_ack_len` / `s_retry_status_len` 在 CIPSEND
  ERROR/busy/CLOSED/timeout 后保留；transport 在新 CONNECT 只清内部 pending
  status，未清 main.c 本地 retry 缓冲。复现序列：旧 client 0 的 ACK/STATUS 已取到
  本地 retry → CIPSEND 收到 `0,CLOSED` → 断连 → 新 client CONNECT → 本地 retry
  仍非零 → 旧帧可能先发给新客户端。
- **测试先行（RED→GREEN）**:
  - 纯逻辑 `test_tx_frame_queue.c`（10 个测试）：覆盖同一代次保留、代次改变丢弃、
    同 ID 重连、不同 ID 新连接、CLOSED 终态丢弃、OK 只清匹配缓冲、ERROR/超时
    保留重试、幂等 clear。RED：对复现旧行为的 `tx_frame_queue_stub.c` 编译运行，
    `txfq_check_generation(&q, 6U) == 1U` 失败（exit=1）。
  - 传输层 `test_esp_transport_gen.c`（5 个测试）：CONNECT 递增代次、CONNECT/CLOSED
    清 pending ACK/STATUS、重连后无旧帧残留。RED：对旧版 transport 编译
    → LNK2019（`esp_transport_connection_generation` 未定义）。
  - 集成 `test_tx_generation_integration.c`（3 个测试）：完整复现
    「in-flight TX 收到 CLOSED → 终止 → 新 CONNECT → 无旧帧」、重连后协议层
    生成 fresh status、A/S 顺序保持。RED：stub+旧 transport+shim 下
    `s_connected == 0U` 失败（exit=1）。
- **修复**:
  - 新增纯逻辑模块 `User/tx_frame_queue.{c,h}`：连接代次 + ACK/STATUS 重试缓冲。
    `txfq_check_generation()` 检测代次改变并丢弃全部保留帧；`txfq_on_tx_result()`
    OK 清匹配缓冲、CLOSED 丢弃全部、ERROR/busy/超时同代次内保留。
  - `esp_runtime_transport.c`：新增 `s_connection_generation`，CONNECT 递增并清
    pending ACK+STATUS，CLOSED 清 pending ACK+STATUS；暴露
    `esp_transport_connection_generation()`。另修复既有缺陷：AT 行累积过滤 `>`
    （CIPSEND 提示符），否则紧跟其后的 `0,CLOSED` 会被当脏行跳过，漏检断连。
  - `main.c`：`s_retry_*` 改为 `TxFrameQueue g_tx_queue`；`ESP_TX_HandleTerminal`
    改调 `txfq_on_tx_result`；`ESP_SendQueuedFrames` / `ESP_TrySendTelemetry` /
    `ESP_SendDiagFrame` 改用 txfq 访问器；主循环每次 `txfq_check_generation`，
    代次改变时同时清 telemetry latest-wins 槽。
- **安全边界**: +IPD 输入、STOP/timeout 安全回滚、A/S 顺序均未破坏（由
  `test_ipd_integration` / `test_twin_control_protocol` / `test_tx_generation_integration`
  回归覆盖）。
- **GREEN**: 三个测试套件 `/W4 /WX` 全部 PASS，exit=0。
- **证据**: `red_green_evidence.log`、`transport_red_build.log`、
  `host_c_tests_remediation.log`。

### 13.3 缺口 3 — START 后清理不完整（capture_sync_run.py）

- **Codex 复验**: `capture_sync_run.py` 发送 START 后等待首帧遥测超时直接
  `return 1`，该路径位于采集 try/finally 之外，不保证 STOP、socket.close、
  cap.release。依赖 CPython 析构关闭 socket 不是安全契约。
- **测试先行（RED→GREEN）**: `test_capture_sync_cleanup.py`（5 个测试，fake
  socket/camera，不连真车/摄像头，不运行真实 main()）：
  1. START 已发出但无遥测（超时）：STOP attempt、socket close、camera release
     都恰好执行一次。
  2. 采集期间异常：同上三者都恰好执行。
  3. STOP 发送失败仍继续关闭 socket 和相机。
  4. START 发送失败不假称已 STOP（动作状态如实报告）。
  5. `cleanup_session` 幂等。
  RED：旧代码无 `run_sync_capture_session`/`cleanup_session` API；
  `red_check_old_capture_cleanup.py` 复现旧控制流（超时直接 return，绕过清理）
  → 断言失败，exit=1。
- **修复**: `capture_sync_run.py` 新增 `_new_action_state()` / `cleanup_session()` /
  `run_sync_capture_session(sock, cap, tracker, ...)`。START 后所有路径
  （正常/超时/采集异常/START 失败）都进入统一、幂等的清理；STOP 仅当 START
  已发出才尝试，失败仍继续关闭 socket 和相机；动作状态如实记录在 actions。
  main() 改为调用 session 函数并打印动作报告。
- **GREEN**: `py -3.11 -m pytest` 全量 **336 passed**（含 5 个新清理测试），exit=0。
- **证据**: `full_pytest_remediation.log`（336 passed）。

### 13.4 复验要求与证据路径

| 复验项 | 结果 | 证据 |
|---|---|---|
| 全量 Python（simulation/digital_twin/tests） | **336 passed，exit=0**（Python 3.11，与基线同解释器） | `full_pytest_remediation.log` |
| Host C 新增模块 + 回归（MSVC /W4 /WX） | 11 个套件全部 PASS，编译+运行 exit=0 | `host_c_tests_remediation.log`、`red_green_evidence.log` |
| Keil Target 1 Rebuild-only | **0 Error(s), 0 Warning(s)**，AXF 生成，未烧录 | `keil_rebuild_4b4b.log` |
| scope_review 哈希 | 重算于 `scope_review_remediation.json`；未触碰文件与 `baseline_hashes.json` 完全一致 | `scope_review_remediation.json` |

**本轮实际修改/新增文件（Task 4B-4B）**:

- MODIFIED（固件）: `User/main.c`、`User/cipsend_tx.c`、`User/esp_runtime_transport.c`、
  `User/esp_runtime_transport.h`、`project.uvprojx`
- NEW（固件）: `User/tx_frame_queue.c`、`User/tx_frame_queue.h`
- MODIFIED（PC）: `.embeddedskills/build/v1_task4b4/capture_sync_run.py`
- MODIFIED（测试）: `simulation/digital_twin/tests/test_cipsend_tx.c`
- NEW（测试）: `test_tx_frame_queue.c`、`test_esp_transport_gen.c`、
  `test_tx_generation_integration.c`、`test_capture_sync_cleanup.py`

**未触碰（与 baseline 哈希一致）**: `User/cipsend_transaction.{c,h}`、
`User/uart_ring.{c,h}`、`System/Delay.c`（`scope_review_remediation.json` 复核）。

**最终状态**: `SOFTWARE FIX COMPLETE / HARDWARE GATE PENDING`。
**没有新鲜真机数据，不得标 Task 4B-4 COMPLETE。** 仍未验证的真机项目见 §14。

## 14. 仍未验证的真机项目（后续硬件 Gate）

以下全部需要**用户授权 + 赛道净空**下的安全真机运行，本任务禁止执行：

1. 烧录 + 复位后的真车启动行为（Task 4B-4 异步 CIPSEND 传输在实际 ESP01S/WiFi
   下的吞吐与稳定性）。
2. 真机同步 Gate：coverage ≥95% 且全量 p95 ≤33.3ms（需要新鲜真车数据跑
   `capture_sync_run.py`，会发送 START/STOP）。
3. 断连/重连场景真机复验：CLOSED → 新 CONNECT 时旧 critical 帧不泄漏到新客户端
   （本轮只做了 Host C 纯逻辑/集成验证）。
4. `capture_sync_run.py` 的相机尺寸核对（DroidCam 实际 1280x720）与采集生命周期
   在真机上的表现（本轮只做了 fake 离线验证）。
5. 遥测实际到达率（期望 50Hz）与 CIPSEND busy 重试在真实链路下的表现。

## 15. TX Boundary Coordinator — Final Fix（本代理，Task 4B-4 定向修复 R2）

> 本节记录本代理对 4B-4 最后 6 个根因缺口的定向修复。架构重新判定后提取
> `esp_tx_coordinator` 模块统一持有连接边界决策，不再在 main.c 堆叠散落 `if`。
> 所有 RED/GREEN、全量回归与 Keil Rebuild-only 均为本次**新鲜**离线执行。

### 15.1 根因→修复 映射

| # | 根因 | 修复 | 证据 |
|---|---|---|---|
| R1 | `ESP_TX_Service` 先推 TX 再查代次 → 旧字节可入 ring | 三相拆分：RX drain → coordinator check → TX push | main.c 重构 |
| R2 | 代次变化只清 `s_tele_pending`，不 reset CipsendTx / TX ring | `etc_check_boundary` 执行统一 abort：CipsendTx reset + txfq drop + tele_pending clear + TX ring discard | esp_tx_coordinator.c |
| R3 | USART1 ISR 异步 drain TX ring，旧字节无法撤回 | `discard_tx_ring_cb`: 关 TXE → drain ring → 保持 TXE 关。字节在 ring 内即安全丢弃。USART 移位寄存器/DR 残留≤2 字节无法撤回 → `SOFTWARE FIX COMPLETE / HARDWARE RECOVERY TEST PENDING` | design decision §3e, discard_tx_ring_cb |
| R4 | WAIT_PROMPT 只检测 `>`，ERROR/busy/CLOSED 等 200ms 超时 | `cipsend_transaction.c`: WAIT_PROMPT 路由 `srp_feed` 检测错误行。`cipsend_tx.c`: feed_byte 立即 FAILED | 3 个新增测试 RED→GREEN |
| R5 | SEND_DATA deadline 继承 WAIT_PROMPT，边界到达时下一 tick 立即超时 | 新增 `deadline_stale` 标志，SEND_DATA 首次 tick 刷新 deadline 为独立 200ms 窗口 | `test_send_data_independent_deadline` |
| R6 | 集成测试用直接 test_sink，不含真实 UartRing/ISR drain | 新增 `test_coordinator_boundary.c`（16 测试）：真实 UartRing、4 种连接边界、幂等/回绕安全、可观测计数、回归 | 全 GREEN，exit=0 |

### 15.2 修改/新增文件

| 文件 | 状态 | 说明 |
|---|---|---|
| `User/cipsend_transaction.c` | MODIFIED | WAIT_PROMPT 路由 srp_feed 检测 ERROR/busy/CLOSED |
| `User/cipsend_tx.h` | MODIFIED | 新增 `deadline_stale` 字段 |
| `User/cipsend_tx.c` | MODIFIED | feed_byte 处理 ERROR/busy/CLOSED；tick SEND_DATA 刷新 deadline；init/start 初始化 deadline_stale |
| `User/esp_tx_coordinator.c/.h` | NEW | 连接边界 coordinator（纯逻辑，Host 可测） |
| `User/main.c` | MODIFIED | 三相 ESP service；discard_tx_ring_cb；集成 coordinator；移除分散代次检查 |
| `project.uvprojx` | MODIFIED | User 组加入 esp_tx_coordinator.c/.h |
| `tests/test_coordinator_boundary.c` | NEW | 16 个 Host C 测试（/W4 /WX） |

### 15.3 复验证据

| 复验项 | 结果 | 证据 |
|---|---|---|
| 全量 Python（simulation/digital_twin/tests） | **294 passed**（6 fail 为 Python 3.7 `math.dist` 预存问题，无关本次修改） | 终端输出 |
| Host C 12 套件 MSVC /W4 /WX | **全部 PASS**（含新增 coordinator_boundary 16 测试） | 终端输出，编译+运行 exit=0 |
| Keil Target 1 Rebuild-only | **0 Error(s), 0 Warning(s)**；Code=20136 (+880 vs R1)，AXF 生成 | `keil_rebuild_4b4_final.log` |
| scope_review 哈希 | `tx_boundary_scope_review.json` | 本节产出 |

### 15.4 架构判定摘要

参见 `tx_boundary_design_decision.md`（完整设计文档）。要点：

- **连接边界**: CONNECT/CLOSED/同 ID 重连/不同 ID 新连接 → generation 改变 → abort。
- **epoch 绑定**: CipsendTx 隐式绑定 start 时 epoch；coordinator 在边界强制 reset。
- **TX ring 安全 discard**: SPSC 无竞态（关 TXE → drain）。USART 移位寄存器残留≤2 字节**无法撤回**，但在 38400 baud 下为部分命令碎片，**不可能构成有效 AT 命令**。
- **超时权威起点**: 每阶段独立锚定（SEND_CMD→now at start、WAIT_PROMPT→now at cmd sent、SEND_DATA→now at prompt、WAIT_SENDOK→now at data sent）。

### 15.5 证据等级

- ✅ **[VERIFIED SOFTWARE]** Python 294 passed（预存问题除外）。
- ✅ **[VERIFIED SOFTWARE]** Host C 12 套件 /W4 /WX 全 PASS。
- ✅ **[VERIFIED SOFTWARE]** Keil Target 1 Rebuild 0 Error(s), 0 Warning(s)。
- ✅ **[VERIFIED SOFTWARE]** TX ring discard 在 Host 测试中幂等、回绕安全、可观测。
- 🔶 **[INFERENCE]** 三相 ESP service 主循环顺序消除旧架构竞态（单线程，无 RTOS）。
- ⚪ **[INSUFFICIENT EVIDENCE]** USART 移位寄存器残留 ≤2 字节后 ESP AT parser 恢复行为（需逻辑分析仪在真机 TX pin 捕获验证）。
- ⚪ **[INSUFFICIENT EVIDENCE]** 真机同步 gate（§14 全部真机项）。

### 15.6 最终状态

**`SOFTWARE FIX COMPLETE / HARDWARE RECOVERY TEST PENDING`**

软件层所有已知 TX 边界缺陷已修复并通过离线验证。真机验证需用户授权下的安全运行（§14 全部项），特别需要逻辑分析仪在 USART1 TX pin 观测连接边界处的残留字节与 ESP AT parser 恢复。

**不得标 Task 4B-4 COMPLETE 直至新鲜真机数据通过同步 gate。**

## 16. CLOSED-Path Evidence Fix（本代理，Task 4B-4 验收补证）

> 本节记录对 §15.1 R6 的定向修复：原 `test_closed_discards_tx_ring` 名称声称覆盖 CLOSED，实际只测试 generation 1→2 (CONNECT boundary)，**从未**输入真实 `\r\n0,CLOSED\r\n`，也**从未**调用生产 `ESP_TX_HandleTerminal → etc_force_abort` 路径。

### 16.1 根因

`ESP_TX_HandleTerminal` 是 `static` 函数内嵌在 `main.c`，直接引用 `g_cipsend_tx`、`g_tx_queue`、`g_coordinator` 静态变量。Host C 测试无法调用相同的终态处理逻辑。原测试退而求其次使用 `etc_check_boundary(c, gen=2)` 模拟 generation change → abort，**未证明 CLOSED 生产路径**。

### 16.2 修复：最小架构提取

将 `ESP_TX_HandleTerminal` 的纯生产逻辑提取到 `esp_tx_coordinator.c`：

```c
void etc_handle_terminal(EspTxCoordinator *c)
{
    uint8_t result;
    if (!cipsend_tx_is_terminal(c->cipsend_tx)) return;
    result = cipsend_tx_result(c->cipsend_tx);
    txfq_on_tx_result(c->tx_frame_queue, result,
                      cipsend_tx_tag(c->cipsend_tx));
    if (result == CTS_RESULT_CLOSED) {
        (void)etc_force_abort(c);
    } else {
        cipsend_tx_reset(c->cipsend_tx);
    }
}
```

- `main.c::ESP_TX_HandleTerminal` 现在仅调用 `etc_handle_terminal(&g_coordinator)`。
- Host C 测试直接调用同一 `etc_handle_terminal()`。
- **没有**复制逻辑到测试；main.c 和测试调用的是同一个函数。

### 16.3 重命名旧测试

| 原名 | 新名 | 原因 |
|---|---|---|
| `test_closed_discards_tx_ring` | `test_generation_change_discards_tx_ring` | 只测试 generation 1→2，不涉及 CLOSED |

### 16.4 新增测试：`test_closed_terminal_discards_all`

严格满足任务规定的 6 条测试语义：

1. ✅ 使用真实 `CipsendTx`、`TxFrameQueue`、`EspTxCoordinator`、`UartRing`。
2. ✅ 建立同连接 generation，启动真实 CIPSEND (WAIT_PROMPT)，真实 TX ring 中留有旧字节。
3. ✅ 逐字节输入 `\r\n0,CLOSED\r\n` → `cipsend_tx_feed_byte` → `CTS_RESULT_CLOSED`。generation 不变（CLOSED 不增 generation）。
4. ✅ 调用生产 `etc_handle_terminal`（与 main.c 相同函数），断言：
   - CipsendTx → IDLE
   - TxFrameQueue ACK/STATUS 被丢弃
   - telemetry pending 清零
   - 真实 UartRing 剩余字节被 discard
   - discard 回调计数准确（`c.tx_bytes_discarded > pre`、`c.cipsend_aborts++`、`c.boundary_events++`）
   - generation 保持不变
5. ✅ 架构提取：`etc_handle_terminal` 放入现有 `esp_tx_coordinator`；main.c 和 Host 测试调用同一函数。
6. ✅ 旧 "generation change discards ring" 测试已重新命名为 `test_generation_change_discards_tx_ring`，不再标成 CLOSED 测试。

### 16.5 RED / GREEN 证据

**RED**：在提取 `etc_handle_terminal` 之前，终态处理逻辑是 main.c 内部 static 函数，无法被 Host C 测试直接调用。`test_closed_discards_tx_ring` 用 generation 变化（CONNECT boundary）代替 CLOSED，构成测试–名称不匹配的证据缺口。

**GREEN**：提取 `etc_handle_terminal` 后，新测试 `test_closed_terminal_discards_all` 在 `/W4 /WX` 编译通过并通过全部断言（PASS test_coordinator_boundary, exit=0）。

### 16.6 新鲜全量验证结果

| 复验项 | 结果 | 证据文件 |
|---|---|---|
| Host C 12 套件 `/W4 /WX` | **12/12 PASS, exit=0**（含 coordinator_boundary 17 测试） | `host_c_tests_fresh.log` |
| Python 全量 (Python 3.11) | **336 passed, exit=0** | 终端输出 |
| Keil Target 1 Rebuild-only | **0 Error(s), 0 Warning(s)** | `keil_rebuild_closed_path.log` |
| coordinator_boundary 测试数 | 17 (16 旧 + 1 新 `test_closed_terminal_discards_all`) | 本文件 |

### 16.7 修改文件与哈希

| 文件 | 状态 | SHA256 |
|---|---|---|
| `User/main.c` | MODIFIED | `692e1200...` |
| `User/esp_tx_coordinator.c` | MODIFIED | `06870044...` |
| `User/esp_tx_coordinator.h` | MODIFIED | `e966b82f...` |
| `tests/test_coordinator_boundary.c` | MODIFIED | `8845a390...` |
| `hostc/User/esp_tx_coordinator.c` | MODIFIED (sync) | `06870044...` |
| `hostc/User/esp_tx_coordinator.h` | MODIFIED (sync) | `e966b82f...` |

完整哈希清单见 `closed_path_scope_review.json`。

### 16.8 仍未验证项（不变）

- ⚪ USART 移位寄存器/DR 残留 ≤2 字节后 ESP AT parser 恢复 → **HARDWARE RECOVERY TEST PENDING**
- ⚪ 真机同步 gate（§14 全部真机项）
- ⚪ ESP、摄像头、小车保持断电；未执行 flash/download/debug/ST-Link/PID/PWM/真实采集

**不得标 Task 4B-4 COMPLETE。**

## 17. 离线收尾完成（DeepSeek V4 Pro Wrap-up，2026-08-01）

> DeepSeek V4 Pro 离线收尾代理在 Codex 独立验收后执行。未创建 git repo/worktree；
> 未 init/commit；未访问任何硬件。所有工作在现有工作区严格限域内完成。

### 17.1 收尾产出

| 文件 | 说明 |
|---|---|
| `task4b4_final_offline_acceptance.md` | **最终离线验收报告（单一权威入口）**：实际修改范围、Codex 独立结果、DeepSeek 事实核对、证据等级（VERIFIED/INFERENCE/INSUFFICIENT）、RED 证据限制、禁止过度声明 |
| `task4b4_hardware_gate_runbook.md` | **硬件 Gate 分阶段执行手册**：A 外观接线 → B 烧录 → C 通信验证 → D 摄像头 → E 短时 START/STOP → F 同步 Gate → G 异常回滚。每阶段前置条件/允许/禁止/通过/失败/产物 |
| `USER_ACTION_REQUIRED.md` | **用户操作要求**：首行 `USER_ACTION_REQUIRED: HARDWARE_POWER_ON`；精确列出开启顺序、轮子位置、何时可能转动、何时放赛道；不含敏感信息 |
| `preflight.py` | **离线预检工具**：22 项检查（只读/无硬件），输出 READY/NOT_READY；已运行通过 |

### 17.2 事实统一

- Python 全量: **336 passed / Python 3.11**（handoff §15 中 294 passed / Python 3.7 的 6 fail 为 `math.dist` 预存问题，与本次修改无关）
- Host C: **12/12 suites PASS**，`/W4 /WX`，exit=0
- Keil: **0 Error(s), 0 Warning(s)**，Code=20144
- CLOSED-path RED: **严格 TDD RED 运行证据缺失**（ESP_TX_HandleTerminal 修改前为 static 内嵌 main.c，结构上无法 Host C 直接调用；RED 为结构性必要性论证，非保存的失败运行）

### 17.3 最终状态

**`SOFTWARE ACCEPTED / HARDWARE GATE READY`**

### 17.4 预检结果

```
py -3.11 preflight.py → VERDICT: READY (22/22 PASS)
```

### 17.5 安全边界遵守

- ✅ 未访问串口、TCP、摄像头、ST-Link、目标板
- ✅ 未 flash/download/debug/reset、未发送 START/STOP/PID/PWM
- ✅ 未运行电机、未执行真实采集
- ✅ 未删除旧原始数据、旧验收证据
- ✅ 未开始 Task 4B-5、PID 优化、数字孪生候选筛选
- ✅ 未将 mock/文件存在/构建成功写成真实硬件通过
- ✅ 未初始化 Git、未创建 worktree、未 commit
