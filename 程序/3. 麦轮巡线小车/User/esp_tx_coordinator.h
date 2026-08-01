#ifndef ESP_TX_COORDINATOR_H
#define ESP_TX_COORDINATOR_H

#include <stdint.h>
#include "cipsend_tx.h"
#include "tx_frame_queue.h"

/* ── Task 4B-4 final fix: TX connection-boundary coordinator ────────────
 *
 * Single authority for all connection-boundary abort decisions.  Ensures
 * that when a new TCP client connects (generation change), no byte from
 * the old epoch reaches the ESP UART.
 *
 * The coordinator is pure logic (Host-testable).  The TX-hardware path is
 * abstracted behind the discard callback, which the firmware implements by
 * disabling TXE, draining the UART TX ring, and leaving TXE disabled.
 *
 * Properties: ARMCC5, no dynamic memory, single call site in main loop. */

/* Callback: discard all pending bytes from the TX hardware path.
 * Returns the number of bytes discarded.
 * Firmware implementation:
 *   1. USART_ITConfig(USART1, USART_IT_TXE, DISABLE)
 *   2. while (uart_ring_pop(&g_uart_tx_ring, &dummy)) count++
 *   3. return count
 * (TXE stays disabled; uart_tx_sink re-enables on next push.) */
typedef uint16_t (*EspTxCoordinatorDiscardFn)(void *ctx);

/* ── Coordinator state ───────────────────────────────────────────────── */
typedef struct {
    /* References to external modules (set at init, never changed). */
    CipsendTx    *cipsend_tx;       /* in-flight CIPSEND TX state machine    */
    TxFrameQueue *tx_frame_queue;   /* ACK/STATUS logical retry queue        */
    uint8_t      *tele_pending;     /* pointer to s_tele_pending in main.c   */

    /* Epoch tracking. */
    uint32_t      epoch;            /* last seen connection generation        */
    uint8_t       epoch_valid;      /* 1 after first check_boundary call      */

    /* TX-ring discard callback (hardware abstraction). */
    EspTxCoordinatorDiscardFn discard_tx_ring;
    void        *discard_ctx;

    /* Observable counters (for tests and production telemetry). */
    uint32_t      boundary_events;  /* total connection-boundary detections   */
    uint32_t      cipsend_aborts;   /* CipsendTx force-abort count            */
    uint32_t      tx_bytes_discarded; /* total bytes dropped from TX ring     */
} EspTxCoordinator;

/* ── API ─────────────────────────────────────────────────────────────── */

/* Initialise the coordinator.  Call once after all referenced modules
 * have been initialised, before the main loop.
 *
 * Parameters:
 *   c             - coordinator state (caller-allocated)
 *   tx            - the CipsendTx used by main.c (non-null)
 *   q             - the TxFrameQueue used by main.c (non-null)
 *   tele_pending  - pointer to main.c's s_tele_pending (non-null)
 *   discard_fn    - callback that discards and returns count of TX-ring
 *                   bytes; NULL = no hardware TX path (test-only)
 *   discard_ctx   - opaque context for discard_fn */
void etc_init(EspTxCoordinator *c,
              CipsendTx *tx, TxFrameQueue *q,
              uint8_t *tele_pending,
              EspTxCoordinatorDiscardFn discard_fn, void *discard_ctx);

/* Check the connection boundary.  Call ONCE per main-loop iteration,
 * AFTER draining the RX ring (which may have processed CONNECT/CLOSED
 * bytes) but BEFORE calling cipsend_tx_tick() (which may push new bytes
 * to the TX ring).
 *
 * When a boundary is detected (current_generation != epoch):
 *   1. Abort the old CipsendTx (force-reset to IDLE).
 *   2. Drop all retained ACK/STATUS via txfq_check_generation().
 *   3. Clear the telemetry latest-wins slot.
 *   4. Discard all pending bytes from the TX ring via the callback.
 *
 * Returns 1 if a boundary was detected and abort was performed, 0
 * otherwise.  On first call (epoch_valid == 0), establishes the baseline
 * epoch and returns 0. */
uint8_t etc_check_boundary(EspTxCoordinator *c, uint32_t current_generation);

/* Force an abort independent of generation change (e.g. after detecting
 * a CLOSED during TX service that the boundary check missed because no
 * new CONNECT has arrived yet).  Resets CipsendTx, drops txfq frames,
 * clears tele_pending, discards TX ring.  Does NOT change epoch.
 *
 * Returns the number of bytes discarded from the TX ring. */
uint16_t etc_force_abort(EspTxCoordinator *c);

/* Handle the terminal result of the in-flight CipsendTx through the
 * coordinator's unified boundary logic.  Called from ESP_ServiceTX in
 * main.c and from Host C tests via the same production code path.
 *
 * Logic (identical to original ESP_TX_HandleTerminal in main.c):
 *   1. If CipsendTx is not terminal, return immediately.
 *   2. Call txfq_on_tx_result() with the result and tag.
 *   3. If result == CTS_RESULT_CLOSED: etc_force_abort() (resets CipsendTx,
 *      drops txfq frames, clears tele_pending, discards TX ring).
 *   4. Otherwise: cipsend_tx_reset() (return to IDLE for next transaction).
 *
 * Does NOT change epoch (generation does not increment on CLOSED).
 * Host-testable: uses only injected struct pointers, no static globals. */
void etc_handle_terminal(EspTxCoordinator *c);

#endif /* ESP_TX_COORDINATOR_H */
