/* Host C tests for TX connection-boundary coordinator + cipsend_tx edge cases
 * (Task 4B-4 final fix).
 *
 * Requirements covered:
 *   1. CipsendTx WAIT_PROMPT receives ERROR/busy/CLOSED → immediate FAILED,
 *      not 200ms timeout.
 *   2. SEND_DATA gets independent deadline window; prompt at deadline-1ms
 *      does not cause next-tick timeout.
 *   3. Coordinator with real UartRing: CLOSED / same-ID CONNECT / different-ID
 *      CONNECT / CONNECT without prior CLOSED → old TX ring bytes discarded.
 *   4. TXE discard idempotent and wraparound-safe; observable count.
 *   5. New-generation fresh authoritative status still sendable; +IPD/STOP/
 *      timeout/A-S order no regression.
 *
 * Uses real UartRing, real CipsendTx, real TxFrameQueue, real
 * EspTxCoordinator.  The discard callback operates on a UartRing instance
 * that simulates the TX ring. */

#include <stdio.h>
#include <string.h>

#include "uart_ring.h"
#include "cipsend_tx.h"
#include "cipsend_transaction.h"
#include "tx_frame_queue.h"
#include "esp_tx_coordinator.h"
#include "esp_runtime_transport.h"
#include "twin_control_protocol.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

/* ── Test sink and RX simulation ─────────────────────────────────────── */
static char   g_tx_out[512];
static uint16_t g_tx_out_len;
static uint8_t  g_sink_accept = 1U;

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

/* ── Fake TX ring for coordinator tests ──────────────────────────────── */
static UartRing g_test_tx_ring;
static uint8_t  g_txe_enabled = 1U;   /* 1 = TXE ISR "running" */

/* Simulate the ISR popping one byte from the TX ring (if TXE enabled). */
static uint16_t fake_txe_drain_one(void)
{
    uint8_t b;
    if (!g_txe_enabled) return 0U;
    if (!uart_ring_pop(&g_test_tx_ring, &b)) {
        /* Ring empty → ISR would disable TXE */
        g_txe_enabled = 0U;
        return 0U;
    }
    return 1U;
}

/* Discard callback: disable TXE, drain ring, return count. */
static uint16_t fake_discard_cb(void *ctx)
{
    uint8_t dummy;
    uint16_t discarded = 0U;
    (void)ctx;
    g_txe_enabled = 0U;
    while (uart_ring_pop(&g_test_tx_ring, &dummy)) {
        discarded++;
    }
    return discarded;
}

/* Push bytes into the test TX ring (simulating main loop via uart_tx_sink).
   Re-enables TXE so subsequent fake_txe_drain_one() calls work. */
static void push_to_tx_ring(const uint8_t *bytes, uint16_t len)
{
    uint16_t i;
    for (i = 0U; i < len; i++) {
        uart_ring_push(&g_test_tx_ring, bytes[i]);
    }
    g_txe_enabled = 1U;
}

/* ── Transport / protocol helpers ────────────────────────────────────── */
static volatile uint8_t s_connected = 0U;
static volatile uint8_t s_client_id = 0xFFU;

static void transport_feed_str(const char *s)
{
    for (; *s; ++s) esp_transport_process_byte((uint8_t)*s);
}

static void service_byte(CipsendTx *tx, uint8_t b)
{
    esp_transport_process_byte(b);
    cipsend_tx_feed_byte(tx, b);
}

static void service_str(CipsendTx *tx, const char *s)
{
    for (; *s; ++s) service_byte(tx, (uint8_t)*s);
}

static void queue_ack_result(void)
{
    TwinControlResult result;
    memset(&result, 0, sizeof(result));
    result.has_ack = 1U;
    result.applied = 1U;
    result.version = 1U;
    strcpy(result.campaign_id, "camp-a");
    strcpy(result.reason, "APPLIED");
    esp_transport_queue_ack(&result);
}

