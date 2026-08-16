#include "esp_at_diagnostic.h"

#include <stdio.h>
#include <string.h>

#define ESP_AT_DIAG_QUERY_COUNT 4U

static const char *const s_commands[ESP_AT_DIAG_QUERY_COUNT] = {
    "AT+GMR\r\n",
    "AT+CIPMUX?\r\n",
    "AT+CIPMODE?\r\n",
    "AT+CIPDINFO?\r\n"
};

static const char *const s_query_ids[ESP_AT_DIAG_QUERY_COUNT] = {
    "GMR", "CIPMUX", "CIPMODE", "CIPDINFO"
};

static uint8_t command_length(uint8_t query_index)
{
    if (query_index >= ESP_AT_DIAG_QUERY_COUNT) return 0U;
    return (uint8_t)strlen(s_commands[query_index]);
}

static const char *status_text(uint8_t status)
{
    switch (status) {
    case ESP_AT_DIAG_STATUS_OK: return "OK";
    case ESP_AT_DIAG_STATUS_ERROR: return "ERROR";
    case ESP_AT_DIAG_STATUS_TIMEOUT: return "TIMEOUT";
    case ESP_AT_DIAG_STATUS_TRUNCATED: return "TRUNCATED";
    default: return "REJECTED";
    }
}

static uint8_t is_alpha_numeric(uint8_t byte)
{
    return (uint8_t)(((byte >= (uint8_t)'0' && byte <= (uint8_t)'9') ||
                      (byte >= (uint8_t)'A' && byte <= (uint8_t)'Z') ||
                      (byte >= (uint8_t)'a' && byte <= (uint8_t)'z')) ? 1U : 0U);
}

static uint8_t is_nonce_byte(uint8_t byte)
{
    return (uint8_t)(is_alpha_numeric(byte) || byte == (uint8_t)'_' ||
                     byte == (uint8_t)'-');
}

static uint8_t has_prefix(const uint8_t *value, uint16_t length,
                          const char *prefix)
{
    uint16_t prefix_len = (uint16_t)strlen(prefix);
    if (length < prefix_len) return 0U;
    return (memcmp(value, prefix, prefix_len) == 0) ? 1U : 0U;
}

static uint8_t parse_request(EspAtDiagnostic *state)
{
    static const char prefix[] = "D,ESP_CAPS,";
    uint16_t prefix_len = (uint16_t)(sizeof(prefix) - 1U);
    uint16_t i;
    uint16_t nonce_len;

    state->request_valid = 0U;
    state->nonce_len = 0U;
    state->nonce[0] = '\0';
    if (state->request_overflow || state->request_len < prefix_len + 1U) {
        return 0U;
    }
    if (!has_prefix(state->request_buf, state->request_len, prefix)) {
        return 0U;
    }

    nonce_len = (uint16_t)(state->request_len - prefix_len);
    if (nonce_len == 0U || nonce_len > 16U) return 0U;
    for (i = 0U; i < nonce_len; ++i) {
        if (!is_nonce_byte(state->request_buf[prefix_len + i])) {
            state->nonce[0] = '\0';
            state->nonce_len = 0U;
            return 0U;
        }
        state->nonce[i] = state->request_buf[prefix_len + i];
    }
    state->nonce[nonce_len] = '\0';
    state->nonce_len = (uint8_t)nonce_len;
    state->request_valid = 1U;
    return 1U;
}

static void clear_request(EspAtDiagnostic *state)
{
    state->request_len = 0U;
    state->request_overflow = 0U;
    state->request_ready = 0U;
    state->request_valid = 0U;
    state->nonce_len = 0U;
    state->nonce[0] = '\0';
}

static void clear_query_response(EspAtDiagnostic *state)
{
    state->command_sent = 0U;
    state->command_offset = 0U;
    state->raw_len = 0U;
    state->raw_truncated = 0U;
    state->line_len = 0U;
    state->response_ready = 0U;
    state->response_rejected = 0U;
    state->response_status = ESP_AT_DIAG_STATUS_OK;
    state->response_chunk_index = 0U;
    state->response_chunk_count = 0U;
}

static void prepare_response(EspAtDiagnostic *state, uint8_t status)
{
    uint16_t chunks;

    state->response_status = status;
    state->response_rejected = 0U;
    state->response_chunk_index = 0U;
    if (state->raw_len == 0U) {
        chunks = 1U;
    } else {
        chunks = (uint16_t)((state->raw_len +
                            ESP_AT_DIAG_RESPONSE_CHUNK_BYTES - 1U) /
                           ESP_AT_DIAG_RESPONSE_CHUNK_BYTES);
    }
    state->response_chunk_count = (uint8_t)chunks;
    state->response_ready = 1U;
}

