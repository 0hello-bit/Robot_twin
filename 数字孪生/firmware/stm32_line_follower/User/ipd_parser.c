#include "ipd_parser.h"

#include <string.h>

/* Strict prefix: "+IPD," — 5 characters. */
#define IPD_PREFIX   "+IPD,"
#define IPD_PREFIX_LEN 5U

void ipd_parser_init(IpdParser *parser)
{
    parser->state = IPD_STATE_IDLE;
    parser->header_len = 0U;
    parser->payload_remaining = 0U;
    parser->ipd_id = 0UL;
    parser->ipd_length = 0UL;
    parser->match_position = 0U;
}

static uint8_t is_digit(char c)
{
    return (c >= '0' && c <= '9');
}

static unsigned long parse_decimal(const char *text, uint8_t *ok)
{
    unsigned long value = 0UL;
    if (*text == '\0') {
        *ok = 0U;
        return 0UL;
    }
    while (*text != '\0') {
        if (!is_digit(*text)) {
            *ok = 0U;
            return 0UL;
        }
        value = value * 10UL + (unsigned long)(*text - '0');
        if (value > 65535UL) {
            *ok = 0U;
            return 0UL;
        }
        ++text;
    }
    *ok = 1U;
    return value;
}

/* Reset to IDLE so the parser can re-sync on the next byte. */
static void go_idle(IpdParser *parser)
{
    parser->state = IPD_STATE_IDLE;
    parser->header_len = 0U;
    parser->payload_remaining = 0U;
    parser->match_position = 0U;
}

uint8_t ipd_parser_feed(IpdParser *parser, uint8_t byte)
{
    /* COMPLETE and ERROR auto-transition to IDLE on next byte. */
    if (parser->state == IPD_STATE_COMPLETE ||
        parser->state == IPD_STATE_ERROR) {
        go_idle(parser);
        /* Fall through to process this byte fresh. */
    }

    switch (parser->state) {

    case IPD_STATE_IDLE:
        /* Strict prefix matching: "+IPD," */
        if (byte == (uint8_t)IPD_PREFIX[parser->match_position]) {
            ++parser->match_position;
            if (parser->match_position == IPD_PREFIX_LEN) {
                /* Full prefix matched — transition to HEADER.  The prefix
                   itself is NOT stored in header_buf; only the tail after
                   "+IPD," goes there. */
                parser->state = IPD_STATE_HEADER;
                parser->header_len = 0U;
            }
        } else {
            /* Mismatch — reset prefix matcher. */
            parser->match_position = 0U;
            /* If the current byte is '+', start matching from position 1. */
            if (byte == '+') {
                parser->match_position = 1U;
            }
        }
        return IPD_STATE_IDLE;

    case IPD_STATE_HEADER:
        /* Only digits, comma, and colon are legal in the header body. */
        if (!is_digit((char)byte) && byte != ',' && byte != ':') {
            go_idle(parser);
            return IPD_STATE_ERROR;
        }
        if (parser->header_len >= IPD_HEADER_MAX - 1U) {
            go_idle(parser);
            return IPD_STATE_ERROR;
        }
        parser->header_buf[parser->header_len++] = (char)byte;
        parser->header_buf[parser->header_len] = '\0';

        if (byte == ':') {
            /* Header format after "+IPD,":  <id>,<length>:
               So header_buf contains "0,96:" or "0,5:" */
            const char *comma;
            char id_text[16], len_text[16];
            unsigned long parsed_id, parsed_len;
            uint8_t ok;
            size_t field_len;

            comma = strchr(parser->header_buf, ',');
            if (comma == NULL) { go_idle(parser); return IPD_STATE_ERROR; }

            /* Extract id field (before comma) */
            field_len = (size_t)(comma - parser->header_buf);
            if (field_len >= sizeof(id_text)) field_len = sizeof(id_text) - 1U;
            memcpy(id_text, parser->header_buf, field_len);
            id_text[field_len] = '\0';

            /* Extract length field (between comma and colon) */
            {
                const char *colon = strchr(comma + 1, ':');
                if (colon == NULL || colon <= comma + 1) {
                    go_idle(parser);
                    return IPD_STATE_ERROR;
                }
                field_len = (size_t)(colon - comma - 1);
                if (field_len >= sizeof(len_text)) field_len = sizeof(len_text) - 1U;
                memcpy(len_text, comma + 1, field_len);
                len_text[field_len] = '\0';
            }

            parsed_id = parse_decimal(id_text, &ok);
            if (!ok || parsed_id > IPD_CLIENT_ID_MAX) {
                go_idle(parser);
                return IPD_STATE_ERROR;
            }
            parsed_len = parse_decimal(len_text, &ok);
            if (!ok) {
                go_idle(parser);
                return IPD_STATE_ERROR;
            }
            if (parsed_len > IPD_PAYLOAD_MAX) {
                go_idle(parser);
                return IPD_STATE_ERROR;
            }

            parser->ipd_id = parsed_id;
            parser->ipd_length = parsed_len;

            if (parsed_len == 0UL) {
                /* Zero-length payload: complete immediately.
                   Set ipd_length to 0 so payload_count is meaningful. */
                go_idle(parser);
                parser->state = IPD_STATE_COMPLETE;
                return IPD_STATE_COMPLETE;
            }

            parser->payload_remaining = (uint16_t)parsed_len;
            parser->state = IPD_STATE_PAYLOAD;
            /* Return HEADER so caller knows the ':' ended the header;
               subsequent bytes will be PAYLOAD or COMPLETE. */
            return IPD_STATE_HEADER;
        }
        return IPD_STATE_HEADER;

    case IPD_STATE_PAYLOAD:
        if (parser->payload_remaining == 0U) {
            go_idle(parser);
            return IPD_STATE_ERROR;
        }
        --parser->payload_remaining;
        if (parser->payload_remaining == 0U) {
            /* This was the last payload byte. */
            parser->state = IPD_STATE_COMPLETE;
            return IPD_STATE_COMPLETE;
        }
        return IPD_STATE_PAYLOAD;

    default:
        go_idle(parser);
        return IPD_STATE_IDLE;
    }
}

unsigned long ipd_parser_get_id(const IpdParser *parser)
{
    return parser->ipd_id;
}

unsigned long ipd_parser_get_length(const IpdParser *parser)
{
    return parser->ipd_length;
}

uint16_t ipd_parser_payload_count(const IpdParser *parser)
{
    if (parser->state == IPD_STATE_COMPLETE) {
        return (uint16_t)parser->ipd_length;
    }
    return 0U;
}
