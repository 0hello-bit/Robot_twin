# Robot Twin AI — 正式固件健康与安全基线：设计（2026-08-03）

> 状态：**设计已批准，实施计划见**
> `docs/superpowers/plans/2026-08-03-firmware-health-safety-baseline.md`。
> 本批次授权范围：离线设计、测试规划、Keil 构建规划与 ST-Link 只读准备。
> **不授权连接 MCU、halt/reset、擦除、烧录、串口、TCP、START 或电机动作。**
> 本设计不写产品代码；只给出接口、状态机、字节布局、安全行为与验收判读，供
> 实施计划按 TDD 拆分。

---

## 0. 批准且不得擅改的决策（与本设计一致）

1. 原二进制 `0x01` 遥测帧长度（29 字节）、字段（s0–s3, m1–m4, error, pid_output,
   tick_ms, yaw）、解析行为**完全不变**。
2. 新增独立二进制 `0x02` 健康诊断帧，约 1Hz，RUNNING 与 STOPPED（含 INIT）均发送；
   低优先级、可丢、不阻塞 A/S 关键帧；每帧携带 MCU 快照时间戳 `snapshot_tick_ms`
   （采集时刻 mono tick，§5.2）。
3. PC 仅在 RUNNING 期间每 200ms 发送命令心跳；心跳沿用既有 XOR 校验和、
   campaign/run 关联；不逐条 ACK；`0x02` 暴露心跳接收计数与心跳年龄。
4. START 立即开启 1 秒命令租约；连续 1 秒无有效心跳 → 四路电机归零、运动抑制，
   并调用现有 `twin_control_timeout()` 回滚语义。旧 S 帧 reason 仍为 `TIMEOUT`
   （兼容旧工具）；`0x02` 单独记录 `heartbeat_timeout` 计数与最近抑制原因。
5. IWDG 在安全初始化完成、电机已归零后启用；主循环每轮迭代顶部喂狗，语义为
   “上一轮已返回循环顶部”（§4.1，不把当前轮尚未完成描述为已完成）；约 2 秒未喂狗
   则复位（实际范围见 §7.2，受 STM32F1 LSI 误差约束，不得伪称精确 2.000s）；
   复位后默认运动抑制，必须重新 START。
6. 本批次不改 UART 波特率、`TELEMETRY_INTERVAL_MS=20` 生成周期、ESP 模式、
   PID/巡线算法、PWM 逻辑；不加入编码器。
7. 先以观测数据定位 100ms 节拍与偶发断流；**不得**预先断言 CIPSEND、ESP 或
   主循环为已证实根因。本设计只保证新增计数器能够区分机制（§9 判读表）。

---

## 1. 目标 / 非目标

### 1.1 目标

- 为 MCU 侧提供**协议可观测的正式健康与安全基线**：主循环、CIPSEND、遥测管线、
  UART、身份/安全五个维度的计数器与状态字段。
- 引入**命令心跳 + 1 秒租约**：PC 断流 ≤1s 即自动电机归零、运动抑制、TIMEOUT
  回滚，弥补“无 MCU 心跳则非无人值守安全”的空档。
- 引入 **IWDG 看门狗**：主循环失活/死锁约 2s 后自动复位，复位后默认运动抑制。
- 在**不改动 `0x01` 帧**的前提下，用一次最小改动（新增一个可丢 `0x02` 帧）闭合
  断流根因调查（`.embeddedskills/build/v1_task4b4/dropout_root_cause_review.md`
  §7/§8）中最缺的观测量。
- 主机端（`transport_soak.py`）同步纳入：异常路径 STOP 兜底、唯一 run_id、
  门禁拆分、窗口严格排除握手期帧、`0x02` 解析/持久化/跨语言 golden vectors。

### 1.2 非目标

- **不修复**断流本身：本批次只登记诊断基线，把 100ms 节拍与偶发断流定位到
  机制层（主循环阻塞 vs CIPSEND 事务未完成 vs UART 丢失/溢出 vs 连接代次变化），
  不宣称根因闭合、不宣告 4B-4 完成。
- 不改 `0x01` 遥测协议、不改 20ms 生成周期、不改波特率、不改 PID/巡线/PWM、
  不加编码器。
- 不加入电机的启动自检、编码器测速、位置闭环。
- 不做 ESP 侧观测（RSSI/Wi-Fi 状态查询不在本批次；若 §9 判读表落到“ESP 内部/
  Wi-Fi 迟滞”分支，另行授权）。
- **不触碰**存储介质上的旧证据、主说明书历史行、Git 工作区（Git 治理由另一代理
  负责，本批次全程禁止 `git add/commit/init/checkout/reset/clean`）。
- 本批次在主机端只登记基线，**不是**正式 4B-4 同步 Gate（摄像头未接入）。

---

## 2. 现状证据（引用并正确表述 dropout_root_cause_review.md）

以下为 `dropout_root_cause_review.md` 的结论等级原样表述，不得升级：

| 结论等级 | 内容 |
|---|---|
| **VERIFIED** | 20s 短测断流 = PC socket 收字节为零（10/10 个 >300ms 间隔内 RX 事件 = 0，`raw_recv_gap ≈ wall`，tick≈wall 0.99–1.08，无批次、无 tick 倒退）；90/90 遥测与 AA55 事件逐帧匹配；解析器/PC reader 批量迟到不支持。 |
| **LOCALIZED_NOT_ROOT_CAUSED** | （旧口径“异常发生在 MCU 遥测生成之后到 PC socket 之前”系**已否定的过强表述**，不再作为现状；历史原因见判读约束 1：主循环可能本轮未生成。）当前权威结论：**PC socket 收包侧已确认静默；异常仍可能在 MCU 本轮未生成、MCU/ESP 传输、ESP/Wi-Fi 到 PC 之间，尚未最终定位**。证据进一步强烈指向 CIPSEND 事务未完成/重试造成的发送停顿（LEADING HYPOTHESIS），但**没有固件计数器不能宣布最终根因**。 |
| **LEADING HYPOTHESIS** | CIPSEND 完成应答链异常（MCU 侧事务在异常窗口多次未正常完成）。下游仍分：ESP 内部/Wi-Fi 发送迟滞、ESP→MCU UART 丢失/溢出、应答解析遗漏。 |
| **ALTERNATIVES** | 主循环阻塞数秒、连接代次变化/多客户端、ESP 单独供电异常。 |
| **INSUFFICIENT_EVIDENCE** | 区分上述机制的计数器在现有协议中不存在（§7 缺失观测量清单）。 |

**必须遵守的判读约束**：

1. **不得写**“异常一定发生在 MCU 已生成遥测之后”——主循环可能未生成（例如在
   抑制态或阻塞态）。
2. 单个计数异常只能确定**主要机制**，不能宣称其他问题全排除（例如 CIPSEND 计数
   激增不排除 UART 分支，需同时看 overflow/ore）。
3. 一次复跑零断流**不能**证明永久无需修复（360s 零事件只降低常态高频故障的可能
   性，不能证明会话特异）。
4. 结论只能写 `LOCALIZED_NOT_ROOT_CAUSED — LEADING HYPOTHESIS: CIPSEND
   completion-response chain`，除非新证据把等级升级到 VERIFIED。

### 2.1 已知基线数字（作为阈值来源）

| 量 | 60s 运行 | 300s 运行 | 20s 运行 |
|---|---|---|---|
| 帧数 | 660 | 3274 | 90（窗口内 89 + 窗口外 1） |
| 速率（/名义时长） | 11.0 Hz | 10.913 Hz | 窗口内 89/20 = 4.45 Hz |
| 活跃跨度速率 | 11.0 Hz | 10.914 Hz | 89/16.578 = 5.37 Hz；全帧 5.28 Hz（可比口径） |
| tick p50 / p95 / max | 100 / 100 / 150 ms | 100 / 100 / 150 ms | 100 / 673 / 2988 ms |
| 墙钟 p50 / p95 / max | 94 / 109 / 156 ms | 94 / 110 / 141 ms | 94 / 672 / 2985 ms |
| >300ms 间隔数 | 0 | 0 | 10（9 真实 + 1 STOP 过渡） |
| tick 倒退 | 0 | 0 | 0 |

- 稳态 ~100ms 节拍 = CIPSEND 忙窗 + 遥测 latest-wins 覆盖（dropout review §2.2
  记为**设计事实**，非根因）；`tick/wall p50=1.064` 是 20ms 步进采样的量化结果。
- 缺口量级与 CIPSEND 超时窗口吻合（578/641/656/672/703/797 ≈ 1 次未完成事务，
  1204/1234 ≈ 2 次，2985 ≈ 4–5 次），但这是 HYPOTHESIS 层，不是 VERIFIED。

---

## 3. 架构

### 3.1 模块图

```
main.c 主循环
  ├─ 开机：health_reset_cause_from_csr(RCC->CSR) → 复位标志映射 u8 快照 + 清 RMVF
  ├─ 开机（安全初始化完成、电机归零后）：iwdg_init_and_enable()
  ├─ 每轮：health_loop_tick(now_ms)
  │      ├─ hstats_loop_tick()                主循环 seq/间隔
  │      ├─ twin_control_heartbeat_tick()     1s 租约检查（超时→电机归零+timeout）
  │      └─ IWDG_ReloadCounter()              完成一次健康迭代后喂狗
  ├─ 每 ~1s：health_emit(now_ms)
  │      ├─ hstats_build_snapshot(&snap)      读统计 + 环 + coordinator + transport
  │      ├─ health_frame_encode(buf, &snap)   纯编码 0x02（snapshot_tick_ms 一并填）
  │      └─ ESP_SendDiagFrame(buf, 111)       可丢、不阻塞 A/S
  ├─ ESP_SendQueuedFrames / ESP_TrySendTelemetry
  │      └─ cipsend_tx_start() 成功 → hstats_tx_started(tag, now_ms)
  └─ ESP_ServiceTX → etc_handle_terminal(&g_coordinator, now_ms)
         └─ 终态 → hstats_tx_terminal(tag, result, timeout_aborted,
                                      entered_send_data, now_ms)
            entered_send_data = tx->state ∈ {SEND_DATA, WAIT_SENDOK}
            区分 prompt_timeout / sendok_timeout（§4.3）

纯逻辑（Host C 可测）：
  health_stats.c/.h   统计与主循环计时（无硬件依赖，时间由调用方传入）
  health_frame.c/.h   0x02 帧编码器（无硬件依赖）
  twin_control_protocol.c/.h  H 心跳解析 + 租约状态机 + 健康视图 getter（时间传入）
  uart_ring.c/.h      RX ring 增加 high_water（ISR 侧一行比较）
  esp_tx_coordinator.c/.h    终态统计钩子（etc_handle_terminal 增加 now_ms 参数）

硬件薄层（不可 Host 测，逻辑极薄）：
  health_watchdog.c/.h  IWDG 使能与喂狗包装
  main.c                reset cause 快照、1Hz 发射、租约到期电机归零接线
```

