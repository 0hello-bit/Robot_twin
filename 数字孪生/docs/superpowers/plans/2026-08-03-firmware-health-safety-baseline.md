# Robot Twin AI — 正式固件健康与安全基线：实施计划（2026-08-03）

> **For agentic workers:** 先读设计
> `docs/superpowers/specs/2026-08-03-firmware-health-safety-baseline-design.md`，
> 再按本计划逐步执行。步骤用 `- [ ]` 跟踪；每步必须“先测试后实现”，验收后勾选。
>
> **安全边界（全程生效）**：本计划在 **Codex 审核通过且用户再次明确授权之前**，
> 只执行离线设计/测试/Keil 构建/哈希登记；**禁止连接 MCU、halt/reset、擦除、
> 烧录、串口、TCP、START、电机动作**。第 13–15 步为授权门控步骤，缺授权不得执行。
>
> **Git 纪律**：本仓库工作区很脏且 Git 治理由另一代理负责。本计划**禁止
> `git add/commit/init/checkout/reset/clean`**。所有“提交”以**验收检查点**替代：
> 在 `.embeddedskills/build/firmware_health_baseline_design/` 落盘证据并核对。

---

## 0. 全局约束

- 读设计文档后再执行；设计中的字节布局、字段语义、状态机为唯一权威。
- Python：`py -3.11`（与 dropout review 复算命令一致）。
- Host C 构建：`.embeddedskills/build/v1_task4b4_fix/build_host_c_tests.sh`，
  产物路径 ASCII-only（`hostc/User|System` shim，规避 MSVC 中文路径代码页问题）；
  新模块必须同步复制到 shim。
- Keil：`F:\keil\UV4\UV4.exe -r "<repo>\程序\3. 麦轮巡线小车\project.uvprojx" -j0`。
- 产物：AXF 位于 `<repo>\程序\3. 麦轮巡线小车\程序_3_构建产物\Objects\Project.axf`。
- 新增证据目录：`.embeddedskills/build/firmware_health_baseline_design/`。
- 回滚备份目录（不可覆盖）：`.../firmware_health_baseline_design/rollback_artifacts/preflash/`
  与 `.../rollback_artifacts/postbuild/`。
- **任何 Keil Rebuild（Task 6.3 / 7.3）之前必须先完成 Task 0 `build_artifact_backup`**
  （构建产物备份）；否则 Rebuild 会覆盖 `Objects\Project.axf`，仅 `preflash_hashes.json`
  无法执行回滚。**该备份只证明构建目录旧产物，不证明 MCU 实际 Flash**；设备级回滚
  来源由 Phase 6/7 的 Task 12-A `device_firmware_backup/provenance` 门控（Round 2 项 3）。
- 命令中的 `<repo>` = `C:\Users\24668\Desktop\stm32小车`。
- 主机端新增/改动一律带测试；不得以“改了能跑”代替测试命令与退出码。

---

## Phase 0 — `build_artifact_backup`（任何 Rebuild 之前，Codex Round1 项 1）

> **范围声明（Round 2 项 3）**：本节是**构建产物备份**（AXF/HEX 本体），只证明构建
> 目录在 Rebuild 前的旧产物，**不能证明与 MCU 当前 Flash 一致**。设备级回滚来源
> （MCU 实际固件）由 Task 12-A `device_firmware_backup/provenance` 门控，见 Phase 6。

### Task 0：构建产物备份 + `preflash_hashes.json`（构建产物备份与比对依据（未经 provenance 不作为设备回滚件））

**Files:**
- Create: `.embeddedskills/build/firmware_health_baseline_design/rollback_artifacts/preflash/`（不可覆盖）
- Create: `.embeddedskills/build/firmware_health_baseline_design/rollback_artifacts/postbuild/`（Rebuild 后放新产物）
- Create: `.embeddedskills/build/firmware_health_baseline_design/preflash_hashes.json`

**步骤：**
1. 建立不可覆盖备份目录 `rollback_artifacts/preflash/`（已存在则复用，绝不覆盖/删除
   已有文件）。
2. 把当前旧产物**本体**复制进该目录：`<repo>\程序\3. 麦轮巡线小车\程序_3_构建产物\Objects\Project.axf`
   与 `Project.hex`（若存在）。
3. 对**备份副本**生成 `preflash_hashes.json`：`Get-FileHash -Algorithm SHA256`，记录
   `{name, sha256, source_path, size_bytes, backup_path}`；任一副本不可读 → FAIL。
4. **幂等/冲突规则**：
   - 副本已存在且与当前源 sha256 **相同** → 复用既有备份，不重复复制（幂等）；
   - 副本已存在但 sha256 **不同** → **STOP**（旧产物已改变，人工介入，绝不覆盖已有备份）；
   - **绝不删除**任何旧备份。
5. **Gate（任何新 Rebuild 之前必过）**：`preflash_hashes.json` 存在、备份文件可读且
   sha256 与源一致。Task 6.3 是首个 Keil Rebuild，必须先完成 Task 0。新产物在
   Rebuild 成功后复制到 `rollback_artifacts/postbuild/`（Step 11.3），不依赖 Keil
   输出目录长期保存。

---

## Phase 1 — 协议 / 统计纯逻辑（Host C TDD）

### Task 1：`health_frame` — 0x02 编码器与黄金向量

**Files:**
- Create: `程序/3. 麦轮巡线小车/User/health_frame.h`
- Create: `程序/3. 麦轮巡线小车/User/health_frame.c`
- Create: `simulation/digital_twin/tests/test_health_frame.c`
- Sync: 复制 `health_frame.{c,h}` 到 `.embeddedskills/build/v1_task4b4_fix/hostc/User/`
- Create: `.embeddedskills/build/firmware_health_baseline_design/golden_health_0x02.hex`

**Interfaces:**
```c
#define HEALTH_FRAME_TYPE       0x02U
#define HEALTH_FRAME_PAYLOAD_LEN 106U
#define HEALTH_FRAME_TOTAL_LEN  111U
#define HEALTH_FRAME_FW_SCHEMA_VERSION 1U

typedef struct { /* 字段与 §5.2 布局一一对应，见设计文档（含 snapshot_tick_ms 与 health_* 六项） */ ... } HealthSnapshot;

/* 返回帧总长（恒 111）。逐字段 LE 写入（不用 memcpy 结构体，规避对齐/填充）。 */
uint8_t health_frame_encode(uint8_t *buf, const HealthSnapshot *snap);
```

- [ ] **Step 1.1 — 写失败测试（RED）**

在 `test_health_frame.c` 中构造固定快照（值与黄金向量一致），断言编码结果等于
`golden_health_0x02.hex` 记录的 111 字节。黄金向量（本计划直接给出，避免占位；
Round 2 项 2 新增 `health_*` 六项）：

```
AA 55 02 6A
01 01 08 01 01 02 03 00 0A 00 C8 00 00 00 01 00 00 00 40 42 0F 00 40 E2 01 00
06 00 F4 01 64 00 05 00 5F 00 5A 00 05 00 6E 00 69 00 64 00 01 00 02 00 01 00
01 00 64 00 00 00 F4 01 00 00 05 00 04 00 5F 00 02 00 02 00 01 00 00 00 10 27
00 00 88 13 00 00 00 00 00 00 00 00 40 00 30 00 0C 00 02 00 0A 00 09 00 01 00 2D 00
CD
```

