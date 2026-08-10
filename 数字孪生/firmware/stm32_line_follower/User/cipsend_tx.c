/* CIPSEND 非阻塞 TX 状态机 — Task 4B-4 fix。
 *
 * 把旧同步阻塞 CIPSEND 事务改为持久化非阻塞状态机：
 *   IDLE → SEND_CMD → WAIT_PROMPT → SEND_DATA → WAIT_SENDOK → COMPLETE
 *                                                              ↘ FAILED
 *
 * 时间由调用方以 now_ms 传入（单调毫秒，Task 4B-4 的真实时钟）。
 * 纯 C，无动态内存，ARMCC5 兼容，单消费者。
 */

#include "cipsend_tx.h"

/* now 是否已到/超过 deadline（uint32 回绕安全）。 */
#define TX_DEADLINE_REACHED(now, deadline) ((int32_t)((now) - (deadline)) >= 0)

void cipsend_tx_init(CipsendTx *tx)
{
    tx->state = CIPSEND_TX_STATE_IDLE;
    tx->priority = CIPSEND_TX_PRIORITY_DROPPABLE;
    tx->tag = CIPSEND_TX_TAG_NONE;
    tx->result = CTS_RESULT_NONE;
    tx->timeout_abort = 0U;
    tx->cmd_len = 0U;
    tx->cmd_pos = 0U;
    tx->data_len = 0U;
    tx->data_pos = 0U;
    tx->deadline_ms = 0U;
    tx->deadline_stale = 0U;
    tx->data_ready_fn = 0;
    tx->data_ready_ctx = 0;
    tx->data_ready_called = 1U;
    cts_init(&tx->cts);
}

uint8_t cipsend_tx_start(CipsendTx *tx,
                         const char *cmd, uint16_t cmd_len,
                         const uint8_t *data, uint16_t data_len,
                         uint8_t priority, uint8_t tag,
                         uint32_t now_ms)
{
    uint16_t i;
    if (tx->state != CIPSEND_TX_STATE_IDLE) return 0U;
    if (cmd_len > CIPSEND_TX_MAX_CMD) return 0U;
    if (data_len > CIPSEND_TX_MAX_DATA) return 0U;

    for (i = 0; i < cmd_len; i++) tx->cmd[i] = cmd[i];
    tx->cmd_len = cmd_len;
    tx->cmd_pos = 0U;

    for (i = 0; i < data_len; i++) tx->data[i] = data[i];
    tx->data_len = data_len;
    tx->data_pos = 0U;

    tx->priority = priority;
    tx->tag = tag;
    tx->result = CTS_RESULT_NONE;
    tx->timeout_abort = 0U;
    tx->deadline_stale = 0U;
    tx->state = CIPSEND_TX_STATE_SEND_CMD;
    /* 初始截止锚定在 now_ms：即使 sink 一直拒绝（TX ring 满），事务也会
       在 SEND_CMD 超时失败，而不是永远卡死（now_ms 是真实输入，用于 C4100）。 */
    tx->deadline_ms = now_ms + CIPSEND_TX_PROMPT_TIMEOUT_MS;

    cts_init(&tx->cts);
    cts_start(&tx->cts);
    tx->data_ready_fn = 0;
    tx->data_ready_ctx = 0;
    tx->data_ready_called = 1U;
    return 1U;
}

