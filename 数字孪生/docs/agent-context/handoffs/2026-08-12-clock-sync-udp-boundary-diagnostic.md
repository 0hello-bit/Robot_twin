# Handoff: ClockSync UDP boundary attribution before diagnostic instrumentation

Date: 2026-08-12
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `INSUFFICIENT EVIDENCE`

## Goal

在不修改固件、不烧录、不重复正式 TCP/UDP A/B 的前提下，定位 UDP
`+IPD -> Q parse -> ClockSync queue` 链路的第一个不可见边界。当前任务在
工作区整理完成后恢复；先保留已有证据，再决定是否增加最低扰动的直接边界
诊断。

## Current State

### VERIFIED

- 黑盒分流方法有效：`TCP Q300 -> TCP Q301` 间隔约 `2.3927 ms`；`T300`
  返回，`Q301` 在采集窗口内无回包。这证明当前 single-pending 机制可以被
  黑盒观察。
- `UDP Q400 -> TCP Q401` 间隔约 `0.5682 ms`；UDP `Q400` 无回包，TCP
  `Q401` 正常返回，`total RTT = 129.53 ms`，`transport RTT = 27.53 ms`。
  在本次条件下，TCP `Q401` 没有被 UDP `Q400` 阻塞。
- 现有固件静态链路为：`+IPD` 由 `ipd_parser_feed()` 解析后进入
  `esp_transport_process_byte()`；UDP link 4 的 payload 首字节为 `Q` 时
  进入控制解析；Q 收到换行并通过校验后生成 `TwinControlClockSync`，随后
  调用 `esp_transport_queue_clock_sync()`。
- 已有 pending 时，`esp_transport_queue_clock_sync()` 直接返回 `0`；代码中
  没有独立的 `s_pending_clock_sync` timeout。
- pending 的已确认清理路径包括 ClockSync CIPSEND 终态 `SEND OK`、连接清理、
  transport 初始化/复位；`CIPSEND ERROR/timeout` 会保留 pending 以便重试。

### INFERENCE

- `UDP Q400` 很可能没有形成 STM32 内部 ClockSync pending，因此 TCP
  `Q401` 能在理论 pending 竞争关系中正常返回。
- 当前最值得优先检查的是 UDP `+IPD` 头/载荷解析、Q 路由和 UDP 发送路径，
  但现有证据还不能把问题归因到其中任何一个具体点。
- `ESP_Setup()` 设置了 `CIPMUX=1`、`CIPMODE=0` 并建立 UDP link 4，但没有
  明确设置 `CIPDINFO=0`。若设备实际处于 `CIPDINFO=1`，UDP `+IPD` header
  可能带点号 IP 地址，而当前 header parser 只接受数字、逗号和冒号；这是
  静态风险，不是已被真机证实的根因。

### INSUFFICIENT EVIDENCE

目前没有真机证据直接观察以下边界：

```text
UDP +IPD header/payload arrival
    -> +IPD complete / parser result
    -> Q candidate / Q parse result
    -> ClockSync queue accepted or rejected
```

因此还不能区分：UDP 包未到 STM32、`+IPD` header 不兼容、载荷解析未完成、
Q 校验/路由失败，或 ClockSync queue 后的 UDP 回程/CIPSEND 失败。

ClockSync causal gate 仍不能 PASS；不得用删除高 RTT、超时或失败样本的方式
改变结论。

## What Was Changed

- 本 handoff 文件是本轮唯一新增的交接文档。
- 本轮没有新增或修改固件、PC 协议、Q/T payload、`tick_ms` 语义、TCP
  telemetry/health/control 业务，也没有烧录或重新发送测试包。
- 工作区在本轮开始前已经存在大量未提交源代码、测试、计划和 evidence
  目录；这些改动的归属没有在本 handoff 中重新裁决。

## Evidence

- 黑盒实验报告：
  `docs/evidence/v1_b3_clock_sync_pending_black_box_20260812/c260812171714080409/black_box_probe_report.json`
