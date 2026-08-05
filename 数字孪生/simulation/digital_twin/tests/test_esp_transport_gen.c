/* Host C integration tests for connection generation isolation in the ESP
 * transport layer (Task 4B-4 fix, Codex review remediation — Gap 2).
 *
 * Uses the REAL esp_runtime_transport.c (linked from hostc/User).
 * Compile against the PRE-FIX transport → RED (generation API missing +
 * CONNECT does not clear stale pending ACK).  Compile against the FIXED
 * transport → GREEN.
 */

#include <stdio.h>
#include <string.h>

#include "esp_runtime_transport.h"
#include "twin_control_protocol.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static volatile uint8_t s_connected = 0U;
static volatile uint8_t s_client_id = 0xFFU;

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

static void queue_status(void)
{
    TwinControlStatus st;
    memset(&st, 0, sizeof(st));
    strcpy(st.campaign_id, "camp-a");
    strcpy(st.run_id, "run-1");
    strcpy(st.state, "STOPPED");
    strcpy(st.reason, "TIMEOUT");
    st.tick_ms = 0U;
    esp_transport_queue_status(&st);
}

/* ===================================================================
 * CONNECT bumps generation; CLOSED does not
 * =================================================================== */

static int test_generation_increments_on_connect(void)
{
    s_connected = 0U;
    s_client_id = 0xFFU;
    esp_transport_init(&s_connected, &s_client_id);
    CHECK(esp_transport_connection_generation() == 0U);

    feed_str("0,CONNECT\r\n");
    CHECK(esp_transport_connection_generation() == 1U);
    CHECK(s_connected == 1U);
    CHECK(s_client_id == 0U);

    /* CLOSED does not bump generation (only CONNECT starts a new epoch). */
    feed_str("0,CLOSED\r\n");
    CHECK(esp_transport_connection_generation() == 1U);
    CHECK(s_connected == 0U);

    /* 同一 client id 重连 → 代次继续递增。 */
    feed_str("0,CONNECT\r\n");
    CHECK(esp_transport_connection_generation() == 2U);

    /* 不同 id 的新客户端 → 代次继续递增。 */
    feed_str("1,CLOSED\r\n");  /* ignore: client_id is 0, so no effect */
    CHECK(esp_transport_connection_generation() == 2U);
    feed_str("1,CONNECT\r\n");
    CHECK(esp_transport_connection_generation() == 3U);
    return 0;
}

/* ===================================================================
 * CONNECT clears stale pending ACK / STATUS (no leak to new client)
 * =================================================================== */

static int test_connect_clears_pending_ack(void)
{
    s_connected = 0U;
    s_client_id = 0xFFU;
    esp_transport_init(&s_connected, &s_client_id);

    /* An ACK from a previous client is still pending when the old client
       dropped (before we noticed) — a new CONNECT must purge it. */
    queue_ack();
    CHECK(esp_transport_has_pending_ack());

    feed_str("0,CONNECT\r\n");
    CHECK(esp_transport_has_pending_ack() == 0U);
    return 0;
}

static int test_connect_clears_pending_status(void)
{
    s_connected = 0U;
    s_client_id = 0xFFU;
    esp_transport_init(&s_connected, &s_client_id);

    queue_status();
    CHECK(esp_transport_has_pending_status());

    feed_str("0,CONNECT\r\n");
    CHECK(esp_transport_has_pending_status() == 0U);
    return 0;
}

/* ===================================================================
 * CLOSED clears pending ACK / STATUS (connection gone)
 * =================================================================== */

static int test_closed_clears_pending_frames(void)
{
    s_connected = 0U;
    s_client_id = 0xFFU;
    esp_transport_init(&s_connected, &s_client_id);

    feed_str("0,CONNECT\r\n");
    queue_ack();
    queue_status();
    CHECK(esp_transport_has_pending_ack());
    CHECK(esp_transport_has_pending_status());

    feed_str("0,CLOSED\r\n");
    CHECK(s_connected == 0U);
    CHECK(esp_transport_has_pending_ack() == 0U);
    CHECK(esp_transport_has_pending_status() == 0U);
    return 0;
}

/* ===================================================================
 * Full sequence: old ACK fetched into caller queue, connection drops,
 * new client connects — nothing stale remains available.
 * =================================================================== */

static int test_old_frames_not_available_after_reconnect(void)
{
    char buf[TWIN_CONTROL_LINE_MAX + 1U];
    uint16_t n;

    s_connected = 0U;
    s_client_id = 0xFFU;
    esp_transport_init(&s_connected, &s_client_id);

    /* client 0 connects */
    feed_str("0,CONNECT\r\n");

    /* PC sends a P command → transport queues an ACK (not yet fetched) */
    queue_ack();
    CHECK(esp_transport_has_pending_ack());

    /* main.c fetches the ACK into its local queue */
    n = esp_transport_get_pending_ack(buf, sizeof(buf));
    CHECK(n > 0U);
    CHECK(esp_transport_has_pending_ack() == 0U);

    /* old client drops */
    feed_str("0,CLOSED\r\n");
    CHECK(s_connected == 0U);

    /* new client connects */
    feed_str("0,CONNECT\r\n");
    CHECK(s_connected == 1U);

    /* Transport must NOT re-expose the old ACK or any stale status. */
    CHECK(esp_transport_has_pending_ack() == 0U);
    CHECK(esp_transport_has_pending_status() == 0U);
    return 0;
}

/* ===================================================================
 * TEST RUNNER
 * =================================================================== */

static int run_all_tests(void)
{
    if (test_generation_increments_on_connect()) return 1;
    if (test_connect_clears_pending_ack()) return 1;
    if (test_connect_clears_pending_status()) return 1;
    if (test_closed_clears_pending_frames()) return 1;
    if (test_old_frames_not_available_after_reconnect()) return 1;

    puts("PASS test_esp_transport_gen");
    return 0;
}

int main(void)
{
    return run_all_tests();
}
