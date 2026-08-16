#include <stdio.h>
#include <string.h>

#include "esp_at_diagnostic.h"

#define CHECK(expr) do { \
    if (!(expr)) { \
        fprintf(stderr, "FAILED %s:%d: %s\n", __FILE__, __LINE__, #expr); \
        return 1; \
    } \
} while (0)

static void feed_text(EspAtDiagnostic *state, const char *text)
{
    while (*text != '\0') {
        (void)esp_at_diagnostic_feed_request_byte(state, (uint8_t)*text);
        ++text;
    }
}

static void feed_response_text(EspAtDiagnostic *state, const char *text)
{
    while (*text != '\0') {
        esp_at_diagnostic_feed_response_byte(state, (uint8_t)*text);
        ++text;
    }
}

static int start_request(EspAtDiagnostic *state, const char *nonce)
{
    char request[64];
    sprintf(request, "D,ESP_CAPS,%s\n", nonce);
    feed_text(state, request);
    CHECK(esp_at_diagnostic_request_ready(state) == 1U);
    CHECK(esp_at_diagnostic_start(state, 1000U, 1U, 1U, 1U, 0U) == 1U);
    return 0;
}

static int test_request_validation_and_command_order(void)
{
    EspAtDiagnostic state;
    const char *command;
    const char *query_id;
    uint16_t length;
    char line[ESP_AT_DIAG_RESPONSE_MAX];

    esp_at_diagnostic_init(&state);
    CHECK(start_request(&state, "n_1-2") == 0);
    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 1U);
    CHECK(strcmp(command, "AT+GMR\r\n") == 0);
    CHECK(length == (uint16_t)strlen("AT+GMR\r\n"));
    CHECK(strcmp(query_id, "GMR") == 0);
    esp_at_diagnostic_mark_command_sent(&state);

    feed_response_text(&state, "AT version: ESP-AT\r\nO");
    CHECK(esp_at_diagnostic_response_ready(&state) == 0U);
    feed_response_text(&state, "K\r\n");
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, "D,ESP_CAPS,n_1-2,GMR,OK,0,1,") == line);
    CHECK(strstr(line, "41542076657273696F6E") != 0);
    esp_at_diagnostic_consume_response(&state);

    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 1U);
    CHECK(strcmp(command, "AT+CIPMUX?\r\n") == 0);
    CHECK(strcmp(query_id, "CIPMUX") == 0);
    esp_at_diagnostic_mark_command_sent(&state);
    feed_response_text(&state, "+CIPMUX:1\r\nOK\r\n");
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    esp_at_diagnostic_consume_response(&state);

    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 1U);
    CHECK(strcmp(command, "AT+CIPMODE?\r\n") == 0);
    CHECK(strcmp(query_id, "CIPMODE") == 0);
    esp_at_diagnostic_mark_command_sent(&state);
    feed_response_text(&state, "+CIPMODE:0\nOK\n");
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    esp_at_diagnostic_consume_response(&state);

    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 1U);
    CHECK(strcmp(command, "AT+CIPDINFO?\r\n") == 0);
    CHECK(strcmp(query_id, "CIPDINFO") == 0);
    esp_at_diagnostic_mark_command_sent(&state);
    feed_response_text(&state, "+CIPDINFO:0\r\nOK\r\n");
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    esp_at_diagnostic_consume_response(&state);
    CHECK(esp_at_diagnostic_busy(&state) == 0U);
    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 0U);
    return 0;
}

static int test_all_admission_gates_reject_without_at_command(void)
{
    static const uint8_t gate_values[][4] = {
        {0U, 1U, 1U, 0U}, /* disconnected */
        {1U, 0U, 1U, 0U}, /* motion not inhibited */
        {1U, 1U, 0U, 0U}, /* CIPSEND busy */
        {1U, 1U, 1U, 1U}, /* critical frame pending */
    };
    uint8_t i;

    for (i = 0U; i < (uint8_t)(sizeof(gate_values) / sizeof(gate_values[0])); ++i) {
        EspAtDiagnostic state;
        const char *command;
        uint16_t length;
        const char *query_id;
        char line[ESP_AT_DIAG_RESPONSE_MAX];

        esp_at_diagnostic_init(&state);
        CHECK(start_request(&state, "gate") == 0);
        /* Replace the successful start above with a fresh state so each row
           exercises the requested gate, not a previous active request. */
        esp_at_diagnostic_init(&state);
        feed_text(&state, "D,ESP_CAPS,gate\n");
        CHECK(esp_at_diagnostic_start(&state, 1000U,
                                      gate_values[i][0], gate_values[i][1],
                                      gate_values[i][2], gate_values[i][3]) == 1U);
        CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 0U);
        CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
        CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
        CHECK(strstr(line, ",gate,NONE,REJECTED,0,1,\n") != 0);
        esp_at_diagnostic_consume_response(&state);
        CHECK(esp_at_diagnostic_busy(&state) == 0U);
    }
    return 0;
}

static int test_invalid_request_and_concurrent_request_are_rejected(void)
{
    EspAtDiagnostic state;
    const char *command;
    uint16_t length;
    const char *query_id;
    char line[ESP_AT_DIAG_RESPONSE_MAX];

    esp_at_diagnostic_init(&state);
    feed_text(&state, "P,unrelated\n");
    CHECK(esp_at_diagnostic_request_ready(&state) == 0U);
    feed_text(&state, "D,ESP_CAPS,bad nonce\n");
    CHECK(esp_at_diagnostic_request_ready(&state) == 1U);
    CHECK(esp_at_diagnostic_start(&state, 10U, 1U, 1U, 1U, 0U) == 1U);
    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 0U);
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, ",,NONE,REJECTED,0,1,\n") != 0);
    esp_at_diagnostic_consume_response(&state);

    esp_at_diagnostic_init(&state);
    feed_text(&state, "D,ESP_CAPS,first\n");
    CHECK(esp_at_diagnostic_start(&state, 10U, 1U, 1U, 1U, 0U) == 1U);
    CHECK(esp_at_diagnostic_busy(&state) == 1U);
    feed_text(&state, "D,ESP_CAPS,second\n");
    CHECK(esp_at_diagnostic_request_ready(&state) == 0U);
    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 1U);
    CHECK(strcmp(query_id, "GMR") == 0);
    return 0;
}

