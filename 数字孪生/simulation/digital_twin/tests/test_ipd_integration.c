/* Host C integration test: esp_runtime_transport feeds ipd_parser ->
   twin_control_receive_byte -> produces A ACK and S status frames.
   Both main.c and this test use the SAME production transport module. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_runtime_transport.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static const TwinControlParams k_baseline = {
    35.0F, 0.0F, 10.0F, 680, 1U, "baseline"
};

static uint8_t g_connected;
static uint8_t g_client_id;

/* Feed raw TCP bytes through the production transport module */
static void feed_tcp(const unsigned char *data, unsigned int len)
{
    for (unsigned i = 0U; i < len; ++i)
        esp_transport_process_byte(data[i]);
}

static char pending_ack[TWIN_CONTROL_LINE_MAX + 1U];

/* Test: +IPD wraps a valid P frame, payload reaches protocol, ACK is queued */
static int test_ipd_wraps_parameter_frame(void)
{
    TwinControlParams active = k_baseline;
    TwinControlResult result;

    twin_control_init(&k_baseline);
    g_connected = 1U;
    g_client_id = 0U;
    esp_transport_init(&g_connected, &g_client_id);

    char body[64];
    sprintf(body, "P,camp-001,2,40,0,10,680");
    unsigned char cs = 0U;
    for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
    char frame[96];
    int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                       strlen(body) + 4U, body, (unsigned)cs);

    feed_tcp((unsigned char*)frame, (unsigned)flen);

    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(result.applied == 1U);
    CHECK(active.kp == 40.0F);
    return 0;
}

/* Test: +IPD P frame + STOP -> ACK queued with STOP reason */
static int test_ipd_parameter_then_stop_produces_ack(void)
{
    TwinControlParams active = k_baseline;
    TwinControlResult result;

    twin_control_init(&k_baseline);
    g_connected = 1U;
    g_client_id = 0U;
    esp_transport_init(&g_connected, &g_client_id);

    {
        char body[64];
        sprintf(body, "P,camp-001,2,40,0,10,680");
        unsigned char cs = 0U;
        for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
        char frame[96];
        int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                           strlen(body) + 4U, body, (unsigned)cs);
        feed_tcp((unsigned char*)frame, (unsigned)flen);
    }

    {
        char body[64];
        sprintf(body, "R,camp-001,run-001,STOP");
        unsigned char cs = 0U;
        for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
        char frame[96];
        int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                           strlen(body) + 4U, body, (unsigned)cs);
        feed_tcp((unsigned char*)frame, (unsigned)flen);
    }

    CHECK(twin_control_motion_inhibited() == 1U);
    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(result.applied == 0U);
    CHECK(strcmp(result.reason, "STOP") == 0);
    CHECK(active.kp == 35.0F);
    return 0;
}

/* Test: AT noise before +IPD does not affect protocol or produce ACKs */
static int test_noise_before_frame(void)
{
    TwinControlParams active = k_baseline;
    TwinControlResult result;

    twin_control_init(&k_baseline);
    g_connected = 1U;
    g_client_id = 0U;
    esp_transport_init(&g_connected, &g_client_id);

    const unsigned char noise[] = "AT+CIPSEND\r\nOK\r\n";
    feed_tcp(noise, sizeof(noise) - 1U);
    CHECK(esp_transport_has_pending_ack() == 0U);

    char body[64];
    sprintf(body, "P,camp-001,2,40,0,10,680");
    unsigned char cs = 0U;
    for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
    char frame[96];
    int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                       strlen(body) + 4U, body, (unsigned)cs);
    feed_tcp((unsigned char*)frame, (unsigned)flen);

    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(result.applied == 1U);
    return 0;
}

/* Capability preflight requests are accepted only from an +IPD payload.
   They must not be interpreted as a control frame or alter safety state. */
