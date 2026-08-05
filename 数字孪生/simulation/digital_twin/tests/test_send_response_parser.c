/* Host C tests for the bounded SendResponseParser used by ESP_WaitSendOK.
 *
 * Coverage (TDD step 1 — all tests initially fail against stub):
 *   - exact "SEND OK" line
 *   - fragmented/dribbled "SEND OK"
 *   - "Recv N bytes" line preceding SEND OK (noise between lines)
 *   - "ERROR" line
 *   - "busy s..." / "busy p..." lines
 *   - "CLOSED" line
 *   - false substrings ("SEND OKAY", "SEND OK" with prefix/suffix)
 *   - CRLF handling (dribbled \r, \n)
 *   - leading/trailing noise
 *   - timeout behaviour (no terminal line, feed returns NONE)
 *   - multi-line scan resets after terminal match
 *   - consecutive terminal events
 *
 * STRICT COMPLETE LINE MATCHING:
 *   Only an exact complete line "SEND OK" triggers SRP_RESULT_SEND_OK.
 *   Lines containing "SEND OK" as a substring do NOT match —
 *   e.g. "prefix SEND OK suffix", "X SEND OK", "SEND OK X",
 *   "AT+CIPSEND=0,29,SEND OK" all return NONE.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "send_response_parser.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

/* Feed an entire string through srp_feed, return the FIRST non-NONE result.
   Returns SRP_RESULT_NONE if no terminal line was reached. */
static uint8_t feed_str(SendResponseParser *p, const char *s)
{
    uint8_t r = SRP_RESULT_NONE;
    for (; *s != '\0'; ++s) {
        r = srp_feed(p, (uint8_t)*s);
        if (r) break;
    }
    return r;
}

/* ===================================================================
 * Test 1: exact "SEND OK\r\n" triggers SRP_RESULT_SEND_OK
 * =================================================================== */
static int test_send_ok_exact_line(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "SEND OK\r\n") == SRP_RESULT_SEND_OK);
    return 0;
}

/* ===================================================================
 * Test 2: "SEND OK\n" (LF only, no CR) also works
 * =================================================================== */
static int test_send_ok_lf_only(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "SEND OK\n") == SRP_RESULT_SEND_OK);
    return 0;
}

/* ===================================================================
 * Test 3: fragmented "SEND OK" — each character fed one at a time
 * =================================================================== */
static int test_send_ok_fragmented(void)
{
    SendResponseParser p;
    srp_init(&p);
    uint8_t r = 0;
    const char *partial = "SEND OK\r\n";
    for (const char *c = partial; *c != '\0'; ++c) {
        r = srp_feed(&p, (uint8_t)*c);
    }
    CHECK(r == SRP_RESULT_SEND_OK);
    return 0;
}

/* ===================================================================
 * Test 4: "Recv 29 bytes\r\n" followed by "SEND OK\r\n"
 *         The Recv line should NOT trigger SEND OK; the next line does.
 * =================================================================== */
static int test_recv_bytes_then_send_ok(void)
{
    SendResponseParser p;
    srp_init(&p);
    /* Feed "Recv 29 bytes\r\n" — expect NONE */
    CHECK(feed_str(&p, "Recv 29 bytes\r\n") == SRP_RESULT_NONE);
    /* Then feed "SEND OK\r\n" — expect SEND_OK */
    CHECK(feed_str(&p, "SEND OK\r\n") == SRP_RESULT_SEND_OK);
    return 0;
}

/* ===================================================================
 * Test 5: interleaved CRLF noise before SEND OK
 * =================================================================== */
static int test_crlf_noise_then_send_ok(void)
{
    SendResponseParser p;
    srp_init(&p);
    const char *noise_and_ok = "\r\n\r\n\r\nSEND OK\r\n";
    CHECK(feed_str(&p, noise_and_ok) == SRP_RESULT_SEND_OK);
    return 0;
}

/* ===================================================================
 * Test 6: "ERROR\r\n" returns SRP_RESULT_ERROR
 * =================================================================== */
