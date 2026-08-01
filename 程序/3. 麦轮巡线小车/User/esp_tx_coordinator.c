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
              uint8_t *tele_pending,
              EspTxCoordinatorDiscardFn discard_fn, void *discard_ctx)
{
    c->cipsend_tx      = tx;
    c->tx_frame_queue  = q;
    c->tele_pending    = tele_pending;
    c->epoch           = 0U;
    c->epoch_valid     = 0U;
    c->discard_tx_ring = discard_fn;
    c->discard_ctx     = discard_ctx;
    c->boundary_events = 0U;
    c->cipsend_aborts  = 0U;
    c->tx_bytes_discarded = 0U;
}

/* Internal: perform the coordinated abort across all TX resources.
 * Does NOT update epoch — caller decides whether epoch changed. */
static void do_abort(EspTxCoordinator *c)
{
    /* 1. Abort the in-flight CipsendTx.  Any bytes it pushed to the
       TX ring on previous ticks are handled by the discard below. */
    if (c->cipsend_tx != 0) {
        cipsend_tx_reset(c->cipsend_tx);
        c->cipsend_aborts++;
    }

    /* 2. Discard all pending bytes from the TX ring (TXE disabled,
       ring drained, TXE stays disabled). */
    if (c->discard_tx_ring != 0) {
        c->tx_bytes_discarded += c->discard_tx_ring(c->discard_ctx);
    }

    /* 3. Clear the telemetry latest-wins slot — old frame not valid
       for the new client. */
    if (c->tele_pending != 0) {
        *c->tele_pending = 0U;
    }

    c->boundary_events++;
}

uint8_t etc_check_boundary(EspTxCoordinator *c, uint32_t current_generation)
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

    do_abort(c);
    return 1U;
}

uint16_t etc_force_abort(EspTxCoordinator *c)
{
    uint32_t prior = c->tx_bytes_discarded;
    do_abort(c);
    return (uint16_t)(c->tx_bytes_discarded - prior);
}

void etc_handle_terminal(EspTxCoordinator *c)
{
    uint8_t result;
    if (!cipsend_tx_is_terminal(c->cipsend_tx)) return;
    result = cipsend_tx_result(c->cipsend_tx);
    txfq_on_tx_result(c->tx_frame_queue, result,
                      cipsend_tx_tag(c->cipsend_tx));
    if (result == CTS_RESULT_CLOSED) {
        (void)etc_force_abort(c);
    } else {
        cipsend_tx_reset(c->cipsend_tx);
    }
}
