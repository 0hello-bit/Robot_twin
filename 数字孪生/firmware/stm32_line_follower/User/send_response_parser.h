#ifndef SEND_RESPONSE_PARSER_H
#define SEND_RESPONSE_PARSER_H

#include <stdint.h>

/* Maximum line buffer length for matching SEND OK / ERROR / busy / CLOSED.
   Must hold the longest expected response line plus NUL terminator. */
#define SRP_LINE_MAX  28U

/* Terminal result codes returned by srp_feed() */
#define SRP_RESULT_NONE     0U     /* no terminal line detected yet        */
#define SRP_RESULT_SEND_OK  1U     /* "SEND OK" confirmed                  */
#define SRP_RESULT_ERROR    2U     /* "ERROR" or "busy" line detected      */
#define SRP_RESULT_CLOSED   3U     /* "CLOSED" line detected               */

/* The parser context.  Call srp_init() before first use. */
typedef struct {
    char   line[SRP_LINE_MAX];     /* partial AT response line buffer       */
    uint8_t pos;                   /* current write position in line[]      */
    uint8_t result;                /* pending result to return after \n     */
    uint8_t lf_needed;             /* non-zero if result is pending \n      */
} SendResponseParser;

/* Initialise the parser to a clean state. */
void srp_init(SendResponseParser *p);

/* Feed one byte through the line scanner.
 *
 * Returns a non-zero SRP_RESULT_* value ONLY when a complete \n-terminated
 * line has been recognised as a terminal response.  After a terminal return,
 * the parser resets its line accumulator so remaining bytes (noise on the
 * same or next line) continue to be scanned without losing the result.
 *
 * Return values:
 *   0 (SRP_RESULT_NONE)     — scanning, no terminal line yet.
 *   1 (SRP_RESULT_SEND_OK)  — "SEND OK" confirmed.
 *   2 (SRP_RESULT_ERROR)    — "ERROR" or "busy" line detected.
 *   3 (SRP_RESULT_CLOSED)   — "CLOSED" line detected.
 */
uint8_t srp_feed(SendResponseParser *p, uint8_t byte);

#endif /* SEND_RESPONSE_PARSER_H */