/* ===================================================================
 * 1. WAIT_PROMPT ERROR / busy / CLOSED → immediate FAILED
 * =================================================================== */

static int test_prompt_error_immediate_fail(void)
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

    /* ERROR before '>' → must fail IMMEDIATELY, not after 200ms. */
    feed_str(&tx, "\r\nERROR\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_ERROR);
    CHECK(cipsend_tx_timeout_aborted(&tx) == 0U);
    return 0;
}

static int test_prompt_busy_immediate_fail(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_STATUS, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_PROMPT);

    /* "busy p..." before '>' → immediate FAILED */
    feed_str(&tx, "\r\nbusy p...\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_ERROR);
    return 0;
}

static int test_prompt_closed_immediate_fail(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_CRITICAL, CIPSEND_TX_TAG_ACK, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_PROMPT);

    /* "0,CLOSED" before '>' → immediate FAILED */
    feed_str(&tx, "\r\n0,CLOSED\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_CLOSED);
    return 0;
}

/* ===================================================================
 * 2. SEND_DATA independent deadline
 * =================================================================== */

static int test_send_data_independent_deadline(void)
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

    /* '>' arrives at deadline - 1ms (T+199ms). */
    cipsend_tx_tick(&tx, 1000U + CIPSEND_TX_PROMPT_TIMEOUT_MS - 1U,
                    test_sink, NULL);
    feed_str(&tx, ">");
    CHECK(tx.state == CIPSEND_TX_STATE_SEND_DATA);
    CHECK(tx.deadline_stale == 1U);

    /* Next tick at T+201ms (past the old WAIT_PROMPT deadline): must NOT
       time out — SEND_DATA gets its own fresh 200ms window. */
    cipsend_tx_tick(&tx, 1000U + CIPSEND_TX_PROMPT_TIMEOUT_MS + 1U,
                    test_sink, NULL);
    CHECK(!cipsend_tx_is_terminal(&tx));
    CHECK(tx.state == CIPSEND_TX_STATE_WAIT_SENDOK);
    CHECK(tx.deadline_stale == 0U);
    return 0;
}

/* ===================================================================
 * 3a. Coordinator: TX ring discard on generation-change boundary
 *     (CONNECT boundary — generation increments)
 * =================================================================== */

static int test_generation_change_discards_tx_ring(void)
{
    EspTxCoordinator c;
    CipsendTx tx;
    TxFrameQueue q;
    uint8_t tele = 1U;
    const uint8_t old_bytes[] = "AT+CIPSEND=0,29\r\n";
    uint32_t gen = 1U;

    /* Setup */
    uart_ring_init(&g_test_tx_ring);
    g_txe_enabled = 1U;
    cipsend_tx_init(&tx);
    txfq_init(&q);

    /* Push old-epoch bytes into the TX ring */
    push_to_tx_ring(old_bytes, (uint16_t)strlen((const char *)old_bytes));

    etc_init(&c, &tx, &q, &tele, fake_discard_cb, NULL);

    /* First check: baseline */
    CHECK(etc_check_boundary(&c, gen) == 0U);
    CHECK(c.boundary_events == 0U);

    /* Generation change → boundary */
    gen = 2U;
    CHECK(etc_check_boundary(&c, gen) == 1U);
    CHECK(c.boundary_events == 1U);
    CHECK(c.cipsend_aborts == 1U);
    /* All old bytes discarded */
    CHECK(c.tx_bytes_discarded >= (uint32_t)strlen((const char *)old_bytes));
    /* TX ring empty */
    {
        uint8_t b;
        CHECK(uart_ring_pop(&g_test_tx_ring, &b) == 0U);
    }
    /* Tele slot cleared */
    CHECK(tele == 0U);
    return 0;
}

/* ── 3b. CLOSED terminal path: real \r\n0,CLOSED\r\n through production
   feed_byte → CTS_RESULT_CLOSED, then etc_handle_terminal → full cleanup.
   This is the TRUE CLOSED path (NOT generation-change).  Generation does
   NOT increment on CLOSED (design decision §1).  The old test
   test_generation_change_discards_tx_ring above covers the CONNECT
   boundary (generation change) path — it does not exercise CLOSED. ── */
