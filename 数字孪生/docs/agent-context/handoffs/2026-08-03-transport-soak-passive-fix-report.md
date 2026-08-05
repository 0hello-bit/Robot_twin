# 报告：修复 transport_soak 假被动模式（2026-08-03 返工）

**handoff**：`docs/agent-context/handoffs/2026-08-03-transport-soak-passive-fix.md`
**日期**：2026-08-03
**模式**：纯离线（无真机、无真实 TCP、无 Git 写操作）

---

## 1. 根因

CLI 分支把**面向显示的字符串**当作内部控制模式值传入：

`main()` 原来执行：

```python
out, rx_log = capture_session(
    transport, duration,
    "run-mode(START/STOP)" if args.run else "passive(no commands)", ...)
```

而 `capture_session()` 只识别精确字符串：

```python
if run_mode == "passive":
    ... # 被动分支
out = run_handshake(...)  # 其余一切值都落入运行分支
```

`"passive(no commands)" != "passive"` → 未传 `--run` 时照样进入运行分支，实际发送
pre-STOP → START → 200ms 心跳 `H` → final STOP。

**真实证据（RED 阶段 `raw_io.json`）**：`n_send = 1`，唯一 TX 字节
`522c736f616b2c736f616b36613730353133342c53544f502c33350a` =
ASCII `R,soak,soak6a705134,STOP,35\n`。即未传 `--run` 却真实发出了一条 STOP 命令；
握手未确认故退出码为 2（握手 FAIL）并触发 CUT POWER 警告。

---

## 2. 实际修改文件（仅允许范围内两个文件）

1. `.embeddedskills/build/v1_task4b4/transport_soak.py`
2. `.embeddedskills/build/v1_task4b4/test_transport_soak_rework.py`

只读必要接口：`simulation/digital_twin/real_world/frame_parser.py`、
`real_world/runtime_protocol.py`、`v1_twin/v1_twin_capture.py::resolve_run_output_dir`。
未修改产品固件、Keil 工程、其它计划或历史证据。

### 2.1 transport_soak.py 修复内容

- 新增**规范模式值**与**显示映射**（内部控制只用规范值，显示文本仅报告时转换）：

  ```python
  RUN_MODE_RUN     = "run"
  RUN_MODE_PASSIVE = "passive"
  RUN_MODE_DISPLAY = {
      RUN_MODE_RUN:     "run-mode(START/STOP)",
      RUN_MODE_PASSIVE: "passive(no commands)",
  }
  ```

- `capture_session()`：仅按 `RUN_MODE_PASSIVE` 进入被动分支；**任何其它值（含旧显示
  字符串 `'passive(no commands)'`）一律抛 `ValueError`**，绝不静默落入运行分支
  （防御整类回归）。
- `main()`：先计算规范值 `run_mode = RUN_MODE_RUN if args.run else RUN_MODE_PASSIVE`
  并传入 `capture_session()`；报告里的 `run_mode` 字段改为
  `RUN_MODE_DISPLAY[run_mode]`（仅此处产生显示文本）。
- `run_handshake()` 输出的 `out["run_mode"]`、`passive_capture()` 的传参、
  `eval_handshake_gate()` 的判定统一改用规范常量，杜绝字符串字面量漂移。
- `validate_run_duration()` 继续接收布尔 `args.run`（非空字符串会被当 truthy，
  故不得改为传规范字符串——已核对，保持布尔语义不变）。

### 2.2 test_transport_soak_rework.py 新增测试（5 个）

| 测试 | 用途 |
|---|---|
| `test_passive_main_path_zero_tx` | **定向 RED→GREEN**：驱动与真实 CLI 一致的 `main()` 全路径（monkeypatch `SocketTransport` 为无网络替身 + 短握手超时 + tmpdir 输出），断言退出码 3、`raw_io.n_send==0`、无 STOP/START/H 字节 |
| `test_capture_session_passive_zero_tx_even_with_status_stream` | passive 即使收到完整 S 状态流也零 TX |
| `test_capture_session_run_full_safety_chain` | 规范 RUN 经 `capture_session` 全链路 pre-STOP→START/RUNNING→H→final STOP 无回归 |
| `test_run_mode_display_mapping_and_branch_values` | 规范值互异且与显示文本分离 |
| `test_capture_session_rejects_display_string_mode` | 旧 bug 输入形态（显示字符串当模式）必须 `ValueError` |

---

## 3. RED 证据（修复前，只运行新增定向测试）

命令：

```
py -3.11 -m pytest .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py \
    -q --no-header -k test_passive_main_path_zero_tx
```

结果：

```
F
FAILURES:
AssertionError: passive must exit INSUFFICIENT_EVIDENCE=3, got 2
assert 2 == 3
1 failed, 36 deselected in 0.76s   EXIT=1
```

被测 `main()` 实际输出（确认误入运行分支）：

```
帧数: 0  cadence: INSUFFICIENT_EVIDENCE/n/a  主循环无阻塞: INSUFFICIENT_EVIDENCE  握手: FAIL
VERDICT handshake: FAIL  passive: no commands sent
!!! 未确认小车进入 STOPPED。若本会话发送过 START/运动指令，请立即切断电机电源！ !!!
```

