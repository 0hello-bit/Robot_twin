#ifndef HEALTH_STATS_H
#define HEALTH_STATS_H

#include <stdint.h>
#include "health_frame.h"

/* ── 0x02 健康统计（firmware health baseline）───────────────────────────
 *
 * 纯 C，无硬件依赖，时间由调用方以 now_ms 传入（可 Host 测试）。
 * 主循环计时 + 事务/遥测/重试计数 + 0x02 快照构建。
 *
 * 0x02 专属归属（Round 2 项 2）：0x02 走独立 CIPSEND_TX_TAG_DIAG_HEALTH(=5U)，
 * 由 health_* 六项专门归属；TAG_DIAG(=4U) 仅维护 diag_health_started，二者不混计。
 */
#define CIPSEND_TX_TAG_DIAG_HEALTH 5U

/* 计数全部为 u32 内部态；0x02 帧内为 u16/u32，模 2^w 回绕或饱和见
   hstats_fill_health（设计 §5.2 总则）。 */
typedef struct {
    uint32_t loop_seq;
    uint32_t loop_last_gap_ms;          /* 饱和 0xFFFF */
    uint32_t loop_max_gap_ms;           /* 饱和 0xFFFF；峰值不清零 */
    uint32_t cipsend_started, cipsend_completed;
    uint32_t cipsend_ok, cipsend_error, cipsend_prompt_timeout,
             cipsend_sendok_timeout, cipsend_closed;
    uint32_t cipsend_last_duration_ms;  /* mod 2^32；无完成事务=0 */
    uint32_t cipsend_max_duration_ms;   /* 饱和 0xFFFFFFFF */
    uint32_t ack_started, status_started, telemetry_started, diag_health_started;
    uint32_t status_retry, ack_retry, boundary_aborts;
    uint32_t telemetry_generated, telemetry_overwritten,
             telemetry_tx_started, telemetry_tx_ok, telemetry_tx_failed;
    /* Round 2 项 2：0x02 专属（CIPSEND_TX_TAG_DIAG_HEALTH=5U），不含 0x7E。 */
    uint32_t health_generated, health_dropped, health_started,
             health_ok, health_failed;
    uint16_t health_last_duration_ms;   /* 饱和；最近一笔 0x02 事务时长 */
    uint32_t health_start_ms;           /* 当前在途 0x02 事务开始时刻 */
    /* 内部：通用 CIPSEND 事务开始时刻 + 上一轮主循环顶部时刻 */
    uint32_t cipsend_start_ms;
    uint32_t last_loop_ms;
    uint8_t  loop_baseline_ready;       /* P0-2：首次 tick 已建立时间基线 */
    uint8_t  health_due;                /* 1 = 有待发（延迟未发送）健康帧（发送仲裁） */
} HealthStats;

void hstats_init(HealthStats *s);
void hstats_loop_tick(HealthStats *s, uint32_t now_ms);   /* seq/gap/max */
void hstats_tx_started(HealthStats *s, uint8_t tag, uint32_t now_ms);
void hstats_tx_terminal(HealthStats *s, uint8_t tag, uint8_t result,
                        uint8_t timeout_aborted, uint8_t entered_send_data,
                        uint32_t now_ms);
/* entered_send_data=1 表示终态时已进入 SEND_DATA/WaitSENDOK，用于区分
   prompt_timeout(0) 与 sendok_timeout(1)，规则见设计 §4.3。 */
void hstats_health_generated(HealthStats *s);            /* health_emit 每 1Hz +1 */
void hstats_health_dropped(HealthStats *s);              /* 放弃发送 +1（start 失败/顶替/代次放弃） */
/* ── 发送仲裁（CURRENT_STATUS 下一步：健康帧不被遥测饿死）──────────────
   纯逻辑、可 Host 测。ACK/STATUS 最高优先级；0x02 健康帧在 TX 忙或有 A/S
   重试时延迟（不丢），由调用方在 TX 空闲时 flush；遥测让行。
   计数恒等式扩展：generated == dropped + started + due（due∈{0,1}）。 */
uint8_t hstats_health_due(const HealthStats *s);         /* 是否有待发（延迟）健康帧 */
uint8_t hstats_health_gate_defer(HealthStats *s, uint8_t tx_busy, uint8_t retry_pending);
uint8_t hstats_health_can_flush(const HealthStats *s, uint8_t tx_busy, uint8_t retry_pending);
void hstats_health_consume_due(HealthStats *s);          /* 调用方已发送待发帧 → 清 due */
void hstats_health_epoch_changed(HealthStats *s);        /* 连接代次变化 → 放弃待发帧 */
void hstats_telemetry_generated(HealthStats *s);
void hstats_telemetry_overwritten(HealthStats *s);
void hstats_status_retry(HealthStats *s);
void hstats_ack_retry(HealthStats *s);
void hstats_boundary_abort(HealthStats *s);
/* P0-3：连接边界中止对真正在途（busy，非 IDLE/非终态）事务的按 tag 诚实结算。
   health(TAG_DIAG_HEALTH)→health_failed++（并更新 health_last_duration_ms =
   now_ms - start）；telemetry(TAG_TELEMETRY)→telemetry_tx_failed++。只应在
   coordinator do_abort 的 cipsend_tx_reset 前对 busy 事务调用；不冒充
   ESP ERROR / SEND OK 超时，不触碰 cipsend_completed 的终态分类。 */
void hstats_tx_boundary_abort(HealthStats *s, uint8_t tag, uint32_t now_ms);
void hstats_fill_health(const HealthStats *s, uint32_t now_ms, HealthSnapshot *snap);
/* now_ms 同时写入 snap->snapshot_tick_ms（采集时刻 mono tick，设计 §5.2/§5.3）。
   hstats_fill_health 把 health_* 映射进 snap；health_last_duration_ms 饱和写 u16。 */

#endif /* HEALTH_STATS_H */