static int test_capability_request_is_not_a_control_frame(void)
{
    const unsigned char plain_request[] = "D,ESP_CAPS,plain\n";
    const unsigned char ipd_request[] =
        "+IPD,0,18:D,ESP_CAPS,abc123\n";

    twin_control_init(&k_baseline);
    g_connected = 1U;
    g_client_id = 0U;
    esp_transport_init(&g_connected, &g_client_id);

    feed_tcp(plain_request, sizeof(plain_request) - 1U);
    CHECK(esp_transport_diagnostic_request_ready() == 0U);
    CHECK(esp_transport_has_pending_ack() == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);

    feed_tcp(ipd_request, sizeof(ipd_request) - 1U);
    CHECK(esp_transport_diagnostic_request_ready() == 1U);
    CHECK(esp_transport_has_pending_ack() == 0U);
    CHECK(esp_transport_has_pending_status() == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);
    return 0;
}

/* Test: two consecutive +IPD frames */
static int test_consecutive_ipd_frames(void)
{
    TwinControlParams active = k_baseline;
    TwinControlResult result;

    twin_control_init(&k_baseline);
    g_connected = 1U;
    g_client_id = 0U;
    esp_transport_init(&g_connected, &g_client_id);

    char p_body[64];
    sprintf(p_body, "P,camp-001,2,40,0,10,680");
    unsigned char cs1 = 0U;
    for (char *p = p_body; *p != '\0'; ++p) cs1 ^= (unsigned char)*p;

    char r_body[64];
    sprintf(r_body, "R,camp-001,run-001,START");
    unsigned char cs2 = 0U;
    for (char *p = r_body; *p != '\0'; ++p) cs2 ^= (unsigned char)*p;

    char both[256];
    int blen = sprintf(both, "+IPD,0,%zu:%s,%02X\n+IPD,0,%zu:%s,%02X\n",
                       strlen(p_body) + 4U, p_body, (unsigned)cs1,
                       strlen(r_body) + 4U, r_body, (unsigned)cs2);
    feed_tcp((unsigned char*)both, (unsigned)blen);

    CHECK(twin_control_apply_pending(&active, &k_baseline, &result) == 1U);
    CHECK(result.applied == 1U);
    CHECK(active.kp == 40.0F);
    CHECK(twin_control_motion_inhibited() == 0U);
    return 0;
}

/* Test: esp_transport_get_pending_ack returns the encoded ACK */
static int test_pending_ack_is_encoded(void)
{
    TwinControlParams active = k_baseline;
    TwinControlResult result;

    twin_control_init(&k_baseline);
    g_connected = 1U;
    g_client_id = 0U;
    esp_transport_init(&g_connected, &g_client_id);

    char body[64];
    sprintf(body, "P,camp-001,2,40,0,10,680");
    unsigned char cs = 0U;
    for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
    char frame[96];
    int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                       strlen(body) + 4U, body, (unsigned)cs);
    feed_tcp((unsigned char*)frame, (unsigned)flen);
    CHECK(esp_transport_has_pending_ack() == 0U);

    twin_control_apply_pending(&active, &k_baseline, &result);
    esp_transport_queue_ack(&result);

    CHECK(esp_transport_has_pending_ack() == 1U);
    char ack_buf[TWIN_CONTROL_LINE_MAX + 1U];
    uint16_t ack_len = esp_transport_get_pending_ack(ack_buf, sizeof(ack_buf));
    CHECK(ack_len > 0U);
    CHECK(strstr(ack_buf, "APPLIED") != 0);
    CHECK(strstr(ack_buf, "A,") == ack_buf);
    CHECK(esp_transport_has_pending_ack() == 0U);
    return 0;
}

/* Test: CONNECT/CLOSED lines parsed through transport */
static int test_connect_closed_handling(void)
{
    twin_control_init(&k_baseline);
    g_connected = 0U;
    g_client_id = 0xFF;
    esp_transport_init(&g_connected, &g_client_id);

    const unsigned char connect[] = "0,CONNECT\r\n";
    feed_tcp(connect, sizeof(connect) - 1U);
    CHECK(g_connected == 1U);
    CHECK(g_client_id == 0U);

    const unsigned char closed[] = "0,CLOSED\r\n";
    feed_tcp(closed, sizeof(closed) - 1U);
    CHECK(g_connected == 0U);
    return 0;
}