static void prepare_rejected(EspAtDiagnostic *state)
{
    state->active = 0U;
    state->command_sent = 0U;
    state->raw_len = 0U;
    state->raw_truncated = 0U;
    state->response_status = ESP_AT_DIAG_STATUS_REJECTED;
    state->response_rejected = 1U;
    state->response_ready = 1U;
    state->response_chunk_index = 0U;
    state->response_chunk_count = 1U;
}

static uint8_t line_is_status(const EspAtDiagnostic *state,
                              uint8_t *status)
{
    uint8_t len = state->line_len;
    if (len > 0U && state->line_buf[len - 1U] == (uint8_t)'\r') {
        --len;
    }
    if (len == 2U && state->line_buf[0] == (uint8_t)'O' &&
        state->line_buf[1] == (uint8_t)'K') {
        *status = ESP_AT_DIAG_STATUS_OK;
        return 1U;
    }
    if (len == 5U && state->line_buf[0] == (uint8_t)'E' &&
        state->line_buf[1] == (uint8_t)'R' &&
        state->line_buf[2] == (uint8_t)'R' &&
        state->line_buf[3] == (uint8_t)'O' &&
        state->line_buf[4] == (uint8_t)'R') {
        *status = ESP_AT_DIAG_STATUS_ERROR;
        return 1U;
    }
    return 0U;
}

void esp_at_diagnostic_init(EspAtDiagnostic *state)
{
    memset(state, 0, sizeof(*state));
}

uint8_t esp_at_diagnostic_feed_request_byte(EspAtDiagnostic *state,
                                            uint8_t byte)
{
    static const char prefix[] = "D,ESP_CAPS,";
    if (state->active || state->response_ready || state->request_ready) {
        return 0U;
    }
    if (byte == (uint8_t)'\n') {
        if (has_prefix(state->request_buf, state->request_len, prefix)) {
            state->request_ready = 1U;
            (void)parse_request(state);
        } else {
            clear_request(state);
        }
        return 1U;
    }
    if (state->request_len < ESP_AT_DIAG_REQUEST_MAX - 1U) {
        state->request_buf[state->request_len++] = byte;
    } else {
        state->request_overflow = 1U;
    }
    return 0U;
}

uint8_t esp_at_diagnostic_request_ready(const EspAtDiagnostic *state)
{
    return state->request_ready;
}

uint8_t esp_at_diagnostic_start(EspAtDiagnostic *state, uint32_t now_ms,
                                uint8_t connected,
                                uint8_t motion_inhibited,
                                uint8_t cipsend_idle,
                                uint8_t critical_pending)
{
    uint8_t accepted;
    uint8_t saved_nonce[17];
    uint8_t saved_nonce_len;

    if (!state->request_ready || state->active || state->response_ready) {
        return 0U;
    }
    accepted = state->request_valid;
    saved_nonce_len = state->nonce_len;
    memcpy(saved_nonce, state->nonce, sizeof(saved_nonce));
    clear_request(state);
    state->nonce_len = saved_nonce_len;
    memcpy(state->nonce, saved_nonce, sizeof(state->nonce));
    if (!accepted || !connected || !motion_inhibited || !cipsend_idle ||
        critical_pending) {
        prepare_rejected(state);
        return 1U;
    }

    state->active = 1U;
    state->query_index = 0U;
    state->deadline_ms = now_ms + ESP_AT_DIAG_QUERY_TIMEOUT_MS;
    clear_query_response(state);
    return 1U;
}

uint8_t esp_at_diagnostic_command(const EspAtDiagnostic *state,
                                  const char **command,
                                  uint16_t *length,
                                  const char **query_id)
{
    if (!state->active || state->response_ready || state->command_sent ||
        state->query_index >= ESP_AT_DIAG_QUERY_COUNT || command == 0 ||
        length == 0 || query_id == 0) {
        return 0U;
    }
    *command = s_commands[state->query_index] + state->command_offset;
    *length = (uint16_t)command_length(state->query_index) -
              (uint16_t)state->command_offset;
    *query_id = s_query_ids[state->query_index];
    return 1U;
}

void esp_at_diagnostic_mark_command_sent_at(EspAtDiagnostic *state,
                                            uint32_t now_ms)
{
    if (!state->active || state->response_ready || state->command_sent) return;
    state->command_offset = command_length(state->query_index);
    state->command_sent = 1U;
    state->deadline_ms = now_ms + ESP_AT_DIAG_QUERY_TIMEOUT_MS;
}

void esp_at_diagnostic_mark_command_sent(EspAtDiagnostic *state)
{
    if (!state->active || state->response_ready || state->command_sent) return;
    state->command_offset = command_length(state->query_index);
    state->command_sent = 1U;
}