对应固定快照：`fw_schema_version=1 fw_build_id=1 reset_cause=0x08
（=PORRSTF bit27，`health_reset_cause_from_csr` 映射，设计 §5.4/§5.5）
motion_state=1 lease_active=1 heartbeat_last_reason=2 heartbeat_timeout_count=3
heartbeat_count=10 heartbeat_age_ms=200 connection_generation=1 snapshot_tick_ms=1000000
loop_seq=123456 loop_last_gap_ms=6 loop_max_gap_ms=500 telemetry_generated=100
telemetry_overwritten=5 telemetry_tx_started=95 telemetry_tx_ok=90
telemetry_tx_failed=5 cipsend_started=110 cipsend_completed=105 cipsend_ok=100
cipsend_error=1 cipsend_prompt_timeout=2 cipsend_sendok_timeout=1 cipsend_closed=1
cipsend_last_duration_ms=100 cipsend_max_duration_ms=500 ack_started=5
status_started=4 telemetry_started=95 diag_health_started=2 status_retry=2
ack_retry=1 boundary_aborts=0 uart_rx_bytes=10000 uart_tx_bytes=5000
uart_rx_overflow=0 uart_tx_overflow=0 uart_ore_events=0 uart_rx_high_water=64
uart_tx_high_water=48 health_generated=12 health_dropped=2 health_started=10
health_ok=9 health_failed=1 health_last_duration_ms=45`。
    本黄金帧的 `health_*` 值是“截至上一笔已归类尝试”的快照会计状态：`health_generated==
    health_dropped+health_started`（12=2+10）、`health_started==health_ok+health_failed`
    （10=9+1，in_flight=0）；编码时当前发射动作尚未计入（Round 3 项 3）。

- [ ] **Step 1.2 — 运行测试，确认 RED**

```
bash .embeddedskills/build/v1_task4b4_fix/build_host_c_tests.sh \
  .embeddedskills/build/firmware_health_baseline_design/test_health_frame.exe \
  simulation/digital_twin/tests/test_health_frame.c \
  .embeddedskills/build/v1_task4b4_fix/hostc/User/health_frame.c
.embeddedskills/build/firmware_health_baseline_design/test_health_frame.exe
```

期望（RED）：`health_frame.{h,c}` 尚不存在 → `cl` 报“无法打开源文件”/链接失败，
非 0 退出码；创建最小 stub 后断言不满足黄金向量仍非 0。

- [ ] **Step 1.3 — 实现 `health_frame`**

按 §5.2 逐字段 `put_u16_le/put_u32_le`（复用 motor_reg_diag 的编码风格），
checksum = `type ^ len ^ payload[i]`（type=0x02，len=0x6A）。

- [ ] **Step 1.4 — 运行测试，确认 GREEN**

同上命令，期望 `PASS test_health_frame`，退出码 0。

- [ ] **Step 1.5 — 验收检查点**

`golden_health_0x02.hex` 与 `test_health_frame.c` 的字节串一致；GREEN 日志落盘。

---

### Task 2：`health_stats` — 主循环计时与计数器

**Files:**
- Create: `程序/3. 麦轮巡线小车/User/health_stats.h`
- Create: `程序/3. 麦轮巡线小车/User/health_stats.c`
- Create: `simulation/digital_twin/tests/test_health_stats.c`
- Sync: 复制到 `hostc/User/`

**Interfaces:**
```c
typedef struct {
    uint32_t loop_seq;
    uint32_t loop_last_gap_ms;
    uint32_t loop_max_gap_ms;
    uint32_t cipsend_started, cipsend_completed;
    uint32_t cipsend_ok, cipsend_error, cipsend_prompt_timeout,
             cipsend_sendok_timeout, cipsend_closed;
    uint32_t cipsend_last_duration_ms, cipsend_max_duration_ms;
    uint32_t ack_started, status_started, telemetry_started, diag_health_started;
    uint32_t status_retry, ack_retry, boundary_aborts;
    uint32_t telemetry_generated, telemetry_overwritten,
             telemetry_tx_started, telemetry_tx_ok, telemetry_tx_failed;
    /* Round 2 项 2：0x02 专属（CIPSEND_TX_TAG_DIAG_HEALTH=5U），不含 0x7E。 */
    uint32_t health_generated, health_dropped, health_started,
             health_ok, health_failed;
    uint16_t health_last_duration_ms;   /* 饱和；最近一笔 0x02 事务时长 */
    uint32_t health_start_ms;           /* 当前在途 0x02 事务开始时刻（duration 计算用） */
} HealthStats;

void hstats_init(HealthStats *s);
void hstats_loop_tick(HealthStats *s, uint32_t now_ms);   /* seq/gap/max */
void hstats_tx_started(HealthStats *s, uint8_t tag, uint32_t now_ms);
void hstats_tx_terminal(HealthStats *s, uint8_t tag, uint8_t result,
                        uint8_t timeout_aborted, uint8_t entered_send_data,
                        uint32_t now_ms);
/* entered_send_data=1 表示终态时已进入 SEND_DATA/WaitSENDOK，用于区分
   prompt_timeout(0) 与 sendok_timeout(1)，规则见设计 §4.3。 */
/* Round 2 项 2：0x02 走独立 CIPSEND_TX_TAG_DIAG_HEALTH（=5U），health_* 六项专属归属。
   TAG_DIAG（=4U）仅维护 diag_health_started，二者不混计。 */
void hstats_health_generated(HealthStats *s);            /* health_emit 每 1Hz +1 */
void hstats_health_dropped(HealthStats *s);              /* 忙/有 A/S 重试而放弃发送 +1 */
void hstats_telemetry_generated(HealthStats *s);
void hstats_telemetry_overwritten(HealthStats *s);
void hstats_status_retry(HealthStats *s);
void hstats_ack_retry(HealthStats *s);
void hstats_boundary_abort(HealthStats *s);
void hstats_fill_health(const HealthStats *s, uint32_t now_ms, HealthSnapshot *snap);
/* now_ms 同时写入 snap->snapshot_tick_ms（采集时刻 mono tick，见设计 §5.2/§5.3）。
   hstats_fill_health 把 health_* 映射进 snap；health_last_duration_ms 饱和写 u16。 */
/* tx_started/tx_terminal 中 tag == CIPSEND_TX_TAG_DIAG_HEALTH 时维护 health_started /
   health_ok / health_failed / health_last_duration_ms。 */
```

- [ ] **Step 2.1 — 写失败测试（RED）**

`test_health_stats.c` 断言：
1. `hstats_loop_tick` 连续调用 seq 递增、`loop_last_gap_ms = now - prev`、
   `loop_max_gap_ms` 单调峰值；注入 `now` 跨 `0xFFFFFFFF→0x00000005` 验证回绕；
   `hstats_fill_health` 把 gap 字段**饱和**写入 u16 快照字段（>0xFFFF 钳 0xFFFF，
   规则见设计 §5.2）。
