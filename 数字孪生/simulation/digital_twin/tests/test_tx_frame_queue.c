/* Host C tests for the connection-generation send queue (Task 4B-4 fix,
 * Codex review remediation — Gap 2: 旧 critical 帧可能发给新客户端).
 *
 * Requirements covered:
 *   a) Retained ACK/STATUS survive within the SAME connection generation
 *      (retry after ERROR/busy/timeout is still allowed).
 *   b) A generation change (new CONNECT — same ID reconnect OR different ID
 *      new client) drops ALL retained ACK/STATUS.
 *   c) A CLOSED terminal TX result drops all retained frames (connection
 *      gone; retry would leak to the next client).
 *   d) A successful OK clears only the matching buffer (A/S ordering).
 *   e) Timeout (CTS_RESULT_NONE) keeps the frame for in-generation retry.
 */

#include <stdio.h>
#include <string.h>

#include "tx_frame_queue.h"
#include "cipsend_transaction.h"
#include "cipsend_tx.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static const char ACK_TEXT[] = "A,camp-a,1,APPLIED,APPLIED,3F\n";
static const char STATUS_TEXT[] = "S,camp-a,run-1,STOPPED,TIMEOUT,0,AA\n";

/* ===================================================================
 * RETAIN / ACCESSORS
 * =================================================================== */

static int test_retain_and_access(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    CHECK(!txfq_has_ack(&q));
    CHECK(!txfq_has_status(&q));
    CHECK(!txfq_has_retry(&q));

    txfq_retain_ack(&q, ACK_TEXT, (uint16_t)strlen(ACK_TEXT));
    txfq_retain_status(&q, STATUS_TEXT, (uint16_t)strlen(STATUS_TEXT));

    CHECK(txfq_has_ack(&q));
    CHECK(txfq_has_status(&q));
    CHECK(txfq_has_retry(&q));
    CHECK(txfq_ack_len(&q) == (uint16_t)strlen(ACK_TEXT));
    CHECK(txfq_status_len(&q) == (uint16_t)strlen(STATUS_TEXT));
    CHECK(memcmp(txfq_ack_ptr(&q), ACK_TEXT, strlen(ACK_TEXT)) == 0);
    CHECK(memcmp(txfq_status_ptr(&q), STATUS_TEXT, strlen(STATUS_TEXT)) == 0);
    return 0;
}

/* ===================================================================
 * SAME GENERATION: frames survive (in-generation retry allowed)
 * =================================================================== */

static int test_same_generation_keeps_frames(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    txfq_retain_ack(&q, ACK_TEXT, (uint16_t)strlen(ACK_TEXT));
    txfq_retain_status(&q, STATUS_TEXT, (uint16_t)strlen(STATUS_TEXT));

    CHECK(txfq_check_generation(&q, 5U) == 0U);
    CHECK(txfq_has_ack(&q));
    CHECK(txfq_has_status(&q));

    /* 同一代次多次调用：不丢。 */
    CHECK(txfq_check_generation(&q, 5U) == 0U);
    CHECK(txfq_has_retry(&q));
    return 0;
}

/* ===================================================================
 * GENERATION CHANGE: drop all retained critical frames
 * =================================================================== */

static int test_generation_change_drops_frames(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    txfq_retain_ack(&q, ACK_TEXT, (uint16_t)strlen(ACK_TEXT));
    txfq_retain_status(&q, STATUS_TEXT, (uint16_t)strlen(STATUS_TEXT));

    CHECK(txfq_check_generation(&q, 5U) == 0U);
    CHECK(txfq_has_retry(&q));

    /* 新 CONNECT → 代次改变 → 全部丢弃。 */
    CHECK(txfq_check_generation(&q, 6U) == 1U);
    CHECK(!txfq_has_ack(&q));
    CHECK(!txfq_has_status(&q));
    CHECK(!txfq_has_retry(&q));
    return 0;
}

/* ===================================================================
 * SAME-ID RECONNECT vs DIFFERENT-ID NEW CONNECTION
 * =================================================================== */

static int test_same_id_reconnect_drops(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    txfq_retain_ack(&q, ACK_TEXT, (uint16_t)strlen(ACK_TEXT));

    CHECK(txfq_check_generation(&q, 1U) == 0U);   /* 旧 client 0 */
    CHECK(txfq_has_ack(&q));
    /* 同一 client id 重新连接：代次仍从 1 → 2。 */
    CHECK(txfq_check_generation(&q, 2U) == 1U);
    CHECK(!txfq_has_ack(&q));
    return 0;
}