依赖方向：`main.c → {health_stats, health_frame, health_watchdog, esp_*,
twin_control_protocol, uart_ring}`；`esp_tx_coordinator → health_stats`；
`health_frame` 只依赖 `stdint`；`health_stats` 只依赖 `stdint`。

### 3.2 新/改文件清单（与实施计划一一对应）

| 文件 | 动作 | 内容 |
|---|---|---|
| `程序/…/User/health_stats.h/.c` | 新增 | 统计结构体、主循环计时、事务/遥测/重试计数、快照构建 |
| `程序/…/User/health_frame.h/.c` | 新增 | `health_frame_encode()`：0x02 纯编码 |
| `程序/…/User/health_watchdog.h/.c` | 新增 | `iwdg_init_and_enable()`、`iwdg_feed()` |
| `程序/…/User/twin_control_protocol.h/.c` | 修改 | `H` 命令解析、心跳/租约状态机、健康视图 getter |
| `程序/…/User/uart_ring.h/.c` | 修改 | `high_water` 字段（RX/TX 两环，ISR 侧各 2 条比较更新） |
| `程序/…/User/esp_tx_coordinator.h/.c` | 修改 | `etc_handle_terminal(..., now_ms)`；终态统计钩子 |
| `程序/…/User/main.c` | 修改 | reset cause 快照、health_loop_tick、1Hz 发射、租约到期电机归零、IWDG 使能/喂狗接线 |
| `程序/…/project.uvprojx` | 修改 | User 组加入 health_stats.c / health_frame.c / health_watchdog.c |
| `simulation/digital_twin/real_world/frame_parser.py` | 修改 | 0x02 健康帧识别与解码；上层按 `(frame_type, payload_len)` 联合分流（len==106→health、len==7→STATUS、其余判坏） |
| `simulation/digital_twin/real_world/wifi_bridge.py` | 修改 | `_process_binary_frame()` 按 `(frame_type, payload_len)` 分流；106B 健康帧走 health 路径，7B 旧 STATUS 保留，绝不广播为 car_status（Round 2 项 1） |
| `simulation/digital_twin/web_showcase/live_wifi_bridge.py` | 修改 | `_process_frame()` 同一分流规则（Round 2 项 1） |
| `.embeddedskills/build/v1_task4b4/transport_soak.py` | 修改 | 0x02 解析/持久化、心跳发送、finally STOP、唯一 run_id、门禁拆分、窗口排除 |
| `.embeddedskills/build/v1_task4b4/test_transport_soak_rework.py` | 修改 | 新用例 |
| `simulation/digital_twin/tests/test_health_stats.c` | 新增 | 统计纯逻辑测试（含 `health_*` 六项专属计数） |
| `simulation/digital_twin/tests/test_health_frame.c` | 新增 | 0x02 golden vector 测试（111 字节） |
| `simulation/digital_twin/tests/test_twin_control_protocol.c` | 修改 | 心跳/租约用例 |
| `simulation/digital_twin/tests/test_uart_ring.c` | 修改 | RX/TX 两环 high_water 用例 |
| `simulation/digital_twin/tests/test_coordinator_boundary.c` | 修改 | 新签名 + 统计钩子用例 |
| `simulation/digital_twin/tests/test_wifi_bridge_health_dispatch.py` | 新增 | 生产 bridge `_process_binary_frame` 的 `(frame_type, len)` 分流回归（Round 2 项 1，**新建**） |
| `simulation/digital_twin/web_showcase/test_live_wifi_health_dispatch.py` | 新增 | 生产 bridge `_process_frame` 的 `(frame_type, len)` 分流回归（Round 2 项 1，**新建**） |

Host C 构建使用 ASCII 路径 shim（`.embeddedskills/build/v1_task4b4_fix/hostc/User|System`，
见 §11.2），新模块需同时复制到 shim。

---

## 4. 状态机

### 4.1 主循环健康迭代（每轮一次）

采样点在**每轮迭代顶部**、`ESP_ServiceRX()` 之前执行 `health_loop_tick(now_ms)`：

```
health_loop_tick(now_ms):
  g_loop_seq++                                   # 主循环迭代序号（mod 2^32）
  if first tick:                                 # P0-2：首次仅建立时间基线
      g_last_loop_ms = now_ms                    #   （mono 在 ESP_Setup 前启动，
      g_loop_last_gap_ms = 0                     #    首个 tick 可能已过去数秒，
      g_loop_max_gap_ms = 0                      #     不得记成 loop gap/max）
  else:
      gap = now_ms - g_last_loop_ms              # 距上一轮顶部
      g_last_loop_ms = now_ms
      g_loop_last_gap_ms = min(gap, 0xFFFF)      # 饱和，不回绕
      if gap > g_loop_max_gap_ms: g_loop_max_gap_ms = min(gap, 0xFFFF)
  if twin_control_heartbeat_tick(now_ms) == 1:   # 租约到期（已在协议层设 inhibited）
      MotorTargetsZero()                          # 同轮立即四路归零
  IWDG_ReloadCounter()                            # 喂狗：证明上一轮已返回循环顶部（当前轮尚未完成）
```

字段语义：

- `loop_seq`（u32，mod 2^32）：本轮迭代序号。正常 ~200/s（5ms 轮）；PC 端按
  mod 差值核对“主循环在跑”。
- `loop_last_gap_ms`（u16，饱和）：距上一轮顶部的真实单调毫秒。正常 ~5–8ms；
  >100ms 出现于断流窗口 → **A1 主循环阻塞成立**（§9）。
- `loop_max_gap_ms`（u16，饱和）：开机以来最大轮间隔峰值。
- **“正常一轮”喂狗条件**：主循环推进到 `health_loop_tick`（每轮迭代顶部）的喂狗点。
  该喂狗只证明**上一轮**健康迭代已完整跑完并返回本轮顶部；**不把当前轮尚未完成的
  工作描述为已完成**。主循环为 `while(1)`、无正常退出路径，所有正常分支（心跳续约、
  租约到期归零、STOPPED/INIT 抑制等）下一轮都会再次到达该喂狗点；若任一分支使主
  循环死锁/失活（含 `HardFault_Handler` 的 `while(1)`），喂狗停止 → IWDG ~2s 复位。

### 4.2 心跳租约状态机（twin_control_protocol 内，时间由调用方传入）

```
事件：
  H 帧到达（校验和 + campaign/run 匹配当前 g_current_campaign/run_id）
      → 置 g_heartbeat_pending；主循环每轮在 health_loop_tick 前 consume 并调
        twin_control_heartbeat(now_ms)
  twin_control_heartbeat(now_ms):
      g_heartbeat_count++                       # 接收计数（任何状态都计）
      if !g_motion_inhibited:
          g_last_heartbeat_ms = now_ms          # 续约（仅 RUNNING 态生效）

  每轮 twin_control_heartbeat_tick(now_ms):
      if g_motion_inhibited: return 0
      if !g_was_running:                        # inhibited→running 边沿
          g_last_heartbeat_ms = now_ms          # START 立即开启 1s 租约
          g_was_running = 1
          return 0
      if now_ms - g_last_heartbeat_ms >= TWIN_CONTROL_HEARTBEAT_LEASE_MS (1000):
          g_heartbeat_timeout_count++
          g_last_inhibit_reason = REASON_HEARTBEAT
          twin_control_timeout()                # 既有 TIMEOUT 回滚：inhibited=1、
                                                # restore_baseline=1、
                                                # queue STOPPED/TIMEOUT（S 帧 reason 兼容）
          g_was_running = 0
          return 1
      return 0

  STOP/RESTORE_BASELINE/LINE_LOST/legacy timeout 到达时：g_was_running = 0
      （在 parse_run / twin_control_timeout / report_line_lost 抑制分支复位）
```

要点：

- **START 立即开启 1 秒租约**：靠 `!g_was_running` 边沿把 `g_last_heartbeat_ms`
  置为当前时间，PC 首条心跳（~200ms）续约即可，无需在 START 解析点依赖时钟。
- **租约只在 RUNNING 态续约**：STOPPED 时到达的迟发 H 帧只计 `heartbeat_count`，
  不改运动状态、不续约。
- **旧 S 帧 reason 保持 `TIMEOUT`**（`twin_control_timeout()` 原语义）；
  `0x02` 的 `heartbeat_last_reason=HEARTBEAT` 用于区分“心跳租约到期”与“旧式
  命令/断连超时”。
- 主循环接线：租约到期在 `health_loop_tick` 内返回 1 → 立即 `MotorTargetsZero()`；
  随后同一轮进入 `if (twin_control_motion_inhibited())` 分支继续归零与 `Delay_ms(5)`，
  保证**同轮原子性**（到期瞬间不产出任何新 MotorOut）。

### 4.3 CIPSEND 事务状态机（现有，不修改状态图，只加计数）

现有 `IDLE→SEND_CMD→WAIT_PROMPT→SEND_DATA→WAIT_SENDOK→COMPLETE/FAILED`
（`cipsend_tx.c`）与 `etc_handle_terminal` 完全保留。新增统计挂钩：

