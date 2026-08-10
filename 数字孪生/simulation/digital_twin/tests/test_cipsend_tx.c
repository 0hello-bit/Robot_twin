/* Host C tests for the non-blocking CIPSEND TX state machine (Task 4B-4 fix).
 *
 * Requirements covered (Task 4B-4 fix group A):
 *   a) SEND OK / ERROR / busy / CLOSED completion semantics preserved.
 *   b) Non-blocking: tick() only sends pending bytes and checks timeouts,
 *      never blocks; payload sent via sink callback.
 *   c) Strict serial: one transaction at a time; no new transaction before
 *      terminal state is reset.
 *   d) Fragmented '>' and SEND OK.
 *   e) Timeout (now_ms advanced past deadline) → FAILED, timeout_abort=1.
 *   f) Consecutive transactions each wait their own SEND OK.
 *   g) Priority/tag tracked for caller retry/queue decisions.
 *   h) UART mixed +IPD bytes do not corrupt the prompt/SEND OK scan.
 *   i) Sink rejection (TX ring full) defers sending to next tick.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cipsend_tx.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

/* ── Test sink: records bytes into a global buffer ──────────────────── */
static char   g_tx_out[512];
static uint16_t g_tx_out_len;
static uint8_t  g_sink_accept = 1U;
static uint8_t  g_data_ready_calls;
static uint32_t g_data_ready_tick;

static uint8_t test_sink(void *ctx, uint8_t byte)
{
    (void)ctx;
    if (!g_sink_accept) return 0U;
    if (g_tx_out_len < sizeof(g_tx_out)) {
        g_tx_out[g_tx_out_len++] = (char)byte;
        return 1U;
    }
    return 0U;
}

static void feed_str(CipsendTx *tx, const char *s)
{
    for (; *s; ++s) cipsend_tx_feed_byte(tx, (uint8_t)*s);
}

static uint8_t fill_late_payload(uint8_t *data, uint16_t *data_len,
                                 uint16_t capacity, uint32_t now_ms,
                                 void *ctx)
{
    static const uint8_t payload[] = "late";
    (void)ctx;
    g_data_ready_calls++;
    g_data_ready_tick = now_ms;
    if (capacity < (uint16_t)(sizeof(payload) - 1U)) return 0U;
    memcpy(data, payload, sizeof(payload) - 1U);
    *data_len = (uint16_t)(sizeof(payload) - 1U);
    return 1U;
}

static uint8_t reject_late_payload(uint8_t *data, uint16_t *data_len,
                                   uint16_t capacity, uint32_t now_ms,
                                   void *ctx)
{
    (void)data;
    (void)data_len;
    (void)capacity;
    (void)now_ms;
    (void)ctx;
    g_data_ready_calls++;
    return 0U;
}

/* ===================================================================
 * SUCCESS FLOW
 * =================================================================== */

static int test_full_success(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_DROPPABLE,
                           CIPSEND_TX_TAG_TELEMETRY, 1000U));
    CHECK(cipsend_tx_busy(&tx));

    /* tick sends AT+CIPSEND command → WAIT_PROMPT */
    cipsend_tx_tick(&tx, 1000U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_PROMPT);
    CHECK(g_tx_out_len == (uint16_t)strlen(cmd));
    CHECK(memcmp(g_tx_out, cmd, strlen(cmd)) == 0);

    /* '>' prompt → SEND_DATA */
    feed_str(&tx, ">");
    CHECK(tx.state == CIPSEND_TX_STATE_SEND_DATA);

    /* tick sends payload → WAIT_SENDOK */
    cipsend_tx_tick(&tx, 1001U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_SENDOK);
    CHECK(g_tx_out_len == (uint16_t)(strlen(cmd) + 5U));
    CHECK(memcmp(g_tx_out + strlen(cmd), data, 5U) == 0);

    /* SEND OK → COMPLETE */
    feed_str(&tx, "\r\nSEND OK\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_OK);
    CHECK(!cipsend_tx_busy(&tx));

    /* reset allows next transaction */
    cipsend_tx_reset(&tx);
    CHECK(tx.state == CIPSEND_TX_STATE_IDLE);
    return 0;
}