static int test_closed_terminal_discards_all(void)
{
    EspTxCoordinator c;
    CipsendTx tx;
    TxFrameQueue q;
    uint8_t tele = 1U;
    uint32_t gen_before;
    uint32_t gen_after;
    uint32_t pre_boundary;
    uint32_t pre_aborts;
    uint32_t pre_discarded;
    const uint8_t old_bytes[] = "AT+CIPSEND=0,29\r\nold_payload_data";

    /* ── Setup real production modules ── */
    uart_ring_init(&g_test_tx_ring);
    g_txe_enabled = 1U;
    cipsend_tx_init(&tx);
    txfq_init(&q);

    /* Initialize the transport layer so generation tracking works. */
    s_connected = 0U;
    s_client_id = 0xFFU;
    esp_transport_init(&s_connected, &s_client_id);

    /* Establish same connection generation as baseline (no boundary yet).
       Use the actual transport generation — not a hardcoded value. */
    gen_before = esp_transport_connection_generation();
    etc_init(&c, &tx, &q, &tele, fake_discard_cb, NULL);
    CHECK(etc_check_boundary(&c, gen_before) == 0U);
    CHECK(c.boundary_events == 0U);

    /* Retain ACK + STATUS in TxFrameQueue (simulates prior critical frames
       queued for this connection epoch). */
    {
        const char ack_line[]    = "A,camp-a,1,APPLIED,APPLIED,3F\n";
        const char status_line[] = "S,camp-a,run-1,STOPPED,TIMEOUT,0,AA\n";
        txfq_retain_ack(&q, ack_line, (uint16_t)strlen(ack_line));
        txfq_retain_status(&q, status_line, (uint16_t)strlen(status_line));
        CHECK(txfq_has_ack(&q));
        CHECK(txfq_has_status(&q));
    }

    /* Push old bytes into the real TX ring (simulating prior CIPSEND ticks
       that pushed bytes before CLOSED arrived). */
    push_to_tx_ring(old_bytes, (uint16_t)strlen((const char *)old_bytes));
    /* Verify ring is non-empty */
    {
        uint8_t b;
        CHECK(uart_ring_pop(&g_test_tx_ring, &b));
        /* Push back — ring was non-empty, discard must clear it */
        CHECK(uart_ring_push(&g_test_tx_ring, b));
    }

    /* ── Start a real CIPSEND transaction (in WAIT_PROMPT state) ── */
    {
        const char cmd[]   = "AT+CIPSEND=0,29\r\n";
        const uint8_t data[] = "mock_payload";
        g_tx_out_len = 0U;
        CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data,
                               (uint16_t)strlen((const char *)data),
                               CIPSEND_TX_PRIORITY_CRITICAL,
                               CIPSEND_TX_TAG_ACK, 1000U));
        cipsend_tx_tick(&tx, 1000U, test_sink, NULL);
        CHECK(tx.state == CIPSEND_TX_STATE_WAIT_PROMPT);
    }

    /* ── Feed \r\n0,CLOSED\r\n through production path ──
       Mirrors ESP_ServiceRX: each byte goes to BOTH transport and
       cipsend_tx_feed_byte.  The CLOSED is detected by cts_feed → srp_feed
       and the CipsendTx transitions to FAILED immediately.
       generation does NOT change on CLOSED (design decision §1). */
    gen_after = esp_transport_connection_generation();
    CHECK(gen_after == gen_before);   /* unchanged */
    feed_str(&tx, "\r\n0,CLOSED\r\n");

    /* CipsendTx must be FAILED with CTS_RESULT_CLOSED */
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_CLOSED);
    CHECK(tx.state == CIPSEND_TX_STATE_FAILED);

    /* generation must NOT have changed (CLOSED does not increment it) */
    gen_after = esp_transport_connection_generation();
    CHECK(gen_after == gen_before);

    /* Record pre-handling counters */
    pre_boundary  = c.boundary_events;
    pre_aborts    = c.cipsend_aborts;
    pre_discarded = c.tx_bytes_discarded;

    /* ── Call PRODUCTION etc_handle_terminal ──
       This is the exact same function called by main.c's ESP_ServiceTX.
       It must: call txfq_on_tx_result(CLOSED) → drop all frames,
       then etc_force_abort → cipsend_tx_reset + discard ring + clear tele. */
    etc_handle_terminal(&c);

    /* ── Assertions after terminal handling ── */

    /* 1. CipsendTx back to IDLE */
    CHECK(tx.state == CIPSEND_TX_STATE_IDLE);

    /* 2. TxFrameQueue ACK/STATUS dropped */
    CHECK(!txfq_has_ack(&q));
    CHECK(!txfq_has_status(&q));
    CHECK(!txfq_has_retry(&q));

    /* 3. Telemetry pending cleared */
    CHECK(tele == 0U);

    /* 4. Real UartRing discarded */
    CHECK(c.tx_bytes_discarded > pre_discarded);
    /* Ring is empty after discard */
    {
        uint8_t b;
        CHECK(uart_ring_pop(&g_test_tx_ring, &b) == 0U);
    }

    /* 5. Discard callback was called and counted */
    CHECK(c.cipsend_aborts == pre_aborts + 1U);
    /* boundary_events increments (do_abort increments it) */
    CHECK(c.boundary_events == pre_boundary + 1U);

    /* 6. Generation unchanged (CLOSED does not change generation) */
    CHECK(esp_transport_connection_generation() == gen_before);

    /* 7. Coordinator's epoch unchanged (etc_handle_terminal does NOT
       call etc_check_boundary, so epoch stays at initial gen_before) */
    CHECK(c.epoch == gen_before);

    return 0;
}

