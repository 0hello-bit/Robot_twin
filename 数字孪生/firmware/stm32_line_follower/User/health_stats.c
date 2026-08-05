#include "health_stats.h"
#include "cipsend_transaction.h"
#include "cipsend_tx.h"
#include "mono_time_core.h"

/* 饱和到 u16 的峰值/间隔字段。 */
static uint16_t sat_u16(uint32_t value)
{
    return (value > 0xFFFFU) ? 0xFFFFU : (uint16_t)value;
}

/* 模 2^16 的累积计数。 */
static uint16_t mod_u16(uint32_t value)
{
    return (uint16_t)(value & 0xFFFFU);
}

void hstats_init(HealthStats *s)
{
    uint32_t i;
    /* Zero all fields (portable, no memset dependency concerns). */
    {
        uint8_t *p = (uint8_t *)s;
        for (i = 0; i < sizeof(HealthStats); i++) p[i] = 0U;
    }
}

void hstats_loop_tick(HealthStats *s, uint32_t now_ms)
{
    uint32_t gap;
    s->loop_seq++;
    if (!s->loop_baseline_ready) {
        /* P0-2：首次 tick 仅建立时间基线。mono 时钟在 ESP_Setup 前启动，
           第一个主循环 tick 可能已距启动过去数秒；若此时计算 gap 会把
           启动耗时记成永久 loop_max_gap_ms，使断流诊断永远假阳性。
           seq 按设计计 1；gap/max 保持 0。 */
        s->loop_baseline_ready = 1U;
        s->last_loop_ms = now_ms;
        s->loop_last_gap_ms = 0U;
        s->loop_max_gap_ms = 0U;
        return;
    }
    gap = mono_elapsed_ms(s->last_loop_ms, now_ms);
    s->last_loop_ms = now_ms;
    s->loop_last_gap_ms = sat_u16(gap);
    if (gap > s->loop_max_gap_ms) {
        s->loop_max_gap_ms = sat_u16(gap);
    }
}

void hstats_tx_started(HealthStats *s, uint8_t tag, uint32_t now_ms)
{
    s->cipsend_started++;
    s->cipsend_start_ms = now_ms;
    switch (tag) {
        case CIPSEND_TX_TAG_ACK:
            s->ack_started++;
            break;
        case CIPSEND_TX_TAG_STATUS:
            s->status_started++;
            break;
        case CIPSEND_TX_TAG_TELEMETRY:
            s->telemetry_started++;
            s->telemetry_tx_started++;
            break;
        case CIPSEND_TX_TAG_DIAG:
            s->diag_health_started++;
            break;
        case CIPSEND_TX_TAG_DIAG_HEALTH:
            s->health_started++;
            s->health_start_ms = now_ms;
            break;
        default:
            break;
    }
}

void hstats_tx_terminal(HealthStats *s, uint8_t tag, uint8_t result,
                        uint8_t timeout_aborted, uint8_t entered_send_data,
                        uint32_t now_ms)
{
    uint32_t duration;

    s->cipsend_completed++;
    if (result == CTS_RESULT_OK) {
        s->cipsend_ok++;
    } else if (result == CTS_RESULT_ERROR) {
        s->cipsend_error++;
    } else if (result == CTS_RESULT_CLOSED) {
        s->cipsend_closed++;
    } else if (result == CTS_RESULT_NONE && timeout_aborted) {
        if (entered_send_data) {
            s->cipsend_sendok_timeout++;
        } else {
            s->cipsend_prompt_timeout++;
        }
    }

    duration = mono_elapsed_ms(s->cipsend_start_ms, now_ms);
    s->cipsend_last_duration_ms = duration;
    if (duration > s->cipsend_max_duration_ms) {
        s->cipsend_max_duration_ms = duration;
    }

    if (tag == CIPSEND_TX_TAG_TELEMETRY) {
        if (result == CTS_RESULT_OK) {
            s->telemetry_tx_ok++;
        } else {
            s->telemetry_tx_failed++;
        }
    } else if (tag == CIPSEND_TX_TAG_DIAG_HEALTH) {
        if (result == CTS_RESULT_OK) {
            s->health_ok++;
        } else {
            s->health_failed++;
        }
        s->health_last_duration_ms = sat_u16(duration);
    }
}

void hstats_health_generated(HealthStats *s)
{
    s->health_generated++;
}

void hstats_health_dropped(HealthStats *s)
{
    s->health_dropped++;
}

/* ── 发送仲裁（CURRENT_STATUS 下一步：健康帧不被遥测饿死）────────────── */

uint8_t hstats_health_due(const HealthStats *s)
{
    return s->health_due;
}