- `cipsend_tx_start()` 成功处（main.c 三处 + coordinator）调 `hstats_tx_started(tag, now_ms)`。
- `etc_handle_terminal()` 处理终态前调
  `hstats_tx_terminal(tag, result, timeout_aborted, entered_send_data, now_ms)`，
  其中 `entered_send_data = (tx->state ∈ {SEND_DATA, WAIT_SENDOK})` 由调用方从
  `CipsendTx` 状态推导传入；记录结果分类与 `duration = now - start`。

结果分类规则（`0x02` 各计数）：

| `0x02` 字段 | 增量条件 |
|---|---|
| `cipsend_ok` | `result == CTS_RESULT_OK` |
| `cipsend_error` | `result == CTS_RESULT_ERROR`（含 `busy`，见 send_response_parser 前缀匹配） |
| `cipsend_prompt_timeout` | `result == CTS_RESULT_NONE && timeout_aborted &&` 事务未进入 SEND_DATA |
| `cipsend_sendok_timeout` | `result == CTS_RESULT_NONE && timeout_aborted &&` 事务已进入 SEND_DATA/WaitSENDOK |
| `cipsend_closed` | `result == CTS_RESULT_CLOSED` |

`cipsend_started == 各 tag started 之和`；`cipsend_completed ==
ok+error+prompt_timeout+sendok_timeout+closed`（模 2^16 近似，异常时用于校验）。
`last_duration_ms / max_duration_ms`：本事务/历史峰值事务时长（开始→终态，mono ms）。

**0x02 专属归属（Round 2 项 2）**：同一 `hstats_tx_terminal` 钩子中，当
`tag == CIPSEND_TX_TAG_DIAG_HEALTH` 时另增 `health_ok`（`CTS_RESULT_OK`）、
`health_failed`（其它终态）、`health_last_duration_ms`（本事务 duration，饱和 u16）；
`CIPSEND_TX_TAG_DIAG`（0x7E）只增 `diag_health_started`，二者互不混计。`cipsend_*`
全局计数仍按上表对所有 tag 累加（含 0x02），但**不作为** 0x02 专属投递率/事务延迟
的依据。

### 4.4 遥测管线状态机（现有 latest-wins 槽，只加计数）

| `0x02` 字段 | 语义与增量点 |
|---|---|
| `telemetry_generated` | `Telemetry_Queue()` 构建新帧时 +1（无论是否覆盖） |
| `telemetry_overwritten` | `Telemetry_Queue()` 进入时 `s_tele_pending` 已为 1 → +1（latest-wins 覆盖，**该旧帧从未发出**） |
| `telemetry_tx_started` | `ESP_TrySendTelemetry()` 中 `cipsend_tx_start(TAG_TELEMETRY)` 成功 +1 |
| `telemetry_tx_ok` | TELEMETRY tag 事务 `CTS_RESULT_OK` +1 |
| `telemetry_tx_failed` | TELEMETRY tag 事务非 OK 终态 +1 |

**判读禁令**：`telemetry_tx_started` 只表示“已交给 CIPSEND 状态机”，**不得**视为
“已到 PC”；只有 `telemetry_tx_ok`（ESP 回 SEND OK）才证明帧离开 MCU UART 被 ESP
确认，且仍不证明 PC 已收到（ESP/TCP 仍可吞帧，这正是断流待定位机制）。

### 4.5 UART 计数（现状已部分存在 + 新增 high_water）

`UartRing` 现有 `rx_bytes / overflow_drops / ore_events`（RX 环），TX 环复用同一结构
（push 计数 `rx_bytes`，满则 `overflow_drops`）。`0x02` 将：

- `uart_rx_bytes`：RX 环 `rx_bytes`（mod 2^32）。
- `uart_tx_bytes`：TX 环 `rx_bytes`（mod 2^32）。
- `uart_rx_overflow`：RX 环 `overflow_drops`。
- `uart_tx_overflow`：TX 环 `overflow_drops`。
- `uart_ore_events`：RX 环 `ore_events`（USART1_IRQHandler 已计）。
- `uart_rx_high_water`：**新增** RX 环历史最大占用量（`used+1` 写入后
  `if (used+1 > high_water) high_water = used+1`，ISR 侧 2 条比较，成本可接受）。
- `uart_tx_high_water`：**新增** TX 环历史最大占用量（同一比较逻辑）。`UartRing`
  为通用结构，RX/TX 两环共用同一实现，成本仅 ISR 侧 2 条比较；暴露 TX 环峰值即可
  观测 TX 积压，消除“仅命令长度有上界”无法排除 TX 环积压的缺口（Codex Round1 项 4）。
  RX/TX 两处 `UartRing` 的 `high_water` 均在 `uart_ring_init` 清零。

---

## 5. `0x02` 健康诊断帧协议布局

### 5.1 帧骨架（复用 AA55/type/len/payload/XOR）

```
[0] 0xAA
[1] 0x55
[2] type = 0x02
[3] len  = 0x6A (106)
[4..109] payload (106 字节)
[110] XOR checksum = type ^ len ^ payload[0..105]
```

- 总长 **111 字节 ≤ CIPSEND 数据上限 `CIPSEND_TX_MAX_DATA` (112)** ✓（余量仅 1B，
  边界评估见 §10）。
- CIPSEND 命令为 `AT+CIPSEND=<id>,111\r\n`，18 字符 ≤ `CIPSEND_TX_MAX_CMD` (24) ✓。
- 编码器 `health_frame_encode()` 为纯函数，黄金向量由 Host C 与 Python 双侧断言。

### 5.2 精确字节布局（offset 为帧内偏移；全部小端；u16/u32 均为 LE）

| off | 宽度 | 字段 | 类型/单位 | 端序 | 回绕/饱和规则 |
|---|---|---|---|---|---|
| 4 | 1 | `fw_schema_version` | u8 / 版本 | — | 0..255；0x02 布局变化时递增；本版 = 1 |
| 5 | 1 | `fw_build_id` | u8 / 构建序号 | — | 编译期固定（见 §5.4） |
| 6 | 1 | `reset_cause` | u8 / 复位标志映射 | — | 开机快照；位映射见 §5.5（P0-1：高字节复位标志右移，低位 LSI/RMVF 忽略） |
| 7 | 1 | `motion_state` | u8 / 枚举 | — | 0=INIT 1=RUNNING 2=STOPPED 3=TIMEOUT 4=LINE_LOST 255=未知 |
| 8 | 1 | `lease_active` | u8 / 0/1 | — | 1 当 RUNNING 且 now-last_heartbeat < 1000 |
| 9 | 1 | `heartbeat_last_reason` | u8 / 枚举 | — | 0=NONE 1=LEGACY_TIMEOUT 2=HEARTBEAT 3=STOP 4=RESTORE_BASELINE 5=LINE_LOST |
| 10 | 2 | `heartbeat_timeout_count` | u16 / 次数 | LE | mod 2^16 |
| 12 | 2 | `heartbeat_count` | u16 / 帧 | LE | mod 2^16；**parse 时每条校验/身份匹配的 H 都 +1**（同一次 RX drain 多条不合并，P1-4）；无效/错身份 H 不计 |
| 14 | 4 | `heartbeat_age_ms` | u32 / ms | LE | `0xFFFFFFFF`=从未收到有效心跳；否则=now-last_seen_heartbeat（**距最后消费的有效 H**，独立于租约续约时刻，P1-4，mod 2^32） |
| 18 | 4 | `connection_generation` | u32 / 代次 | LE | mod 2^32（`esp_transport_connection_generation()`） |
| 22 | 4 | `snapshot_tick_ms` | u32 / ms | LE | mod 2^32；采集本快照时 `mono_now_ms()`，与 1Hz 发射同一调用点（§5.3） |
| 26 | 4 | `loop_seq` | u32 / 轮 | LE | mod 2^32 |
| 30 | 2 | `loop_last_gap_ms` | u16 / ms | LE | 饱和 0xFFFF |
| 32 | 2 | `loop_max_gap_ms` | u16 / ms | LE | 饱和 0xFFFF；峰值不清零 |
| 34 | 2 | `telemetry_generated` | u16 / 帧 | LE | mod 2^16 |
| 36 | 2 | `telemetry_overwritten` | u16 / 帧 | LE | mod 2^16 |
| 38 | 2 | `telemetry_tx_started` | u16 / 帧 | LE | mod 2^16 |
| 40 | 2 | `telemetry_tx_ok` | u16 / 帧 | LE | mod 2^16 |
| 42 | 2 | `telemetry_tx_failed` | u16 / 帧 | LE | mod 2^16 |
| 44 | 2 | `cipsend_started` | u16 / 事务 | LE | mod 2^16 |
| 46 | 2 | `cipsend_completed` | u16 / 事务 | LE | mod 2^16 |
| 48 | 2 | `cipsend_ok` | u16 / 事务 | LE | mod 2^16 |
| 50 | 2 | `cipsend_error` | u16 / 事务 | LE | mod 2^16 |
| 52 | 2 | `cipsend_prompt_timeout` | u16 / 事务 | LE | mod 2^16 |
| 54 | 2 | `cipsend_sendok_timeout` | u16 / 事务 | LE | mod 2^16 |
| 56 | 2 | `cipsend_closed` | u16 / 事务 | LE | mod 2^16 |
| 58 | 4 | `cipsend_last_duration_ms` | u32 / ms | LE | mod 2^32；无完成事务=0 |
| 62 | 4 | `cipsend_max_duration_ms` | u32 / ms | LE | 饱和 0xFFFFFFFF |
| 66 | 2 | `ack_started` | u16 / 帧 | LE | mod 2^16（TAG_ACK start 成功） |
| 68 | 2 | `status_started` | u16 / 帧 | LE | mod 2^16（TAG_STATUS start 成功） |
| 70 | 2 | `telemetry_started` | u16 / 帧 | LE | mod 2^16（TAG_TELEMETRY start 成功） |
| 72 | 2 | `diag_health_started` | u16 / 帧 | LE | mod 2^16（`CIPSEND_TX_TAG_DIAG` start 成功，仅 0x7E 旧诊断；0x02 归属 `health_started`，Round 2 项 2） |
| 74 | 2 | `status_retry` | u16 / 次 | LE | mod 2^16；见 §5.6 |
| 76 | 2 | `ack_retry` | u16 / 次 | LE | mod 2^16；见 §5.6 |
| 78 | 2 | `boundary_aborts` | u16 / 事件 | LE | mod 2^16（coordinator `boundary_events`） |
| 80 | 4 | `uart_rx_bytes` | u32 / 字节 | LE | mod 2^32（RX 环 `rx_bytes`） |
| 84 | 4 | `uart_tx_bytes` | u32 / 字节 | LE | mod 2^32（TX 环 `rx_bytes`） |
| 88 | 2 | `uart_rx_overflow` | u16 / 丢字节 | LE | mod 2^16 |
| 90 | 2 | `uart_tx_overflow` | u16 / 丢字节 | LE | mod 2^16 |
| 92 | 2 | `uart_ore_events` | u16 / 事件 | LE | mod 2^16 |
| 94 | 2 | `uart_rx_high_water` | u16 / 字节 | LE | 饱和 0xFFFF；峰值不清零 |
| 96 | 2 | `uart_tx_high_water` | u16 / 字节 | LE | 饱和 0xFFFF；峰值不清零（TX 环，§4.5） |
| 98 | 2 | `health_generated` | u16 / 帧 | LE | mod 2^16（每 1Hz 尝试 +1；busy 分支与 dropped 同帧递增，可发送分支在快照填充后、start 前递增，故快照值 = 截至上一笔已归类尝试，Round 3 项 3） |
| 100 | 2 | `health_dropped` | u16 / 帧 | LE | mod 2^16（busy 分支：generated 后立即 +1；可发送分支：start 失败 +1；均在快照归类之后，Round 3 项 3） |
| 102 | 2 | `health_started` | u16 / 帧 | LE | mod 2^16（`CIPSEND_TX_TAG_DIAG_HEALTH` 事务 `cipsend_tx_start` 成功 +1；快照填充时当前笔尚未 start，Round 3 项 3） |
| 104 | 2 | `health_ok` | u16 / 帧 | LE | mod 2^16（`CIPSEND_TX_TAG_DIAG_HEALTH` 事务 `CTS_RESULT_OK` +1） |
| 106 | 2 | `health_failed` | u16 / 帧 | LE | mod 2^16（`CIPSEND_TX_TAG_DIAG_HEALTH` 事务非 OK 终态 +1） |
| 108 | 2 | `health_last_duration_ms` | u16 / ms | LE | 饱和 0xFFFF；最近一笔 0x02 事务开始→终态时长；无完成事务=0；仅存最近一笔，不构成完整事务延迟分布（Round 3 项 4） |