uint8_t cipsend_tx_start_late_data(
    CipsendTx *tx, const char *cmd, uint16_t cmd_len, uint16_t data_len,
    uint8_t priority, uint8_t tag, uint32_t now_ms,
    CipsendTxDataReadyFn data_ready_fn, void *data_ready_ctx)
{
    uint16_t i;
    if (tx->state != CIPSEND_TX_STATE_IDLE || data_ready_fn == 0) return 0U;
    if (cmd_len > CIPSEND_TX_MAX_CMD || data_len > CIPSEND_TX_MAX_DATA) {
        return 0U;
    }

    for (i = 0U; i < cmd_len; i++) tx->cmd[i] = cmd[i];
    tx->cmd_len = cmd_len;
    tx->cmd_pos = 0U;
    tx->data_len = data_len;
    tx->data_pos = 0U;
    tx->priority = priority;
    tx->tag = tag;
    tx->result = CTS_RESULT_NONE;
    tx->timeout_abort = 0U;
    tx->deadline_stale = 0U;
    tx->state = CIPSEND_TX_STATE_SEND_CMD;
    tx->deadline_ms = now_ms + CIPSEND_TX_PROMPT_TIMEOUT_MS;
    tx->data_ready_fn = data_ready_fn;
    tx->data_ready_ctx = data_ready_ctx;
    tx->data_ready_called = 0U;

    cts_init(&tx->cts);
    cts_start(&tx->cts);
    return 1U;
}

uint8_t cipsend_tx_busy(const CipsendTx *tx)
{
    return (tx->state != CIPSEND_TX_STATE_IDLE &&
            tx->state != CIPSEND_TX_STATE_COMPLETE &&
            tx->state != CIPSEND_TX_STATE_FAILED) ? 1U : 0U;
}

void cipsend_tx_feed_byte(CipsendTx *tx, uint8_t byte)
{
    uint8_t r;
    switch (tx->state) {
        case CIPSEND_TX_STATE_SEND_CMD:
        case CIPSEND_TX_STATE_WAIT_PROMPT:
            r = cts_feed(&tx->cts, byte);
            if (r == CTS_RESULT_PROMPT) {
                tx->state = CIPSEND_TX_STATE_SEND_DATA;
                tx->data_pos = 0U;
                /* Deadline was set for WAIT_PROMPT; SEND_DATA needs its
                   own independent window.  tick() will refresh it. */
                tx->deadline_stale = 1U;
            } else if (r == CTS_RESULT_ERROR) {
                tx->state = CIPSEND_TX_STATE_FAILED;
                tx->result = CTS_RESULT_ERROR;
            } else if (r == CTS_RESULT_CLOSED) {
                tx->state = CIPSEND_TX_STATE_FAILED;
                tx->result = CTS_RESULT_CLOSED;
            }
            break;
        case CIPSEND_TX_STATE_SEND_DATA:
        case CIPSEND_TX_STATE_WAIT_SENDOK:
            r = cts_feed(&tx->cts, byte);
            if (r == CTS_RESULT_OK) {
                tx->state = CIPSEND_TX_STATE_COMPLETE;
                tx->result = CTS_RESULT_OK;
            } else if (r == CTS_RESULT_ERROR) {
                tx->state = CIPSEND_TX_STATE_FAILED;
                tx->result = CTS_RESULT_ERROR;
            } else if (r == CTS_RESULT_CLOSED) {
                tx->state = CIPSEND_TX_STATE_FAILED;
                tx->result = CTS_RESULT_CLOSED;
            }
            break;
        default:
            break;
    }
}

uint8_t cipsend_tx_send_pending(CipsendTx *tx,
                                CipsendTxByteSink sink, void *sink_ctx)
{
    if (tx->state == CIPSEND_TX_STATE_SEND_CMD) {
        while (tx->cmd_pos < tx->cmd_len) {
            if (!sink(sink_ctx, (uint8_t)tx->cmd[tx->cmd_pos])) {
                return 0U;   /* 暂不能发送，下轮重试 */
            }
            tx->cmd_pos++;
        }
        tx->state = CIPSEND_TX_STATE_WAIT_PROMPT;
        return 1U;
    }
    if (tx->state == CIPSEND_TX_STATE_SEND_DATA) {
        while (tx->data_pos < tx->data_len) {
            if (!sink(sink_ctx, tx->data[tx->data_pos])) {
                return 0U;
            }
            tx->data_pos++;
        }
        tx->state = CIPSEND_TX_STATE_WAIT_SENDOK;
        return 1U;
    }
    return 1U;
}