static int test_error_line(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "ERROR\r\n") == SRP_RESULT_ERROR);
    return 0;
}

/* ===================================================================
 * Test 7: "busy s..." line returns SRP_RESULT_ERROR
 * =================================================================== */
static int test_busy_sending(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "busy s...\r\n") == SRP_RESULT_ERROR);
    return 0;
}

/* ===================================================================
 * Test 8: "busy p..." line returns SRP_RESULT_ERROR
 * =================================================================== */
static int test_busy_processing(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "busy p...\r\n") == SRP_RESULT_ERROR);
    return 0;
}

/* ===================================================================
 * Test 9: "CLOSED\r\n" returns SRP_RESULT_CLOSED
 * =================================================================== */
static int test_closed_line(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "CLOSED\r\n") == SRP_RESULT_CLOSED);
    return 0;
}

/* ===================================================================
 * Test 10: "SEND OKAY\r\n" must NOT match (false substring guard)
 * =================================================================== */
static int test_send_okay_does_not_match(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "SEND OKAY\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * Test 11: "AT+CIPSEND\r\n" preamble noise + "SEND OK\r\n"
 *          The AT line contains "SEND" but not "SEND OK" — must not match.
 * =================================================================== */
static int test_cipsend_line_does_not_false_trigger(void)
{
    SendResponseParser p;
    srp_init(&p);
    /* The AT+CIPSEND=... echo line contains "SEND" but not "SEND OK" */
    CHECK(feed_str(&p, "AT+CIPSEND=0,29\r\n") == SRP_RESULT_NONE);
    CHECK(feed_str(&p, "\r\n") == SRP_RESULT_NONE);
    CHECK(feed_str(&p, ">") == SRP_RESULT_NONE);
    /* Now data is sent, ESP responds */
    CHECK(feed_str(&p, "\r\nSEND OK\r\n") == SRP_RESULT_SEND_OK);
    return 0;
}

/* ===================================================================
 * Test 12: timeout behaviour — if we never see a terminal line,
 *          feed() keeps returning NONE.
 * =================================================================== */
static int test_timeout_no_terminal_line(void)
{
    SendResponseParser p;
    srp_init(&p);
    /* Feed some random data */
    const char *garbage = "+IPD,0,5:hello\r\nSome other AT response\r\n";
    CHECK(feed_str(&p, garbage) == SRP_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * Test 13: "SEND OK" at end of longer line (embedded in other text)
 *          e.g. "prefix SEND OK suffix" — with STRICT matching this
 *          must NOT return SEND OK because the complete line is NOT
 *          exactly "SEND OK".
 * =================================================================== */
static int test_send_ok_embedded_in_line(void)
{
    SendResponseParser p;
    srp_init(&p);
    /* Line is "prefix SEND OK suffix", not exactly "SEND OK" */
    CHECK(feed_str(&p, "prefix SEND OK suffix\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * Test 14: trailing data after SEND OK on same line
 *          e.g. "SEND OK\r\n+IPD,..." — the SEND OK on its own line
 *          must match; the +IPD is on the NEXT line.
 * =================================================================== */
static int test_send_ok_before_other_data(void)
{
    SendResponseParser p;
    srp_init(&p);
    /* Simulate: one line has SEND OK, next line is +IPD */
    const char *mixed = "SEND OK\r\n+IPD,0,5:hello\r\n";
    uint8_t r = feed_str(&p, mixed);
    CHECK(r == SRP_RESULT_SEND_OK);
    return 0;
}

/* ===================================================================
 * Test 15: consecutive terminal events — parser must reset after
 *          returning a result so the next line is scanned fresh.
 * =================================================================== */
static int test_consecutive_terminal_events(void)
{
    SendResponseParser p;
    srp_init(&p);
    /* Two SEND OK lines in a row (unusual but should both be detected) */
    CHECK(feed_str(&p, "SEND OK\r\n") == SRP_RESULT_SEND_OK);
    /* Re-init to simulate fresh state for next transaction */
    srp_init(&p);
    CHECK(feed_str(&p, "ERROR\r\n") == SRP_RESULT_ERROR);
    return 0;
}

/* ===================================================================
 * Test 16: incomplete line without trailing \n should return NONE
 * =================================================================== */
static int test_incomplete_line_no_lf(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "SEND OK") == SRP_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * Test 17: very long line (> SRP_LINE_MAX) should not overflow
 * =================================================================== */
static int test_long_line_does_not_overflow(void)
{
    SendResponseParser p;
    srp_init(&p);
    /* Build a line much longer than SRP_LINE_MAX that ends with SEND OK */
    char buf[128];
    unsigned i;
    for (i = 0U; i < sizeof(buf) - 12U; ++i) buf[i] = 'A';
    memcpy(buf + sizeof(buf) - 12U, "SEND OK\r\n", 10U);
    buf[sizeof(buf) - 2U] = '\0'; /* safety */

    uint8_t r = SRP_RESULT_NONE;
    for (const char *c = buf; *c != '\0'; ++c) {
        r = srp_feed(&p, (uint8_t)*c);
        if (r) break;
    }
    /* The "SEND OK" may be truncated out of the buffer window,
       so we don't assert SEND_OK — just check no crash. */
    CHECK(p.pos <= SRP_LINE_MAX); /* no buffer overflow */
    return 0;
}

/* ===================================================================
 * Test 18: status line containing "CLOSED" substring
 *          e.g. "0,CLOSED\r\n" from ESP multi-client close
 * =================================================================== */
static int test_closed_with_id_prefix(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "0,CLOSED\r\n") == SRP_RESULT_CLOSED);
    return 0;
}

/* ===================================================================
 * Test 19: "SEND OK" preceded by \r\n only (no other noise)
 * =================================================================== */
static int test_send_ok_after_crlf(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "\r\nSEND OK\r\n") == SRP_RESULT_SEND_OK);
    return 0;
}

/* ===================================================================
 * Test 20: srp_init resets all fields to zero
 * =================================================================== */
static int test_init_resets_state(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(p.pos == 0U);
    CHECK(p.result == 0U);
    CHECK(p.lf_needed == 0U);
    CHECK(p.line[0] == '\0');
    return 0;
}

/* ===================================================================
 * Test 21: double-buffer scenario — SEND OK then ERROR on same parser
 *          (verify parser resets after returning result via \n)
 * =================================================================== */
static int test_send_ok_then_error_same_parser(void)
{
    SendResponseParser p;
    srp_init(&p);
    /* Feed SEND OK\r\n */
    uint8_t r1 = feed_str(&p, "SEND OK\r\n");
    CHECK(r1 == SRP_RESULT_SEND_OK);

    /* Continue feeding ERROR\r\n — parser should detect this fresh */
    uint8_t r2 = feed_str(&p, "ERROR\r\n");
    CHECK(r2 == SRP_RESULT_ERROR);
    return 0;
}

/* ===================================================================
 * Test 22: no false match on line containing "SEND" without "OK"
 * =================================================================== */
static int test_send_alone_does_not_match(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "AT+CIPSEND=0,29\r\n") == SRP_RESULT_NONE);
    CHECK(feed_str(&p, "SEND\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * Test 23: "OK" alone does not match (must be "SEND OK")
 * =================================================================== */
static int test_ok_alone_does_not_match(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "OK\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * Test 24: " FAIL\r\n" (ESP8266 error prefix) should not match any
 *          terminal unless it contains ERROR/CLOSED/busy.
 * =================================================================== */
static int test_fail_line_does_not_false_trigger(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, " FAIL\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * Test 25: "Unhandled event" or other ESP noise
 * =================================================================== */
static int test_noise_line_does_not_false_trigger(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "WIFI DISCONNECT\r\n") == SRP_RESULT_NONE);
    CHECK(feed_str(&p, "WIFI CONNECTED\r\n") == SRP_RESULT_NONE);
    CHECK(feed_str(&p, " +IPD,0,5:hello\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* ===================================================================
 *  STRICT MATCHING — new tests for Issue 1
 * =================================================================== */

/* Test 26: "X SEND OK\r\n" must NOT match (prefix before SEND OK) */
static int test_prefix_before_send_ok_fails(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "X SEND OK\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* Test 27: "SEND OK X\r\n" must NOT match (suffix after SEND OK) */
static int test_suffix_after_send_ok_fails(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "SEND OK X\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* Test 28: "AT+CIPSEND=0,29,SEND OK\r\n" must NOT match */
static int test_send_ok_embedded_in_cipsend_fails(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "AT+CIPSEND=0,29,SEND OK\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* Test 29: "SEND OK" with trailing space must NOT match (strict) */
static int test_send_ok_trailing_space_fails(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "SEND OK \r\n") == SRP_RESULT_NONE);
    return 0;
}

/* Test 30: "error detail\r\n" must NOT match (not exactly "ERROR") */
static int test_error_embedded_fails(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "error detail\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* Test 31: "BUSY\r\n" (uppercase) must NOT match (case-sensitive) */
static int test_busy_uppercase_fails(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "BUSY s...\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* Test 32: "0, CLOSED\r\n" (space after comma) must NOT match */
static int test_closed_with_space_after_comma_fails(void)
{
    SendResponseParser p;
    srp_init(&p);
    CHECK(feed_str(&p, "0, CLOSED\r\n") == SRP_RESULT_NONE);
    return 0;
}

/* ===================================================================
 * Test runner
 * =================================================================== */
static int run_all_tests(void)
{
    /* SEND OK detection — strict exact line only */
    if (test_send_ok_exact_line()) return 1;
    if (test_send_ok_lf_only()) return 1;
    if (test_send_ok_fragmented()) return 1;
    if (test_send_ok_after_crlf()) return 1;
    if (test_send_ok_before_other_data()) return 1;
    if (test_send_ok_embedded_in_line()) return 1;   /* now expects NONE */

    /* Noise/Recv then SEND OK */
    if (test_recv_bytes_then_send_ok()) return 1;
    if (test_crlf_noise_then_send_ok()) return 1;
    if (test_cipsend_line_does_not_false_trigger()) return 1;

    /* Error detection */
    if (test_error_line()) return 1;
    if (test_busy_sending()) return 1;
    if (test_busy_processing()) return 1;

    /* CLOSED detection */
    if (test_closed_line()) return 1;
    if (test_closed_with_id_prefix()) return 1;

    /* False substring guards */
    if (test_send_okay_does_not_match()) return 1;
    if (test_send_alone_does_not_match()) return 1;
    if (test_ok_alone_does_not_match()) return 1;
    if (test_fail_line_does_not_false_trigger()) return 1;
    if (test_noise_line_does_not_false_trigger()) return 1;

    /* Timeout / incomplete / overflow */
    if (test_timeout_no_terminal_line()) return 1;
    if (test_incomplete_line_no_lf()) return 1;
    if (test_long_line_does_not_overflow()) return 1;

    /* Reset and re-entry */
    if (test_init_resets_state()) return 1;
    if (test_send_ok_then_error_same_parser()) return 1;
    if (test_consecutive_terminal_events()) return 1;

    /* Strict matching edge cases */
    if (test_prefix_before_send_ok_fails()) return 1;
    if (test_suffix_after_send_ok_fails()) return 1;
    if (test_send_ok_embedded_in_cipsend_fails()) return 1;
    if (test_send_ok_trailing_space_fails()) return 1;
    if (test_error_embedded_fails()) return 1;
    if (test_busy_uppercase_fails()) return 1;
    if (test_closed_with_space_after_comma_fails()) return 1;

    puts("PASS test_send_response_parser");
    return 0;
}

int main(void)
{
    return run_all_tests();
}
