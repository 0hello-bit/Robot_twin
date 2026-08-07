# ACTIVE TASK: V1-B B2

> **DO NOT EXECUTE B1.** B1 已完成并由 Codex 验收为 `ACCEPTED_OFFLINE_ONLY`。本文件是当前唯一可复制、可发送给新 agent 的 V1-B 任务提示词。

```text
ACTIVE TASK: V1-B B2
DO NOT EXECUTE B1. DO NOT REPEAT B1 OFFLINE PREPARATION.

你现在执行 Robot Twin AI 项目的 V1-B Task B2：安全硬件 Smoke。

正式工作区固定为：
C:\Users\24668\Desktop\stm32小车\数字孪生

硬件授权门槛：本提示词本身不构成硬件授权。只有启动本任务的同一轮用户消息明确写明具体设备、动作和时长，才允许连接 C960、连接 ESP-01S TCP，并进行一次受控的抬轮短时 START/STOP。没有这样的当次授权时，只能完成离线 preflight，随后停止并报告 INSUFFICIENT EVIDENCE；不得连接、烧录、复位、发送 START/STOP 或驱动车轮。

即使获得当次授权，授权也不包括烧录、复位、修改 STM32 固件、修改控制算法、地面运行、连续实验、B3 同步采集、B4 数据冻结或 B5 模型拟合。你只能完成 B2，handoff 后立即停止。

你的唯一目标：证明已有 ESP-01S/STM32 通信、运行时参数 ACK、相机实际模式、短时启动与最终 STOP、以及资源清理能够形成可追溯的真实硬件证据。B2 不是性能测试，不证明高速，不证明数字孪生已校准，也不产生可用于模型拟合的 calibration/holdout 数据。

开始前必须阅读：
1. docs\Robot_Twin_AI_完整计划说明书_v2.7.md
2. docs\agent-context\CURRENT_STATUS.md
3. docs\agent-context\handoffs\2026-08-05-v1-b-offline-preflight.md
4. docs\superpowers\plans\2026-08-05-v1-b-real-calibration-holdout.md
5. docs\agent-context\PROJECT_MEMORY.md
6. tools\shakedown_toolchain\ground_shakedown.py
7. tools\shakedown_toolchain\transport_soak.py
8. simulation\digital_twin\real_world\runtime_protocol.py
9. simulation\digital_twin\real_world\frame_parser.py
10. firmware\stm32_line_follower\User\esp_runtime_transport.c/.h
11. firmware\stm32_line_follower\User\esp_tx_coordinator.c/.h
12. firmware\stm32_line_follower\User\twin_control_protocol.c/.h

必须复用，禁止重复造轮子：
- 直接使用 ground_shakedown.py 的现有 CLI/run_ground_session；不要新建 B2 TCP 客户端、控制循环或证据记录器。
- 由 ground_shakedown.py 继续复用 transport_soak.py 的 SocketTransport、RawIoLogger、MixedStreamParser、HeartbeatCommand 和健康处理；不要手写 H 心跳或 checksum。
- 由 ground_shakedown.py 继续复用 real_world.runtime_protocol 的 ParameterCommand/RunCommand/parse_ack/parse_status 和现有 checksum/frame；禁止手写第二套 P/R/A/S。
- 由 ground_shakedown.py 继续复用现有 parser、逐版本 ACK、speed_max ramp、START/STOP、raw evidence 和 cleanup；禁止新增 ACK registry、reader thread、heartbeat thread 或 session lifecycle。
- capture_sync_run.py 只属于后续 B3 同步采集，本次 B2 不得复制或改造成控制入口；LiveWifiBridge 只读核对，不启动 UI、不复制其连接层。
- 不把 v1_b_preflight.py 改成硬件脚本；它仍必须保持离线。

执行顺序：
1. 先检查 git status，确认没有覆盖用户未提交修改；运行相关离线测试和 compileall。若路径、依赖或协议版本无法确认，停止并报告 INSUFFICIENT EVIDENCE。
2. 核对当前 canonical firmware 源码/构建身份和 SHA-256。不得把历史 handoff 的哈希自动当成当前真机固件哈希；无法证明真机正在运行该固件时，保留为 INSUFFICIENT EVIDENCE，不得烧录补救。
3. 人工准备：C960 固定并确认实际画面；小车四个驱动轮抬起、不得接触地面；用户站在电源/实体急停旁；除本次短时 Smoke 外不允许车辆地面运动。
4. 只连接 C960，读取并记录实际 FourCC、分辨率和 FPS，必须是 MJPG / 1280x720 / 30 fps；不能把 cap.set 请求值当成实际证据。
5. 通过现有 ESP-01S TCP 路径连接当前确认的 host/port。不得猜测 IP；若当前地址或端口无法从配置/用户确认，停止并报告 INSUFFICIENT EVIDENCE。
6. 只通过现有 `ground_shakedown.py` CLI 或 `run_ground_session()` 执行安全序列；不得在外部脚本手动拼接或重复发送控制帧。它会使用已审核的速度安全 ramp：speed_max 680 -> 580 -> 480 -> 380 -> 280 -> 260；每步只发送一次，每个版本必须收到同 campaign_id/version 的 APPLIED/APPLIED ACK。Kp/Ki/Kd 使用当前固件已核对的 baseline，不得自行发明新参数。任一步 ACK 超时、关联不匹配或 REJECTED，立即停止，不重试掩盖问题。
7. 核对并记录 `ground_shakedown.py` 已有的 H 心跳：它通过 `transport_soak.HeartbeatCommand` 在 RUNNING 后按 200 ms 调度，并把 H 放入 raw I/O 证据。当前固件声明 1 秒租约，不能删除或另写 H；如果既有路径的 H 证据缺失，停止并报告 INSUFFICIENT EVIDENCE，不得把短时运行包装成长期安全。
8. 由既有安全入口只发送一次 R START，抬轮运行不超过 0.5 秒，然后发送 R STOP；不得自动重试 START。必须从原始接收流中解析并记录与本 run_id/campaign_id 匹配的 STOPPED/STOP。STOP 未确认、资源未各清理一次或发生异常时，立即停止并将 B2 标为 INSUFFICIENT EVIDENCE。
9. 保存真实证据：run_id、实际相机模式、firmware identity/hash、P 命令和 ACK、R START/STOP、S STOPPED/STOP、连接/断开时间、socket/camera cleanup 状态和失败原因。SMOKE 数据不得加入 calibration 或 holdout。
10. 运行离线回归测试，检查本次新增/修改范围。若现有模块已经能够完成 B2，不要为了“整理”而重构或复制代码；没有必要的代码修改时可以只提交证据 handoff。

允许的最小代码变更：仅当现有 `ground_shakedown.py`/`transport_soak.py` 接口无法表达 B2 的明确证据时，才在现有模块中做最小增量，并为增量先写失败测试再实现。H 心跳已有实现，不得重复添加。禁止修改 STM32 固件、控制算法、PCB、UI、MCP、第二台机器人或开启 Keil/烧录流程。

handoff 必须包含：
- Task/Gate 和 PASS/FAIL/INSUFFICIENT_EVIDENCE；
- 实际 changed files；
- 每条命令、退出码和关键输出；
- VERIFIED / INFERENCE / INSUFFICIENT EVIDENCE；
- Hardware actions 的精确记录：connected / flashed / reset / START / STOP / motion；
- 真实 run_id、原始证据路径和 SHA-256；
- 未完成项和原因；
- 明确写出 B2 不等于 B3 同步 Gate、不等于高速性能提升；
- 下一接口为 B3，且必须等待 Codex 独立验收和用户对地面采集的新授权。

到达 handoff 后立即停止，不得运行 B3/B4/B5，不得自动进入下一阶段。
```

发送本文件中的 `text` 代码块给 agent；不要发送计划书第 6 节的 B1 历史代码块。
