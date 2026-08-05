/* Host C integration test reproducing the confirmed Gap-2 defect and its fix
 * (Task 4B-4 fix, Codex review remediation):
 *
 *   OLD client 0's ACK fetched to local retry -> CIPSEND gets 0,CLOSED ->
 *   connection drops -> NEW client CONNECT -> local retry must NOT be sent
 *   to the new client.
 *
 * Exercises the real wiring used by main.c:
 *   - esp_transport_process_byte() (CONNECT/CLOSED/+IPD routing)
 *   - cipsend_tx (in-flight TX termination on CLOSED)
 *   - TxFrameQueue (connection-generation-scoped retry buffers)
 *
 * RED: run against the buggy tx_frame_queue_stub + old transport (frames
 * retained across connection).  GREEN: real modules.
 */

#include <stdio.h>
#include <string.h>

#include "esp_runtime_transport.h"
#include "twin_control_protocol.h"
#include "cipsend_tx.h"
#include "tx_frame_queue.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static volatile uint8_t s_connected = 0U;
static volatile uint8_t s_client_id = 0xFFU;

static char g_tx_out[512];
static uint16_t g_tx_out_len;

static uint8_t test_sink(void *ctx, uint8_t byte)
{
    (void)ctx;
    if (g_tx_out_len < sizeof(g_tx_out)) {
        g_tx_out[g_tx_out_len++] = (char)byte;
        return 1U;
    }
    return 0U;
}

static void feed_str(const char *s)
{
    for (; *s; ++s) esp_transport_process_byte((uint8_t)*s);
}

static void queue_ack(void)
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

/* Drive the transport RX bytes through BOTH the transport and the TX
   state machine (as main.c's ESP_TX_Service does). */
static void service_byte(CipsendTx *tx, uint8_t b)
{
    esp_transport_process_byte(b);
    cipsend_tx_feed_byte(tx, b);
}

static void service_str(CipsendTx *tx, const char *s)
{
    for (; *s; ++s) service_byte(tx, (uint8_t)*s);
}

/* ===================================================================
 * The confirmed repro: old ACK must not reach the new client
 * =================================================================== */

static int test_old_ack_never_reaches_new_client(void)
{
    TxFrameQueue q;
    CipsendTx tx;
    char tmp[TWIN_CONTROL_LINE_MAX + 1U];
    uint16_t n;

    s_connected = 0U;
    s_client_id = 0xFFU;
    esp_transport_init(&s_connected, &s_client_id);
    txfq_init(&q);
    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;

    /* --- client 0 connects (generation 1) --- */
    service_str(&tx, "0,CONNECT\r\n");
    CHECK(s_connected == 1U);
    CHECK(esp_transport_connection_generation() == 1U);
    CHECK(txfq_check_generation(&q, esp_transport_connection_generation()) == 0U);

    /* --- PC sends P command → ACK queued; main fetches into local queue --- */
    queue_ack();
    CHECK(esp_transport_has_pending_ack());
    n = esp_transport_get_pending_ack(tmp, sizeof(tmp));
    CHECK(n > 0U);
    txfq_retain_ack(&q, tmp, n);
    CHECK(txfq_has_ack(&q));

    /* --- in-flight TX starts with the ACK --- */
    {
        char cmd[24];
        sprintf(cmd, "AT+CIPSEND=0,%u\r\n", (unsigned)txfq_ack_len(&q));
        CHECK(cipsend_tx_start(&tx, cmd, (uint16_t)strlen(cmd),
                               (const uint8_t *)txfq_ack_ptr(&q),
                               txfq_ack_len(&q),
                               CIPSEND_TX_PRIORITY_CRITICAL,
                               CIPSEND_TX_TAG_ACK, 1000U));
        cipsend_tx_tick(&tx, 1000U, test_sink, NULL);
        CHECK(tx.state == CIPSEND_TX_STATE_WAIT_PROMPT);
        service_byte(&tx, '>');
        cipsend_tx_tick(&tx, 1001U, test_sink, NULL);
        CHECK(tx.state == CIPSEND_TX_STATE_WAIT_SENDOK);
    }

    /* --- old client drops: "0,CLOSED" terminates the in-flight TX --- */
    service_str(&tx, "0,CLOSED\r\n");
    CHECK(s_connected == 0U);
    CHECK(cipsend_tx_is_terminal(&tx));
    CHECK(cipsend_tx_result(&tx) == CTS_RESULT_CLOSED);

    /* main.c HandleTerminal: drop retained frames, reset TX machine. */
    txfq_on_tx_result(&q, cipsend_tx_result(&tx), cipsend_tx_tag(&tx));
    CHECK(!txfq_has_ack(&q));
    CHECK(!txfq_has_status(&q));
    cipsend_tx_reset(&tx);
    CHECK(!cipsend_tx_busy(&tx));

    /* --- NEW client connects (generation 2) --- */
    service_str(&tx, "0,CONNECT\r\n");
    CHECK(s_connected == 1U);
    CHECK(esp_transport_connection_generation() == 2U);
    CHECK(txfq_check_generation(&q, esp_transport_connection_generation()) == 1U);

    /* --- nothing old remains to send to the new client --- */
    CHECK(!txfq_has_retry(&q));
    CHECK(esp_transport_has_pending_ack() == 0U);
    CHECK(esp_transport_has_pending_status() == 0U);
    CHECK(!cipsend_tx_busy(&tx));
    return 0;
}