static int test_late_payload_callback_runs_after_prompt(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,4\r\n";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    g_data_ready_calls = 0U;
    g_data_ready_tick = 0U;
    CHECK(cipsend_tx_start_late_data(
        &tx, cmd, (uint16_t)strlen(cmd), 4U,
        CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_DIAG, 1000U,
        fill_late_payload, NULL));

    cipsend_tx_tick(&tx, 1000U, test_sink, NULL);
    CHECK(g_data_ready_calls == 0U);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1042U, test_sink, NULL);

    CHECK(g_data_ready_calls == 1U);
    CHECK(g_data_ready_tick == 1042U);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_SENDOK);
    CHECK(g_tx_out_len == (uint16_t)(strlen(cmd) + 4U));
    CHECK(memcmp(g_tx_out + strlen(cmd), "late", 4U) == 0);
    return 0;
}

static int test_late_payload_callback_failure_is_not_timeout(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,4\r\n";

    cipsend_tx_init(&tx);
    g_data_ready_calls = 0U;
    CHECK(cipsend_tx_start_late_data(
        &tx, cmd, (uint16_t)strlen(cmd), 4U,
        CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_DIAG, 1000U,
        reject_late_payload, NULL));
    cipsend_tx_tick(&tx, 1000U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1001U, test_sink, NULL);

    CHECK(g_data_ready_calls == 1U);
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_timeout_aborted(&tx) == 0U);
    return 0;
}

static int test_fragmented_prompt(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,29\r\n";
    uint8_t d = 0xAA;
    uint8_t i;

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), &d, 1U,
                           CIPSEND_TX_PRIORITY_CRITICAL,
                           CIPSEND_TX_TAG_ACK, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_PROMPT);

    /* prompt bytes one at a time */
    for (i = 0; i < 20U; i++) {
        cipsend_tx_feed_byte(&tx, (uint8_t)('a' + i));   /* noise */
    }
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_PROMPT);
    cipsend_tx_feed_byte(&tx, '>');
    CHECK(tx.state == CIPSEND_TX_STATE_SEND_DATA);
    return 0;
}

static int test_fragmented_send_ok(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";
    const char ok[] = "\r\nSEND OK\r\n";
    uint16_t i;

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_DROPPABLE,
                           CIPSEND_TX_TAG_TELEMETRY, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_SENDOK);

    /* SEND OK one byte at a time — 除末尾 '\n' 外的所有字节都不应触发终态 */
    for (i = 0; i < (uint16_t)strlen(ok) - 1U; i++) {
        cipsend_tx_feed_byte(&tx, (uint8_t)ok[i]);
        CHECK(!cipsend_tx_is_terminal(&tx));
    }
    /* 末尾 '\n' 完成 "SEND OK" 行 → terminal */
    cipsend_tx_feed_byte(&tx, (uint8_t)ok[strlen(ok) - 1U]);
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_OK);
    return 0;
}

/* ===================================================================
 * ERROR / BUSY / CLOSED
 * =================================================================== */

static int test_error_response(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_STATUS, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1U, test_sink, NULL);
    feed_str(&tx, "\r\nERROR\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_ERROR);
    CHECK(cipsend_tx_timeout_aborted(&tx) == 0U);
    return 0;
}

static int test_busy_response(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1U, test_sink, NULL);
    feed_str(&tx, "\r\nbusy s...\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_ERROR);
    return 0;
}

static int test_closed_response(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1U, test_sink, NULL);
    feed_str(&tx, "\r\n0,CLOSED\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_CLOSED);
    return 0;
}

/* ===================================================================
 * TIMEOUT
 * =================================================================== */

static int test_prompt_timeout(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 1000U));
    cipsend_tx_tick(&tx, 1000U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_PROMPT);

    /* no prompt; advance past deadline (200ms) */
    cipsend_tx_tick(&tx, 1000U + CIPSEND_TX_PROMPT_TIMEOUT_MS + 1U, test_sink, NULL);
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_NONE);
    CHECK(cipsend_tx_timeout_aborted(&tx) == 1U);
    return 0;
}