void cipsend_tx_tick(CipsendTx *tx, uint32_t now_ms,
                     CipsendTxByteSink sink, void *sink_ctx)
{
    if (tx->state == CIPSEND_TX_STATE_IDLE ||
        tx->state == CIPSEND_TX_STATE_COMPLETE ||
        tx->state == CIPSEND_TX_STATE_FAILED) {
        return;
    }

    if (tx->state == CIPSEND_TX_STATE_SEND_CMD) {
        /* 卡在 SEND_CMD（sink 持续拒绝）也受初始截止约束。 */
        if (TX_DEADLINE_REACHED(now_ms, tx->deadline_ms)) {
            tx->state = CIPSEND_TX_STATE_FAILED;
            tx->result = CTS_RESULT_NONE;   /* 无终端行 */
            tx->timeout_abort = 1U;
            return;
        }
        if (cipsend_tx_send_pending(tx, sink, sink_ctx)) {
            /* 命令发送完成 → 开始等 '>' */
            tx->deadline_ms = now_ms + CIPSEND_TX_PROMPT_TIMEOUT_MS;
        }
        return;
    }

    if (tx->state == CIPSEND_TX_STATE_SEND_DATA) {
        /* When we just entered SEND_DATA from WAIT_PROMPT (deadline_stale),
           refresh the deadline so SEND_DATA has its own independent window.
           Without this, a '>' arriving at the very end of the WAIT_PROMPT
           window would cause SEND_DATA to time out on the very next tick. */
        if (tx->deadline_stale) {
            tx->deadline_ms = now_ms + CIPSEND_TX_PROMPT_TIMEOUT_MS;
            tx->deadline_stale = 0U;
        }
        if (!tx->data_ready_called) {
            uint16_t reserved_len = tx->data_len;
            uint16_t filled_len = reserved_len;
            tx->data_ready_called = 1U;
            if (tx->data_ready_fn == 0
                || !tx->data_ready_fn(tx->data, &filled_len,
                                      CIPSEND_TX_MAX_DATA, now_ms,
                                      tx->data_ready_ctx)
                || filled_len != reserved_len) {
                tx->state = CIPSEND_TX_STATE_FAILED;
                tx->result = CTS_RESULT_NONE;
                /* The callback rejected payload materialization; no prompt
                   or SEND OK timeout occurred. */
                tx->timeout_abort = 0U;
                return;
            }
        }
        /* 卡在 SEND_DATA（sink 持续拒绝）同样受截止约束。 */
        if (TX_DEADLINE_REACHED(now_ms, tx->deadline_ms)) {
            tx->state = CIPSEND_TX_STATE_FAILED;
            tx->result = CTS_RESULT_NONE;
            tx->timeout_abort = 1U;
            return;
        }
        if (cipsend_tx_send_pending(tx, sink, sink_ctx)) {
            tx->deadline_ms = now_ms + CIPSEND_TX_SENDOK_TIMEOUT_MS;
        }
        return;
    }

    /* WAIT_PROMPT / WAIT_SENDOK：检查超时 */
    if (TX_DEADLINE_REACHED(now_ms, tx->deadline_ms)) {
        tx->state = CIPSEND_TX_STATE_FAILED;
        tx->result = CTS_RESULT_NONE;   /* 无终端行 */
        tx->timeout_abort = 1U;
    }
}

uint8_t cipsend_tx_is_terminal(const CipsendTx *tx)
{
    return (tx->state == CIPSEND_TX_STATE_COMPLETE ||
            tx->state == CIPSEND_TX_STATE_FAILED) ? 1U : 0U;
}

uint8_t cipsend_tx_result(const CipsendTx *tx)
{
    if (!cipsend_tx_is_terminal(tx)) return CTS_RESULT_NONE;
    return tx->result;
}

uint8_t cipsend_tx_tag(const CipsendTx *tx)
{
    return tx->tag;
}

uint8_t cipsend_tx_timeout_aborted(const CipsendTx *tx)
{
    return tx->timeout_abort;
}

void cipsend_tx_reset(CipsendTx *tx)
{
    cipsend_tx_init(tx);
}