payload 总长 = 106（offset 4..109），帧总长 = 111。

**health 专属计数与 `diag_health_started` 的边界（Round 2 项 2）**：`diag_health_started`
仅计 `CIPSEND_TX_TAG_DIAG`（0x7E 旧诊断）start，**不含** 0x02；0x02 走独立
`CIPSEND_TX_TAG_DIAG_HEALTH`（=5U，新增），由 `health_*` 六项专门归属，消除“0x7E
与 0x02 混合计数”的不可归因问题。

**0x02 快照时序与恒等式（Round 3 项 3）**：`health_emit` 归类顺序固定为——① due 后先判
`cipsend_tx_busy || txfq_has_retry`；busy 分支 `generated++` 与 `dropped++` 后退出
（不发射）；② 可发送分支**先**以“截至上一笔已归类尝试”的计数填快照并编码，**随后**
`generated++`，再调用 start，成功 `started++`、失败 `dropped++`。因此每帧快照报告的
是当前发送动作之前的**完整会计状态**：`health_generated == health_dropped +
health_started`（模 2^16）恒成立；`health_started == health_ok + health_failed +
in_flight`，`in_flight ∈ {0,1}`（已 start 尚未终态的 0x02 事务；可发送分支快照时
in_flight=0，相邻帧之间最多 1 笔在途）。PC 端按相邻快照的模差增量联合判读，不逐笔
对账。

**连接边界中止进入恒等式（P0-3）**：`esp_tx_coordinator::do_abort` 在 reset 在途
CIPSEND 前，对**真正在途**（`cipsend_tx_busy()`，非 IDLE/非终态）事务按 tag 调
`hstats_tx_boundary_abort(s, tag, now_ms)` 诚实结算——0x02（`TAG_DIAG_HEALTH`）→
`health_failed++`（`health_last_duration_ms = now_ms - start`，now_ms 由调用方显式传，
不猜测）；telemetry（`TAG_TELEMETRY`）→ `telemetry_tx_failed++`。边界中止**不**
进入 `cipsend_error/prompt_timeout/sendok_timeout`（不冒充 ESP ERROR/SEND OK 超时），
也**不**触碰 `cipsend_completed`（那是终态分类）；结算后 `started == ok + failed +
in_flight` 恢复（in_flight 回 0），`boundary_aborts` 计数器 +1。终态 CLOSED 清理路径
（`etc_handle_terminal`）已由 `hstats_tx_terminal` 结算 failed，其后的 `etc_force_abort`
见 `cipsend_tx_busy()==0` 故不二次计。

**回绕/饱和总则**：累积计数（`*_count`、`*_started`、`*_ok`、字节数等）为**模
2^w 回绕**，PC 端按模差值计算间隔增量（1s 内任何字段增量都远小于 2^16/2^32，
不会歧义）；`snapshot_tick_ms` 为 mono tick 时间戳，同样按**模 2^32 回绕**，PC 端
以相邻快照的模差值估计真实间隔（期望 ~1000ms，偏差即发射/投递延迟）；峰值/间隔/
年龄字段（`*_max_*`、`*_last_gap`、`heartbeat_age_ms`）为**饱和**，其中“从未发生”
用 `0` 或 `0xFFFFFFFF` 哨兵，字段表已逐项注明。

### 5.3 快照一致性（Cortex-M3）

- 对齐的 32 位 load（LDR）与 16 位 load（LDRH）在 Cortex-M3 上是单指令、原子完成；
  ISR 的 read-modify-write（如 `rx_bytes++`）与主上下文的一次对齐 load 不会撕裂。
- `UartRing` 结构 `buf[128]` 使 `head/tail(u16)` 与 `rx_bytes(u32)` 自然对齐
  （buf 128 字节 → 后续字段 4 字节对齐），u16/u32 字段均对齐访问。
- `snapshot_tick_ms` 在构建快照的同一调用点取 `mono_now_ms()`（采集与发射同时），
  保证该时间戳与同帧各字段属同一次快照。
- 快照构建只做**每字段一次对齐读**，不做 IRQ 关闭（临界区最小化为零）；整体快照
  各字段可能跨数个 ISR 滴答，属 1Hz 诊断可接受的不一致，文档明示。
- `health_stats` 计数器全部为主上下文单写者；跨 ISR 共享的只有 RX/TX 两环
  `rx_bytes/overflow_drops/ore_events/high_water`，读方为主上下文对齐 load。
- 新增 `high_water` 为 u16，放入 `UartRing`（RX/TX 两环均为 ISR 写、主上下文读），
  同样满足对齐原子读。
- 新增 `health_*` 六项全部为**主上下文单写者**（health_emit 写 generated/dropped，
  tx_started/tx_terminal 写 started/ok/failed/duration），跨 ISR 共享仅为 RX/TX 两环
  计数，快照读为对齐 load，无撕裂。

### 5.4 身份与构建标识（避免“日期字符串即唯一证明”）

- `fw_schema_version`：0x02 布局的语义版本（本版 = 1）。布局变必变。
- `fw_build_id`：编译期手动设定的 u8 构建序号（`#define FW_BUILD_ID 1U` 于
  `health_frame.h` 单一来源），**不**从 RTC/时钟派生。
- **正确性声明**：机内 `fw_build_id` 只是排查便利标识，**不是**“哪个二进制在
  MCU 上”的唯一证明。唯一证明是烧录前后对 AXF/HEX 产物的 SHA-256 比对（§10 runbook）
  与 `0x02` 上报值 + 记录哈希的交叉核对。日期/时间字符串不得作为固件身份证据。
- `reset_cause`：开机最早在 `main()` 顶部用纯函数 `health_reset_cause_from_csr()`
  把 `RCC->CSR` 原始 u32 映射为协议 u8 存全局，随后写 `RCC_CSR_RMVF` 清除标志，
  使下一次复位原因独立可判。IWDG 复位时 CSR 的 `IWDGRST` 位置位 → 可证明“上次复位
  由看门狗触发”。
- **位映射（P0-1）**：STM32F1 复位标志在 CSR **高字节**，低位是 LSI 状态
  （LSION/LSIRDY）。以实际头文件 `stm32f10x.h` RCC_CSR 定义为权威：
  `RMVF=0x01000000(bit24)`、`PINRSTF=0x04000000(bit26)`、`PORRSTF=0x08000000(bit27)`、
  `SFTRSTF=0x10000000(bit28)`、`IWDGRSTF=0x20000000(bit29)`、`WWDGRSTF=0x40000000(bit30)`、
  `LPWRRSTF=0x80000000(bit31)`。映射保留高字节 flag 原位、仅清 RMVF(bit24) 与保留位
  (bit25)：`(uint8_t)((csr >> 24U) & 0xFCU)`。（Codex 实现审核 Round 2：旧文本
  `& 0x3F` 会把 RMVF 误报为复位原因、丢弃 WWDG/LPWR。）

  | CSR 位 | 含义 | 协议 u8 |
  |---|---|---|
  | 24 | RMVF（清标志写位，非复位原因） | 0x00 |
  | 25 | 保留位 | 0x00 |
  | 26 | PINRSTF（NRST 引脚） | 0x04 |
  | 27 | PORRSTF（上电/掉电） | 0x08 |
  | 28 | SFTRSTF（软件复位） | 0x10 |
  | 29 | IWDGRSTF（独立看门狗） | 0x20 |
  | 30 | WWDGRSTF（窗口看门狗） | 0x40 |
  | 31 | LPWRRSTF（低功耗复位） | 0x80 |

  多标志可组合（例如 PIN+POR = 0x0C）。低位仅 0x1F 时应为 0。

### 5.5 `motion_state` 与 `heartbeat_last_reason` 映射

