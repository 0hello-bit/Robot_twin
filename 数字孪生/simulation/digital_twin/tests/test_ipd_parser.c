#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ipd_parser.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

/* Feed a string, return 1 if COMPLETE was ever reached. */
static int reaches_complete(IpdParser *p, const char *s)
{
    for (unsigned i = 0U; s[i] != '\0'; ++i) {
        if (ipd_parser_feed(p, (uint8_t)s[i]) == IPD_STATE_COMPLETE) return 1;
    }
    return 0;
}

/* Feed a string, return 1 if ERROR was ever reached. */
static int reaches_error(IpdParser *p, const char *s)
{
    for (unsigned i = 0U; s[i] != '\0'; ++i) {
        if (ipd_parser_feed(p, (uint8_t)s[i]) == IPD_STATE_ERROR) return 1;
    }
    return 0;
}

/* ================================================================== */
static int test_complete_ipd_frame(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(reaches_complete(&p, "+IPD,0,5:hello"));
    CHECK(ipd_parser_get_id(&p) == 0UL);
    CHECK(ipd_parser_get_length(&p) == 5UL);
    return 0;
}

static int test_zero_length_payload(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(reaches_complete(&p, "+IPD,1,0:"));
    CHECK(ipd_parser_get_length(&p) == 0UL);
    return 0;
}

static int test_strict_prefix_foobar(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    /* +FOO must NOT be accepted */
    CHECK(!reaches_complete(&p, "+FOO,0,3:abc"));
    return 0;
}

static int test_strict_prefix_at_cipsend(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(!reaches_complete(&p, "AT+CIPSEND\r\n"));
    return 0;
}

static int test_resync_after_error(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    /* Garbage that partially matches then fails due to non-digit in header */
    CHECK(reaches_error(&p, "+IPD,xx,"));
    /* Now a valid frame must succeed — parser has auto-reset */
    CHECK(reaches_complete(&p, "+IPD,0,2:ok"));
    CHECK(ipd_parser_get_length(&p) == 2UL);
    return 0;
}

static int test_two_consecutive_frames(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    /* +IPD,0,2:ab+IPD,1,3:cde */
    const char *input = "+IPD,0,2:ab+IPD,1,3:cde";
    /* Feed all bytes, track last COMPLETE's id */
    for (unsigned i = 0U; input[i] != '\0'; ++i) {
        ipd_parser_feed(&p, (uint8_t)input[i]);
    }
    /* After processing all, the second frame should be the latest parsed */
    CHECK(ipd_parser_get_id(&p) == 1UL);
    CHECK(ipd_parser_get_length(&p) == 3UL);
    return 0;
}

static int test_segmented_header(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(!reaches_complete(&p, "+IP"));
    CHECK(reaches_complete(&p, "D,0,5:hello"));
    CHECK(ipd_parser_get_length(&p) == 5UL);
    return 0;
}

static int test_header_overflow(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    char buf[64];
    memcpy(buf, "+IPD,", 5);
    memset(buf + 5, 'X', 35);
    buf[40] = '\0';
    CHECK(reaches_error(&p, buf));
    return 0;
}

static int test_invalid_client_id(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(!reaches_complete(&p, "+IPD,999,5:hello"));
    return 0;
}

static int test_non_numeric_id(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(!reaches_complete(&p, "+IPD,abc,5:"));
    return 0;
}

static int test_payload_exceeds_max(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(!reaches_complete(&p, "+IPD,0,999:"));
    return 0;
}

static int test_at_noise_before_frame(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(!reaches_complete(&p, "AT+CIPSEND\r\n"));
    CHECK(reaches_complete(&p, "+IPD,0,3:abc"));
    CHECK(ipd_parser_get_length(&p) == 3UL);
    return 0;
}

static int test_damaged_prefix_then_valid(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    /* "+IP" then 'X' (mismatch at position 2), then valid frame */
    CHECK(!reaches_complete(&p, "+IPX"));
    CHECK(reaches_complete(&p, "+IPD,0,2:ok"));
    CHECK(ipd_parser_get_length(&p) == 2UL);
    return 0;
}

static int test_overlong_payload_at_runtime(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    /* +IPD,0,3:abcdef — length says 3, feed 6 extra */
    int payload_bytes = 0;
    for (unsigned i = 0U; "+IPD,0,3:abcdef"[i] != '\0'; ++i) {
        uint8_t s = ipd_parser_feed(&p, (uint8_t)"+IPD,0,3:abcdef"[i]);
        if (s == IPD_STATE_PAYLOAD) ++payload_bytes;
    }
    CHECK(payload_bytes == 2); /* 'a','b' PAYLOAD; 'c' COMPLETE; rest ignored */
    CHECK(ipd_parser_get_length(&p) == 3UL);
    return 0;
}

static int test_payload_count_matches_length(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    int payloads = 0;
    for (unsigned i = 0U; "+IPD,0,3:XYZ"[i] != '\0'; ++i) {
        uint8_t s = ipd_parser_feed(&p, (uint8_t)"+IPD,0,3:XYZ"[i]);
        if (s == IPD_STATE_PAYLOAD) ++payloads;
    }
    CHECK(payloads == 2);
    CHECK(ipd_parser_payload_count(&p) == 3UL);
    return 0;
}

static int test_missing_comma(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    /* "+IPD,0:5:hello" — missing comma between id and length */
    CHECK(!reaches_complete(&p, "+IPD,0:5:hello"));
    return 0;
}

static int test_noise_crlf_then_ipd(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(!reaches_complete(&p, "\r\n\r\n"));
    CHECK(reaches_complete(&p, "+IPD,0,2:OK"));
    CHECK(ipd_parser_get_length(&p) == 2UL);
    return 0;
}

static int test_connected_then_ipd(void)
{
    IpdParser p;
    ipd_parser_init(&p);
    CHECK(!reaches_complete(&p, "CONNECT\r\n"));
    CHECK(reaches_complete(&p, "+IPD,1,4:data"));
    CHECK(ipd_parser_get_id(&p) == 1UL);
    CHECK(ipd_parser_get_length(&p) == 4UL);
    return 0;
}

int main(void)
{
    if (test_complete_ipd_frame()) return 1;
    if (test_zero_length_payload()) return 1;
    if (test_strict_prefix_foobar()) return 1;
    if (test_strict_prefix_at_cipsend()) return 1;
    if (test_resync_after_error()) return 1;
    if (test_two_consecutive_frames()) return 1;
    if (test_segmented_header()) return 1;
    if (test_header_overflow()) return 1;
    if (test_invalid_client_id()) return 1;
    if (test_non_numeric_id()) return 1;
    if (test_payload_exceeds_max()) return 1;
    if (test_at_noise_before_frame()) return 1;
    if (test_damaged_prefix_then_valid()) return 1;
    if (test_overlong_payload_at_runtime()) return 1;
    if (test_payload_count_matches_length()) return 1;
    if (test_missing_comma()) return 1;
    if (test_noise_crlf_then_ipd()) return 1;
    if (test_connected_then_ipd()) return 1;
    puts("PASS test_ipd_parser");
    return 0;
}
