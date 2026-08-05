/* Bounded AT response line scanner with STRICT COMPLETE LINE MATCHING.
 *
 * Detects terminal ESP8266 AT response lines:
 *   "SEND OK"  — exact line match
 *   "ERROR"    — exact line match
 *   "CLOSED"   — exact match or "<id>,CLOSED" format
 *   "busy..."  — prefix match ("busy s..." / "busy p...")
 *
 * No substring matching — a line containing "SEND OK" as a substring
 * (e.g. "prefix SEND OK suffix") is NOT recognised as a terminal line.
 */

#include "send_response_parser.h"
#include <string.h>

/* Length of "SEND OK" for the delimiter check (not used with strcmp, but
   kept as a named constant for the memcmp in CLOSED suffix matching). */
#define SEND_OK_LEN 7U

void srp_init(SendResponseParser *p)
{
    p->pos = 0U;
    p->result = 0U;
    p->lf_needed = 0U;
    p->line[0] = '\0';
}

uint8_t srp_feed(SendResponseParser *p, uint8_t byte)
{
    /* Defensive: if a previous result delivery was deferred waiting for
       a trailing \n, handle that now.  (Currently unused in normal flow,
       but kept for forward compatibility — the struct carries the fields.) */
    if (p->lf_needed) {
        if (byte == '\n') {
            uint8_t r = p->result;
            p->result = 0U;
            p->lf_needed = 0U;
            return r;
        }
        /* Unexpected byte — discard deferred result and treat this byte
           as part of the next line. */
        p->result = 0U;
        p->lf_needed = 0U;
    }

    if (byte == '\n') {
        /* End of line — scan for terminal patterns with strict matching. */
        uint8_t r = SRP_RESULT_NONE;

        if (p->pos > 0U) {
            /* --- "SEND OK" — exact complete line only --- */
            if (strcmp(p->line, "SEND OK") == 0) {
                r = SRP_RESULT_SEND_OK;
            }

            /* --- "CLOSED" — exact match or "<id>,CLOSED" format --- */
            if (r == SRP_RESULT_NONE) {
                if (strcmp(p->line, "CLOSED") == 0) {
                    r = SRP_RESULT_CLOSED;
                } else {
                    /* Check for ",CLOSED" suffix (e.g. "0,CLOSED", "1,CLOSED") */
                    uint8_t len = (uint8_t)strlen(p->line);
                    if (len >= 8U && memcmp(&p->line[len - 7U], ",CLOSED", 7U) == 0) {
                        r = SRP_RESULT_CLOSED;
                    }
                }
            }

            /* --- "ERROR" — exact complete line only --- */
            if (r == SRP_RESULT_NONE) {
                if (strcmp(p->line, "ERROR") == 0) {
                    r = SRP_RESULT_ERROR;
                }
            }

            /* --- "busy" — prefix match for "busy s...", "busy p..." --- */
            if (r == SRP_RESULT_NONE) {
                if (strncmp(p->line, "busy", 4U) == 0) {
                    r = SRP_RESULT_ERROR;
                }
            }
        }

        /* Reset line buffer for the next line. */
        p->pos = 0U;
        p->line[0] = '\0';
        return r;
    }

    /* Ignore carriage return; accumulate everything else up to max length. */
    if (byte != '\r' && p->pos < (uint8_t)(sizeof(p->line) - 1U)) {
        p->line[p->pos++] = (char)byte;
        p->line[p->pos] = '\0';
    }

    return SRP_RESULT_NONE;
}