2. `hstats_tx_started(TAG_TELEMETRY)` → `telemetry_started`+1；
   `hstats_tx_terminal(TAG_TELEMETRY, CTS_RESULT_OK, 0, entered_send_data, now)`
   → `telemetry_tx_ok`+1、`cipsend_completed`+1；分类
   `ERROR/PROMPT_TIMEOUT/SENDOK_TIMEOUT/CLOSED` 各自命中：`timeout_aborted=1`
   且 `entered_send_data=0` → prompt_timeout；`timeout_aborted=1` 且
   `entered_send_data=1` → sendok_timeout。
3. `hstats_tx_started` 记 `start_ms`，`hstats_tx_terminal` 计算 duration；
   `cipsend_max_duration_ms` 为峰值。
4. `hstats_fill_health` 把 stats 字段映射进 `HealthSnapshot`（黄金值抽查），且
   `snapshot_tick_ms == now_ms`。
5. **Round 2 项 2（health 专属）**：`hstats_health_generated()` 后
   `health_generated`+1；`hstats_health_dropped()` 后 `health_dropped`+1；
   `hstats_tx_started(CIPSEND_TX_TAG_DIAG_HEALTH, now)` → `health_started`+1 且
   **不增加** `diag_health_started`；`hstats_tx_terminal(CIPSEND_TX_TAG_DIAG_HEALTH,
   CTS_RESULT_OK, 0, entered, now)` → `health_ok`+1、`health_last_duration_ms`=duration；
   非 OK → `health_failed`+1。断言 `TAG_DIAG`（0x7E）只增 `diag_health_started`，
   **二者互不混计**。
6. **Round 3 项 3（快照时序与恒等式，五个转换）**：按 `health_emit` 归类顺序逐转换
   断言，每步 `health_generated == health_dropped + health_started`、
   `health_started == health_ok + health_failed + in_flight`（in_flight ∈ {0,1}）：
   ① busy-drop：`generated`+1 且 `dropped`+1，恒等式保持；② start-fail：先填快照
   （值=归类前计数，恒等式成立）→ `generated`+1 → start 失败 `dropped`+1，恒等式
   恢复；③ start-success/in-flight：填快照 → `generated`+1 → start 成功 `started`+1，
   此时 in_flight=1、`started==ok+failed+1`；④ terminal-ok：`ok`+1、in_flight 归 0、
   `started==ok+failed`；⑤ terminal-fail：非 OK 终态 `failed`+1、in_flight 归 0。
   注入 `health_*` u16 跨 `0xFFFF→0x0001` 回绕，验证模 2^16 差值与恒等式在回绕后
   仍成立。

- [ ] **Step 2.2 — 运行测试，确认 RED**（同上 build 命令，stub 缺失即失败）
- [ ] **Step 2.3 — 实现 `health_stats`**（纯 C，时间由调用方传入；`mono_time_core.h`
  的回绕安全差值复用：`(uint32_t)(now - prev)`）
- [ ] **Step 2.4 — 运行测试，确认 GREEN**：`PASS test_health_stats`，退出码 0。
- [ ] **Step 2.5 — 验收检查点**：GREEN 日志落盘。

---

### Task 3：心跳命令 + 1s 租约（`twin_control_protocol`）

**Files:**
- Modify: `程序/3. 麦轮巡线小车/User/twin_control_protocol.h/.c`
- Modify: `simulation/digital_twin/tests/test_twin_control_protocol.c`
- Sync: 复制到 `hostc/User/`

**Interfaces（新增，头文件）:**
```c
#define TWIN_CONTROL_HEARTBEAT_LEASE_MS 1000U
#define TWIN_CONTROL_HEARTBEAT_PENDING_FLAG 1U   /* consume 返回值 */

void     twin_control_heartbeat(uint32_t now_ms);          /* 有效 H 帧到 */
uint8_t  twin_control_consume_heartbeat_pending(void);     /* 解析后置位 */
uint8_t  twin_control_heartbeat_tick(uint32_t now_ms);     /* 每轮租约检查 */
uint8_t  twin_control_health_motion_state(void);           /* 0/1/2/3/4/255 */
uint8_t  twin_control_lease_active(uint32_t now_ms);
uint16_t twin_control_heartbeat_count(void);
uint16_t twin_control_heartbeat_timeout_count(void);
uint8_t  twin_control_heartbeat_last_reason(void);
uint32_t twin_control_heartbeat_age_ms(uint32_t now_ms);
```

- [ ] **Step 3.1 — 写失败测试（RED）**

`test_twin_control_protocol.c` 新增：
1. `H,soak,soak0000002,<cs>\n`（校验正确、campaign/run 匹配）→ `consume` 置位；
   **P1-4**：`heartbeat_count` 在 parse 时 +1（同 drain 多条不合并），
   `twin_control_heartbeat(now)` 只更新 last_seen（任何状态）与 lease（仅 RUNNING）。
2. 校验错误 / campaign 不匹配 / run 不匹配 → 不置位、不计。
3. `twin_control_heartbeat_tick`：初始 inhibited → 返回 0；START 后
   `!g_was_running` 边沿开启租约（last_lease=now），随后 now+999 不超时、
   now+1000 超时 → 返回 1，`heartbeat_timeout_count`+1，
   `twin_control_motion_inhibited()==1`，`heartbeat_last_reason==HEARTBEAT`，
   且 S 帧 reason 仍为 `TIMEOUT`（`consume_pending_status` 断言）。
4. STOPPED 态收到 H → 计 `heartbeat_count`、更新 last_seen（age 正确），**不续约**
   （lease_active=0）；再 START 边沿重新开启租约。
5. `heartbeat_age_ms`：从未收到有效心跳 → `0xFFFFFFFF`；收到后 → now-last_seen。
6. `twin_control_health_motion_state` 映射：INIT/RUNNING/STOPPED/TIMEOUT/LINE_LOST。

- [ ] **Step 3.2 — 运行测试，确认 RED**

```
bash .embeddedskills/build/v1_task4b4_fix/build_host_c_tests.sh \
  .embeddedskills/build/firmware_health_baseline_design/test_twin_control_protocol.exe \
  simulation/digital_twin/tests/test_twin_control_protocol.c \
  .embeddedskills/build/v1_task4b4_fix/hostc/User/twin_control_protocol.c
.embeddedskills/build/firmware_health_baseline_design/test_twin_control_protocol.exe
```

期望：新用例 FAIL（函数不存在/行为不符），非 0 退出码。

- [ ] **Step 3.3 — 实现**：`parse_line` 增加 `H` 分支（`verify_frame(line, fields, 3)`
  + campaign/run 匹配 + 置 `g_heartbeat_pending`）；新增心跳/租约函数；在
  `parse_run` 的 STOP/RESTORE_BASELINE、`twin_control_timeout()`、
  `report_line_lost` 硬停分支复位 `g_was_running=0`；`motion_state` 映射由
  `g_last_state/g_last_reason` 推导。
