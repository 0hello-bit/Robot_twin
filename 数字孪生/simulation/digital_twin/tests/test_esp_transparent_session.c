#include <assert.h>
#include <stdio.h>

#include "esp_transparent_session.h"

static void test_capability_gate_is_fail_closed(void)
{
    EspTransparentSession session;

    ets_init(&session);
    assert(ets_begin_config(&session) == 0U);
    assert(ets_state(&session) == ETS_STATE_FAILED);
    assert(ets_stop_requested(&session) == 1U);
}

static void test_transparent_lifecycle_and_guarded_exit(void)
{
    EspTransparentSession session;

    ets_init(&session);
    ets_set_capabilities(&session, 1U, 1U, 1U, 1U);
    assert(ets_begin_config(&session) == 1U);
    assert(ets_state(&session) == ETS_STATE_CONFIGURING);
    assert(ets_on_tcp_connected(&session) == 1U);
    assert(ets_state(&session) == ETS_STATE_TCP_CONNECTED);
    assert(ets_enter_transparent(&session) == 1U);
    assert(ets_state(&session) == ETS_STATE_TRANSPARENT);

    assert(ets_request_exit(&session, 1U, 0U, 1U) == 0U);
    assert(ets_request_exit(&session, 0U, 1U, 1U) == 0U);
    assert(ets_request_exit(&session, 1U, 1U, 0U) == 0U);
    assert(ets_request_exit(&session, 1U, 1U, 1U) == 1U);
    assert(ets_state(&session) == ETS_STATE_EXITING);
}

static void test_transparent_link_loss_requests_local_stop(void)
{
    EspTransparentSession session;

    ets_init(&session);
    ets_set_capabilities(&session, 1U, 1U, 1U, 1U);
    assert(ets_begin_config(&session) == 1U);
    assert(ets_on_tcp_connected(&session) == 1U);
    assert(ets_enter_transparent(&session) == 1U);
    assert(ets_on_link_loss(&session) == 1U);
    assert(ets_state(&session) == ETS_STATE_DISCONNECTED);
    assert(ets_stop_requested(&session) == 1U);
}

int main(void)
{
    test_capability_gate_is_fail_closed();
    test_transparent_lifecycle_and_guarded_exit();
    test_transparent_link_loss_requests_local_stop();
    puts("esp_transparent_session: all tests passed");
    return 0;
}
