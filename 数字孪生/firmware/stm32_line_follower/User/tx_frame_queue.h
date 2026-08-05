#ifndef TX_FRAME_QUEUE_H
#define TX_FRAME_QUEUE_H

#include <stdint.h>
#include "twin_control_protocol.h"
#include "cipsend_transaction.h"
#include "cipsend_tx.h"

/* ── Task 4B-4 fix (Codex review remediation): 连接代次隔离 ─────────────
 *
 * Critical 帧（ACK/STATUS）的可靠性只在一个连接代次内保证。跨连接必须：
 *   - 丢弃旧 ACK/STATUS（不得发给新客户端）；
 *   - 终止旧 in-flight TX、清理不再有效的 TX 字节；
 *   - 由协议层为新连接生成 authoritative status。
 *
 * 本模块是发送队列的纯逻辑部分（可 Host C 测试，不依赖 static main.c
 * 变量）：持有 ACK/STATUS 重试缓冲 + 它们所属的连接代次。
 *
 * 连接代次由调用方在每个主循环从传输层读取
 * `esp_transport_connection_generation()` 并传给 `txfq_check_generation()`。
 * 代次改变 → 旧缓冲全部丢弃（连接边界）。
 */

#define TX_FRAME_QUEUE_LINE_MAX  TWIN_CONTROL_LINE_MAX

typedef struct {
    char     ack[TX_FRAME_QUEUE_LINE_MAX + 1U];
    uint16_t ack_len;
    char     status[TX_FRAME_QUEUE_LINE_MAX + 1U];
    uint16_t status_len;
    uint32_t generation;        /* 当前连接代次                             */
    uint8_t  generation_valid;  /* 代次是否已初始化                          */
} TxFrameQueue;

/* 初始化（清空所有缓冲、代次无效）。开机调用一次。 */
void txfq_init(TxFrameQueue *q);

/* 每次主循环调用，传入传输层当前连接代次。
 * 若代次相比上次改变（新客户端 CONNECT），丢弃所有保留的 ACK/STATUS，
 * 返回 1（调用方可顺带清理遥测 latest-wins 槽）；同代次返回 0。 */
uint8_t txfq_check_generation(TxFrameQueue *q, uint32_t generation);

/* 处理一次 TX 事务终态：
 *   - CTS_RESULT_OK：清对应的重试缓冲（ACK 或 STATUS）。
 *   - CTS_RESULT_CLOSED：丢弃所有保留帧（连接已断，重试无意义且会泄漏
 *     到下一连接）。
 *   - ERROR / busy / 超时（CTS_RESULT_ERROR / CTS_RESULT_NONE）：保留，
 *     在同一连接代次内重试。 */
void txfq_on_tx_result(TxFrameQueue *q, uint8_t result, uint8_t tag);

/* 从传输层取到新帧后 retain（拷贝）进队列。 */
void txfq_retain_ack(TxFrameQueue *q, const char *buf, uint16_t len);
void txfq_retain_status(TxFrameQueue *q, const char *buf, uint16_t len);

/* 发送成功后清对应缓冲。 */
void txfq_clear_ack(TxFrameQueue *q);
void txfq_clear_status(TxFrameQueue *q);

uint8_t txfq_has_ack(const TxFrameQueue *q);
uint8_t txfq_has_status(const TxFrameQueue *q);
uint8_t txfq_has_retry(const TxFrameQueue *q);

const char *txfq_ack_ptr(const TxFrameQueue *q);
uint16_t    txfq_ack_len(const TxFrameQueue *q);
const char *txfq_status_ptr(const TxFrameQueue *q);
uint16_t    txfq_status_len(const TxFrameQueue *q);

#endif /* TX_FRAME_QUEUE_H */