| 枚举 | motion_state | 来源 |
|---|---|---|
| INIT | 0 | 权威状态 `g_last_state == "INIT"` |
| RUNNING | 1 | 权威状态 `"RUNNING"` |
| STOPPED | 2 | 权威状态 `"STOPPED"` 且 reason ∈ {STOP, RESTORE_BASELINE} |
| TIMEOUT | 3 | 权威状态 `"STOPPED"` 且 reason == `"TIMEOUT"`（含心跳租约到期与旧式超时） |
| LINE_LOST | 4 | 权威状态 `"STOPPED"` 且 reason == `"LINE_LOST"` |
| 未知 | 255 | 其它 |

`heartbeat_last_reason`：最近一次运动抑制事件的原因索引：
0=NONE（开机后未抑制过）、1=LEGACY_TIMEOUT、2=HEARTBEAT（心跳租约到期）、
3=STOP、4=RESTORE_BASELINE、5=LINE_LOST。
判读组合：`motion_state==TIMEOUT(3) && heartbeat_last_reason==HEARTBEAT(2)` =
“该超时由心跳租约到期造成”；`motion_state==TIMEOUT(3) && heartbeat_last_reason==
LEGACY_TIMEOUT(1)` = “旧式命令/断连超时”。旧 S 帧两种都显示 `STOPPED/TIMEOUT`
（兼容），`0x02` 负责区分。

### 5.6 重试计数定义

`status_retry` / `ack_retry`：启动一次 STATUS/ACK 事务时，若载荷来自**保留重试缓冲**
（`txfq_has_status()`/`txfq_has_ack()` 在取新帧前已为真，即上笔非 OK 终态后重发），
则 +1；若为传输层新取帧则不计。该计数直接回答“断流窗口内 STATUS 是否被重试”
（dropout review §7 缺失观测量之一），与 `connection_generation` 变化组合可区分
“STATUS 重试”与“连接代次变化权威状态重发”两条重复 RUNNING 路径。

---

## 6. 安全行为

### 6.1 心跳租约

- 周期：PC RUNNING 态每 200ms 发 `H,<campaign>,<run_id>,<cs>\n`；MCU 连续
  ≥1000ms 无有效心跳 → `MotorTargetsZero()` + `twin_control_timeout()`。
- 有效心跳判定：XOR 校验通过，且 campaign/run 与当前 `g_current_campaign_id/
  g_current_run_id` 匹配（**防旧状态误关联**——每次运行唯一 run_id 的 MCU 侧对应）。
- **计数与年龄（P1-4）**：每条校验/身份匹配的 H 都在 parse 时计入 `heartbeat_count`
  （即使 `pending` 已为 1，同一 RX drain 多条不合并）；无效/错身份 H 不计。
  `pending` 仍是“至少一条新心跳待续约”的布尔量，安全租约只续一次。消费有效 pending
  时**始终**更新 `last_seen_heartbeat_ms`（`heartbeat_age_ms` 口径 = 距最后处理的
  有效 H，未见过返回 `0xFFFFFFFF`）；仅 RUNNING 态更新 `last_lease_heartbeat_ms`
  （租约续约），STOPPED 的迟发 H 更新 count/age 但不续约。
- 心跳帧格式：`H,<campaign>,<run_id>,<checksum>\n`，长度 ≤
  `TWIN_CONTROL_LINE_MAX`(96)，可整帧放入一个 +IPD 载荷（`IPD_PAYLOAD_MAX` 96）✓。
- S 帧 reason 保持 `TIMEOUT`（兼容）；`0x02` 暴露 `heartbeat_timeout_count` 与
  `heartbeat_last_reason`。

### 6.2 IWDG

- 使能时机：`main()` 中安全初始化完成（`twin_control_init` 后 motion 默认抑制）、
  电机已归零（开机未使能前不调用 MotorOut）、且 **`ESP_Setup()` 的阻塞延时全部
  结束之后**（否则 10s/1.5s 阻塞会误触发看门狗）。放置点在主循环前、`while(1)` 外。
- 喂狗：每轮主循环迭代顶部 `health_loop_tick()` 内 `IWDG_ReloadCounter()`（见 §4.1）；
  语义为证明**上一轮**已返回循环顶部，当前轮尚未完成的工作不被描述为已完成。所有
  正常分支下一轮均会再次到达该喂狗点。
- 复位：约 2s 名义超时；**实际范围**见 §7.2。复位后 `main()` 重新初始化 →
  motion 默认抑制（`twin_control_init`），必须重新 START。
- 副作用（正面）：现有 `HardFault_Handler` 等 `while(1)` 死循环在 IWDG 下会
  自动复位恢复，`0x02` 的 `reset_cause` 带 `IWDGRST` 位可证明。

### 6.3 失联默认行为

TCP CLOSED（现有）与心跳租约到期（新增）都走 `twin_control_timeout()`：
motion_inhibited=1、restore_baseline=1、queue `STOPPED/TIMEOUT`、主循环同轮
`MotorTargetsZero()`。二者在 S 帧外观相同（兼容），`0x02` 用
`heartbeat_last_reason`/`connection_generation`/`cipsend_closed` 区分。

---

## 7. 故障模型与 IWDG 时间范围

### 7.1 故障 → 观测 → 动作映射

| 故障 | 观测字段 | 动作/行为 |
|---|---|---|
| 主循环死锁/失活 | `loop_last_gap_ms`、`loop_max_gap_ms` 激增；`loop_seq` 停更 | IWDG ~2s 复位；`reset_cause.IWDGRST=1` |
| PC 停止心跳 | `heartbeat_age_ms` ≥1000、`heartbeat_timeout_count`+1 | 电机归零、抑制、S `STOPPED/TIMEOUT` |
| ESP→MCU 噪声灌满 RX 环 | `uart_rx_overflow`、`uart_rx_high_water`=128 | 丢 `>`/`SEND OK`→CIPSEND 超时（`cipsend_prompt_timeout`/`sendok_timeout`） |
| TX 环积压（发送拥塞） | `uart_tx_high_water` 峰值、`cipsend_*` 联合 | 与 `cipsend_*`/`telemetry_tx_*` 增量联合判读发送链路是否拥塞 |
| ORE | `uart_ore_events` | 与 overflow 类似影响 RX |
| CIPSEND 事务失败 | `cipsend_error/prompt_timeout/sendok_timeout/closed`、`*_retry` | A/S 保留重试；telemetry/health 丢弃 |
| 连接代次变化/多客户端 | `connection_generation`、`boundary_aborts` | coordinator 边界清理；权威状态重发 |
| 遥测槽覆盖 | `telemetry_overwritten` | 设计行为，正常负载下上升 |
| 硬故障死循环 | `reset_cause.IWDGRST` | IWDG 复位恢复，抑制态重启 |
| 固件逻辑 bug 致循环持续但无遥测发出 | `telemetry_generated` 持续但 `telemetry_tx_*` 停滞 | 定位到发送链路而非生成链路 |

### 7.2 IWDG 实际超时范围（必须如实声明）

STM32F103 LSI 典型 40kHz，datasheet 范围 **30–60kHz**。IWDG 超时：
`t = (PR 分频 × (RLR+1)) / f_LSI`。取 PR=`IWDG_Prescaler_64`（分频 64）、
`RLR=1249`：

- 名义：`64 × 1250 / 40kHz = 2000ms`
- 下限：`64 × 1250 / 60kHz ≈ 1333ms`
- 上限：`64 × 1250 / 30kHz ≈ 2667ms`

**因此“约 2 秒未喂狗则复位”的实际窗口为 [~1.33s, ~2.67s]**。固件注释、0x02 文档
与主机判读都必须使用该范围，不得伪称精确 2.000s。正常每轮 ~5ms 喂狗远小于该
窗口，只有主循环真正停喂才触发复位。

---

## 8. 兼容性

### 8.1 旧 PC（未更新解析器）遇到 `0x02`

- 现有 `simulation/digital_twin/real_world/frame_parser.py` 定义
  `FRAME_TYPE_STATUS = 0x02`、`PAYLOAD_LEN_STATUS = 7`——该定义**从未被固件发射过**
  （固件 0x02 此前无实际字节流），属于孑遗定义。
- **旧 parser 对 `0x02(len=106)` 的行为（本轮 Round 2 Codex 新鲜只读复算的观察，
  非已建测试证据）**：源文件 `frame_parser.feed()` 的 `len>64` 分支决定，新 `0x02`
  帧 `len=106 > 64` 会在收到 LEN 字节后被旧 `FrameParser` 判坏——`frames_bad++`、
  `resync_count++`、状态回到 `S_IDLE` 继续扫描下一帧头。**不崩溃、不会进入
  `decode_status` 产生垃圾**、不会造成持续失步（拒绝后从 IDLE 重新同步，下一帧可
  正常解析）。该行为当前只是只读复算的观察；**永久回归测试
  `test_old_parser_health_compat.py` 是计划 Task 8 Step 8.0 的待建项，尚未创建**，
  不得把未来测试写成已存在证据。
- **这是指标兼容性变化，不宣称完全兼容**：旧工具会把每帧新 `0x02` 计入 `frames_bad`
  与 `resync_count`（判读时必须明确这是新帧被拒绝而非链路错误）；因此**不能**笼统
  称“向后完全兼容”。兼容边界以计划 Task 8 Step 8.0 的测试 gate（待建）为准：向旧
  parser 喂入新黄金帧 → 不崩溃、无持续失步、`frames_bad`/`resync_count` 各 +1。
- 若把健康帧压到 ≤64 字节反而会被旧解码器误吞（`decode_status` 产生垃圾），故保持
  106 字节是**有意**的显式拒绝。
- `transport_soak.py` 的 `MixedStreamParser` 同样按旧规则把 `0x02(len=106)` 记为坏帧；
  本次计划会把工具同步升级为 0x02 识别（§8.2），因此正式 soak 判读不再受此影响。