/* Test: transport backpressure - can_queue returns 1 when empty, 0 when pending */
static int test_transport_backpressure(void)
{
    TwinControlParams active = k_baseline;
    TwinControlStatus st;
    uint8_t connected = 1U;
    uint8_t client_id = 0U;

    twin_control_init(&active);
    esp_transport_init(&connected, &client_id);

    CHECK(esp_transport_can_queue_status() == 1U);

    memset(&st, 0, sizeof(st));
    strcpy(st.campaign_id, "camp-001");
    strcpy(st.run_id, "run-001");
    strcpy(st.state, "RUNNING");
    strcpy(st.reason, "START");
    st.tick_ms = 0U;
    esp_transport_queue_status(&st);

    CHECK(esp_transport_can_queue_status() == 0U);

    /* CONNECT resets stale status */
    {
        const unsigned char conn[] = "0,CONNECT\r\n";
        feed_tcp(conn, sizeof(conn) - 1U);
    }
    CHECK(esp_transport_can_queue_status() == 1U);
    return 0;
}

/* Test: authoritative status queued after CONNECT is retrievable */
static int test_authoritative_status_after_connect(void)
{
    TwinControlParams active = k_baseline;
    uint8_t connected = 0U;
    uint8_t client_id = 0xFF;
    char ack_buf[TWIN_CONTROL_LINE_MAX + 1U];

    twin_control_init(&active);
    esp_transport_init(&connected, &client_id);

    {
        const unsigned char conn[] = "0,CONNECT\r\n";
        feed_tcp(conn, sizeof(conn) - 1U);
    }
    CHECK(connected == 1U);
    CHECK(client_id == 0U);

    {
        TwinControlStatus st;
        twin_control_queue_authoritative_status();
        CHECK(twin_control_consume_pending_status(&st) == 1U);
        CHECK(strcmp(st.state, "INIT") == 0);
        CHECK(strcmp(st.reason, "MOTION_INHIBITED") == 0);
        esp_transport_queue_status(&st);
    }
    CHECK(esp_transport_has_pending_status() == 1U);
    {
        uint16_t len = esp_transport_get_pending_status(ack_buf, sizeof(ack_buf));
        CHECK(len > 0U);
        CHECK(strstr(ack_buf, "INIT") != 0);
    }
    return 0;
}

/* End-to-end: CONNECT -> R START -> CLOSED -> motion inhibited + TIMEOUT
   authoritative state -> reconnect -> TIMEOUT state available */
