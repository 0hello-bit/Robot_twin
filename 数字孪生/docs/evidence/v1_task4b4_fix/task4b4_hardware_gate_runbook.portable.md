# Task 4B-4 硬件 Gate 执行手册

> **版本**: 1.0
> **日期**: 2026-08-01
> **前置状态**: `SOFTWARE ACCEPTED / HARDWARE GATE READY`
> **目标**: 通过真机验证将 Task 4B-4 从 HARDWARE GATE READY 升级为 COMPLETE
>
> ⚠️ **本手册为执行者操作指南。每阶段必须逐项通过后才可进入下一阶段。
> 任何阶段失败即停止，先回滚再分析。**

---

## 风险分阶段总览

| 阶段 | 风险 | 需要硬件 | 可能运动 |
|---|---|---|---|
| A. 外观/接线/供电检查 | 极低 | 小车+ESP+ST-Link | ❌ 无 |
| B. Rebuild + 受控烧录 | 低 | 小车+ESP+ST-Link | ❌ 无（烧录后不启动） |
| C. 不运动通信验证 | 低 | 小车+ESP+摄像头 | ❌ 无 |
| D. 摄像头标定尺寸检查 | 低 | 摄像头 | ❌ 无 |
| E. 低风险短时 START/STOP | **中** | 全部 | ✅ 可能转动 |
| F. 同步 Gate | **中** | 全部 | ✅ 持续转动 |
| G. 异常回滚 | — | — | — |

---

## 阶段 A：外观/接线/供电检查（用户在场）

### A.1 前置条件
- 小车在安全台面（非赛道）
- 轮子架空或不接触赛道
- 用户在场

### A.2 允许动作
- 目视检查所有杜邦线、电池线、电机线连接牢固
- 目视检查 ESP01S 正确插入插座、天线无遮挡
- 目视检查 ST-Link 连接：SWDIO / SWCLK / GND / 3.3V
- 目视检查车顶 AprilTag 标签无污损、无脱落
- 目视检查灰度传感器排线完好
- 万用表测量电池电压（锂电池 7.4V~8.4V 正常范围）
- 检查 DroidCam 摄像头 USB 连接与支架稳固

### A.3 禁止动作
- 不得通电（电池/ST-Link/USB 均保持断开）
- 不得旋转车轮
- 不得重新布线（仅检查，不更改）

### A.4 通过条件
- 所有连接件牢固、无松动
- AprilTag 标签清洁无损
- 电池外观无鼓包、漏液
- 传感器排线无断裂

### A.5 失败处理
- 任何不满足 → 记录问题，**停止，不进入 B**

### A.6 产物
- 无（检查为人工观察）

---

## 阶段 B：Rebuild 后受控烧录与复位（需单独授权）

### B.1 前置条件
- 阶段 A 通过
- **用户明确口头或书面授权烧录**
- 赛道净空（小车不在赛道上，轮子架空）
- ST-Link 已连接但目标板尚未通电

### B.2 允许动作
1. Keil Target 1 Rebuild（验证 0 Error/0 Warning）
   ```bash
   "<KEIL_ROOT>/UV4/UV4.exe" -r project.uvprojx -j0 -o keil_rebuild_gate.log
   ```
2. 编译通过后：
   - 给目标板供电（连接电池或 ST-Link 3.3V）
   - 烧录 AXF
3. 烧录成功后复位小车

### B.3 禁止动作
- 不得在烧录期间连接 ESP 电源/USB（避免 ESP 干扰 UART1）
- 不得在未确认赛道净空前烧录
- 不得跳过 Rebuild
- 不得修改代码后不重新 Rebuild 即烧录

### B.4 通过条件
- Keil Rebuild: **0 Error(s), 0 Warning(s)**
- Flash Download: **成功**，校验通过
- 复位后板载 LED 按预期行为（main.c 初始化序列正常）

### B.5 失败处理
- Keil 编译失败 → **停止**，保存日志，回滚到上一已知良好 AXF
- 烧录失败 → 检查 ST-Link 连接，重试 1 次；仍失败 → **停止**

### B.6 产物
- `keil_rebuild_gate.log`

---

## 阶段 C：不运动的 ESP/TCP/遥测/断连重连恢复验证

### C.1 前置条件
- 阶段 B 通过
- 小车供电正常
- ESP01S 供电（插入 ESP 模块或连接 USB 供电）
- ESP WiFi 热点已开启，PC 可连接
- **轮子保持架空，不放在赛道上**
- **不发送 START**

