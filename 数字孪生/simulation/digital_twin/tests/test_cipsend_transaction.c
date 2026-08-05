/* Host C integration tests for the CIPSEND transaction state machine.
 *
 * Tests the full CIPSEND transaction flow in pure C (no hardware):
 *   AT+CIPSEND=... → '>' prompt → payload → SEND OK / ERROR / busy / CLOSED
 *
 * RED phase: all tests fail against the stub implementation.
 * GREEN phase: all tests pass against the real implementation.
 *
 * Coverage (per Codex review requirements):
 *   a) First transaction must not succeed before SEND OK; second must not
 *      start before first completes.
 *   b) Fragmented/byte-by-byte '>' and SEND OK\r\n.
 *   c) Recv N bytes noise before SEND OK.
 *   d) ERROR/busy/CLOSED/timeout.
 *   e) Two consecutive transactions, each waiting for its own SEND OK.
 *   f) Generic timeout → no disconnect decision; only CLOSED produces
 *      CTS_RESULT_CLOSED (the disconnect signal).
 *   g) (Retry buffer tests handled in integration with main.c)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cipsend_transaction.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

/* ── Feed helpers ─────────────────────────────────────────────────── */

/* Feed entire string, return first non-NONE result (or NONE). */
static uint8_t feed_str(CipsendTransaction *t, const char *s)
{
    uint8_t r;
    for (; *s; ++s) {
        r = cts_feed(t, (uint8_t)*s);
        if (r) return r;
    }
    return CTS_RESULT_NONE;
}

/* ===================================================================
 * SUCCESS FLOW
 * =================================================================== */

/* Test 1: Full success — prompt then SEND OK */
static int test_full_success(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    /* Echo + prompt */
    uint8_t r = feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>");
    CHECK(r == CTS_RESULT_PROMPT);
    CHECK(!cts_is_terminal(&t));

    /* SEND OK */
    r = feed_str(&t, "\r\nSEND OK\r\n");
    CHECK(r == CTS_RESULT_OK);
    CHECK(cts_is_terminal(&t));
    CHECK(cts_result(&t) == CTS_RESULT_OK);
    return 0;
}

/* Test 2: Fragmented prompt — one byte at a time */
static int test_fragmented_prompt(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(cts_feed(&t, 'A') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'T') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '+') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'C') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'I') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'P') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'S') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'E') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'N') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'D') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '=') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '0') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, ',') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '2') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '9') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '\r') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '\n') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '\r') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '\n') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '>') == CTS_RESULT_PROMPT);
    return 0;
}

/* Test 3: Fragmented SEND OK — one byte at a time after prompt */
static int test_fragmented_send_ok(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);

    CHECK(cts_feed(&t, '\r') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '\n') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'S') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'E') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'N') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'D') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, ' ') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'O') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, 'K') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '\r') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '\n') == CTS_RESULT_OK);
    CHECK(cts_is_terminal(&t));
    return 0;
}

/* Test 4: "Recv N bytes" noise line then SEND OK */
static int test_recv_noise_then_send_ok(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "Recv 29 bytes\r\n") == CTS_RESULT_NONE);
    CHECK(feed_str(&t, "SEND OK\r\n") == CTS_RESULT_OK);
    return 0;
}

/* ===================================================================
 * ERROR DETECTION
 * =================================================================== */

/* Test 5: ERROR response */
static int test_error_response(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nERROR\r\n") == CTS_RESULT_ERROR);
    CHECK(cts_is_terminal(&t));
    CHECK(cts_result(&t) == CTS_RESULT_ERROR);
    return 0;
}

/* Test 6: "busy s..." response */
static int test_busy_sending(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nbusy s...\r\n") == CTS_RESULT_ERROR);
    return 0;
}

/* Test 7: "busy p..." response */
static int test_busy_processing(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nbusy p...\r\n") == CTS_RESULT_ERROR);
    return 0;
}

/* Test 8: CLOSED response */
static int test_closed_response(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nCLOSED\r\n") == CTS_RESULT_CLOSED);
    CHECK(cts_is_terminal(&t));
    CHECK(cts_result(&t) == CTS_RESULT_CLOSED);
    return 0;
}

/* Test 9: CLOSED with ID prefix like "0,CLOSED" */
static int test_closed_with_id(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\n0,CLOSED\r\n") == CTS_RESULT_CLOSED);
    return 0;
}

/* Test 10: Timeout — no terminal response within expected window */
static int test_timeout_no_terminal(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    /* Feed normal noise but no terminal pattern */
    CHECK(feed_str(&t, "Recv 29 bytes\r\n") == CTS_RESULT_NONE);
    CHECK(feed_str(&t, "Some other line\r\n") == CTS_RESULT_NONE);
    CHECK(!cts_is_terminal(&t));
    return 0;
}

/* ===================================================================
 * TRANSACTION BOUNDARIES
 * =================================================================== */

/* Test 11: Two consecutive transactions — first success, second error */
static int test_consecutive_transactions(void)
{
    CipsendTransaction t;
    cts_init(&t);

    /* --- Transaction 1: success --- */
    cts_start(&t);
    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nSEND OK\r\n") == CTS_RESULT_OK);
    CHECK(cts_is_terminal(&t));

    /* --- Transaction 2: error --- */
    cts_start(&t);
    CHECK(feed_str(&t, "AT+CIPSEND=0,10\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nERROR\r\n") == CTS_RESULT_ERROR);
    CHECK(cts_is_terminal(&t));
    CHECK(cts_result(&t) == CTS_RESULT_ERROR);
    return 0;
}