- [ ] **Step 3.4 — 运行测试，确认 GREEN**：全量 `test_twin_control_protocol` PASS，退出码 0。
- [ ] **Step 3.5 — 验收检查点**：GREEN 日志落盘；确认未改 `0x01`/S 帧编码路径。

---

### Task 4：RX 环 `high_water`（`uart_ring`）

**Files:**
- Modify: `程序/3. 麦轮巡线小车/User/uart_ring.h/.c`
- Modify: `simulation/digital_twin/tests/test_uart_ring.c`
- Sync: 复制到 `hostc/User/`

**Interfaces:** `UartRing` 增 `volatile uint16_t high_water;`；
`uart_ring_init` 清零；`uart_ring_push` 在写入后
`if (used+1 > ring->high_water) ring->high_water = used+1;`。
该比较对 RX/TX 两处 `UartRing` 实例均生效（同一结构、同一 push，设计 §4.5 要求
两环都记录）。

- [ ] **Step 4.1 — RED**：`test_uart_ring.c` 新增：连续 push 至满环，high_water==128；
  交替 push/pop 峰值只升不降；pop 后 push 新峰值更新；init 后 high_water==0。
  对 RX 与 TX 两个实例均验证（设计 §4.5 要求两环都记录）。
- [ ] **Step 4.2 — 运行 RED**（期望 FAIL，字段/更新缺失）。
- [ ] **Step 4.3 — 实现**（ISR 侧仅 2 条比较，见设计 §4.5）。
- [ ] **Step 4.4 — GREEN**：`PASS test_uart_ring`，退出码 0。
- [ ] **Step 4.5 — 验收检查点**：确认 RX/TX 两处 `UartRing` 均被 init 覆盖。

---

### Task 5：`esp_tx_coordinator` 终态统计钩子

**Files:**
- Modify: `程序/3. 麦轮巡线小车/User/esp_tx_coordinator.h/.c`
- Modify: `simulation/digital_twin/tests/test_coordinator_boundary.c`
- Sync: 复制到 `hostc/User/`

**Interfaces:** `void etc_handle_terminal(EspTxCoordinator *c, uint32_t now_ms);`
处理终态时在 `txfq_on_tx_result` 之前调用
`hstats_tx_terminal(&g_health_stats, tag, result, timeout_aborted, now_ms)`——
但 coordinator 为纯逻辑、不持有 `g_health_stats` 全局；改为在 `EspTxCoordinator`
结构增加 `HealthStats *health_stats` 引用（`etc_init` 注入），
`etc_handle_terminal` 内 `hstats_tx_terminal(c->health_stats, ...)`。

- [ ] **Step 5.1 — RED**：更新 `test_coordinator_boundary.c` 到新签名；新增断言：
  各终态结果（OK/ERROR/CLOSED/timeout_abort）经 `etc_handle_terminal` 触发
  `health_stats` 对应计数与 duration；`CLOSED` 分支仍走 `etc_force_abort`。
  `entered_send_data` 由 `tx->state ∈ {SEND_DATA, WAIT_SENDOK}` 推导后传入
  `hstats_tx_terminal`（设计 §4.3 分类规则）。
- [ ] **Step 5.2 — 运行 RED**（期望编译失败/断言失败，签名不匹配）。
- [ ] **Step 5.3 — 实现**：结构加 `health_stats` 指针；`etc_init` 加参数；
  `etc_handle_terminal(..., now_ms)`。
- [ ] **Step 5.4 — GREEN**：`PASS test_coordinator_boundary`，退出码 0。
- [ ] **Step 5.5 — 验收检查点**：确认 `main.c` 侧调用点将在 Task 6 同步为
  `etc_handle_terminal(&g_coordinator, mono_now_ms())`。

---

## Phase 2 — 主循环集成（Keil 可构建 + Host 可测部分）

### Task 6：`health_watchdog`（IWDG 薄层）

**Files:**
- Create: `程序/3. 麦轮巡线小车/User/health_watchdog.h/.c`
- Sync: 复制到 `hostc/User/`（仅头文件常量可测；`stm32f10x_iwdg.c` 已在 Keil 引用集）

**Interfaces:**
```c
/* PR=IWDG_Prescaler_64，RLR=1249 → 名义 2.0s；LSI 30–60kHz → 实际 [~1.33, ~2.67]s */
void iwdg_init_and_enable(void);
void iwdg_feed(void);   /* IWDG_ReloadCounter()；在主循环迭代顶部调用，证明上一轮已
                           返回循环顶部（当前轮尚未完成），见设计 §4.1 */
```

- [ ] **Step 6.1 — RED（常量断言）**：`test_health_watchdog.c`（或并入
  `test_health_frame.c`）断言常量：PR 分频 64、RLR=1249、以及设计文档
  §7.2 的 LSI 范围换算表（`1333 / 2000 / 2667`）作为可复算注释；Host 无法测
  硬件，仅测“参数=期望值”。
- [ ] **Step 6.2 — 实现**：`health_watchdog.c` 用标准库
  `IWDG_WriteAccessCmd(IWDG_WriteAccess_Enable); IWDG_SetPrescaler(
  IWDG_Prescaler_64); IWDG_SetReload(1249); IWDG_ReloadCounter(); IWDG_Enable();`。
- [ ] **Step 6.3 — Keil Rebuild**（命令见 §0）：期望 0 Error / 0 Warning，
  Program Size 增量记录到 `keil_rebuild_health.log`。

### Task 7：`main.c` 接线

**Files:**
- Modify: `程序/3. 麦轮巡线小车/User/main.c`
- Sync: 复制改动相关头文件到 `hostc/`（main.c 本身不 Host 编译）

**接线点（与设计 §4.1/§5.3 一致）：**
1. `main()` 顶部：`g_reset_cause = health_reset_cause_from_csr(RCC->CSR);
   RCC->CSR |= RCC_CSR_RMVF;`（P0-1：用纯函数取高字节复位标志，不再用
   `RCC->CSR & 0x1F`——那读的是低位 LSI 状态，无法报告 POR/IWDG）。
2. 所有初始化完成后、`while(1)` 前：`iwdg_init_and_enable();`。
3. `while(1)` 顶部：`health_loop_tick(mono_now_ms());` —— 该函数在 main.c 内，
   依次调 `hstats_loop_tick`、`if (twin_control_consume_heartbeat_pending())
   twin_control_heartbeat(now)`、`if (twin_control_heartbeat_tick(now))
   MotorTargetsZero();`、`iwdg_feed();`。`iwdg_feed()` 语义：证明上一轮已返回循环
   顶部；主循环为 while(1) 无正常退出路径，所有正常分支下一轮再次到达该喂狗点。
4. `Telemetry_Queue`：构建帧后 `hstats_telemetry_generated()`；
   进入时 `s_tele_pending` 已真 → `hstats_telemetry_overwritten()`。
5. `ESP_TrySendTelemetry` / `ESP_SendDiagFrame` / `ESP_SendQueuedFrames` 中
   `cipsend_tx_start(...)` 成功处 → `hstats_tx_started(tag, now_ms)`；
   ACK/STATUS 起始处若 `txfq_has_ack/status` 已真 → `hstats_ack_retry/status_retry()`。
