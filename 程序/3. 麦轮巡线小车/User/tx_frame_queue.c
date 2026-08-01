/* 发送队列纯逻辑：连接代次隔离 + ACK/STATUS 重试缓冲（Task 4B-4 fix，
 * Codex review remediation）。纯 C、无动态内存、ARMCC5 兼容、单消费者。
 */

#include "tx_frame_queue.h"
#include <string.h>

static void drop_all(TxFrameQueue *q)
{
    q->ack_len = 0U;
    q->status_len = 0U;
    q->ack[0] = '\0';
    q->status[0] = '\0';
}

static void retain(char *dst, uint16_t *dst_len,
                   const char *src, uint16_t len)
{
    uint16_t copy_len = len;
    if (copy_len > TX_FRAME_QUEUE_LINE_MAX) copy_len = TX_FRAME_QUEUE_LINE_MAX;
    if (copy_len > 0U && src != 0) memcpy(dst, src, copy_len);
    dst[copy_len] = '\0';
    *dst_len = copy_len;
}

void txfq_init(TxFrameQueue *q)
{
    q->ack_len = 0U;
    q->status_len = 0U;
    q->generation = 0U;
    q->generation_valid = 0U;
    q->ack[0] = '\0';
    q->status[0] = '\0';
}

uint8_t txfq_check_generation(TxFrameQueue *q, uint32_t generation)
{
    if (q->generation_valid && q->generation != generation) {
        drop_all(q);
        q->generation = generation;
        return 1U;
    }
    q->generation = generation;
    q->generation_valid = 1U;
    return 0U;
}

void txfq_on_tx_result(TxFrameQueue *q, uint8_t result, uint8_t tag)
{
    if (result == CTS_RESULT_OK) {
        if (tag == CIPSEND_TX_TAG_ACK) {
            txfq_clear_ack(q);
        } else if (tag == CIPSEND_TX_TAG_STATUS) {
            txfq_clear_status(q);
        }
        /* telemetry/diag 在 start 时已消费（latest-wins / 一次性）。 */
    } else if (result == CTS_RESULT_CLOSED) {
        /* 连接已断：保留帧对下一连接无效，全部丢弃。 */
        drop_all(q);
    }
    /* ERROR / busy / 超时（CTS_RESULT_ERROR / CTS_RESULT_NONE）：
       在同一连接代次内保留重试。 */
}

void txfq_retain_ack(TxFrameQueue *q, const char *buf, uint16_t len)
{
    retain(q->ack, &q->ack_len, buf, len);
}

void txfq_retain_status(TxFrameQueue *q, const char *buf, uint16_t len)
{
    retain(q->status, &q->status_len, buf, len);
}

void txfq_clear_ack(TxFrameQueue *q)
{
    q->ack_len = 0U;
    q->ack[0] = '\0';
}

void txfq_clear_status(TxFrameQueue *q)
{
    q->status_len = 0U;
    q->status[0] = '\0';
}

uint8_t txfq_has_ack(const TxFrameQueue *q)
{
    return (q->ack_len > 0U) ? 1U : 0U;
}

uint8_t txfq_has_status(const TxFrameQueue *q)
{
    return (q->status_len > 0U) ? 1U : 0U;
}

uint8_t txfq_has_retry(const TxFrameQueue *q)
{
    return (txfq_has_ack(q) || txfq_has_status(q)) ? 1U : 0U;
}

const char *txfq_ack_ptr(const TxFrameQueue *q)
{
    return q->ack;
}

uint16_t txfq_ack_len(const TxFrameQueue *q)
{
    return q->ack_len;
}

const char *txfq_status_ptr(const TxFrameQueue *q)
{
    return q->status;
}

uint16_t txfq_status_len(const TxFrameQueue *q)
{
    return q->status_len;
}