/* Test 12: Second transaction waits for its own SEND OK */
static int test_second_waits_own_send_ok(void)
{
    CipsendTransaction t;
    cts_init(&t);

    /* First: complete success */
    cts_start(&t);
    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nSEND OK\r\n") == CTS_RESULT_OK);

    /* Second: start, get prompt, but NOT terminal until its SEND OK */
    cts_start(&t);
    CHECK(feed_str(&t, "AT+CIPSEND=0,10\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(!cts_is_terminal(&t));                   /* still waiting */
    CHECK(feed_str(&t, "\r\nSEND OK\r\n") == CTS_RESULT_OK);
    CHECK(cts_is_terminal(&t));
    return 0;
}

/* Test 13: First transaction NOT complete before its SEND OK line ends */
static int test_no_send_ok_before_completion(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    /* "SEND OK" without trailing \n — not a complete line yet */
    CHECK(feed_str(&t, "\r\nSEND OK") == CTS_RESULT_NONE);
    CHECK(!cts_is_terminal(&t));
    /* Complete the line */
    CHECK(cts_feed(&t, '\r') == CTS_RESULT_NONE);
    CHECK(cts_feed(&t, '\n') == CTS_RESULT_OK);
    CHECK(cts_is_terminal(&t));
    return 0;
}

/* ===================================================================
 * FALSE POSITIVE GUARDS
 * =================================================================== */

/* Test 14: "SEND OKAY" must NOT return OK */
static int test_send_okay_no_match(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nSEND OKAY\r\n") == CTS_RESULT_NONE);
    CHECK(!cts_is_terminal(&t));
    return 0;
}

/* Test 15: "OK" alone must NOT return OK */
static int test_ok_alone_no_match(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nOK\r\n") == CTS_RESULT_NONE);
    CHECK(!cts_is_terminal(&t));
    return 0;
}

/* Test 16: Extra '>' after prompt consumed must be ignored in SEND OK wait */
static int test_stray_prompt_ignored(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    /* Stray '>' after prompt should not cause issues */
    CHECK(feed_str(&t, "\r\n>\r\n") == CTS_RESULT_NONE);
    CHECK(feed_str(&t, "SEND OK\r\n") == CTS_RESULT_OK);
    return 0;
}

/* ===================================================================
 * TIMEOUT vs DISCONNECT
 * =================================================================== */

/* Test 17: Generic timeout (no bytes) → NOT terminal, NOT disconnect */
static int test_timeout_no_disconnect(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    /* No more bytes — simulate caller timeout */
    CHECK(!cts_is_terminal(&t));
    CHECK(cts_result(&t) == CTS_RESULT_NONE);
    return 0;
}

/* Test 18: Only CLOSED yields CTS_RESULT_CLOSED (the disconnect signal).
 *          ERROR yields CTS_RESULT_ERROR, not CLOSED. */
static int test_only_closed_is_closed(void)
{
    CipsendTransaction t;
    cts_init(&t);
    cts_start(&t);

    CHECK(feed_str(&t, "AT+CIPSEND=0,29\r\n\r\n>") == CTS_RESULT_PROMPT);
    CHECK(feed_str(&t, "\r\nERROR\r\n") == CTS_RESULT_ERROR);
    CHECK(cts_result(&t) != CTS_RESULT_CLOSED);   /* not a disconnect signal */
    return 0;
}

/* ===================================================================
 * INIT / RESET
 * =================================================================== */

/* Test 19: cts_init resets all fields */
static int test_init_resets(void)
{
    CipsendTransaction t;
    cts_init(&t);
    CHECK(t.state == 0U);
    CHECK(t.result == CTS_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * TEST RUNNER
 * =================================================================== */

static int run_all_tests(void)
{
    /* Success flow */
    if (test_full_success()) return 1;
    if (test_fragmented_prompt()) return 1;
    if (test_fragmented_send_ok()) return 1;
    if (test_recv_noise_then_send_ok()) return 1;

    /* Error detection */
    if (test_error_response()) return 1;
    if (test_busy_sending()) return 1;
    if (test_busy_processing()) return 1;
    if (test_closed_response()) return 1;
    if (test_closed_with_id()) return 1;
    if (test_timeout_no_terminal()) return 1;

    /* Transaction boundaries */
    if (test_consecutive_transactions()) return 1;
    if (test_second_waits_own_send_ok()) return 1;
    if (test_no_send_ok_before_completion()) return 1;

    /* False positive guards */
    if (test_send_okay_no_match()) return 1;
    if (test_ok_alone_no_match()) return 1;
    if (test_stray_prompt_ignored()) return 1;

    /* Timeout / disconnect */
    if (test_timeout_no_disconnect()) return 1;
    if (test_only_closed_is_closed()) return 1;

    /* Init */
    if (test_init_resets()) return 1;

    puts("PASS test_cipsend_transaction");
    return 0;
}

int main(void)
{
    return run_all_tests();
}
