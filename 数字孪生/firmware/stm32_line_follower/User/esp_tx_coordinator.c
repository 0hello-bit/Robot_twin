/* TX connection-boundary coordinator — Task 4B-4 final fix.
 *
 * Single authority for all connection-boundary abort decisions.  Ensures
 * that when a new TCP client connects (generation change), no byte from
 * the old epoch reaches the ESP UART.
 *
 * Pure logic, Host-testable.  ARMCC5, no dynamic memory. */

#include "esp_tx_coordinator.h"

void etc_init(EspTxCoordinator *c,
              CipsendTx *tx, TxFrameQueue *q,
              uint8_t *tele_pending, HealthStats *health_stats,
              EspTxCoordinatorDiscardFn discard_fn, void *discard_ctx)
{
    c->cipsend_tx      = tx;
    c->tx_frame_queue  = q;
    c->tele_pending    = tele_pending;
    c->health_stats    = health_stats;
    c->epoch           = 0U;
    c->epoch_valid     = 0U;
    c->discard_tx_ring = discard_fn;
    c->discard_ctx     = discard_ctx;
    c->clear_telemetry = 0;
    c->clear_telemetry_ctx = 0;
    c->boundary_events = 0U;
    c->cipsend_aborts  = 0U;
    c->tx_bytes_discarded = 0U;
}

void etc_set_telemetry_clear(EspTxCoordinator *c,
                             EspTxCoordinatorClearTelemetryFn clear_fn,
                             void *clear_ctx)
{
    c->clear_telemetry = clear_fn;
    c->clear_telemetry_ctx = clear_ctx;
}

uint8_t etc_telemetry_blocked(uint8_t retry_pending,
                              uint8_t pending_ack,
                              uint8_t pending_status)
{
    return (retry_pending || pending_ack || pending_status) ? 1U : 0U;
}

uint8_t etc_telemetry_dispatch_allowed(uint8_t control_cycle_ready,
                                        uint8_t retry_pending,
                                        uint8_t pending_ack,
                                        uint8_t pending_status,
                                        uint8_t protocol_status_pending)
{
    if (!control_cycle_ready) return 0U;
    if (etc_telemetry_blocked(retry_pending, pending_ack, pending_status)) {
        return 0U;
    }
    return protocol_status_pending ? 0U : 1U;
}

/* Internal: perform the coordinated abort across all TX resources.
 * Does NOT update epoch — caller decides whether epoch changed.
 * now_ms is the monotonic tick at the abort, used for the honest duration
 * of an aborted in-flight health transaction (never guessed). */
static void do_abort(EspTxCoordinator *c, uint32_t now_ms)
{
    /* 1. P0-3: before resetting, settle any truly in-flight (busy,
       non-IDLE/non-terminal) transaction by tag.  health→health_failed++,
       telemetry→telemetry_tx_failed++.  This restores the accounting
       identity started == ok + failed + in_flight.  The terminal CLOSED
       path (etc_handle_terminal) already settled failed via
       hstats_tx_terminal; there cipsend_tx_busy()==0, so no double-count. */
    if (c->cipsend_tx != 0 && cipsend_tx_busy(c->cipsend_tx)) {
        if (c->health_stats != 0) {
            hstats_tx_boundary_abort(c->health_stats,
                                     cipsend_tx_tag(c->cipsend_tx), now_ms);
        }
    }

    /* 2. Abort the in-flight CipsendTx.  Any bytes it pushed to the
       TX ring on previous ticks are handled by the discard below. */
    if (c->cipsend_tx != 0) {
        cipsend_tx_reset(c->cipsend_tx);
        c->cipsend_aborts++;
    }

    /* 3. Discard all pending bytes from the TX ring (TXE disabled,
       ring drained, TXE stays disabled). */
    if (c->discard_tx_ring != 0) {
        c->tx_bytes_discarded += c->discard_tx_ring(c->discard_ctx);
    }

    /* 4. Clear the telemetry latest-wins slot — old frame not valid
       for the new client. */
    if (c->clear_telemetry != 0) {
        c->clear_telemetry(c->clear_telemetry_ctx);
    } else if (c->tele_pending != 0) {
        *c->tele_pending = 0U;
    }

    c->boundary_events++;
    /* P0-3: 让全局 boundary_aborts 诚实反映每一次边界中止（0x02 快照字段由
       hstats_fill_health 从 health_stats 读取，main.c 不再用 coordinator 覆盖）。 */
    if (c->health_stats != 0) {
        hstats_boundary_abort(c->health_stats);
    }
}

uint8_t etc_check_boundary(EspTxCoordinator *c, uint32_t current_generation,
                           uint32_t now_ms)
{
    /* First call: establish baseline epoch, no boundary. */
    if (!c->epoch_valid) {
        c->epoch = current_generation;
        c->epoch_valid = 1U;
        /* Also propagate the initial generation into txfq so retained
           frames from a prior boot (none) are dropped. */
        if (c->tx_frame_queue != 0) {
            (void)txfq_check_generation(c->tx_frame_queue, current_generation);
        }
        return 0U;
    }

    /* Same generation: nothing to do. */
    if (c->epoch == current_generation) {
        return 0U;
    }

    /* Generation changed → connection boundary.  Abort everything. */
    c->epoch = current_generation;

    /* Drop retained ACK/STATUS from the old generation. */
    if (c->tx_frame_queue != 0) {
        (void)txfq_check_generation(c->tx_frame_queue, current_generation);
    }

    do_abort(c, now_ms);
    return 1U;
}

uint16_t etc_force_abort(EspTxCoordinator *c, uint32_t now_ms)
{
    uint32_t prior = c->tx_bytes_discarded;
    do_abort(c, now_ms);
    return (uint16_t)(c->tx_bytes_discarded - prior);
}

void etc_handle_terminal(EspTxCoordinator *c, uint32_t now_ms)
{
    uint8_t result;
    uint8_t tag;
    uint8_t timeout_aborted;
    uint8_t entered_send_data;
    if (!cipsend_tx_is_terminal(c->cipsend_tx)) return;
    result = cipsend_tx_result(c->cipsend_tx);
    tag = cipsend_tx_tag(c->cipsend_tx);
    timeout_aborted = cipsend_tx_timeout_aborted(c->cipsend_tx);
    /* entered_send_data：终态时事务是否已进入 SEND_DATA/WaitSENDOK（设计
       §4.3 区分 prompt_timeout / sendok_timeout）。CipsendTx 在超时时已将
       state 转 FAILED，因此用内部 cts 子状态的最后阶段推导（2 = WAIT_SEND_OK，
       即已收到 '>' 进入 SEND_DATA 之后）；WAIT_PROMPT 超时 cts 仍为 1。 */
    entered_send_data = (cts_state(&c->cipsend_tx->cts) == 2U) ? 1U : 0U;
    if (c->health_stats != 0) {
        hstats_tx_terminal(c->health_stats, tag, result,
                           timeout_aborted, entered_send_data, now_ms);
    }
    txfq_on_tx_result(c->tx_frame_queue, result, tag);
    if (result == CTS_RESULT_CLOSED) {
        (void)etc_force_abort(c, now_ms);
    } else {
        cipsend_tx_reset(c->cipsend_tx);
    }
}