void esp_at_diagnostic_mark_command_byte_sent(EspAtDiagnostic *state,
                                              uint32_t now_ms)
{
    uint8_t length;
    if (!state->active || state->response_ready || state->command_sent) return;
    length = command_length(state->query_index);
    if (state->command_offset >= length) return;
    state->command_offset++;
    if (state->command_offset == length) {
        state->command_sent = 1U;
        state->deadline_ms = now_ms + ESP_AT_DIAG_QUERY_TIMEOUT_MS;
    }
}

void esp_at_diagnostic_feed_response_byte(EspAtDiagnostic *state,
                                          uint8_t byte)
{
    uint8_t status;

    if (!state->active || !state->command_sent || state->response_ready) {
        return;
    }
    if (state->raw_len < ESP_AT_DIAG_MAX_RESPONSE_BYTES) {
        state->raw_response[state->raw_len++] = byte;
    } else {
        state->raw_truncated = 1U;
        prepare_response(state, ESP_AT_DIAG_STATUS_TRUNCATED);
        return;
    }

    if (byte == (uint8_t)'\n') {
        if (line_is_status(state, &status)) {
            prepare_response(state, status);
        }
        state->line_len = 0U;
    } else if (state->line_len < (uint8_t)sizeof(state->line_buf)) {
        state->line_buf[state->line_len++] = byte;
    } else {
        state->line_len = 0U;
    }
}

void esp_at_diagnostic_tick(EspAtDiagnostic *state, uint32_t now_ms)
{
    if (!state->active || !state->command_sent || state->response_ready) return;
    if ((int32_t)(now_ms - state->deadline_ms) >= 0) {
        prepare_response(state, ESP_AT_DIAG_STATUS_TIMEOUT);
    }
}

uint8_t esp_at_diagnostic_response_ready(const EspAtDiagnostic *state)
{
    return state->response_ready;
}

static uint8_t hex_digit(uint8_t value)
{
    value &= 0x0FU;
    return (value < 10U) ? (uint8_t)('0' + value)
                         : (uint8_t)('A' + value - 10U);
}

uint16_t esp_at_diagnostic_peek_response(const EspAtDiagnostic *state,
                                         char *output,
                                         uint16_t capacity)
{
    uint16_t pos = 0U;
    uint16_t start;
    uint16_t count;
    uint16_t i;
    int written;

    if (!state->response_ready || output == 0 || capacity == 0U) return 0U;
    if (state->response_rejected) {
        written = sprintf(output, "D,ESP_CAPS,%s,NONE,REJECTED,0,1,\n",
                          state->nonce);
        if (written < 0 || (uint16_t)written >= capacity) return 0U;
        return (uint16_t)written;
    }

    written = sprintf(output, "D,ESP_CAPS,%s,%s,%s,%u,%u,",
                      state->nonce, s_query_ids[state->query_index],
                      status_text(state->response_status),
                      (unsigned)state->response_chunk_index,
                      (unsigned)state->response_chunk_count);
    if (written < 0 || (uint16_t)written >= capacity) return 0U;
    pos = (uint16_t)written;
    start = (uint16_t)state->response_chunk_index *
            ESP_AT_DIAG_RESPONSE_CHUNK_BYTES;
    count = state->raw_len > start ? (uint16_t)(state->raw_len - start) : 0U;
    if (count > ESP_AT_DIAG_RESPONSE_CHUNK_BYTES) {
        count = ESP_AT_DIAG_RESPONSE_CHUNK_BYTES;
    }
    for (i = 0U; i < count; ++i) {
        if ((uint16_t)(pos + 2U) >= capacity) return 0U;
        output[pos++] = (char)hex_digit(
            (uint8_t)(state->raw_response[start + i] >> 4));
        output[pos++] = (char)hex_digit(state->raw_response[start + i]);
    }
    if ((uint16_t)(pos + 2U) >= capacity) return 0U;
    output[pos++] = '\r';
    output[pos++] = '\n';
    output[pos] = '\0';
    return pos;
}

void esp_at_diagnostic_consume_response(EspAtDiagnostic *state)
{
    if (!state->response_ready) return;
    if (state->response_rejected) {
        clear_query_response(state);
        return;
    }
    if ((uint8_t)(state->response_chunk_index + 1U) <
        state->response_chunk_count) {
        state->response_chunk_index++;
        return;
    }
    state->response_ready = 0U;
    state->response_chunk_index = 0U;
    state->response_chunk_count = 0U;
    if ((uint8_t)(state->query_index + 1U) >= ESP_AT_DIAG_QUERY_COUNT) {
        state->active = 0U;
        state->command_sent = 0U;
        return;
    }
    state->query_index++;
    clear_query_response(state);
}

uint8_t esp_at_diagnostic_busy(const EspAtDiagnostic *state)
{
    return (state->active || state->response_ready) ? 1U : 0U;
}