static int test_timeout_error_and_truncation_statuses(void)
{
    EspAtDiagnostic state;
    char line[ESP_AT_DIAG_RESPONSE_MAX];
    uint8_t long_response[ESP_AT_DIAG_MAX_RESPONSE_BYTES + 1U];
    uint16_t i;

    esp_at_diagnostic_init(&state);
    CHECK(start_request(&state, "error") == 0);
    esp_at_diagnostic_mark_command_sent(&state);
    feed_response_text(&state, "ERROR\r");
    CHECK(esp_at_diagnostic_response_ready(&state) == 0U);
    feed_response_text(&state, "\n");
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, ",ERROR,0,1,") != 0);
    esp_at_diagnostic_consume_response(&state);

    esp_at_diagnostic_init(&state);
    CHECK(start_request(&state, "timeout") == 0);
    esp_at_diagnostic_mark_command_sent(&state);
    esp_at_diagnostic_tick(&state, 1000U + ESP_AT_DIAG_QUERY_TIMEOUT_MS);
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, ",TIMEOUT,0,1,") != 0);
    esp_at_diagnostic_consume_response(&state);

    esp_at_diagnostic_init(&state);
    CHECK(start_request(&state, "truncate") == 0);
    esp_at_diagnostic_mark_command_sent(&state);
    for (i = 0U; i < (uint16_t)sizeof(long_response); ++i) {
        long_response[i] = (uint8_t)('a' + (i % 26U));
        esp_at_diagnostic_feed_response_byte(&state, long_response[i]);
    }
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, ",TRUNCATED,0,4,") != 0);
    CHECK(strlen(line) >= 130U);
    esp_at_diagnostic_consume_response(&state);
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    CHECK(strstr(line, ",TRUNCATED,1,4,") == 0);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, ",TRUNCATED,1,4,") != 0);
    esp_at_diagnostic_consume_response(&state);
    esp_at_diagnostic_consume_response(&state);
    esp_at_diagnostic_consume_response(&state);
    CHECK(esp_at_diagnostic_busy(&state) == 1U);
    return 0;
}

static int test_nonce_bounds_and_exact_response_chunking(void)
{
    EspAtDiagnostic state;
    char line[ESP_AT_DIAG_RESPONSE_MAX];
    uint8_t i;

    esp_at_diagnostic_init(&state);
    feed_text(&state, "D,ESP_CAPS,12345678901234567\n");
    CHECK(esp_at_diagnostic_start(&state, 0U, 1U, 1U, 1U, 0U) == 1U);
    CHECK(esp_at_diagnostic_command(&state, 0, 0, 0) == 0U);
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, ",,NONE,REJECTED,0,1,\n") != 0);
    esp_at_diagnostic_consume_response(&state);

    esp_at_diagnostic_init(&state);
    CHECK(start_request(&state, "chunk") == 0);
    esp_at_diagnostic_mark_command_sent(&state);
    for (i = 0U; i < 100U; ++i) {
        esp_at_diagnostic_feed_response_byte(&state, (uint8_t)i);
    }
    feed_response_text(&state, "\nOK\n");
    CHECK(esp_at_diagnostic_response_ready(&state) == 1U);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, ",OK,0,3,") != 0);
    esp_at_diagnostic_consume_response(&state);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, ",OK,1,3,") != 0);
    esp_at_diagnostic_consume_response(&state);
    CHECK(esp_at_diagnostic_peek_response(&state, line, sizeof(line)) > 0U);
    CHECK(strstr(line, ",OK,2,3,") != 0);
    CHECK(strstr(line, "00010203") != 0 || strstr(line, "60616263") != 0);
    esp_at_diagnostic_consume_response(&state);
    CHECK(esp_at_diagnostic_busy(&state) == 1U);
    return 0;
}

static int test_command_progress_preserves_unsent_suffix(void)
{
    EspAtDiagnostic state;
    const char *command;
    const char *query_id;
    uint16_t length;

    esp_at_diagnostic_init(&state);
    CHECK(start_request(&state, "partial") == 0);
    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 1U);
    CHECK(strcmp(command, "AT+GMR\r\n") == 0);
    CHECK(length == (uint16_t)strlen("AT+GMR\r\n"));
    esp_at_diagnostic_mark_command_byte_sent(&state, 1000U);
    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 1U);
    CHECK(command[0] == 'T');
    CHECK(length == (uint16_t)strlen("T+GMR\r\n"));
    esp_at_diagnostic_mark_command_sent_at(&state, 1001U);
    CHECK(esp_at_diagnostic_command(&state, &command, &length, &query_id) == 0U);
    return 0;
}

int main(void)
{
    int failed = 0;
    failed += test_request_validation_and_command_order();
    failed += test_all_admission_gates_reject_without_at_command();
    failed += test_invalid_request_and_concurrent_request_are_rejected();
    failed += test_timeout_error_and_truncation_statuses();
    failed += test_nonce_bounds_and_exact_response_chunking();
    failed += test_command_progress_preserves_unsent_suffix();
    if (failed != 0) {
        fprintf(stderr, "%d test group(s) FAILED\n", failed);
        return 1;
    }
    puts("PASS test_esp_at_diagnostic");
    return 0;
}