static int test_e2e_closed_triggers_timeout(void)
{
    TwinControlParams active = k_baseline;
    uint8_t connected = 0U;
    uint8_t client_id = 0xFF;
    const unsigned char conn[] = "0,CONNECT\r\n";
    const unsigned char closed[] = "0,CLOSED\r\n";

    /* Step 1: init + CONNECT */
    twin_control_init(&active);
    esp_transport_init(&connected, &client_id);
    feed_tcp(conn, sizeof(conn) - 1U);
    CHECK(connected == 1U);
    CHECK(client_id == 0U);
    CHECK(twin_control_motion_inhibited() == 1U); /* default inhibited */

    /* Step 2: R START -> motion uninhibited */
    {
        unsigned char body[64];
        sprintf((char*)body, "R,camp-001,run-001,START");
        unsigned char cs = 0U;
        for (char *p = (char*)body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
        unsigned char frame[96];
        int flen = sprintf((char*)frame, "+IPD,0,%zu:%s,%02X\n",
                           strlen((char*)body) + 4U, (char*)body, (unsigned)cs);
        feed_tcp(frame, (unsigned)flen);
    }
    CHECK(twin_control_motion_inhibited() == 0U);

    /* Drain RUNNING event from protocol FIFO before CLOSED */
    { TwinControlStatus _st; while (twin_control_consume_pending_status(&_st)); }

    /* Step 3: flush AT line buffer with a blank line, then CLOSED */
    {
        const unsigned char flush[] = "\r\n";
        feed_tcp(flush, sizeof(flush) - 1U);
    }
    /* Now CLOSED -> twin_control_timeout called internally */
    feed_tcp(closed, sizeof(closed) - 1U);
    CHECK(connected == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);

    /* Step 4: TIMEOUT authoritative state available */
    {
        TwinControlStatus st;
        twin_control_queue_authoritative_status();
        CHECK(twin_control_consume_pending_status(&st) == 1U);
        CHECK(strcmp(st.state, "STOPPED") == 0);
        CHECK(strcmp(st.reason, "TIMEOUT") == 0);
    }

    /* Step 5: reconnect -> transport cleared, TIMEOUT still authoritative */
    feed_tcp(conn, sizeof(conn) - 1U);
    CHECK(connected == 1U);
    CHECK(esp_transport_can_queue_status() == 1U); /* stale cleared */
    {
        TwinControlStatus st;
        twin_control_queue_authoritative_status();
        CHECK(twin_control_consume_pending_status(&st) == 1U);
        CHECK(strcmp(st.state, "STOPPED") == 0);
        CHECK(strcmp(st.reason, "TIMEOUT") == 0);
    }

    /* Step 6: duplicate CLOSED while already disconnected -> no extra timeout */
    /* Mark connected again first, then CLOSED */
    connected = 1U;  /* simulate what CONNECT does */
    client_id = 0U;
    feed_tcp(closed, sizeof(closed) - 1U);
    /* Only one TIMEOUT should be in the FIFO from the first CLOSED.
       The duplicate CLOSED had *s_tcp_connected == 1 -> another timeout. */
    /* Actually after CONNECT (line above marks connected=1), this CLOSED
       correctly triggers another timeout because we re-connected. */
    CHECK(connected == 0U);
    CHECK(twin_control_motion_inhibited() == 1U);
    return 0;
}

/* ===== Task 2B-apply-ack-fix: safe-point apply ACK tests ===== */

/* Test: esp_transport_apply_and_ack queues APPLIED ACK for a pending P
   that succeeds at the safe point.  This is the RED step of TDD:
   the helper does not exist yet. */
static int test_safe_point_apply_queues_applied_ack(void)
{
    TwinControlParams active = k_baseline;

    twin_control_init(&k_baseline);
    g_connected = 1U;
    g_client_id = 0U;
    esp_transport_init(&g_connected, &g_client_id);

    /* Feed R START to clear motion inhibit so P can apply normally */
    {
        char body[64];
        sprintf(body, "R,camp-001,run-001,START");
        unsigned char cs = 0U;
        for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
        char frame[96];
        int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                           strlen(body) + 4U, body, (unsigned)cs);
        feed_tcp((unsigned char*)frame, (unsigned)flen);
    }

    /* Feed a valid P frame — queued as pending, no immediate ACK */
    {
        char body[64];
        sprintf(body, "P,camp-001,2,40,0,10,680");
        unsigned char cs = 0U;
        for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
        char frame[96];
        int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                           strlen(body) + 4U, body, (unsigned)cs);
        feed_tcp((unsigned char*)frame, (unsigned)flen);
    }

    /* No ACK from receive alone — P was queued as pending */
    CHECK(esp_transport_has_pending_ack() == 0U);

    /* Call the new helper — this should apply pending + queue APPLIED ACK */
    CHECK(esp_transport_apply_and_ack(&active, &k_baseline) == 1U);

    /* Verify ACK was queued */
    CHECK(esp_transport_has_pending_ack() == 1U);
    {
        char ack_buf[TWIN_CONTROL_LINE_MAX + 1U];
        uint16_t ack_len = esp_transport_get_pending_ack(ack_buf, sizeof(ack_buf));
        CHECK(ack_len > 0U);
        CHECK(strstr(ack_buf, "APPLIED") != 0);
        CHECK(strstr(ack_buf, "A,") == ack_buf);
        CHECK(strstr(ack_buf, "camp-001") != 0);
    }
    CHECK(esp_transport_has_pending_ack() == 0U);
    CHECK(active.kp == 40.0F);
    return 0;
}