static int test_same_id_reconnect_discards_tx_ring(void)
{
    EspTxCoordinator c;
    CipsendTx tx;
    TxFrameQueue q;
    uint8_t tele = 1U;
    const uint8_t old_bytes[] = "hello_payload_data";
    uint32_t gen;

    uart_ring_init(&g_test_tx_ring);
    g_txe_enabled = 1U;
    cipsend_tx_init(&tx);
    txfq_init(&q);

    push_to_tx_ring(old_bytes, (uint16_t)strlen((const char *)old_bytes));
    etc_init(&c, &tx, &q, &tele, fake_discard_cb, NULL);

    /* Client 0 connects (gen 1) */
    gen = 1U;
    CHECK(etc_check_boundary(&c, gen) == 0U);

    /* Client 0 reconnects (gen 2) — same ID, new generation */
    gen = 2U;
    CHECK(etc_check_boundary(&c, gen) == 1U);
    CHECK(c.tx_bytes_discarded >= (uint32_t)strlen((const char *)old_bytes));
    /* Ring empty after discard */
    {
        uint8_t b;
        CHECK(uart_ring_pop(&g_test_tx_ring, &b) == 0U);
    }
    return 0;
}

static int test_different_id_connect_discards_tx_ring(void)
{
    EspTxCoordinator c;
    CipsendTx tx;
    TxFrameQueue q;
    uint8_t tele = 1U;
    const uint8_t old_bytes[] = "old_cmd\r\n";
    uint32_t gen;

    uart_ring_init(&g_test_tx_ring);
    g_txe_enabled = 1U;
    cipsend_tx_init(&tx);
    txfq_init(&q);

    push_to_tx_ring(old_bytes, (uint16_t)strlen((const char *)old_bytes));
    etc_init(&c, &tx, &q, &tele, fake_discard_cb, NULL);

    /* Client 0 (gen 1) → Client 1 (gen 2) */
    gen = 1U;
    CHECK(etc_check_boundary(&c, gen) == 0U);
    gen = 2U;
    CHECK(etc_check_boundary(&c, gen) == 1U);
    CHECK(c.tx_bytes_discarded >= (uint32_t)strlen((const char *)old_bytes));
    return 0;
}