6. `ESP_ServiceTX` → `etc_handle_terminal(&g_coordinator, mono_now_ms())`。
7. 每 ~1s（`mono_now_ms() - s_last_health_ms >= 1000`）→ `health_emit()`（归类顺序
   Round 3 项 3：快照值 = 截至上一笔已归类尝试）：
   先判 `cipsend_tx_busy || txfq_has_retry`：
   - busy/有 A/S 重试 → `hstats_health_generated()` 后立即 `hstats_health_dropped()`
     并跳过发送（不发射帧）；
   - 可发送 → **先**以当前计数填 `HealthSnapshot`（`hstats_fill_health + twin_control
     健康字段 + uart 环计数（含 RX/TX high_water）+ coordinator.boundary_events +
     esp_transport_connection_generation + 身份字段`；`snapshot_tick_ms =
     mono_now_ms()`，与发射同一调用点）→ `health_frame_encode(buf,&snap)` → **再**
     `hstats_health_generated()` → 调 `ESP_SendDiagFrame(buf,111)`，内部
     `cipsend_tx_start(CIPSEND_TX_TAG_DIAG_HEALTH)` 成功处 →
     `hstats_tx_started(CIPSEND_TX_TAG_DIAG_HEALTH, now)`（`health_started`+1）；
     start 失败 → `hstats_health_dropped()`；
   `s_last_health_ms = mono_now_ms()`。

- [ ] **Step 7.1 — RED**：先建一个 main.c 接线的最小集成测试无法 Host 直接测，
  因此 RED 以**编译期**证明：Keil Rebuild 在改动前引用缺失函数 → 链接失败
  （作为 RED 证据日志）。修改完成后 Rebuild 通过 = GREEN。
- [ ] **Step 7.2 — 实现接线**（严格按上述 7 点）。
- [ ] **Step 7.3 — Keil Rebuild**：0 Error / 0 Warning；`Program Size` 增量记录。
- [ ] **Step 7.4 — 验收检查点**：`main.c` 中无新阻塞点、无新全局延迟；
  `hw`/`stub` 编译产物存在；遥测路径未改动 `0x01` 构建代码。

---

## Phase 3 — 主机解析与心跳

### Task 8：`frame_parser.py` 0x02 识别与解码 + 生产 bridge `(frame_type, len)` 分流（Round 2 项 1）

**Files:**
- Modify: `simulation/digital_twin/real_world/frame_parser.py`
- Modify: `simulation/digital_twin/real_world/wifi_bridge.py`（Round 2 项 1：`_process_binary_frame` 按 `(frame_type, len)` 分流）
- Modify: `simulation/digital_twin/web_showcase/live_wifi_bridge.py`（Round 2 项 1：`_process_frame` 按 `(frame_type, len)` 分流）
- Create: `simulation/digital_twin/tests/test_frame_parser_health.py`
- Create: `simulation/digital_twin/tests/test_old_parser_health_compat.py`（旧 parser 兼容性 gate 的永久回归，Codex Round1 项 7；**待建**，当前未存在）
- Create: `simulation/digital_twin/tests/test_wifi_bridge_health_dispatch.py`（Round 2 项 1，**新建**）
- Create: `simulation/digital_twin/web_showcase/test_live_wifi_health_dispatch.py`（Round 2 项 1，**新建**）

**接口：**
```python
FRAME_TYPE_HEALTH = 0x02
PAYLOAD_LEN_HEALTH = 106
PAYLOAD_LEN_MAX = 106          # 原 len>64 拒绝 → 改为 len>106 拒绝（容纳 0x02）
def decode_health(payload) -> dict   # 字段名/单位与 C 布局一致（含 snapshot_tick_ms、health_* 六项）

# 所有消费 0x02 的分发点统一规则（Round 2 项 1）：
#   (0x02, len==7)   → decode_status（旧 STATUS，保留）
#   (0x02, len==106) → decode_health（health 路径）
#   (0x02, 其它 len) → 判坏丢弃，绝不广播成 car_status
```

- [ ] **Step 8.0 — 旧 parser 兼容性 gate（修改 `frame_parser.py` 之前执行，Codex Round1
  项 7）**：用当前（未修改）`FrameParser` 喂入新黄金帧 `AA55 02 6A … CD`
  （len=106 > 64），断言：不抛异常、不返回帧、`frames_bad`+1、`resync_count`+1；
  随后喂入 `0x01` 遥测帧仍能正确解析（**无持续失步**）。结果落盘
  `old_parser_0x02_compat_gate.json`。
  **这是指标兼容性变化**：旧工具会把每帧 0x02 计入坏帧（`frames_bad`/`resync_count`），
  不宣称完全兼容。该语义由**待建**的永久回归测试 `test_old_parser_health_compat.py`
  固化（以文档化的旧规则复现断言，防止未来无谓回归）；本 gate 执行前该测试尚不存在。
- [ ] **Step 8.1 — RED**：`test_frame_parser_health.py`：
  1. 喂入黄金帧 `AA55 02 6A … CD` → 返回 `(0x02, payload)`，`decode_health` 字段
     与黄金快照一致（抽查 8 个字段：snapshot_tick_ms、loop_seq、heartbeat_age_ms、
     uart_rx_bytes、uart_tx_high_water、health_started、health_ok、
     health_last_duration_ms 等）。
  2. `decode_health` 对错误长度抛/返回 None。
  3. 新行为：`(0x02, len==7)` → `decode_status`；`(0x02, 其它非 7/106 len)` →
     `frames_bad++`；len>106 帧 → `frames_bad++`；`0x01` 遥测仍按 `decode_telemetry`。
- [ ] **Step 8.2 — 运行 RED**：`py -3.11 -m pytest simulation/digital_twin/tests/test_frame_parser_health.py simulation/digital_twin/tests/test_old_parser_health_compat.py simulation/digital_twin/tests/test_wifi_bridge_health_dispatch.py simulation/digital_twin/web_showcase/test_live_wifi_health_dispatch.py -v`
  → 期望 FAIL（无 `decode_health` / len 上限仍是 64 / bridge 无分流）。
- [ ] **Step 8.3 — 实现**：`FRAME_TYPE_HEALTH`、`PAYLOAD_LEN_HEALTH`、
  `PAYLOAD_LEN_MAX=106`、`decode_health`；`feed()` 的 `len>106` 判坏保持；并实现
  `wifi_bridge.py::_process_binary_frame` 与 `live_wifi_bridge.py::_process_frame`
  的 `(frame_type, payload_len)` 联合分流（7B STATUS 保留、106B health、其余判坏，
  绝不广播 car_status）。
- [ ] **Step 8.4 — GREEN**：全部用例 PASS（含 `test_old_parser_health_compat.py`、
  `test_wifi_bridge_health_dispatch.py`、`test_live_wifi_health_dispatch.py`），退出码 0。

### Task 9：`transport_soak.py` 心跳发送 + 0x02 解析持久化

**Files:**
- Modify: `.embeddedskills/build/v1_task4b4/transport_soak.py`
- Modify: `.embeddedskills/build/v1_task4b4/test_transport_soak_rework.py`