- 该报告保留 raw TX/RX、PC `perf_counter_ns`、发送间隔、序列号、回包匹配、
  timeout/late/duplicate 统计，以及 `mcu_rx_tick`/`mcu_tx_tick`。
- 关键静态代码位置：
  - `firmware/stm32_line_follower/User/ipd_parser.c:88`
  - `firmware/stm32_line_follower/User/esp_runtime_transport.c:173`
  - `firmware/stm32_line_follower/User/esp_runtime_transport.c:337`
  - `firmware/stm32_line_follower/User/twin_control_protocol.c:379`
  - `firmware/stm32_line_follower/User/main.c:98`
- 实验范围是真机网络黑盒 Q/T 探测；没有把它扩大为 telemetry、health、
  control 或物理运动结论。

## Tests

- 本 handoff 保存阶段未执行构建、单元测试、烧录或真机采集。
- 黑盒实验结果以以上 JSON 为准；报告明确记录 `firmware_modified=false`，
  两组均为 no-retry Q-only 探测。
- 下一轮修改前必须重新读取当前工作区状态，并以实际测试输出确认，不得把
  本 handoff 中的历史结果当作新一轮验证。

## Known Risks

- 当前 `mcu_rx_tick` / `mcu_tx_tick` 的语义是协议处理边界，不是 UART 物理
  首字节接收和物理发射时间；不要用它们过度解释 UDP 丢包位置。
- `SEND OK` 是 ESP/AT 发送事务结果，不是 PC 已收到 T 的证明。
- 当前没有 UDP `+IPD`、Q parse、queue accept/reject 的计数或 last-event 证据，
  所以组件级归因仍然是不充分证据。
- 工作区有大量 dirty changes 和新增 evidence；清理代理可能误删尚未提交的
  实验产物。所有删除必须有明确的可再生证据，不能用 reset/checkout 覆盖。

## Do Not Change

- 不要执行 `git reset --hard`、`git checkout --` 或任何会覆盖用户/其他代理
  改动的操作。
- 保留全部现有 dirty source、tests、plans、docs、evidence；不因文件未提交
  就删除或回滚。
- 不修改 latest-5/latest-8 实验结论：latest-8 仍是当前 baseline，latest-5
  只是 freshness candidate，不得晋级。
- 不修改 Q/T payload、`tick_ms` 语义、TCP telemetry/health/control 业务，
  不迁移 telemetry、health、control 到 UDP，不实现实时流/记录流双流架构。
- 不重复正式 UDP A/B，不在没有新增边界证据时通过重试或样本筛选制造 PASS。
- 未得到针对下一步真机采集的明确授权前，不烧录、不复位、不发送控制或诊断
  测试包。

## Next Exact Step

工作区整理完成后，先只读恢复本 handoff，再检查现有测试和固件接口能否直接
观察 UDP `+IPD` 完成、Q parse 和 ClockSync queue 三个边界。若不能，设计
最低扰动的诊断状态，仅增加计数和最近事件字段，例如：

```text
udp_ipd_prefix_count
udp_ipd_complete_count
udp_ipd_error_count
udp_q_candidate_count
udp_q_parse_ok_count
udp_q_parse_reject_count
clock_queue_accepted_count
clock_queue_rejected_pending_count
last_event_code
last_event_tick_ms
last_link_id
last_sequence
```

先为正常 UDP `+IPD`、异常 header、`CIPDINFO=1` 风格 header、合法/非法 Q、
已有 pending 时的 queue 拒绝和 TCP 回归补齐 host C TDD；离线测试通过后，
再决定是否修改 parser 或显式设置 `CIPDINFO=0`。若需要真机观测，必须另行
获得授权，并只做一次最小诊断采集，产出原始 evidence 后再分类为
`VERIFIED`、`INFERENCE` 或 `INSUFFICIENT EVIDENCE`。