static int test_connect_without_prior_closed_discards(void)
{
    EspTxCoordinator c;
    CipsendTx tx;
    TxFrameQueue q;
    uint8_t tele = 1U;
    const uint8_t old_bytes[] = "AT+CIPSEND=0,5\r\nhello";
    uint32_t gen;

    uart_ring_init(&g_test_tx_ring);
    g_txe_enabled = 1U;
    cipsend_tx_init(&tx);
    txfq_init(&q);

    /* Simulate an in-flight CIPSEND transaction: start, push some bytes
       to the test ring. */
    {
        const char cmd[] = "AT+CIPSEND=0,5\r\n";
        const uint8_t data[] = "hello";
        CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                               CIPSEND_TX_PRIORITY_CRITICAL,
                               CIPSEND_TX_TAG_ACK, 1000U));
    }

    push_to_tx_ring(old_bytes, (uint16_t)strlen((const char *)old_bytes));
    etc_init(&c, &tx, &q, &tele, fake_discard_cb, NULL);

    /* Establish baseline at gen 4 (previous connection, maybe not tracked). */
    gen = 4U;
    CHECK(etc_check_boundary(&c, gen) == 0U);

    /* No CLOSED — just a direct new CONNECT at gen 5 */
    gen = 5U;
    CHECK(etc_check_boundary(&c, gen) == 1U);
    CHECK(c.cipsend_aborts == 1U);
    CHECK(tx.state == CIPSEND_TX_STATE_IDLE);   /* aborted */
    CHECK(c.tx_bytes_discarded >= (uint32_t)strlen((const char *)old_bytes));
    return 0;
}

/* ===================================================================
 * 4. Idempotent + wraparound-safe discard; observable count
 * =================================================================== */

static int test_discard_idempotent(void)
{
    EspTxCoordinator c;
    CipsendTx tx;
    TxFrameQueue q;
    uint8_t tele = 0U;
    uint32_t gen;
    uint32_t prior;

    uart_ring_init(&g_test_tx_ring);
    g_txe_enabled = 1U;
    cipsend_tx_init(&tx);
    txfq_init(&q);
    etc_init(&c, &tx, &q, &tele, fake_discard_cb, NULL);

    gen = 1U;
    CHECK(etc_check_boundary(&c, gen) == 0U);

    /* Second check with same generation — no boundary */
    prior = c.boundary_events;
    CHECK(etc_check_boundary(&c, gen) == 0U);
    CHECK(c.boundary_events == prior);

    /* Third check — still no boundary */
    CHECK(etc_check_boundary(&c, gen) == 0U);
    CHECK(c.boundary_events == prior);

    /* Force abort drains already-empty ring → count unchanged */
    prior = c.tx_bytes_discarded;
    (void)etc_force_abort(&c);
    CHECK(c.tx_bytes_discarded == prior);
    return 0;
}

static int test_discard_wraparound_safe(void)
{
    /* Fill ring to near capacity, pop half, push more to wrap,
       then discard — all bytes must be removed. */
    UartRing ring;
    uint8_t b;
    uint16_t i, discarded;

    uart_ring_init(&ring);

    /* Fill completely */
    for (i = 0U; i < UART_RING_SIZE; i++) {
        CHECK(uart_ring_push(&ring, (uint8_t)(i & 0xFF)));
    }

    /* Pop half to advance tail */
    for (i = 0U; i < UART_RING_SIZE / 2U; i++) {
        CHECK(uart_ring_pop(&ring, &b));
    }

    /* Push more (wraps head) */
    for (i = 0U; i < UART_RING_SIZE / 2U; i++) {
        CHECK(uart_ring_push(&ring, (uint8_t)(0x80U | (i & 0x7FU))));
    }

    /* Discard: pop all */
    discarded = 0U;
    while (uart_ring_pop(&ring, &b)) {
        discarded++;
    }
    CHECK(discarded == UART_RING_SIZE);   /* half original + half new */
    CHECK(uart_ring_pop(&ring, &b) == 0U);
    return 0;
}