### C.2 允许动作
1. PC 连接 ESP WiFi: `<ESP_HOST>:8888`
2. 验证 TCP 连接建立、传输协议握手正常
3. 监听遥测流（不发送 START）：
   - 验证遥测帧格式（传感器 4 值、error、pid_output、pwm 有符号、
     tick_ms、yaw 原始值）
   - 验证遥测到达频率（期望约 50Hz，idle 状态下可能 10-20Hz）
   - 记录 60s 遥测样本到 `C_telemetry_idle.json`
4. **断连/重连恢复测试（黑盒）**：
   a. PC 断开 TCP 连接，等待 5s
   b. PC 重新连接 TCP
   c. 继续监听遥测 ≥30s，验证：
      - 重连后遥测正常恢复
      - 无旧帧泄漏到新连接（对比重连前后 tick_ms 连续性，
        **注意**: 黑盒观察只能确认"未见明显异常帧"，不能证明无残留字节）
      - 重连后 telemetry 格式一致
   d. 重复步骤 a-c 共 **3 次**
5. 记录全部断连/重连日志到 `C_reconnect_log.txt`

### C.3 禁止动作
- 不得发送 START/STOP
- 不得将轮子放到赛道
- 不得声称观察到/未观察到 USART 移位寄存器残留字节（无逻辑分析仪时，只能做黑盒功能观察）

### C.4 通过条件
- TCP 连接可建立
- 遥测持续到达 ≥60s（idle 状态），未断流超过 5s
- 3 次断连/重连后遥测均正常恢复
- 遥测帧格式符合 `V1TelemetryFrame` schema

### C.5 失败处理
- 遥测断流 >10s → 检查 ESP WiFi 信号、TCP 连接；重试 1 次 → 仍失败 **停止**
- 重连后遥测不恢复 → **停止**，检查 coordinator 边界逻辑、ESP AT parser 状态
- 出现格式异常帧 → **停止**，保存异常帧原始字节

### C.6 产物
- `C_telemetry_idle.json`
- `C_reconnect_log.txt`

---

## 阶段 D：摄像头标定尺寸和视野检查

### D.1 前置条件
- 阶段 C 通过
- DroidCam 摄像头 USB 连接并供电
- 小车位置可被摄像头拍摄到（车顶 AprilTag 在视野内）
- **轮子保持架空**

### D.2 允许动作
1. 打开 DroidCam（或相机 index）
2. 读取并记录实际帧尺寸：
   ```python
   import cv2
   cap = cv2.VideoCapture(1)  # 或 DroidCam index
   actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
   actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
   print(actual_w, actual_h)
   cap.release()
   ```
3. 与标定 `intrinsics_final.json` 中 `image_size` 比对
4. 确认 AprilTag 在视野内可被检测到（运行简单检测脚本，不采集数据）

### D.3 禁止动作
- 不得修改相机分辨率设置后不重新标定
- 不得使用 cap.set() 返回值作为尺寸核对依据（必须读实际值）

### D.4 通过条件
- `actual_size == calibration.image_size`（严格等于）
- AprilTag 在静态帧中可被检测到

### D.5 失败处理
- 尺寸不匹配 → **停止**。需要重新标定或确认 DroidCam 设置。
  当前标定: `intrinsics_final.json` 查看 `image_size`。
  **警告**: 历史 handoff 记载 DroidCam 在不同连接方式下可能返回 640x480 或 1280x720。
  必须以 `cap.get()` 实际读到的值为准。

### D.6 产物
- `D_camera_check.txt`（记录实际尺寸、标定尺寸、通过/失败）

---

## 阶段 E：低风险短时 START/STOP（需赛道净空、急停、用户明确授权）

### E.1 前置条件
- 阶段 D 通过
- **赛道净空**（无障碍物、无人员踏入）
- **急停可用**（物理开关或软件 STOP 命令就绪）
- **用户明确口头或书面授权运行**
- ⚠️ **小车先放在赛道起点（轮子接触赛道），用户手放在急停开关上**

### E.2 允许动作
1. 发送 START，小车运行 **≤3 秒**
2. 立即发送 STOP
3. 观察小车行为：
   - 电机启动响应正常
   - 循线行为正常（不冲出赛道）
   - STOP 后电机立即停止
4. 检查遥测：START 后遥测帧的 tick_ms 连续递增、pwm 值有正负、
   传感器值随赛道变化
