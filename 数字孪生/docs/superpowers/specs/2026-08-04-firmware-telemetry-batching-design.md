# Robot Twin AI — 固件遥测批量发送设计（R4 前置）

> 状态：**设计草案，待实施计划**。本设计不写产品代码；实现 + 烧录 + 真机验证
> 需单独授权（真机运行/烧录/车轮运动须重新取得用户当次授权）。
> 目标：把遥测**送达**从 ~10Hz 提到 ~30Hz，满足 4B-4 同步 Gate（p95≤33.3ms）的
> 数据侧需求。

## 1. 问题

- 固件**生成**遥测每 20ms（`TELEMETRY_INTERVAL_MS=20`，50Hz）。
- ESP01S CIPSEND **串行**每笔 ~100ms（等 SEND OK），latest-wins 覆盖后实际**送达 ~10Hz**。
- 4B-4 同步 Gate 假设相机 30fps + 遥测 50Hz → p95 ≤ 33.3ms。10Hz 遥测大概率
  coverage<95% / p95 超标（计划 §17.3 #8 已预警）。

## 2. 方案：遥测批量（3 帧/ CIPSEND）

### 2.1 固件（main.c）

- `s_tele_frame[29]`（单槽）→ **批量槽**：
  ```
  static uint8_t  s_tele_batch[3 * 29];   /* 最多 3 帧 = 87 字节 */
  static uint16_t s_tele_batch_len;       /* 当前已装字节数 */
  static uint8_t  s_tele_batch_n;         /* 当前帧数 0..3 */
  ```
- `build_telemetry_frame()` 仍构建到临时 29B 帧；`Telemetry_Queue()` **追加**到批量槽：
  - 满 3 帧 → 丢弃最旧（memmove 左移一帧），追加最新（保持 latest-3，符合
    "遥测可丢/覆盖"）。
- `ESP_TrySendTelemetry()`：一次性发送**整个批量槽**：
  - CIPSEND 载荷 = `s_tele_batch`，长度 = `s_tele_batch_len`（≤87 ≤ 112 ✓）。
  - 命令 `AT+CIPSEND=<id>,<len>`，len = batch_len（≤87，命令 ≤24 ✓）。
  - 发送后清空批量槽（`s_tele_batch_len=0, n=0`）。
- **CIPSEND 命令长度**：`AT+CIPSEND=0,87\r\n` = 17 字符 ≤ 24 ✓。
- **CIPSEND_TX_MAX_DATA=112**：3×29=87 ≤ 112，余 25B ✓（不再像 0x02 那样只剩 1B）。

### 2.2 计数语义（health_stats §4.4 需更新）

- `telemetry_generated`：每**帧**构建 +1（不变）。
- `telemetry_tx_started`：每次 **CIPSEND start**（一笔批量） +1（**不再是每帧**）。
- `telemetry_tx_ok/failed`：每**笔批量事务** +1。
- PC 端判读口径改为：`Δgenerated` ≈ N×Δstarted（N=平均批内帧数），
  不得再假定 generated≈started。
- 0x02 帧内 `telemetry_tx_started` 仍是 u16 累计，判读用模差。

### 2.3 PC 解析（frame_parser.py）

- 0x01 帧自定界（`AA55 type len ...`）。一个 CIPSEND 载荷含多帧时，
  逐字节喂 `FrameParser.feed()` 自然扫描多个 AA55 头即可。
- **已验证（2026-08-04）**：向 `FrameParser` 喂 3 帧拼接载荷（87B，正确
  `type^len^payload` 校验）→ `frames_ok=3, frames_bad=0, resync=0`。无需改解析器。
- 仍需新增黄金测试固化该行为（实现任务内）。

### 2.4 其他

- 批量槽与 `s_tele_pending` 的替代：批量槽空 = 无待发；`Telemetry_Queue` 构建后
  若槽非空则 `ESP_TrySendTelemetry()`。
- 仲裁：批量遥测仍是 DROPPABLE、`CIPSEND_TX_TAG_TELEMETRY`；health_due 时让行
  （`ESP_TrySendTelemetry` 现有让行逻辑不变）。
- 连接代次变化：coordinator 清空批量槽（旧代次帧不得泄漏）。

## 3. 测试计划（TDD，Host C + Python）

- Host C（新 `test_telemetry_batch.c` 或扩展）：批量槽追加/满 3 丢最旧/发送清空；
  拼接载荷长度正确；`Telemetry_Queue` 时序下批量不溢出。
- Python `test_frame_parser_health.py`：3 帧拼接载荷解析为 3 帧。
- `transport_soak`：批量后遥测送达频率（需真机，授权后）。
- Keil Rebuild 0/0。

## 4. 验收

- 离线：Host C 全绿 + Python 回归 + Keil 0/0。
- 真机（授权后）：架空轮/赛道运行，遥测送达 ~30Hz（tick p50 ≈ 33ms），
  4B-4 同步 Gate（coverage≥95%、p95≤33.3ms）数据侧达成。

## 5. 边界

- 不改 `0x01` 帧字节布局；不改 PID/巡线/电机。
- 真机运行/烧录/车轮运动须重新取得用户当次授权；不沿用旧授权。
- 未达 Gate 前不得宣称 4B-4 完成。