**接口：**
- `class HeartbeatCommand(campaign, run_id)` → 编码 `H,campaign,run_id,<cs>\n`。
- `MixedStreamParser(on_health=...)`；`_feed_binary` 对 `(FRAME_TYPE_HEALTH, len==106)`
  分发（其它 0x02 长度判坏）。
- `_SessionCtx` 增加 `health_frames`；`_on_health(payload)` → `decode_health` →
  `{"frame_ts_s", "pc_recv_ns", **fields}`（fields 含 `snapshot_tick_ms`、
  `health_*` 六项、`uart_rx_high_water`、`uart_tx_high_water`）。
- `run_handshake` 采集期启动心跳发送：RUNNING 确认后，每 0.2s 发一条
  `H,campaign,run_id,<cs>\n`，final STOP 前停止。
- `_finalize` 输出 `health` 摘要 + 落盘 `raw_health.json`（新增输出文件名）；
  摘要记录 **0x02 投递率（多跳归因）**与 **0x02 事务延迟**（Round 2 项 2）：
  - PC 实收帧数：窗口内 `raw_health.json` 计数；
  - 期望/发出帧数：以首末帧 `snapshot_tick_ms` 模差（≈窗口秒数）为期望，并以
    首末帧的 Δ`health_generated`（尝试）、Δ`health_started`（进入 CIPSEND）、
    Δ`health_ok`（ESP 回 SEND OK）作三跳分母/分子；
  - 0x02 事务延迟（Round 3 项 4）：`health_last_duration_ms` 的**可观测去重
    last-duration 样本及完整性标志**——仅当相邻收到的 0x02 满足
    `Δ(health_ok+health_failed)==1` 时计一个**新样本**；delta=0 不重复计样；delta>1
    置 `duration_samples_incomplete=true`，只保留 latest，不声称完整分布（**仅 0x02
    tag，不可用全局 `cipsend_last_duration_ms` 冒充**）。

**注意（Codex Round1 项 2/5 + Round 2 项 2）**：0x02 与 0x01 同走 CIPSEND 链路，断流
窗口内 0x02 也可能不可达；PC 侧仅能用断流恢复前后快照的 `snapshot_tick_ms` 模差
定位缺失区间，**不宣称逐秒连续观测**。投递率、帧率、断流分布与历史 60s/300s soak
不直接横向比较。0x02 投递率/事务延迟以 **health 专属计数**（`health_generated/
dropped/started/ok/failed`、`health_last_duration_ms`）与 PC 实收帧数联合计算，
**不得**用混入 0x7E 的 `diag_health_started` 或全局 `cipsend_last_duration_ms` 冒充
专属指标。

- [ ] **Step 9.1 — RED**：
  1. 心跳编码：黄金 `H,soak,soak0000002,<cs>\n`（cs 为既有 XOR 算法）。
  2. 脚本化回放：把一段含 `0x02` 黄金帧的字节流喂给 `MixedStreamParser` →
     `health_frames` 有记录、字段正确（含 `health_*` 六项）。
  3. 心跳发送在 RUNNING 期间每 0.2s 一次、final STOP 前停止（用
     `_ScriptedTransport` 回放验证 TX 事件序列）。
  4. 摘要计算：给一组回放帧 → 断言 0x02 投递率三跳分母/分子与
     `health_last_duration_ms` 去重样本字段存在且口径正确（Round 2 项 2）；
     构造相邻帧 `Δ(health_ok+health_failed)` = 0 / 1 / >1 三组 → 断言 delta=0 不重复
     计样、delta=1 计一个新样本、delta>1 置 `duration_samples_incomplete=true` 且只
     保留 latest（Round 3 项 4）。
- [ ] **Step 9.2 — 运行 RED**：`py -3.11 -m pytest .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py -v`
  → 期望新用例 FAIL。
- [ ] **Step 9.3 — 实现**。
- [ ] **Step 9.4 — GREEN**：全量 25+ 用例 PASS（含旧回归）。

---

## Phase 4 — 工具安全修复

### Task 10：finally-STOP、唯一 run_id、门禁拆分、窗口排除

**Files:** 同上（`transport_soak.py` + 测试）。

- [ ] **Step 10.1 — RED**：
  1. **finally-STOP**：`run_handshake` 在 START 已发送、未确认 STOPPED 时，
     若 `_collect`/`wait_for_status` 抛异常或 KeyboardInterrupt，`finally` 中
     best-effort `_final_stop`，等待关联 STOPPED；等待失败 → `out["cut_power_warning"]=True`
     且醒目打印 `CUT POWER`。用 `_ScriptedTransport` 注入“START 后 recv 抛错”场景断言。
  2. **唯一 run_id**：`--cmd-run-id` 默认改为运行时生成的
     `soak{epoch_s:08x}`（12 字符，`re.fullmatch(r"[A-Za-z0-9-]{1,16}")`）；
     `make_run_id()`（输出目录名）与命令 run_id 分离；测试断言合规与唯一。
  3. **门禁拆分**：`eval_gates_split` 输出
     `TRANSPORT_CONTINUITY`（max_wall_gap_s ≤ `CONTINUITY_GAP_THRESHOLD_S`，
     初值 5.0，来源：既有 runbook 阶段 C 定义“未断流超过 5s”，本批次登记基线
     明确 `BASELINE_REGISTERED` 而非 PASS/FAIL）与
     `DELIVERY_CADENCE`（p50/p95/p99/max + >300ms 缺口密度，阈值从 health-baseline
     复测分布登记，**无来源阈值不得固化**）。测试断言 verdict 键名与
     `BASELINE_REGISTERED` 语义。
  4. **窗口排除**：`compute_metrics`/采集窗口 = `[RUNNING 确认, +duration)`，
     窗口外帧（START 前、final STOP 握手期）一律排除；用脚本化回放构造
     “窗口外 1 帧 + 窗口内 N 帧”断言只统计窗口内。
  5. **分项登记（Codex Round1 项 5 + Round 2 项 2 + Round 3 项 4）**：每次
     health-baseline 运行分别记录 0x01 帧率、0x02 投递率（health_* 多跳归因 + PC
     实收）、0x02 事务延迟（`health_last_duration_ms` 的可观测去重样本及完整性标志，
     仅 0x02 tag；`Δ(health_ok+health_failed)`=0 不重复计样、>1 置
     `duration_samples_incomplete=true` 只保留 latest，不得称完整分布）、断流分布；
     health-baseline 与历史 60s/300s soak 不直接横向比较（新链路含 0x02 事务，基线
     口径不同）。不得用 0x7E 混合计数或全局 CIPSEND 时长冒充 0x02 专属指标。
- [ ] **Step 10.2 — 运行 RED**：`py -3.11 -m pytest .../test_transport_soak_rework.py -v`
  → 新用例 FAIL。
- [ ] **Step 10.3 — 实现**。
- [ ] **Step 10.4 — GREEN**：全量 PASS，退出码 0。

---

## Phase 5 — 跨语言黄金向量 + 全量离线验收

### Task 11：跨语言 golden + 离线验收脚本