static int test_sendok_timeout(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_STATUS, 1000U));
    cipsend_tx_tick(&tx, 1000U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1000U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_SENDOK);

    /* no SEND OK; advance past deadline (500ms) */
    cipsend_tx_tick(&tx, 1000U + CIPSEND_TX_SENDOK_TIMEOUT_MS + 1U, test_sink, NULL);
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_timeout_aborted(&tx) == 1U);
    return 0;
}

/* ===================================================================
 * STRICT SERIAL / OVERLAP FORBIDDEN
 * =================================================================== */

static int test_overlap_forbidden(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_DROPPABLE, CIPSEND_TX_TAG_TELEMETRY, 0U));
    /* second start while busy must fail */
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 0U) == 0U);
    /* even after terminal, must reset before next start */
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1U, test_sink, NULL);
    feed_str(&tx, "\r\nSEND OK\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 1U) == 0U);
    cipsend_tx_reset(&tx);
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 1U) == 1U);
    return 0;
}

static int test_consecutive_transactions(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t d1[] = "aaaaa";
    const uint8_t d2[] = "bbbbb";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;

    /* Transaction 1: success */
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), d1, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1U, test_sink, NULL);
    feed_str(&tx, "\r\nSEND OK\r\n");
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_OK);
    CHECK(cipsend_tx_tag(&tx) == CIPSEND_TX_TAG_ACK);
    cipsend_tx_reset(&tx);

    /* Transaction 2: success, must wait its own SEND OK */
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), d2, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_STATUS, 10U));
    cipsend_tx_tick(&tx, 10U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 11U, test_sink, NULL);
    CHECK(!cipsend_tx_is_terminal(&tx));
    feed_str(&tx, "\r\nSEND OK\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_OK);
    return 0;
}

/* ===================================================================
 * PRIORITY / TAG TRACKING
 * =================================================================== */

static int test_priority_tag_tracked(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 0U));
    CHECK(tx.priority == CIPSEND_TX_PRIORITY_CRITICAL);
    CHECK(tx.tag == CIPSEND_TX_TAG_ACK);
    return 0;
}

/* ===================================================================
 * MIXED +IPD ROUTING (bytes routed to transport do not corrupt scan)
 * =================================================================== */

static int test_mixed_ipd_does_not_corrupt_scan(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,29\r\n";
    uint8_t data[29];
    uint16_t i;

    for (i = 0; i < 29U; i++) data[i] = (uint8_t)(0xAA + i);

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 29U,
                           CIPSEND_TX_PRIORITY_DROPPABLE, CIPSEND_TX_TAG_TELEMETRY, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);

    /* +IPD preamble + binary payload interleaved before the prompt */
    feed_str(&tx, "+IPD,0,5:HELLO");
    cipsend_tx_feed_byte(&tx, '>');
    CHECK(tx.state == CIPSEND_TX_STATE_SEND_DATA);
    cipsend_tx_tick(&tx, 1U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_SENDOK);

    /* SEND OK with +IPD noise lines interleaved */
    feed_str(&tx, "Recv 29 bytes\r\n");
    CHECK(!cipsend_tx_is_terminal(&tx));
    feed_str(&tx, "+IPD,0,3:ABC\r\n");
    CHECK(!cipsend_tx_is_terminal(&tx));
    feed_str(&tx, "SEND OK\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_OK);
    return 0;
}

/* ===================================================================
 * SINK REJECTION (TX ring full) → defer to next tick
 * =================================================================== */

static int test_sink_rejection_defers_send(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_STATUS, 0U));

    /* sink rejects first byte → still SEND_CMD, nothing consumed */
    g_sink_accept = 0U;
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_SEND_CMD);
    CHECK(g_tx_out_len == 0U);

    /* sink accepts → command sent */
    g_sink_accept = 1U;
    cipsend_tx_tick(&tx, 1U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_PROMPT);
    CHECK(g_tx_out_len == (uint16_t)strlen(cmd));
    return 0;
}