static int test_different_id_new_connection_drops(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    txfq_retain_ack(&q, ACK_TEXT, (uint16_t)strlen(ACK_TEXT));
    txfq_retain_status(&q, STATUS_TEXT, (uint16_t)strlen(STATUS_TEXT));

    CHECK(txfq_check_generation(&q, 1U) == 0U);
    CHECK(txfq_has_retry(&q));
    /* 不同 id 的新客户端：代次改变 → 丢弃。 */
    CHECK(txfq_check_generation(&q, 2U) == 1U);
    CHECK(!txfq_has_retry(&q));
    return 0;
}

/* ===================================================================
 * TX TERMINAL RESULTS
 * =================================================================== */

static int test_closed_result_drops_all(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    txfq_retain_ack(&q, ACK_TEXT, (uint16_t)strlen(ACK_TEXT));
    txfq_retain_status(&q, STATUS_TEXT, (uint16_t)strlen(STATUS_TEXT));

    /* 事务内收到 0,CLOSED → 终态 CLOSED → 全部丢弃（连接已断）。 */
    txfq_on_tx_result(&q, CTS_RESULT_CLOSED, CIPSEND_TX_TAG_ACK);
    CHECK(!txfq_has_ack(&q));
    CHECK(!txfq_has_status(&q));
    CHECK(!txfq_has_retry(&q));
    return 0;
}

static int test_ok_clears_matching_only(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    txfq_retain_ack(&q, ACK_TEXT, (uint16_t)strlen(ACK_TEXT));
    txfq_retain_status(&q, STATUS_TEXT, (uint16_t)strlen(STATUS_TEXT));

    /* ACK 发送成功 → 只清 ACK，STATUS 保留（A/S 顺序不破坏）。 */
    txfq_on_tx_result(&q, CTS_RESULT_OK, CIPSEND_TX_TAG_ACK);
    CHECK(!txfq_has_ack(&q));
    CHECK(txfq_has_status(&q));
    return 0;
}

static int test_error_keeps_frames(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    txfq_retain_ack(&q, ACK_TEXT, (uint16_t)strlen(ACK_TEXT));

    /* ERROR/busy：同一代次内保留重试。 */
    txfq_on_tx_result(&q, CTS_RESULT_ERROR, CIPSEND_TX_TAG_ACK);
    CHECK(txfq_has_ack(&q));
    return 0;
}

static int test_timeout_keeps_frames(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    txfq_retain_status(&q, STATUS_TEXT, (uint16_t)strlen(STATUS_TEXT));

    /* 超时（无终端行，CTS_RESULT_NONE）：保留重试。 */
    txfq_on_tx_result(&q, CTS_RESULT_NONE, CIPSEND_TX_TAG_STATUS);
    CHECK(txfq_has_status(&q));
    return 0;
}

/* ===================================================================
 * CLEAR
 * =================================================================== */

static int test_clear_ack_keeps_status(void)
{
    TxFrameQueue q;
    txfq_init(&q);
    txfq_retain_ack(&q, ACK_TEXT, (uint16_t)strlen(ACK_TEXT));
    txfq_retain_status(&q, STATUS_TEXT, (uint16_t)strlen(STATUS_TEXT));

    txfq_clear_ack(&q);
    CHECK(!txfq_has_ack(&q));
    CHECK(txfq_has_status(&q));
    txfq_clear_status(&q);
    CHECK(!txfq_has_status(&q));
    return 0;
}

/* ===================================================================
 * TEST RUNNER
 * =================================================================== */

static int run_all_tests(void)
{
    if (test_retain_and_access()) return 1;
    if (test_same_generation_keeps_frames()) return 1;
    if (test_generation_change_drops_frames()) return 1;
    if (test_same_id_reconnect_drops()) return 1;
    if (test_different_id_new_connection_drops()) return 1;
    if (test_closed_result_drops_all()) return 1;
    if (test_ok_clears_matching_only()) return 1;
    if (test_error_keeps_frames()) return 1;
    if (test_timeout_keeps_frames()) return 1;
    if (test_clear_ack_keeps_status()) return 1;

    puts("PASS test_tx_frame_queue");
    return 0;
}

int main(void)
{
    return run_all_tests();
}
