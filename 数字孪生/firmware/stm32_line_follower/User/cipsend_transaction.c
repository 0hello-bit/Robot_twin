/* CIPSEND Transaction State Machine — production implementation.
 *
 * Pure-C byte-processing module for the AT+CIPSEND transaction flow:
 *   AT+CIPSEND=... → '>' prompt → payload → SEND OK / ERROR / busy / CLOSED
 *
 * The caller drives timing (timeout counters) and payload transmission.
 * This module processes one byte at a time and returns result codes.
 *
 * Thread-safety: NOT thread-safe.  Single-consumer.
 * ARMCC5-compatible POD struct, no dynamic allocation. */

#include "cipsend_transaction.h"

void cts_init(CipsendTransaction *t)
{
    t->state = 0U;                /* IDLE */
    t->result = CTS_RESULT_NONE;
    srp_init(&t->parser);
}

void cts_start(CipsendTransaction *t)
{
    t->state = 1U;                /* WAIT_PROMPT */
    t->result = CTS_RESULT_NONE;
    srp_init(&t->parser);
}

uint8_t cts_feed(CipsendTransaction *t, uint8_t byte)
{
    if (t->state == 1U) {         /* WAIT_PROMPT */
        /* Route bytes through the line scanner so ERROR / busy / CLOSED
           arriving before the '>' prompt are detected immediately instead
           of forcing a 200 ms timeout.  The AT+CIPSEND command echo
           bytes (e.g. "AT+CIPSEND=0,29") do not match any known terminal
           pattern and return SRP_RESULT_NONE. */
        uint8_t r = srp_feed(&t->parser, byte);
        if (r == SRP_RESULT_ERROR) {
            t->state = 4U;        /* FAILED */
            t->result = CTS_RESULT_ERROR;
            return CTS_RESULT_ERROR;
        }
        if (r == SRP_RESULT_CLOSED) {
            t->state = 4U;        /* FAILED */
            t->result = CTS_RESULT_CLOSED;
            return CTS_RESULT_CLOSED;
        }
        if (byte == '>') {
            t->state = 2U;        /* auto-advance to WAIT_SEND_OK */
            srp_init(&t->parser); /* fresh parser for SEND OK scan */
            return CTS_RESULT_PROMPT;
        }
        return CTS_RESULT_NONE;
    }

    if (t->state == 2U) {         /* WAIT_SEND_OK */
        uint8_t r = srp_feed(&t->parser, byte);
        if (r == SRP_RESULT_SEND_OK) {
            t->state = 3U;        /* COMPLETE */
            t->result = CTS_RESULT_OK;
            return CTS_RESULT_OK;
        }
        if (r == SRP_RESULT_ERROR) {
            t->state = 4U;        /* FAILED */
            t->result = CTS_RESULT_ERROR;
            return CTS_RESULT_ERROR;
        }
        if (r == SRP_RESULT_CLOSED) {
            t->state = 4U;        /* FAILED */
            t->result = CTS_RESULT_CLOSED;
            return CTS_RESULT_CLOSED;
        }
        return CTS_RESULT_NONE;
    }

    /* IDLE (0), COMPLETE (3), or FAILED (4): no byte processing. */
    return CTS_RESULT_NONE;
}

uint8_t cts_is_terminal(const CipsendTransaction *t)
{
    return (t->state >= 3U) ? 1U : 0U;
}

uint8_t cts_result(const CipsendTransaction *t)
{
    return (t->state >= 3U) ? t->result : CTS_RESULT_NONE;
}

uint8_t cts_state(const CipsendTransaction *t)
{
    return t->state;
}