uint8_t hstats_health_gate_defer(HealthStats *s, uint8_t tx_busy, uint8_t retry_pending)
{
    if (tx_busy || retry_pending) {
        /* TX 忙或有 A/S 重试 → 延迟本帧（不丢）。若此前已有待发帧，旧帧被
           新帧顶替（latest-wins，与遥测一致）：dropped++。 */
        if (s->health_due) {
            s->health_dropped++;
        }
        s->health_due = 1U;
        return 0U;                     /* 延迟 */
    }
    /* TX 空闲且无 A/S 重试 → 立即发送。防御性处理遗留 due（正常 flush 会先清）。 */
    if (s->health_due) {
        s->health_dropped++;
    }
    s->health_due = 0U;
    return 1U;                         /* 立即发送 */
}

uint8_t hstats_health_can_flush(const HealthStats *s, uint8_t tx_busy, uint8_t retry_pending)
{
    return (s->health_due && !tx_busy && !retry_pending) ? 1U : 0U;
}

void hstats_health_consume_due(HealthStats *s)
{
    s->health_due = 0U;
}

void hstats_health_epoch_changed(HealthStats *s)
{
    if (s->health_due) {
        s->health_dropped++;           /* 旧代次待发帧不得泄漏给新客户端 */
        s->health_due = 0U;
    }
}

void hstats_telemetry_generated(HealthStats *s)
{
    s->telemetry_generated++;
}

void hstats_telemetry_overwritten(HealthStats *s)
{
    s->telemetry_overwritten++;
}

void hstats_status_retry(HealthStats *s)
{
    s->status_retry++;
}

void hstats_ack_retry(HealthStats *s)
{
    s->ack_retry++;
}

void hstats_boundary_abort(HealthStats *s)
{
    s->boundary_aborts++;
}

void hstats_tx_boundary_abort(HealthStats *s, uint8_t tag, uint32_t now_ms)
{
    uint32_t duration;
    if (tag == CIPSEND_TX_TAG_TELEMETRY) {
        s->telemetry_tx_failed++;
    } else if (tag == CIPSEND_TX_TAG_DIAG_HEALTH) {
        s->health_failed++;
        /* 时长由调用方显式传 now_ms 计算，不猜测。 */
        duration = mono_elapsed_ms(s->health_start_ms, now_ms);
        s->health_last_duration_ms = sat_u16(duration);
    }
}

void hstats_fill_health(const HealthStats *s, uint32_t now_ms, HealthSnapshot *snap)
{
    snap->snapshot_tick_ms     = now_ms;
    snap->loop_seq             = s->loop_seq;
    snap->loop_last_gap_ms     = sat_u16(s->loop_last_gap_ms);
    snap->loop_max_gap_ms      = sat_u16(s->loop_max_gap_ms);
    snap->telemetry_generated  = mod_u16(s->telemetry_generated);
    snap->telemetry_overwritten = mod_u16(s->telemetry_overwritten);
    snap->telemetry_tx_started = mod_u16(s->telemetry_tx_started);
    snap->telemetry_tx_ok      = mod_u16(s->telemetry_tx_ok);
    snap->telemetry_tx_failed  = mod_u16(s->telemetry_tx_failed);
    snap->cipsend_started      = mod_u16(s->cipsend_started);
    snap->cipsend_completed    = mod_u16(s->cipsend_completed);
    snap->cipsend_ok           = mod_u16(s->cipsend_ok);
    snap->cipsend_error        = mod_u16(s->cipsend_error);
    snap->cipsend_prompt_timeout = mod_u16(s->cipsend_prompt_timeout);
    snap->cipsend_sendok_timeout = mod_u16(s->cipsend_sendok_timeout);
    snap->cipsend_closed       = mod_u16(s->cipsend_closed);
    snap->cipsend_last_duration_ms = s->cipsend_last_duration_ms;
    snap->cipsend_max_duration_ms  = s->cipsend_max_duration_ms;
    snap->ack_started          = mod_u16(s->ack_started);
    snap->status_started       = mod_u16(s->status_started);
    snap->telemetry_started    = mod_u16(s->telemetry_started);
    snap->diag_health_started  = mod_u16(s->diag_health_started);
    snap->status_retry         = mod_u16(s->status_retry);
    snap->ack_retry            = mod_u16(s->ack_retry);
    snap->boundary_aborts      = mod_u16(s->boundary_aborts);
    snap->health_generated     = mod_u16(s->health_generated);
    snap->health_dropped       = mod_u16(s->health_dropped);
    snap->health_started       = mod_u16(s->health_started);
    snap->health_ok            = mod_u16(s->health_ok);
    snap->health_failed        = mod_u16(s->health_failed);
    snap->health_last_duration_ms = s->health_last_duration_ms;
}
