#ifndef ESP_TRANSPARENT_SESSION_H
#define ESP_TRANSPARENT_SESSION_H

#include <stdint.h>

typedef enum {
    ETS_STATE_IDLE = 0U,
    ETS_STATE_CONFIGURING = 1U,
    ETS_STATE_TCP_CONNECTED = 2U,
    ETS_STATE_TRANSPARENT = 3U,
    ETS_STATE_EXITING = 4U,
    ETS_STATE_DISCONNECTED = 5U,
    ETS_STATE_FAILED = 6U
} EspTransparentState;

typedef struct {
    uint8_t cipmode_transparent;
    uint8_t cipmux_single;
    uint8_t topology_compatible;
    uint8_t known;
} EspTransparentCapabilities;

typedef struct {
    EspTransparentCapabilities capabilities;
    uint8_t state;
    uint8_t stop_requested;
} EspTransparentSession;

void ets_init(EspTransparentSession *session);

/* Capabilities must be observed and recorded before selecting transparent TCP. */
void ets_set_capabilities(EspTransparentSession *session,
                          uint8_t cipmode_transparent,
                          uint8_t cipmux_single,
                          uint8_t topology_compatible,
                          uint8_t known);

/* Entering configuration is fail-closed when the recorded capabilities are
 * missing or incompatible. No AT command is emitted by this module. */
uint8_t ets_begin_config(EspTransparentSession *session);
uint8_t ets_on_tcp_connected(EspTransparentSession *session);
uint8_t ets_enter_transparent(EspTransparentSession *session);

/* `+++` is legal only after motors stopped, stream quiet, and guard time. */
uint8_t ets_request_exit(EspTransparentSession *session,
                         uint8_t motors_stopped,
                         uint8_t stream_quiet,
                         uint8_t guard_time_satisfied);

/* A transparent link loss requests local safety stop before recovery. */
uint8_t ets_on_link_loss(EspTransparentSession *session);

uint8_t ets_state(const EspTransparentSession *session);
uint8_t ets_stop_requested(const EspTransparentSession *session);

#endif /* ESP_TRANSPARENT_SESSION_H */