/* ===================================================================
 * Same-ID reconnect: retained STATUS dropped; fresh authoritative status
 * can still be queued and sent after reconnect.
 * =================================================================== */

static int test_reconnect_fresh_status_ok(void)
{
    TxFrameQueue q;
    CipsendTx tx;
    char tmp[TWIN_CONTROL_LINE_MAX + 1U];
    uint16_t n;

    s_connected = 0U;
    s_client_id = 0xFFU;
    esp_transport_init(&s_connected, &s_client_id);
    txfq_init(&q);
    cipsend_tx_init(&tx);
    g_tx_out_len = 0U;

    /* old client 0, generation 1 */
    service_str(&tx, "0,CONNECT\r\n");
    CHECK(txfq_check_generation(&q, 1U) == 0U);

    /* a STATUS is retained (send failed with ERROR, in-generation retry) */
    {
        TwinControlStatus st;
        memset(&st, 0, sizeof(st));
        strcpy(st.campaign_id, "camp-a");
        strcpy(st.run_id, "run-1");
        strcpy(st.state, "STOPPED");
        strcpy(st.reason, "TIMEOUT");
        esp_transport_queue_status(&st);
        n = esp_transport_get_pending_status(tmp, sizeof(tmp));
        CHECK(n > 0U);
        txfq_retain_status(&q, tmp, n);
        CHECK(txfq_has_status(&q));
        txfq_on_tx_result(&q, CTS_RESULT_ERROR, CIPSEND_TX_TAG_STATUS);
        CHECK(txfq_has_status(&q));   /* in-generation retry kept */
    }

    /* disconnect then same-ID reconnect → generation changes → dropped */
    service_str(&tx, "0,CLOSED\r\n");
    service_str(&tx, "0,CONNECT\r\n");
    CHECK(esp_transport_connection_generation() == 2U);
    CHECK(txfq_check_generation(&q, esp_transport_connection_generation()) == 1U);
    CHECK(!txfq_has_status(&q));

    /* protocol layer supplies authoritative status on reconnect; transport
       accepts a fresh frame (backpressure gate open). */
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
 * A/S ordering preserved within a generation: ACK success clears only ACK.
 * =================================================================== */

static int test_as_ordering_within_generation(void)
{
    TxFrameQueue q;
    char tmp[TWIN_CONTROL_LINE_MAX + 1U];
    uint16_t n;

    txfq_init(&q);
    txfq_retain_ack(&q, "A,camp-a,1,APPLIED,APPLIED,3F\n",
                    (uint16_t)strlen("A,camp-a,1,APPLIED,APPLIED,3F\n"));
    txfq_retain_status(&q, "S,camp-a,run-1,STOPPED,TIMEOUT,0,AA\n",
                       (uint16_t)strlen("S,camp-a,run-1,STOPPED,TIMEOUT,0,AA\n"));

    CHECK(txfq_check_generation(&q, 9U) == 0U);
    /* ACK succeeds → STATUS still queued; ACK is sent before STATUS. */
    txfq_on_tx_result(&q, CTS_RESULT_OK, CIPSEND_TX_TAG_ACK);
    CHECK(!txfq_has_ack(&q));
    CHECK(txfq_has_status(&q));
    (void)tmp; (void)n;
    return 0;
}

/* ===================================================================
 * TEST RUNNER
 * =================================================================== */

static int run_all_tests(void)
{
    if (test_old_ack_never_reaches_new_client()) return 1;
    if (test_reconnect_fresh_status_ok()) return 1;
    if (test_as_ordering_within_generation()) return 1;

    puts("PASS test_tx_generation_integration");
    return 0;
}

int main(void)
{
    return run_all_tests();
}
