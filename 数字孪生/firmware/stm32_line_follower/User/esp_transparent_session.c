#include "esp_transparent_session.h"

static uint8_t capabilities_allow_transparent(
    const EspTransparentCapabilities *capabilities)
{
    return (capabilities != 0
            && capabilities->known
            && capabilities->cipmode_transparent
            && capabilities->cipmux_single
            && capabilities->topology_compatible) ? 1U : 0U;
}

void ets_init(EspTransparentSession *session)
{
    if (session == 0) return;
    session->capabilities.cipmode_transparent = 0U;
    session->capabilities.cipmux_single = 0U;
    session->capabilities.topology_compatible = 0U;
    session->capabilities.known = 0U;
    session->state = ETS_STATE_IDLE;
    session->stop_requested = 0U;
}

void ets_set_capabilities(EspTransparentSession *session,
                          uint8_t cipmode_transparent,
                          uint8_t cipmux_single,
                          uint8_t topology_compatible,
                          uint8_t known)
{
    if (session == 0) return;
    session->capabilities.cipmode_transparent =
        cipmode_transparent ? 1U : 0U;
    session->capabilities.cipmux_single = cipmux_single ? 1U : 0U;
    session->capabilities.topology_compatible =
        topology_compatible ? 1U : 0U;
    session->capabilities.known = known ? 1U : 0U;
}

uint8_t ets_begin_config(EspTransparentSession *session)
{
    if (session == 0) return 0U;
    if (!capabilities_allow_transparent(&session->capabilities)) {
        session->state = ETS_STATE_FAILED;
        session->stop_requested = 1U;
        return 0U;
    }
    session->state = ETS_STATE_CONFIGURING;
    return 1U;
}

uint8_t ets_on_tcp_connected(EspTransparentSession *session)
{
    if (session == 0 || session->state != ETS_STATE_CONFIGURING) return 0U;
    session->state = ETS_STATE_TCP_CONNECTED;
    return 1U;
}

uint8_t ets_enter_transparent(EspTransparentSession *session)
{
    if (session == 0 || session->state != ETS_STATE_TCP_CONNECTED) return 0U;
    session->state = ETS_STATE_TRANSPARENT;
    return 1U;
}

uint8_t ets_request_exit(EspTransparentSession *session,
                         uint8_t motors_stopped,
                         uint8_t stream_quiet,
                         uint8_t guard_time_satisfied)
{
    if (session == 0 || session->state != ETS_STATE_TRANSPARENT) return 0U;
    if (!motors_stopped || !stream_quiet || !guard_time_satisfied) return 0U;
    session->state = ETS_STATE_EXITING;
    return 1U;
}

uint8_t ets_on_link_loss(EspTransparentSession *session)
{
    if (session == 0) return 0U;
    if (session->state != ETS_STATE_TRANSPARENT
        && session->state != ETS_STATE_TCP_CONNECTED
        && session->state != ETS_STATE_EXITING) {
        return 0U;
    }
    session->state = ETS_STATE_DISCONNECTED;
    session->stop_requested = 1U;
    return 1U;
}

uint8_t ets_state(const EspTransparentSession *session)
{
    return session == 0 ? ETS_STATE_FAILED : session->state;
}

uint8_t ets_stop_requested(const EspTransparentSession *session)
{
    return session == 0 ? 1U : session->stop_requested;
}