**Files:**
- Create: `.embeddedskills/build/firmware_health_baseline_design/acceptance.py`（或等价脚本）
- Create: `.embeddedskills/build/firmware_health_baseline_design/golden_health_0x02.json`

- [ ] **Step 11.1 — 跨语言锁死**：`test_frame_parser_health.py` 与
  `test_health_frame.c` 引用同一 `golden_health_0x02.hex/json`（111B，len=0x6A，
  校验 CD）；C 断言 `encode==golden`，Python 断言 `decode(golden)==golden 字段`
  （含 `health_*` 六项）；两处同时通过才算 GREEN。
- [ ] **Step 11.2 — 全量命令（每项必须有退出码证据）**：
  1. Host C 全部 exe（`test_health_frame / test_health_stats / test_twin_control_protocol
     / test_uart_ring / test_coordinator_boundary / test_*`）退出码 0。
  2. `py -3.11 -m pytest simulation/digital_twin/tests/test_frame_parser_health.py -v` → PASS。
  3. `py -3.11 -m pytest simulation/digital_twin/tests/test_wifi_bridge_health_dispatch.py simulation/digital_twin/web_showcase/test_live_wifi_health_dispatch.py -v`
     → 全 PASS（Round 2 项 1，生产 bridge 分流回归）。
  4. `py -3.11 -m pytest .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py -v`
     → 全 PASS。
  5. Keil Rebuild → 0 Error / 0 Warning；`Program Size` 增量记录。
- [ ] **Step 11.3 — 哈希登记与产物备份（只读，授权门控前置；前置 Task 0 已备份旧本体）**：
  ```
  Get-FileHash -Algorithm SHA256 "<repo>\程序\3. 麦轮巡线小车\程序_3_构建产物\Objects\Project.axf"
  ```
  旧 AXF/HEX 本体已在 Task 0 复制到 `rollback_artifacts/preflash/`，`preflash_hashes.json`
  记录的是**备份副本**的 sha256。Rebuild 成功后将新产物复制到独立
  `rollback_artifacts/postbuild/`，生成 `postbuild_hashes.json`，记录 `fw_build_id=1`
  （不依赖 Keil 输出目录长期保存）。两 manifest 不可变更——是**可执行回滚**的依据：
  回滚 = 用 `rollback_artifacts/preflash/` 下的旧 AXF 备份本体（sha256 校验）重新烧录，
  不以被 Rebuild 覆盖的 Keil 输出目录为准。
- [ ] **Step 11.4 — 验收检查点 A**：全部命令退出码 + 日志 + 哈希三件套齐全，
  组织成给 Codex 的证据包（见 Task 12）。

### Task 12：离线验收证据包（替代“提交”）

- [ ] 在 `.embeddedskills/build/firmware_health_baseline_design/` 落盘：
  - `tdd_red_log.txt` / `tdd_green_log.txt`（各 Host C + Python 阶段）
  - `keil_rebuild_health.log`、`preflash_hashes.json`（build_artifact_backup）、
    `postbuild_hashes.json`
  - `rollback_artifacts/preflash/`（旧 AXF/HEX 备份本体）与 `rollback_artifacts/postbuild/`
  - `golden_health_0x02.hex` / `.json`（111B）
  - `old_parser_0x02_compat_gate.json`（旧 parser 兼容性 gate 证据，**执行后**产生）
  - `test_old_parser_health_compat.py`、`test_wifi_bridge_health_dispatch.py`、
    `test_live_wifi_health_dispatch.py`（兼容边界 + 生产 bridge 分流永久回归，Round 2 项 1）
  - `device_flash_hashes.json` / `rollback_artifacts/device_flash/`（**仅授权后**，见
    Task 12-A；本离线阶段不产生）
  - `acceptance_summary.md`（每项命令+退出码+结论）
  - 明确标注：**本批次只登记基线，非正式 4B-4 同步 Gate；不宣布 4B-4/项目完成**。
- [ ] 提交给 Codex 独立审核；**未通过不得进入 Phase 6 授权门控**。

---

## Phase 6 — Codex 审核门控（无代码步骤）

- [ ] Codex 审核设计/计划/证据包；如有纠偏，回到对应 Task 修复后重跑验收。
- [ ] 审核通过后，在可见窗口向用户请求烧录授权；**未获授权不执行 Phase 7**。
- [ ] **设备固件来源 gate（Round 2 项 3）**：烧录授权后、执行 Task 13 之前，先执行
      **Task 12-A**（只读，见下），不得跳过；状态非 `DEVICE_ROLLBACK_READY` 或
      `PROVEN_BY_HASH` 时禁止烧录。

---

### Task 12-A：`device_firmware_backup` / provenance（授权后、烧录前，只读，Round 2 项 3）

> 本节区分两类回滚依据（设计 §12.1/§12.2）：
> - `build_artifact_backup`（Task 0：计划前置、尚待执行，进入任何 Keil Rebuild 前必须
>   完成）：只证明构建目录旧产物 AXF/HEX，**不
>   证明 MCU 实际 Flash 与其一致**；
> - `device_firmware_backup`（本 Task）：证明/备份 MCU 实际在跑的固件来源，是
>   **设备级回滚件**。

**Files（授权后落盘）：**
- Create: `.embeddedskills/build/firmware_health_baseline_design/rollback_artifacts/device_flash/`
- Create: `.embeddedskills/build/firmware_health_baseline_design/device_flash_hashes.json`

**步骤（均需用户当次明确授权，且为只读；本离线阶段不执行）：**
1. **来源证明（二选一，首选 1a）**：
   - **1a. 只读导出应用 Flash（首选）**：ST-Link 只读读回 STM32F103C8 应用 Flash，
     保存为独立 `device_flash_<build>.bin`。命令模板（`STM32_Programmer_CLI` 只读
     `-r` 模式；实际由用户在工具内执行，代理不自动执行）：
     `STM32_Programmer_CLI -c port=SWD mode=UR -r "device_flash_<build>.bin" <addr> <len>`
     ——**地址范围必须从 Keil 工程 Target 选项 IROM1（起始地址/大小）与芯片手册
     STM32F103C8（主 Flash 64KB @ 0x08000000）双向核实后填写，禁止猜测**；执行前把
     核实来源记录到 runbook。
   - **1b. 上次烧录哈希链证明**：若存在可核实的上次烧录日志，其中记录了实际烧录产物
     的确切 SHA-256，且与 Task 0 `preflash_hashes.json` 当前备份 sha256 **一致**，
     则状态置 `PROVEN_BY_HASH`，可省去读回。
2. 对读回 `.bin` 计算 SHA-256，记录 `{name, sha256, addr_start, len_bytes,
   source_verified}` 到 `device_flash_hashes.json`。
3. **Gate**：工具链无法只读导出且无哈希链 → 状态 = **`BLOCKED_DEVICE_ROLLBACK_PROVENANCE`**，
   **不得进入烧录**；记录原因与待补齐证据，回到 Phase 6 请求处置。
4. 通过后状态 = `DEVICE_ROLLBACK_READY`（设备级 `.bin`）或 `PROVEN_BY_HASH`
   （哈希链）；进入 Task 13。