RED 阶段 `raw_io.json`：

```json
{ "n_send": 1, "n_recv": 0,
  "events": [ { "dir": "TX", "n_bytes": 28,
    "bytes_hex": "522c736f616b2c736f616b36613730353133342c53544f502c33350a" } ] }
```

`522c...` 解码为 `R,soak,soak6a705134,STOP,35\n` —— 未传 `--run` 却真实发送了
STOP 命令。**RED 成立。**

---

## 4. GREEN 证据（修复后，同一定向测试）

命令同上。

结果：

```
1 passed, 36 deselected in 0.33s   EXIT=0
```

GREEN 阶段 `raw_io.json`（本仓库证据文件）：

```json
{ "n_send": 0, "n_recv": 0 }
// TX 事件总数：0
```

GREEN 阶段 `transport_report.json` 关键字段：

```json
"run_mode": "passive(no commands)",
"exit_code": 3,
"raw_io": { "n_tx_events": 0, "n_rx_events": 0 },
"handshake": { "initial_status": null, "pre_stop": null,
               "start": null, "stop": null }
```

被动模式零握手、零发送；退出码 3（无帧 → `INSUFFICIENT_EVIDENCE`，与
`exit_code_for` 契约一致，绝不冒充 PASS）。**GREEN 成立。**

---

## 5. 完整测试数与退出码

| 阶段 | 命令 | 结果 | 退出码 |
|---|---|---|---|
| 基线（修改前） | 全套 | 36 passed, 0 failed | 0 |
| RED（仅新增定向测试，修复前） | `-k test_passive_main_path_zero_tx` | 1 failed（`code==2`） | 1（pytest） |
| GREEN（仅新增定向测试，修复后） | 同上 | 1 passed | 0 |
| **全套（修复后）** | 全套 `test_transport_soak_rework.py` | **41 passed, 0 failed**（36 原有 + 5 新增） | 0 |
| health 0x02 混合流子集 | `-k "health or mixed_parse or heartbeat or esp_noise"` | **12 passed, 0 failed** | 0 |

health 0x02 子集覆盖：`test_heartbeat_command_golden`、
`test_mixed_parse_health_frame`、`test_session_records_health_frames`、
`test_heartbeats_sent_during_running_only`、
`test_health_summary_multi_hop_and_duration_dedup`、`test_health_summary_empty`，
以及 5 个 `test_mixed_parse_*` 与 `test_run_pre_stop_confirmed_despite_esp_noise`。

---

## 6. 被动模式零 TX 的可执行证据

1. `test_passive_main_path_zero_tx` 在**真实 CLI 全路径**（`main()`→`capture_session()`）
   下断言：`raw_io.n_send == 0`、`b"STOP" not in tx`、`b"START" not in tx`、
   `b"H," not in tx`，并断言退出码为 3（无 FAIL）。
2. GREEN 落盘的 `raw_io.json`：`n_send=0`、`n_recv=0`、TX 事件数 0。
3. `test_capture_session_passive_zero_tx_even_with_status_stream`：passive 即使在
   收到完整 `S,...,STOPPED,STOP` 状态流时，`transport.tx` 仍为空、`n_send==0`。
4. `test_capture_session_rejects_display_string_mode`：把旧显示字符串当模式传入
   立即 `ValueError`，从结构上排除同类误入运行分支的可能。

## 7. --run 安全链路无回归证据

- 既有握手测试全部通过（`test_run_full_handshake_confirmed`、
  `test_run_requires_pre_start_stop_confirmed_before_start`、
  `test_run_without_pre_stop_confirmation_never_starts`、
  `test_run_final_stop_timeout_requires_cut_power_warning`、
  `test_heartbeats_sent_during_running_only`、`test_finally_stop_on_reader_error` 等）。
- 新增 `test_capture_session_run_full_safety_chain`：规范 RUN 经 `capture_session`
  全链路确认 pre-STOP→START/RUNNING→H→final STOP/STOPPED，且 TX 顺序
  `STOP < START < 最终 STOP`，`eval_handshake_gate()=="PASS"`，
  `cut_power_warning is False`。

---

## 8. 仍未验证项

- 修复后的**真机被动 soak**尚未执行（本轮按 handoff 强制要求不连接硬件、不开真实
  TCP）。2026-08-03 真机误触发属修复前缺陷；修复已用全脚本化 transport 验证，真机
  复测需另行授权。
- 长时运行（`--long-run`）无人值守安全边界未变化：本工具不发 MCU 命令心跳，仍不宣称
  无人值守安全。
- health 0x02 三跳归因/`health_last_duration_ms` 去重只做了单元级验证；真实链路
  逐秒连续观测不在本轮范围。

---

## 9. 声明

本轮**未连接或控制任何硬件**（不烧录、不复位、不发送 START、不运行电机），
**未打开任何真实 TCP/网络连接**（所有传输均为 scripted/fake transport），
**未执行任何 Git 写操作**（无 add/commit/push/reset）。