/* ===================================================================
 * START-TIME DEADLINE (C4100 remediation: now_ms is a real input)
 *
 * The transaction must be bounded even before any byte is sent: if the
 * sink never accepts a byte (TX ring permanently full), the transaction
 * must time out instead of stalling in SEND_CMD forever.  The initial
 * deadline is anchored at cipsend_tx_start() using now_ms.
 * =================================================================== */

static int test_start_sets_initial_deadline(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 1000U));
    /* now_ms must anchor the initial SEND_CMD deadline. */
    CHECK(tx.deadline_ms == 1000U + CIPSEND_TX_PROMPT_TIMEOUT_MS);
    return 0;
}

static int test_start_stall_timeout(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    g_sink_accept = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 0U));
    /* Sink rejects every byte: without an initial deadline the transaction
       would stay in SEND_CMD forever.  It must time out (no terminal line). */
    cipsend_tx_tick(&tx, CIPSEND_TX_PROMPT_TIMEOUT_MS + 1U, test_sink, NULL);
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_NONE);
    CHECK(cipsend_tx_timeout_aborted(&tx) == 1U);
    return 0;
}

/* ===================================================================
 * TELEMETRY BATCH CAPACITY
 * =================================================================== */

static int test_accepts_eight_telemetry_frames(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,248\r\n";
    uint8_t data[248];
    uint16_t i;

    for (i = 0U; i < (uint16_t)sizeof(data); i++) {
        data[i] = (uint8_t)(i ^ 0x5AU);
    }

    cipsend_tx_init(&tx);
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data,
                           (uint16_t)sizeof(data),
                           CIPSEND_TX_PRIORITY_DROPPABLE,
                           CIPSEND_TX_TAG_TELEMETRY, 0U));
    CHECK(tx.data_len == (uint16_t)sizeof(data));
    CHECK(tx.data[0] == data[0]);
    CHECK(tx.data[247] == data[247]);
    return 0;
}

static int test_rejects_payload_above_new_bound(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,249\r\n";
    uint8_t data[249];

    memset(data, 0xA5, sizeof(data));
    cipsend_tx_init(&tx);
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data,
                           (uint16_t)sizeof(data),
                           CIPSEND_TX_PRIORITY_DROPPABLE,
                           CIPSEND_TX_TAG_TELEMETRY, 0U) == 0U);
    return 0;
}

/* ===================================================================
 * INIT / RESET
 * =================================================================== */

static int test_init_resets(void)
{
    CipsendTx tx;
    cipsend_tx_init(&tx);
    CHECK(tx.state == CIPSEND_TX_STATE_IDLE);
    CHECK(tx.tag == CIPSEND_TX_TAG_NONE);
    CHECK(tx.result == CTS_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * TEST RUNNER
 * =================================================================== */

static int run_all_tests(void)
{
    if (test_full_success()) return 1;
    if (test_late_payload_callback_runs_after_prompt()) return 1;
    if (test_late_payload_callback_failure_is_not_timeout()) return 1;
    if (test_fragmented_prompt()) return 1;
    if (test_fragmented_send_ok()) return 1;
    if (test_error_response()) return 1;
    if (test_busy_response()) return 1;
    if (test_closed_response()) return 1;
    if (test_prompt_timeout()) return 1;
    if (test_sendok_timeout()) return 1;
    if (test_overlap_forbidden()) return 1;
    if (test_consecutive_transactions()) return 1;
    if (test_priority_tag_tracked()) return 1;
    if (test_mixed_ipd_does_not_corrupt_scan()) return 1;
    if (test_sink_rejection_defers_send()) return 1;
    if (test_start_sets_initial_deadline()) return 1;
    if (test_start_stall_timeout()) return 1;
    if (test_accepts_eight_telemetry_frames()) return 1;
    if (test_rejects_payload_above_new_bound()) return 1;
    if (test_init_resets()) return 1;

    puts("PASS test_cipsend_tx");
    return 0;
}

int main(void)
{
    return run_all_tests();
}
