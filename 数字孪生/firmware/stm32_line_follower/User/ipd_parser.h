#ifndef IPD_PARSER_H
#define IPD_PARSER_H

#include <stdint.h>

/* Maximum +IPD,<id>,<length>: header length we can accumulate.
   e.g. "+IPD,0,96:"  = 12 chars — generous margin. */
#define IPD_HEADER_MAX 32U

/* Maximum expected +IPD payload length (matches TWIN_CONTROL_LINE_MAX). */
#define IPD_PAYLOAD_MAX 96U

/* Maximum client ID that the parser accepts. */
#define IPD_CLIENT_ID_MAX 255U

/* Parser states */
#define IPD_STATE_IDLE      0U
#define IPD_STATE_HEADER    1U
#define IPD_STATE_PAYLOAD   2U
#define IPD_STATE_COMPLETE  3U
#define IPD_STATE_ERROR     4U

typedef struct {
    uint8_t state;
    char header_buf[IPD_HEADER_MAX];
    uint8_t header_len;
    uint16_t payload_remaining;
    unsigned long ipd_id;
    unsigned long ipd_length;
    uint8_t match_position;   /* for strict "+IPD," prefix matching */
} IpdParser;

/* Initialise/reset the parser to IDLE. */
void ipd_parser_init(IpdParser *parser);

/* Feed one byte.  Returns:
     IPD_STATE_IDLE      — still waiting for +IPD header, or junk discarded
     IPD_STATE_HEADER    — accumulating header bytes
     IPD_STATE_PAYLOAD   — in payload; byte was consumed
     IPD_STATE_COMPLETE  — payload completed (last payload byte processed)
     IPD_STATE_ERROR     — malformed header, invalid client ID, overlength, etc.
   After COMPLETE or ERROR the parser automatically transitions back to IDLE
   on the NEXT byte, re-synchronising for subsequent frames.  The caller must
   check the return value every byte.
*/
uint8_t ipd_parser_feed(IpdParser *parser, uint8_t byte);

/* After COMPLETE, the parsed IPD id and length fields. */
unsigned long ipd_parser_get_id(const IpdParser *parser);
unsigned long ipd_parser_get_length(const IpdParser *parser);

/* The number of payload bytes that were delivered since PAYLOAD was entered.
   Only meaningful after COMPLETE. */
uint16_t ipd_parser_payload_count(const IpdParser *parser);

#endif /* IPD_PARSER_H */