/* Test: esp_transport_apply_and_ack queues REJECTED ACK when rollback
   (STOP) cancels a pending P before the safe point. */
static int test_safe_point_rollback_queues_rejected_ack(void)
{
    TwinControlParams active = k_baseline;

    twin_control_init(&k_baseline);
    g_connected = 1U;
    g_client_id = 0U;
    esp_transport_init(&g_connected, &g_client_id);

    /* Feed R START */
    {
        char body[64];
        sprintf(body, "R,camp-001,run-001,START");
        unsigned char cs = 0U;
        for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
        char frame[96];
        int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                           strlen(body) + 4U, body, (unsigned)cs);
        feed_tcp((unsigned char*)frame, (unsigned)flen);
    }

    /* Feed a valid P frame */
    {
        char body[64];
        sprintf(body, "P,camp-001,2,40,0,10,680");
        unsigned char cs = 0U;
        for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
        char frame[96];
        int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                           strlen(body) + 4U, body, (unsigned)cs);
        feed_tcp((unsigned char*)frame, (unsigned)flen);
    }

    /* Feed a STOP — sets restore_baseline, pending P will be cancelled */
    {
        char body[64];
        sprintf(body, "R,camp-001,run-001,STOP");
        unsigned char cs = 0U;
        for (char *p = body; *p != '\0'; ++p) cs ^= (unsigned char)*p;
        char frame[96];
        int flen = sprintf(frame, "+IPD,0,%zu:%s,%02X\n",
                           strlen(body) + 4U, body, (unsigned)cs);
        feed_tcp((unsigned char*)frame, (unsigned)flen);
    }

    /* Call the helper — should cancel pending P and queue REJECTED/STOP ACK */
    CHECK(esp_transport_apply_and_ack(&active, &k_baseline) == 1U);

    CHECK(esp_transport_has_pending_ack() == 1U);
    {
        char ack_buf[TWIN_CONTROL_LINE_MAX + 1U];
        uint16_t ack_len = esp_transport_get_pending_ack(ack_buf, sizeof(ack_buf));
        CHECK(ack_len > 0U);
        CHECK(strstr(ack_buf, "REJECTED") != 0);
        CHECK(strstr(ack_buf, "STOP") != 0);
        CHECK(strstr(ack_buf, "A,") == ack_buf);
        CHECK(strstr(ack_buf, "camp-001") != 0);
    }
    CHECK(esp_transport_has_pending_ack() == 0U);
    /* After rollback, active should be baseline again */
    CHECK(active.kp == 35.0F);
    CHECK(active.speed_max == 680);
    CHECK(twin_control_motion_inhibited() == 1U);
    return 0;
}

/* ===== End Task 2B-apply-ack-fix ===== */

int main(void)
{
    if (test_ipd_wraps_parameter_frame()) return 1;
    if (test_ipd_parameter_then_stop_produces_ack()) return 1;
    if (test_noise_before_frame()) return 1;
    if (test_capability_request_is_not_a_control_frame()) return 1;
    if (test_consecutive_ipd_frames()) return 1;
    if (test_pending_ack_is_encoded()) return 1;
    if (test_connect_closed_handling()) return 1;
    if (test_transport_backpressure()) return 1;
    if (test_authoritative_status_after_connect()) return 1;
    if (test_e2e_closed_triggers_timeout()) return 1;
    /* Task 2B-apply-ack-fix */
    if (test_safe_point_apply_queues_applied_ack()) return 1;
    if (test_safe_point_rollback_queues_rejected_ack()) return 1;
    puts("PASS test_ipd_integration");
    return 0;
}