- **生产 bridge 分发（Round 2 项 1）**：`frame_parser.py` 的 `len` 上限从 64 提到
  106 后，`0x02` 健康帧会通过 `FrameParser` 到达两个生产消费者——
  `real_world/wifi_bridge.py::_process_binary_frame()` 与
  `web_showcase/live_wifi_bridge.py::_process_frame()`。二者现对**所有** type 0x02 调
  `decode_status(payload)`（只校验 `len>=7`），会把 106B 健康帧前 7 字节误解码后广播
  成 `car_status`。因此两者必须按 `(frame_type, payload_len)` **联合分流**：
  `(0x02, len==7) → decode_status`（旧 STATUS，保留）、`(0x02, len==106) →
  decode_health`（health 路径）、其它 `(0x02, len)` → 判坏丢弃，**绝不把健康帧
  广播成 car_status**。修改与回归纳入计划 Task 8，其测试为**新建**
  （`test_wifi_bridge_health_dispatch.py`、`test_live_wifi_health_dispatch.py`）。

### 8.2 新 PC parser / logger / 生产 bridge

- `frame_parser.py`：新增 `FRAME_TYPE_HEALTH = 0x02`、`PAYLOAD_LEN_HEALTH = 106`、
  `decode_health(payload) -> dict`；`feed()` 的 `len` 上限改为 `PAYLOAD_LEN_MAX = 106`；
  上层按 `(frame_type, payload_len)` **联合分流**：
  `(0x02, len==106) → decode_health`、`(0x02, len==7) → decode_status`（保留孑遗
  STATUS 解码，固件不发 7 字节 0x02，不冲突）、其它 `(0x02, len)` → 判坏丢弃。
- **生产 bridge（Round 2 项 1）**：`real_world/wifi_bridge.py` 与
  `web_showcase/live_wifi_bridge.py` 按同一规则在 `_process_binary_frame` /
  `_process_frame` 内分流；106B 健康帧走 health 路径（新 bridge 回调/日志），7B 旧
  STATUS 保持原广播，其余长度判坏丢弃；**绝不把健康帧广播成 `car_status`**。测试为
  **新建**，纳入计划 Task 8 回归。
- `transport_soak.py`：`MixedStreamParser` 识别 0x02 帧 → 校验和验证 → 调
  `decode_health` → 追加到 `raw_health.json`（结构：`{frame_ts_s, mono_ts_s, fields}`，
  fields 含 `snapshot_tick_ms`、`health_*` 六项、`uart_rx_high_water`、
  `uart_tx_high_water`）；
  `transport_report.json` 增补 `health` 快照摘要（含 reset_cause、motion_state、
  heartbeat_age、`snapshot_tick_ms` 序列、`health_*` 各计数最近一次值）。
- **0x02 事务延迟统计（Round 3 项 4）**：`health_last_duration_ms` 只保存最近一笔
  health 事务；PC 端仅当相邻收到的 0x02 满足 `Δ(health_ok + health_failed) == 1` 时，
  把当帧 `health_last_duration_ms` 作为**一个可观测的新样本**计入；delta=0（相邻 0x02
  之间无新 terminal）不重复计样；delta>1（中间丢了多个 0x02）记录
  `duration_samples_incomplete=true`，只保留 latest，不声称完整事务延迟分布。报告口径
  固定为“可观测的去重 last-duration 样本及完整性标志”。
- 跨语言 golden vectors：C 编码器的 111 字节黄金帧与 Python 解码器共享同一硬编码
  期望值；C 侧断言 `encode(snapshot)==expected`，Python 侧断言
  `decode_health(expected[4:110])==期望字段`，双向锁死字节布局（§11.5）。

### 8.3 `0x01` 遥测

不变。29 字节、字段顺序、XOR 校验、`decode_telemetry` 全部保持。

### 8.4 旧 S 帧

不变。`S,campaign,run,state,reason,tick,cs` 编码逻辑不动；心跳租约超时仍走
`twin_control_timeout()` 产 `STOPPED/TIMEOUT`。

---

## 9. 断流诊断判读表（health-baseline 复测使用）

**执行条件**：架空轮、净空、用户在场可断电；与 20s 短测相同命令；不新增网络/
命令；不改遥测节拍。**必须**先获用户当次明确授权（本批次不执行）。

**时间窗口语义**：`0x02` 与 `0x01` 走同一 CIPSEND 发送链路，断流窗口内 `0x02`
**同样可能不可达**，不存在逐秒连续观测。判读以 `snapshot_tick_ms`（MCU mono tick，
模 2^32）为对齐基准：用**断流恢复后**首帧与**断流前**最后一帧的 `snapshot_tick_ms`
模差 + 计数增量，把缺失时段定位到 [前帧, 恢复帧) 区间，并按“同一
`snapshot_tick_ms` 时间窗口内多计数器增量的联合证据”判读。缺帧时段只能以恢复前后
差值推算，**不宣称逐秒连续观测**。

**判读总则（Codex Round1 项 3）**：单个计数异常只能支持**主要机制**，不能宣称其他
问题全排除；必须使用同一 `snapshot_tick_ms` 窗口内**多个计数器增量**的联合证据；
**共因/并发故障仍可能存在**（例如 CIPSEND 激增同时主循环阻塞），下表结论一律表述为
“支持 X 为主要机制”，并在记录中列出未排除的共因。成功标准不要求“其余假设被排除”。

| 断流窗口内观测（同一 `snapshot_tick_ms` 窗口内计数增量） | 结论 |
|---|---|
| 窗口内 `loop_max_gap_ms > 300` 且 `loop_seq` 增量连续，同时 `cipsend_*`/`telemetry_tx_*` 增量无明显异常 | 支持 **A1 主循环阻塞为主要机制**；不排除该窗口内同时存在 CIPSEND 迟到等共因 |
| 窗口内 `cipsend_error+prompt_timeout+sendok_timeout` 增量激增、`telemetry_tx_ok` 增量停滞、`status_retry` 增量>0 | 支持 **H1 CIPSEND 发送停顿为主要机制**；重复 RUNNING 倾向归因为 STATUS 重试（可与连接代次变化共因）；再看下游增量：`uart_rx_overflow/ore`=0 且 `cipsend_*` 失败多 → 指向 ESP 内部/Wi-Fi 迟滞；>0 → UART 分支 |
| 窗口内 `telemetry_tx_ok` 增量保持 ~100ms 节拍、`telemetry_generated≈telemetry_tx_started`、`status_retry` 增量=0、`connection_generation` 未变，但 PC 静默 | 支持 H1 的“ESP 收到但 TCP 未送达/Wi-Fi 卡顿”子分支为主要机制（或需 ESP 侧日志确认，升级观测另行授权） |
| 窗口内 `connection_generation` 变化或 `boundary_aborts` 增量>0 | 支持 **A2 连接代次变化为主要机制**；重复 RUNNING 倾向归因为权威状态重发 |
| 窗口内 `connection_generation` 未变、`status_retry` 增量=0、`telemetry_tx_ok` 增量连续、但 PC 静默且重复 RUNNING | 矛盾组合 → 检查 STATUS 完成应答是否被误解析（解析遗漏分支）；单行不能定论，需联合更多增量 |
| 窗口内 `uart_rx_overflow` 或 `uart_ore_events` 增量>0 | 支持 H1 下游 UART 分支为主要机制 |
| 窗口内 `loop_seq` 停更、`loop_last_gap_ms` 激增 | 支持 A1 主循环/固件失活为主要机制；IWDG 即将复位 |
| 全部计数增量连续正常但 PC 仍静默 | 需 ESP 侧日志（RSSI/Wi-Fi/供电），升级到 ESP 观测；A3 供电在其中 |

**成功标准**：9 段真实断流中 ≥7 段由同一**主要机制**一致解释（基于同一
`snapshot_tick_ms` 窗口内多计数器增量联合证据）；记录**矛盾证据**与**未排除的
共因/并发故障**；不要求“其余假设被排除”。另以同条件复跑一次验证可重复性（若
复测零断流，登记为低频/条件触发事件，不做代码修复）。**本设计不预判结果**。

---

## 10. 资源预算

当前 Keil 基线（`keil_rebuild_4b4b.log`）：`Code=19760 RO-data=460 RW-data=116
ZI-data=2540`。本批次预估增量（实施后以 Rebuild 实测为准并记录到 runbook）：

| 项 | 预估 |
|---|---|
| Flash (Code) | +~900 B（health_stats ~320（含 `health_*` 六项计数与 duration）、health_frame ~200（106B 布局）、health_watchdog ~80、protocol 心跳 ~200、main 接线 ~100、coordinator 钩子 ~40） |
| Flash (RO-data) | +~10 B（字符串/常量） |
| RAM (RW) | +~14 B（RX/TX 两环 `high_water` u16 各 2B） |
| RAM (ZI) | +~259 B（HealthSnapshot 106 + 0x02 缓冲 111 + 计数状态 ~42（含 `health_*` 6×u16=12B）） |
| 外设 | IWDG 用 LSI（30–60kHz），与现有 TIM3(mono_time)/TIM2/TIM4(电机) 无冲突；`stm32f10x_iwdg.c` 已在 Keil 引用集内（rebuild 日志已见编译），不新增外设库文件 |
| CPU | 每轮 health_loop_tick：计数器+心跳检查 ≈ 数十周期；每秒 0x02 编码 + 发送一次，可忽略 |

约束核对：`0x02` 总长 111 ≤ CIPSEND 数据上限 112（**余量仅 1B**，见下方边界评估）；
CIPSEND 命令 `AT+CIPSEND=<id>,111` 18 字符 ≤ 24；heartbeat `H` 行 ≤ 96（+IPD 载荷
上限 96）。全部满足。

**带宽/优先级影响评估**（决策 #2 要求）：

- 当前链路观测 ~10.9Hz（60s/300s），每帧 29B 数据 + ~18B CIPSEND 命令 + ESP 应答。
  基础 MCU→ESP 数据速率 ≈ 10.9 × (29+18) ≈ 512 B/s。
- 新增 0x02 每 1s 一帧（111B + ~18B 命令）≈ 129 B/s，占基础速率 ~25%；按事务数计，
  每秒 +1 事务，相对 10.9 事务/s 为 **~9% 事务开销增加**。