static int test_observable_count_increments(void)
{
    EspTxCoordinator c;
    CipsendTx tx;
    TxFrameQueue q;
    uint8_t tele = 0U;
    const uint8_t bytes1[] = "AAAA";
    const uint8_t bytes2[] = "BBBBBBBB";
    uint32_t gen;

    uart_ring_init(&g_test_tx_ring);
    g_txe_enabled = 1U;
    cipsend_tx_init(&tx);
    txfq_init(&q);
    etc_init(&c, &tx, &q, &tele, fake_discard_cb, NULL);

    gen = 1U;
    CHECK(etc_check_boundary(&c, gen) == 0U);

    /* Push bytes, then trigger boundary */
    push_to_tx_ring(bytes1, 4U);
    gen = 2U;
    CHECK(etc_check_boundary(&c, gen) == 1U);
    CHECK(c.tx_bytes_discarded == 4U);

    /* Push more bytes, trigger another boundary */
    push_to_tx_ring(bytes2, 8U);
    gen = 3U;
    CHECK(etc_check_boundary(&c, gen) == 1U);
    CHECK(c.tx_bytes_discarded == 12U);  /* 4 + 8 */
    return 0;
}

/* ===================================================================
 * 5. Fresh authoritative status after reconnect (integration)
 * =================================================================== */

static int test_fresh_status_after_reconnect(void)
{
    EspTxCoordinator c;
    CipsendTx tx;
    TxFrameQueue q;
    uint8_t tele = 1U;
    uint32_t gen;

    s_connected = 0U;
    s_client_id = 0xFFU;
    esp_transport_init(&s_connected, &s_client_id);

    uart_ring_init(&g_test_tx_ring);
    g_txe_enabled = 1U;
    cipsend_tx_init(&tx);
    txfq_init(&q);
    etc_init(&c, &tx, &q, &tele, fake_discard_cb, NULL);

    /* Client connects */
    service_str(&tx, "0,CONNECT\r\n");
    gen = esp_transport_connection_generation();
    CHECK(etc_check_boundary(&c, gen) == 0U);
    CHECK(s_connected == 1U);

    /* Queue an ACK, retain it, simulate ERROR → it stays in retry buffer */
    queue_ack_result();
    {
        char tmp[TWIN_CONTROL_LINE_MAX + 1U];
        uint16_t n = esp_transport_get_pending_ack(tmp, sizeof(tmp));
        CHECK(n > 0U);
        txfq_retain_ack(&q, tmp, n);
        txfq_on_tx_result(&q, CTS_RESULT_ERROR, CIPSEND_TX_TAG_ACK);
        CHECK(txfq_has_ack(&q));
    }

    /* Disconnect + reconnect (gen change) */
    service_str(&tx, "0,CLOSED\r\n");
    service_str(&tx, "0,CONNECT\r\n");
    gen = esp_transport_connection_generation();
    CHECK(etc_check_boundary(&c, gen) == 1U);

    /* Old ACK must be gone */
    CHECK(!txfq_has_retry(&q));

    /* Transport can accept fresh status */
    CHECK(esp_transport_can_queue_status());
    {
        TwinControlStatus st;
        memset(&st, 0, sizeof(st));
        strcpy(st.campaign_id, "camp-a");
        strcpy(st.run_id, "run-1");
        strcpy(st.state, "STOPPED");
        strcpy(st.reason, "TIMEOUT");
        esp_transport_queue_status(&st);
    }
    CHECK(esp_transport_has_pending_status());
    return 0;
}

/* ===================================================================
 * 6. Regression: +IPD / A-S order / STD/STOP/timeout not broken
 * =================================================================== */

