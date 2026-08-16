#ifndef ESP_AT_DIAGNOSTIC_H
#define ESP_AT_DIAGNOSTIC_H

#include <stdint.h>

#define ESP_AT_DIAG_MAX_RESPONSE_BYTES 192U
#define ESP_AT_DIAG_RESPONSE_CHUNK_BYTES 48U
#define ESP_AT_DIAG_QUERY_TIMEOUT_MS 1500U
#define ESP_AT_DIAG_REQUEST_MAX 64U
#define ESP_AT_DIAG_RESPONSE_MAX 512U

typedef struct {
    uint8_t request_buf[ESP_AT_DIAG_REQUEST_MAX];
    uint16_t request_len;
    uint8_t request_overflow;
    uint8_t request_ready;
    uint8_t request_valid;
    uint8_t nonce[17];
    uint8_t nonce_len;

    uint8_t active;
    uint8_t command_sent;
    uint8_t command_offset;
    uint8_t query_index;
    uint32_t deadline_ms;

    uint8_t raw_response[ESP_AT_DIAG_MAX_RESPONSE_BYTES];
    uint16_t raw_len;
    uint8_t raw_truncated;
    uint8_t line_buf[8];
    uint8_t line_len;

    uint8_t response_ready;
    uint8_t response_rejected;
    uint8_t response_status;
    uint8_t response_chunk_index;
    uint8_t response_chunk_count;
} EspAtDiagnostic;

#define ESP_AT_DIAG_STATUS_OK        0U
#define ESP_AT_DIAG_STATUS_ERROR     1U
#define ESP_AT_DIAG_STATUS_TIMEOUT   2U
#define ESP_AT_DIAG_STATUS_TRUNCATED 3U
#define ESP_AT_DIAG_STATUS_REJECTED  4U

void esp_at_diagnostic_init(EspAtDiagnostic *state);
uint8_t esp_at_diagnostic_feed_request_byte(EspAtDiagnostic *state,
                                            uint8_t byte);
uint8_t esp_at_diagnostic_request_ready(const EspAtDiagnostic *state);
uint8_t esp_at_diagnostic_start(EspAtDiagnostic *state, uint32_t now_ms,
                                uint8_t connected,
                                uint8_t motion_inhibited,
                                uint8_t cipsend_idle,
                                uint8_t critical_pending);

uint8_t esp_at_diagnostic_command(const EspAtDiagnostic *state,
                                  const char **command,
                                  uint16_t *length,
                                  const char **query_id);
void esp_at_diagnostic_mark_command_sent(EspAtDiagnostic *state);
void esp_at_diagnostic_mark_command_byte_sent(EspAtDiagnostic *state,
                                              uint32_t now_ms);
void esp_at_diagnostic_mark_command_sent_at(EspAtDiagnostic *state,
                                            uint32_t now_ms);
void esp_at_diagnostic_feed_response_byte(EspAtDiagnostic *state,
                                          uint8_t byte);
void esp_at_diagnostic_tick(EspAtDiagnostic *state, uint32_t now_ms);

uint8_t esp_at_diagnostic_response_ready(const EspAtDiagnostic *state);
uint16_t esp_at_diagnostic_peek_response(const EspAtDiagnostic *state,
                                         char *output,
                                         uint16_t capacity);
void esp_at_diagnostic_consume_response(EspAtDiagnostic *state);
uint8_t esp_at_diagnostic_busy(const EspAtDiagnostic *state);

#endif /* ESP_AT_DIAGNOSTIC_H */