- UART 利用率：38400 baud ≈ 3840 B/s 上限；基础 + 新增 ≈ 641 B/s ≈ **16.7% 利用率**，
  未饱和。
- **优先级**：0x02 走 `ESP_SendDiagFrame`（DROPPABLE、`CIPSEND_TX_TAG_DIAG_HEALTH`），
  先检查 `cipsend_tx_busy` 与 `txfq_has_retry`，忙/有 A/S 待发即放弃本帧——**绝不
  抢占 A/S**，也不占用 telemetry latest-wins 槽。1Hz 丢弃窗口 ≤1s，可接受。

**CIPSEND 边界与诊断扰动重估（Round 2 项 2）**：0x02 帧从 99B 增至 **111B，占
`CIPSEND_TX_MAX_DATA`(112) 的 99.1%，仅剩 1B 余量**——这是本设计有意保留 health
专属计数换取可归因指标的结果。影响评估：(a) 每笔 0x02 事务数据字节 +12B，MCU→ESP
总速率 629→641 B/s（+1.9%），UART 利用率 16.4%→16.7%，仍远未饱和；(b) CIPSEND
命令 17→18 字符，仍 ≤24；(c) 事务数不变（~+1 txn/s ≈ +9%），每笔时长因字节略增仅
增数 ms，在 CIPSEND 200/500ms 超时窗内可忽略；(d) **111B 后不再有净余量**，任何
后续字段新增都必须重新走布局评审并重估 112B 边界，不得静默扩帧；(e) 诊断扰动口径
不变：0x02 每秒新增一次较大 CIPSEND 事务本身即可能参与拥塞，仍为待实测假设。

**结论（Codex Round1 项 5 + Round 2 项 2）**：以上为**可接受的待实测设计假设**，不是
“不会放大断流”的已证实证明。静态 UART 利用率（~16.7%）不足以证明新增事务不会在
异常窗口放大断流；0x02 每秒新增一次较大 CIPSEND 事务（~+1 txn/s ≈ +9% 事务数）
本身即可能参与拥塞。因此 health-baseline 复测必须**分别记录**：`0x01` 帧率、
`0x02` 投递率（多跳归因：Δ`health_generated`/Δ`health_started`/Δ`health_ok` 与 PC
实收帧数之比）、`0x02` 事务延迟（`health_last_duration_ms` 的可观测去重 last-duration
样本及完整性标志——仅当 `Δ(health_ok+health_failed)==1` 计一个新样本，delta=0 不重复
计样、delta>1 置 `duration_samples_incomplete=true` 只保留 latest，**不构成完整分布**；
**仅 0x02 tag，不是全局 `cipsend_last_duration_ms`**）、断流分布；并以
`telemetry_tx_ok` 节拍与
0x02 自身 `health_*`/`cipsend_*` 计数回验。**health-baseline 与历史 60s/300s soak
不可直接横向比较**（新链路含 0x02 事务，基线口径不同），须单独登记新基线。

---

## 11. 测试策略

### 11.1 Host C 单测（MSVC，`/W4 /WX`，ASCII shim 路径）

- `test_health_stats.c`：loop_seq/gap/max 语义；tx_started/terminal 结果分类；
  duration 记录；retry 递增；u16/u32 回绕注入（now 跨 2^32）；快照字段映射；
  `health_*` 六项专属计数与 `TAG_DIAG`/`TAG_DIAG_HEALTH` 不混计（Round 2 项 2）；
  Round 3 项 3 的五个转换（busy-drop / start-fail / start-success-in-flight /
  terminal-ok / terminal-fail）与模 2^16 恒等式
  （`generated==dropped+started`、`started==ok+failed+in_flight`，in_flight∈{0,1}）。
- `test_health_frame.c`：黄金向量（构造快照 → 断言 111 字节精确相等，含校验和）。
- `test_twin_control_protocol.c`（扩展）：`H` 帧校验失败/成功；campaign/run 不匹配
  忽略；RUNNING 边沿开启租约；到期触发 timeout + 计数；STOPPED 态 H 只计数不续约；
  age 哨兵；S 帧 reason 仍 `TIMEOUT`。
- `test_uart_ring.c`（扩展）：RX/TX 两环 high_water 单调、峰值、满环 128。
- `test_coordinator_boundary.c`（更新）：`etc_handle_terminal(..., now_ms)` 新签名；
  各终态结果触发 `hstats_tx_terminal` 计数正确。

### 11.2 Host C 构建/运行命令（沿用 v1_task4b4_fix 的 build_host_c_tests.sh 模式）

```
bash .embeddedskills/build/v1_task4b4_fix/build_host_c_tests.sh \
  test_health_stats.exe \
  simulation/digital_twin/tests/test_health_stats.c \
  <shim>/User/health_stats.c \
  <shim>/System/mono_time_core.c
```

逐个 exe 运行，退出码 0 = PASS，非 0 = FAIL。所有新模块复制到
`hostc/User`（纯 ASCII 路径，规避 MSVC 对中文路径的代码页问题）。

### 11.3 Python 单测

- `frame_parser.py` + `test_frame_parser_health.py`：0x02 识别/校验/解码（len=106）；
  `(frame_type, len)` 联合分流；len>106 判坏；`0x01` 遥测回归；与 C 黄金帧交叉断言。
- `test_old_parser_health_compat.py`（**待建**，计划 Task 8 Step 8.0 固化旧 parser
  兼容边界）：向未修改的旧 `FrameParser` 喂新黄金帧（len=106>64）→ 不崩溃、无持续
  失步、`frames_bad`/`resync_count` +1——**指标兼容性变化**，不宣称完全兼容。该测试
  当前**尚未创建**，文档不把它写成已存在证据。
- **生产 bridge 分发（Round 2 项 1，均**新建**）**：
  `test_wifi_bridge_health_dispatch.py` 与 `test_live_wifi_health_dispatch.py`：
  `(0x02, len==7)` → `decode_status` 旧 STATUS 保留；`(0x02, len==106)` →
  `decode_health` 进入 health 路径，**绝不广播 `car_status`**；`(0x02, 其它 len)` →
  判坏丢弃。
- `transport_soak.py` + `test_transport_soak_rework.py`（扩展）：心跳命令编码；
  finally-STOP 路径；唯一 run_id 合规（≤16、[A-Za-z0-9-]）；窗口排除 START 前/
  final STOP 握手期帧；门禁拆分后的 verdict 判定；0x02 `health_*` 解析与摘要
  （Round 2 项 2）。

### 11.4 故障注入（Host C / 脚本化回放）

- CIPSEND 脚本化回放（`_ScriptedTransport` 模式）：喂 `>`、SEND OK、ERROR、busy、
  CLOSED、超时字节流 → 断言 `cipsend_*` 与 `*_retry` 计数。
- 租约：合成 now_ms 序列（0→200→999→1000）→ 断言 1000ms 处超时。
- UART：灌满环 → overflow/high_water 断言。

### 11.5 跨语言 golden vectors

- 固定快照 → C `health_frame_encode` 输出 111 字节 → 与 Python 侧硬编码期望相等；
- 该期望帧喂给 Python `decode_health` → 字段与固定快照相等（含 `health_*` 六项）；
- 一份 golden 文件（`.embeddedskills/build/firmware_health_baseline_design/golden_health_0x02.hex`
  的十六进制记录 + `.json` 解析值）同时被 C 与 Python 测试引用。

### 11.6 Keil Rebuild

```
"F:\keil\UV4\UV4.exe" -r "C:\Users\24668\Desktop\stm32小车\程序\3. 麦轮巡线小车\project.uvprojx" -j0
```

期望：0 Error、0 Warning；Program Size 增量记录；AXF/HEX 产物**备份本体 + 哈希**
保存（§12.1 `build_artifact_backup`；任何 Rebuild 前先执行构建产物备份，设备级
来源见 §12.2）。

---

## 12. 烧录前后 Runbook 与回滚

> 本批次只做到 ST-Link 只读准备；**任何烧录/复位/串口/TCP/START 均需再次明确
> 授权**。以下为获批后的执行步骤，作为计划 §执行顺序 的对照。

### 12.1 烧录前（离线）——`build_artifact_backup`（构建产物备份）

> **范围声明（Round 2 项 3）**：本节只备份构建产物 AXF/HEX，**只证明构建目录在
> Rebuild 前的旧产物**，**不能证明它与 MCU 当前 Flash 一致**（产物可能在上次烧录
> 后被 Rebuild 覆盖）。MCU 实际在跑固件的设备级来源证明见 §12.2 前置 gate
> `device_firmware_backup/provenance`，二者不可混同。

1. **构建产物备份（任何 Rebuild 之前，Codex Round1 项 1）**：在证据目录建立
   不可覆盖备份子目录
   `.embeddedskills/build/firmware_health_baseline_design/rollback_artifacts/preflash/`，
   将当前旧 `Objects\Project.axf` 与 `Project.hex`（若存在）**复制**到该目录
   （备份的是副本本体，不是哈希）。
2. 生成哈希 manifest `preflash_hashes.json`：对**备份副本**计算
   `Get-FileHash -Algorithm SHA256`，记录 sha256、源路径、大小、副本路径。
   幂等/冲突规则（实施细节见计划 Task 0）：
   - 同名副本与当前源文件 sha256 **相同** → 复用既有备份，不重复复制（幂等）；
   - 同名 sha256 **不同** → **STOP**，人工介入，绝不覆盖已有备份；
   - **绝不删除**旧备份。
3. 新固件 Rebuild 成功（§11.6）后，将新产物复制到独立
   `rollback_artifacts/postbuild/` 子目录（**不依赖 Keil 输出目录长期保存**），
   生成 `postbuild_hashes.json`，记录 `fw_build_id`。
4. 全量离线验收通过（§11 全部 + 跨语言 golden + 判定表文档化）后才可请求授权。

### 12.2 烧录（授权后，ST-Link）——先过 `device_firmware_backup/provenance` gate

> 本 gate 在**获得用户明确授权**后执行，且为**只读**操作，不得在本批次离线阶段执行。