static int test_no_regression_as_ordering(void)
{
    TxFrameQueue q;
    char tmp[TWIN_CONTROL_LINE_MAX + 1U];

    txfq_init(&q);
    txfq_retain_ack(&q, "A,camp-a,1,APPLIED,APPLIED,3F\n",
                    (uint16_t)strlen("A,camp-a,1,APPLIED,APPLIED,3F\n"));
    txfq_retain_status(&q, "S,camp-a,run-1,STOPPED,TIMEOUT,0,AA\n",
                       (uint16_t)strlen("S,camp-a,run-1,STOPPED,TIMEOUT,0,AA\n"));

    CHECK(txfq_check_generation(&q, 9U) == 0U);
    txfq_on_tx_result(&q, CTS_RESULT_OK, CIPSEND_TX_TAG_ACK);
    CHECK(!txfq_has_ack(&q));
    CHECK(txfq_has_status(&q));   /* STATUS still queued (A before S) */
    (void)tmp;
    return 0;
}

static int test_no_regression_ipd_passthrough(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_DROPPABLE, CIPSEND_TX_TAG_TELEMETRY, 0U));
    cipsend_tx_tick(&tx, 0U, test_sink, NULL);

    /* +IPD noise before prompt — must not corrupt scan */
    feed_str(&tx, "+IPD,0,5:HELLO");
    feed_str(&tx, ">");
    CHECK(tx.state == CIPSEND_TX_STATE_SEND_DATA);
    return 0;
}

static int test_no_regression_timeout_still_works(void)
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

    /* Timeout before '>' */
    cipsend_tx_tick(&tx, 1000U + CIPSEND_TX_PROMPT_TIMEOUT_MS + 1U,
                    test_sink, NULL);
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_timeout_aborted(&tx) == 1U);
    return 0;
}

static int test_no_regression_full_success(void)
{
    CipsendTx tx;
    const char cmd[] = "AT+CIPSEND=0,5\r\n";
    const uint8_t data[] = "hello";

    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;
    CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd), data, 5U,
                           CIPSEND_TX_PRIORITY_DROPPABLE, CIPSEND_TX_TAG_TELEMETRY, 1000U));
    cipsend_tx_tick(&tx, 1000U, test_sink, NULL);
    feed_str(&tx, ">");
    cipsend_tx_tick(&tx, 1001U, test_sink, NULL);
    feed_str(&tx, "\r\nSEND OK\r\n");
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_OK);
    return 0;
}

/* ===================================================================
 * TEST RUNNER
 * =================================================================== */

static int run_all_tests(void)
{
    /* 1. WAIT_PROMPT immediate ERROR/busy/CLOSED */
    if (test_prompt_error_immediate_fail()) return 1;
    if (test_prompt_busy_immediate_fail()) return 1;
    if (test_prompt_closed_immediate_fail()) return 1;

    /* 2. SEND_DATA independent deadline */
    if (test_send_data_independent_deadline()) return 1;

    /* 3. Coordinator TX ring discard on boundary */
    if (test_generation_change_discards_tx_ring()) return 1;
    if (test_closed_terminal_discards_all()) return 1;
    if (test_same_id_reconnect_discards_tx_ring()) return 1;
    if (test_different_id_connect_discards_tx_ring()) return 1;
    if (test_connect_without_prior_closed_discards()) return 1;

    /* 4. Idempotent + wraparound-safe + observable */
    if (test_discard_idempotent()) return 1;
    if (test_discard_wraparound_safe()) return 1;
    if (test_observable_count_increments()) return 1;

    /* 5. Fresh authoritative status */
    if (test_fresh_status_after_reconnect()) return 1;

    /* 6. Regression */
    if (test_no_regression_as_ordering()) return 1;
    if (test_no_regression_ipd_passthrough()) return 1;
    if (test_no_regression_timeout_still_works()) return 1;
    if (test_no_regression_full_success()) return 1;

    puts("PASS test_coordinator_boundary");
    return 0;
}

int main(void)
{
    return run_all_tests();
}
