#ifndef CIPSEND_TRANSACTION_H
#define CIPSEND_TRANSACTION_H

#include <stdint.h>
#include "send_response_parser.h"

/* ── Result codes returned by cts_feed() ────────────────────────────── */
#define CTS_RESULT_NONE     0U   /* still in progress                       */
#define CTS_RESULT_OK       1U   /* SEND OK confirmed — transaction done    */
#define CTS_RESULT_ERROR    2U   /* ERROR or "busy" — transaction failed    */
#define CTS_RESULT_CLOSED   3U   /* CLOSED — connection closed              */
#define CTS_RESULT_PROMPT   4U   /* '>' received — caller should send data  */

/* ── Transaction context (ARMCC5-compatible POD, no dynamic allocation) */
typedef struct {
    SendResponseParser parser;   /* line scanner for SEND OK/ERROR/CLOSED   */
    uint8_t            state;    /* 0=idle, 1=wait_prompt, 2=wait_sendok,
                                    3=complete, 4=failed                   */
    uint8_t            result;   /* terminal code (valid when state >= 3)   */
} CipsendTransaction;

/* ── API ───────────────────────────────────────────────────────────── */

/* Initialise transaction context.  Call once before first use. */
void cts_init(CipsendTransaction *t);

/* Start a new CIPSEND transaction; enters WAIT_PROMPT state.
 * Call after sending "AT+CIPSEND=<id>,<len>\r\n". */
void cts_start(CipsendTransaction *t);

/* Feed one byte of receive data through the transaction state machine.
 *
 * Return values:
 *   CTS_RESULT_NONE   — in progress, no terminal event.
 *   CTS_RESULT_PROMPT — '>' prompt detected; caller should send payload
 *                       bytes, then continue calling cts_feed().
 *   CTS_RESULT_OK     — "SEND OK" confirmed (state = complete).
 *   CTS_RESULT_ERROR  — "ERROR" or "busy" (state = failed).
 *   CTS_RESULT_CLOSED — "CLOSED" (state = failed).
 *
 * After a terminal return, call cts_start() to begin a new transaction. */
uint8_t cts_feed(CipsendTransaction *t, uint8_t byte);

/* True after CTS_RESULT_OK / ERROR / CLOSED has been returned. */
uint8_t cts_is_terminal(const CipsendTransaction *t);

/* Terminal result code (CTS_RESULT_OK / ERROR / CLOSED).
 * Valid only when cts_is_terminal() is true; returns NONE otherwise. */
uint8_t cts_result(const CipsendTransaction *t);

/* Current state: 0=idle, 1=wait_prompt, 2=wait_sendok, 3=complete, 4=failed */
uint8_t cts_state(const CipsendTransaction *t);

#endif /* CIPSEND_TRANSACTION_H */