4. **设备固件来源证明（Round 2 项 3，二选一，首选 4a）**：
   - **4a. 只读导出应用 Flash（首选）**：用 ST-Link 只读读回 STM32F103C8 应用 Flash，
     保存为独立文件 `rollback_artifacts/device_flash/device_flash_<build>.bin`，并记录
     **地址范围 + 长度 + SHA-256** 到 `device_flash_hashes.json`。此 `.bin` 即**设备级
     回滚件**（回滚依据是设备实读内容，不是构建目录 AXF）。
     - **地址范围必须从芯片/Keil 工程核实，禁止猜测**：以 Keil 工程 Target 选项
       `IROM1` 的起始地址与大小、以及芯片手册 STM32F103C8 主 Flash 容量（64KB @
       0x08000000）双向核对后记录来源；执行前不得使用未核实的假设值。
   - **4b. 上次烧录哈希链证明**：若存在可核实的上次烧录日志，其中记录了**实际烧录
     产物**的确切 SHA-256，且该哈希与 §12.1 `build_artifact_backup` 当前备份一致，
     则以该哈希链证明设备来源（`device_firmware_backup` 状态 = `PROVEN_BY_HASH`），
     可省去读回。
   - 若工具链当前**无法只读导出**且无哈希链 → 设备固件来源状态 =
     **`BLOCKED_DEVICE_ROLLBACK_PROVENANCE`**，**不得进入烧录**，待工具链或证据
     补齐后再继续。
5. 由用户/ST-Link 工具按 `postbuild_hashes.json` 产物烧录（ST-Link Utility 或
   `STM32_Programmer_CLI` 命令记录在 runbook，**不自动执行**）。
6. 烧录后只读验证：读回 `0x02` 的 `fw_build_id` 与预置值一致；`reset_cause` 初值
   为 POR/上电；不做任何 START/电机动作。

### 12.3 回滚方案

7. 若任一验证失败或运行异常，回滚件只按 §12.2 门控后允许烧录的**已证明来源**选择
   （Round 3 项 2，门控状态决定回滚依据）：
   - **`DEVICE_ROLLBACK_READY` → 设备级回滚件**：`rollback_artifacts/device_flash/`
     的**设备实读 .bin**（按 `device_flash_hashes.json` 校验 sha256）重新烧录，恢复
     MCU 实际在跑固件；
   - **`PROVEN_BY_HASH` → 已证明回滚件**：与上次实际烧录哈希链一致的
     `rollback_artifacts/preflash/` 旧 AXF/HEX 备份（`preflash_hashes.json` 校验），
     回滚后必须重跑只读验证确认行为符合预期；
   - **其它状态（`BLOCKED_DEVICE_ROLLBACK_PROVENANCE`）→ 禁止烧录**，不存在烧录后的
     回滚 fallback；构建目录备份只用于构建比对，不得称设备回滚件。
   旧 S 帧 reason 兼容，PC 旧工具仍可判读。**回滚依据不是被 Rebuild 覆盖的 Keil
   输出目录。**
8. 回滚后重跑离线验收确认旧哈希与备份一致。**不自动擦除/烧录**，全部人工授权。

### 12.4 授权后验证序列（对应计划第 9–10 步）

9. 烧录 → 只读验证 STOPPED（INIT）态 `0x02` 帧：motion_state=0、lease_active=0、
   计数为 0、reset_cause 正确。
10. 再次授权后 ≤20s 架空轮运行：`transport_soak.py --run` 发送 200ms 心跳 + 安全
    握手 + final STOP；验收窗口严格排除握手期帧；判读表（§9）定位机制；复跑一次
    验证可重复性。

---

## 13. 主机端同步（同一计划，不得混为固件根因修复）

1. **finally STOP 兜底**：`run_handshake`/`capture_session` 在 START 后的异常与
   KeyboardInterrupt 路径，`finally` 中 best-effort 发送 STOP 并等待关联 STOPPED
   （复用 `_final_stop`）；等待失败 → 醒目打印 `CUT POWER`，退出码保持非 0。
   当前 Codex 已确认的缺口（`transport_soak_rework_handoff.md` §9.1）由本批次修复。
2. **唯一 run_id**：`--cmd-run-id` 默认值改为每次运行自动生成的
   `soak{epoch_s:08x}`（12 字符，[a-z0-9]，≤16 合规，唯一到秒）；保留 `--cmd-run-id`
   显式覆盖用于离线脚本化回放；`make_run_id()`（输出目录名）与命令 run_id 分离。
   MCU 侧心跳校验 campaign/run 匹配即防旧状态误关联。
3. **门禁拆分**：`transport_cadence` 拆为 `TRANSPORT_CONTINUITY`（无彻底断流：
   任一墙钟间隔 ≤ 阈值）与 `DELIVERY_CADENCE`（分布质量：p50/p95/p99/max + 缺口
   密度）。**阈值来源**：本批次以 health-baseline 复测的观测分布**登记基线**，
   明确标 `BASELINE_REGISTERED`（非 PASS/FAIL），**不是**正式 4B-4 同步 Gate；
   阈值必须在基线收集 ≥3 次运行且来源可溯后才可固化为 Gate 参数。不得凭空设阈。
4. **窗口排除**：采集窗口 = `[RUNNING 确认, RUNNING 确认 + duration)`；窗口外帧
   （START 前 INIT/STOPPED、final STOP 握手期到达的帧）一律排除；统计口径沿用
   dropout review §2.1 的“窗口内/窗口外”拆分，不再用首末跨度混口径。
5. **0x02 解析/持久化/黄金向量/生产 bridge 分流**：见 §8.2/§11.5；两个生产 bridge
   （`real_world/wifi_bridge.py`、`web_showcase/live_wifi_bridge.py`）同步按
   `(frame_type, payload_len)` 分流（Round 2 项 1）。

---

## 14. 风险与未验证项

| 风险/未验证项 | 影响 | 缓解/验证 |
|---|---|---|
| 1s 租约过严：Wi-Fi 延迟偶发 >1s 导致误停 | 正常 200ms 心跳留 5 倍余量；但弱 Wi-Fi 下可能误停 | 用 health-baseline 复测的 `heartbeat_age_ms` 分布评估；若误停率不可接受，调整租约时长须重新走批准流程 |
| IWDG LSI 误差 [~1.33, ~2.67]s | 复位窗口宽 | 如实声明；喂狗间隔 5ms 远小于窗口，无实际影响；`reset_cause.IWDGRST` 验证 |
| `etc_handle_terminal` 签名变更波及现有 host 测试 | 回归 | 计划含更新 `test_coordinator_boundary.c` 与全部相关用例 |
| 旧 PC `frames_bad` 上升（0x02 len=106 被旧 parser 拒绝） | **指标兼容性变化** | 文档化 + 测试 gate（§8.1、计划 Task 8 Step 8.0 待建）；不宣称完全兼容；正式 soak 使用升级后工具 |
| `heartbeat_timeout_count` 与 `cipsend_*` u16 回绕 | 长 soak 计数回绕 | 模差计算（§5.2 总则）；每 1s 增量远小于 2^16 |
| 0x02 帧在 CIPSEND 忙时丢弃 | 1Hz 观测可能缺帧 | 可接受（设计）；`health_dropped` 记录丢弃数，`health_generated−health_started` 印证；断流窗口内 0x02 同链路也可能不可达，缺帧时段用 S 帧 + 恢复前后快照的 `snapshot_tick_ms` 模差定位区间，不宣称逐秒连续观测 |
| 0x02 每秒新增 CIPSEND 事务可能放大断流 | 未实测 | 判定为**可接受的待实测设计假设**（§10）；复测分别记录 0x01 帧率/0x02 投递率（health_* 多跳归因）/0x02 事务延迟（`health_last_duration_ms` 可观测去重样本及完整性标志，Round 3 项 4）/断流分布，与历史 soak 不横向比较 |
| 0x02 帧 111B 仅余 1B 到 CIPSEND 上限 | 后续扩帧即超限 | 文档化边界（§10 CIPSEND 边界重估）；任何字段新增须重新走布局评审与 112B 重估，禁止静默扩帧（Round 2 项 2） |
| 无上次烧录哈希链 / 工具链无法只读导出 Flash | 无法证明 MCU 实际固件来源 | §12.2 gate：先只读读回 `.bin`+地址/长度+SHA-256；仍不可行 → 状态 `BLOCKED_DEVICE_ROLLBACK_PROVENANCE`，不烧录（Round 2 项 3） |
| 心跳帧在 +IPD 分片/噪声下被吞 | 租约延后 | 有效帧校验 + 200ms 周期留 5 倍余量；`heartbeat_count` 观测缺口 |
| 主循环内 blocking 段（软件 I²C 1000 次迭代） | 极短，< 看门狗窗口 | loop_last_gap 观测 |
| ESP 侧供电/噪声未观测 | A3 未闭合 | 判读表落到该分支时另行授权 ESP 观测 |
| 本批次只登记基线，非 4B-4 同步 Gate | 不宣称完成 | 交付物与判读文档均明确标注 |

---

## 15. 交付物

1. 本设计：`docs/superpowers/specs/2026-08-03-firmware-health-safety-baseline-design.md`
2. 实施计划：`docs/superpowers/plans/2026-08-03-firmware-health-safety-baseline.md`
3. 证据/交接：`.embeddedskills/build/firmware_health_baseline_design/handoff.md`

自审要点：设计/计划字段类型一致；`0x02` 字节布局两侧一致（payload 106 / 总长 111 /
len 0x6A，`snapshot_tick_ms`、`uart_tx_high_water`、`health_*` 六项两侧同步）；所有
生产消费者覆盖（`frame_parser.py` / `wifi_bridge.py` / `live_wifi_bridge.py` /
`transport_soak.py`，Round 2 项 1）；无旧 99/94/0x5E 数值（历史变更说明除外）；无
过强因果结论（旧说法已标否定）；`0x02` 指标可归因（health 专属计数，Round 2 项 2）；
回滚区分构建产物与设备固件来源（Round 2 项 3）；路径存在性；无越权操作（本批次
不烧录/不复位/不串口/TCP/START/电机/读回 Flash）；不使用 TODO/TBD/占位语；不宣告
整个项目或 4B-4 完成。