---

## Phase 7 — 授权门控执行（缺授权禁止）

> **前置 gate（Round 2 项 3）**：Task 13 烧录前必须已过 Task 12-A，状态为
> `DEVICE_ROLLBACK_READY` 或 `PROVEN_BY_HASH`；否则状态为
> `BLOCKED_DEVICE_ROLLBACK_PROVENANCE`，不得烧录。

### Task 13：ST-Link 烧录（授权后）

- [ ] 按 `postbuild_hashes.json` 的 AXF/HEX 烧录（ST-Link Utility /
  `STM32_Programmer_CLI` 命令由用户在工具内执行，代理不自动执行）。
- [ ] 烧录后**只读验证**：被动接收 `0x02` → `fw_build_id==1`、`fw_schema_version==1`、
  `reset_cause` 为 POR/上电、`motion_state==0(INIT)`、`lease_active==0`、计数≈0。
- [ ] 失败 → 回滚依据按设计 §12.3 分级（仅限已过 Task 12-A gate 的已证明来源）：
      `DEVICE_ROLLBACK_READY` → `rollback_artifacts/device_flash/` 设备级 `.bin`
      （`device_flash_hashes.json` 校验）；`PROVEN_BY_HASH` → 与上次实际烧录哈希链
      一致的 `rollback_artifacts/preflash/` 旧 AXF 备份本体（`preflash_hashes.json`
      校验），回滚后须重跑只读验证；其它状态禁止烧录、无烧录后的回滚 fallback。并记录。

### Task 14：STOPPED 健康帧验证（授权后，不 START）

- [ ] 被动捕获（`transport_soak.py --run-mode passive`）≥10s：确认 RUNNING 未发生，
  只收到 STOPPED/INIT 态 `0x02`；断言 heartbeat_age==0xFFFFFFFF、
  cipsend/telemetry 计数为 0 或仅少量；无异常 S 帧。
- [ ] 记录 `raw_health.json` 证据；退出码 0 或符合预期。

### Task 15：≤20s 架空轮心跳运行（再次授权后）

- [ ] 用户再次明确授权（架空轮、净空、在场可断电）。
- [ ] `py -3.11 transport_soak.py --run --duration 20`：
  安全握手（pre-STOP→START/RUNNING→collect→final STOPPED）+ 200ms 心跳；
  run_id 自动生成唯一值。
- [ ] 采集窗口严格排除握手期帧（Task 10 窗口规则）。
- [ ] 用 §9 判读表对断流窗口以 `snapshot_tick_ms` 模差对齐 `0x02` 计数（0x02 同链路
      可能缺帧，用恢复前后差值定位区间，不宣称逐秒连续观测），输出
  `LOCALIZED_NOT_ROOT_CAUSED — LEADING HYPOTHESIS: CIPSEND completion-response chain`
  或更高证据等级；**不宣称根因闭合**。
- [ ] 同条件复跑一次验证可重复性；结果写入 `acceptance_summary.md`。

---

## 附录 A：可执行命令速查

| 动作 | 命令 |
|---|---|
| 构建产物备份（Task 0，任何 Rebuild 前） | `New-Item -ItemType Directory -Force "<repo>\.embeddedskills\build\firmware_health_baseline_design\rollback_artifacts\preflash"`；`Copy-Item "<repo>\程序\3. 麦轮巡线小车\程序_3_构建产物\Objects\Project.axf"`（及 `.hex` 若有）至该目录；`Get-FileHash -Algorithm SHA256` 对备份副本生成 `preflash_hashes.json` |
| Host C 构建+运行 | `bash .embeddedskills/build/v1_task4b4_fix/build_host_c_tests.sh <exe> <test.c> <prod.c> …` 后运行 `<exe>` |
| Python 单测 | `py -3.11 -m pytest simulation/digital_twin/tests/test_frame_parser_health.py simulation/digital_twin/tests/test_old_parser_health_compat.py -v` |
| 生产 bridge 分流回归（Round 2 项 1） | `py -3.11 -m pytest simulation/digital_twin/tests/test_wifi_bridge_health_dispatch.py simulation/digital_twin/web_showcase/test_live_wifi_health_dispatch.py -v` |
| soak 回归 | `py -3.11 -m pytest .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py -v` |
| Keil Rebuild | `"F:\keil\UV4\UV4.exe" -r "<repo>\程序\3. 麦轮巡线小车\project.uvprojx" -j0` |
| 哈希 | `Get-FileHash -Algorithm SHA256 "<repo>\程序\3. 麦轮巡线小车\程序_3_构建产物\Objects\Project.axf"` |
| 设备固件读回（Task 12-A，授权后只读） | `STM32_Programmer_CLI -c port=SWD mode=UR -r "<repo>\.embeddedskills\build\firmware_health_baseline_design\rollback_artifacts\device_flash\device_flash_<build>.bin" <addr> <len>`（**地址/长度必须从 Keil IROM1 与芯片手册核实**；工具无法只读导出 → `BLOCKED_DEVICE_ROLLBACK_PROVENANCE`） |
| 授权后短测 | `py -3.11 transport_soak.py --run --duration 20`（CWD=`.embeddedskills/build/v1_task4b4`） |

## 附录 B：自审清单（交付前逐项核对）

- [ ] 设计/计划字段类型一致（`0x02` 布局两侧：payload 106 / 总长 111 / len 0x6A /
      `snapshot_tick_ms`、`uart_tx_high_water`、`health_*` 六项两侧同步、
      `HealthSnapshot` 字段名、Python dict 键）。
- [ ] 路径存在性：所有引用的源码/测试/产物路径已核实。
- [ ] Task 0 构建产物备份已过 Gate（`preflash_hashes.json` + `rollback_artifacts/preflash/`
      备份文件 sha256 与源一致）；Task 0 为计划前置、尚待执行，任何 Rebuild 前必须完成。
- [ ] 旧 parser 兼容性 gate 证据存在（`old_parser_0x02_compat_gate.json` +
      `test_old_parser_health_compat.py`，后者为**待建**项，执行前不存在）。
- [ ] 生产消费者全覆盖（Round 2 项 1）：`frame_parser.py` / `wifi_bridge.py` /
      `live_wifi_bridge.py` / `transport_soak.py` 均按 `(frame_type, payload_len)`
      分流并纳入回归。
- [ ] 设备固件来源 gate（Round 2 项 3）：Task 13 烧录前必须过 Task 12-A
      （`DEVICE_ROLLBACK_READY` / `PROVEN_BY_HASH`）；否则
      `BLOCKED_DEVICE_ROLLBACK_PROVENANCE` 禁止烧录。
- [ ] 无旧 99/94/0x5E 数值（历史变更说明除外）；无过强因果结论。
- [ ] 无越权操作：Phase 1–6 不触 MCU/串口/TCP/START/电机/读回 Flash；Phase 7 全部
      授权门控。
- [ ] 无 TODO/TBD/“适当处理”占位语。
- [ ] 未执行任何 git 写操作；验收检查点代替提交。
- [ ] 未宣布整个项目或 4B-4 完成。