5. 如果 3 秒正常，再执行一次 **≤5 秒** START/STOP

### E.3 禁止动作
- 不得在无急停下运行
- 不得运行超过 5 秒（本轮仅验证基本启动/停止，不采集完整数据）
- 不得在人员靠近赛道时运行
- 不得发送 PID/PWM 手动命令（仅 START/STOP）

### E.4 通过条件
- START → 小车开始跑线
- STOP → 小车**立即**停止（≤1s）
- 遥测流在 START 后连续到达（含有符号 PWM、tick_ms 单调递增）
- 无异常行为（打转、冲出、电机异响）

### E.5 失败处理
- 小车不启动 → 检查电机供电、PWM 线；重试 1 次 → 仍失败 **停止**
- 小车冲出赛道 → 立即 STOP；检查传感器/线损系数；**停止**，不进入 F
- STOP 无效 → 物理断电；**停止**，检查协议层 STOP 命令处理

### E.6 产物
- `E_start_stop_log.txt`（记录时间、行为观察、通过/失败）

---

## 阶段 F：同步 Gate（coverage ≥95%，全量 p95 ≤33.3ms）

### F.1 前置条件
- 阶段 E 通过
- 赛道净空，急停可用
- 用户明确授权
- 摄像头正常工作，AprilTag 在视野内
- 准备好停止条件（见 F.4）

### F.2 允许动作
1. 为采集创建独立 run_id 输出目录
2. 运行 `capture_sync_run.py`：
   ```bash
   py -3.11 .embeddedskills/build/v1_task4b4/capture_sync_run.py \
       --host <ESP_HOST> --duration 12 --out <output_dir>
   ```
3. 脚本自动：核对相机尺寸（fail-closed）→ 发送 START → 等待遥测 →
   采集 12s → 发送 STOP → 拟合 ClockSync → build_synchronized_dataset →
   evaluate_sync_gate → 输出 PASS/FAIL/INSUFFICIENT EVIDENCE
4. 检查 gate 输出：
   - **PASS**: coverage ≥95% 且 p95 ≤33.3ms → 同步 Gate ✅
   - **FAIL**: 不满足 → 记录指标，分析原因
   - **INSUFFICIENT EVIDENCE**: 数据不足 → 延长时间重试
5. 如果 PASS：再采集 **2 次** 不同 run（不同时长：8s + 15s），
   确保结果可复现

### F.3 禁止动作
- 不得修改 coverage 阈值（0.95）或 p95 阈值（33.3ms）来伪造 PASS
- 不得手动筛选帧来提升覆盖率
- 不得在 p95 计算前过滤失败样本

### F.4 通过条件（同步 Gate PASS）
- coverage ≥ 0.95
- p95_time_diff_ns ≤ 33,300,000（33.3ms）
- n_common_poses ≥ 20
- n_telemetry_distinct ≥ 2
- 至少 2 次独立 run 均 PASS

### F.5 失败处理
- FAIL → 检查遥测实际到达率、CIPSEND 事务完成时间、相机帧率
- INSUFFICIENT EVIDENCE → 延长时间（--duration 20），重试
- 连续 2 次 FAIL → **停止**，分析根因（handoff §14 列出的可能原因）
- 小车失控 → 立即 STOP；物理断电；**停止**

### F.6 产物
- `F_gate_run_1/`（含 raw_poses.json、raw_telemetry.json、sync_report.json）
- `F_gate_run_2/`
- `F_gate_run_3/`
- `F_gate_summary.md`（3 次 run 的 gate 结果对比）

---

## 阶段 G：失败/超时/断线时 STOP、回滚与证据保存

### G.1 任何阶段异常时的 SOP

1. **立即 STOP**（软件命令 → 物理断电，优先级升序）
2. **保存当前状态证据**：
   - 遥测最后 100 帧（如有）
   - 相机最后 10 帧（如有）
   - 终端输出完整保存
   - Keil 编译日志、烧录日志
3. **不要覆盖任何产物**。新建 `recovery_<timestamp>/` 目录保存。
4. **回滚决策**：
   - 与上一已知良好状态对比
   - 确定是固件问题（回滚 AXF）、协议问题、硬件问题还是环境问题
5. **记录**：异常现象、时间、可能原因、回滚动作、证据路径

### G.2 不可接受的回滚
- 不得为了"让测试通过"而跳过 CIPSEND 事务完成等待
- 不得降低 coverage/p95 阈值
- 不得关闭 fail-closed 检查（相机尺寸、输出目录）
