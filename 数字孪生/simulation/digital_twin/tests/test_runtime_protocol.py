"""Behavioral tests for the bounded runtime PID protocol.

Each test names the production break it must catch.  The expected frame values
are hand-derived so the tests do not reuse the implementation under test.
"""

import pytest
from datetime import datetime, timezone

from real_world.runtime_protocol import (
    KD_MAX,
    KD_MIN,
    KD_STEP_MAX,
    KI_MAX,
    KI_MIN,
    KI_STEP_MAX,
    KP_MAX,
    KP_MIN,
    KP_STEP_MAX,
    ParameterAck,
    ParameterCommand,
    ProtocolError,
    RunCommand,
    RuntimeParameterBoundary,
    frame,
    make_runtime_identifier,
    parse_ack,
    parse_command,
    parse_status,
    validate_parameter_update,
)


def test_runtime_identifier_avoids_collisions_within_one_output_millisecond():
    """Catches IDs that truncate distinct same-ms timestamps to one value."""
    first_time = datetime(2026, 8, 6, 10, 0, 0, 123100, tzinfo=timezone.utc)
    second_time = datetime(2026, 8, 6, 10, 0, 0, 123900, tzinfo=timezone.utc)

    first = make_runtime_identifier("q", now=first_time)
    second = make_runtime_identifier("q", now=second_time)

    assert first != second


def test_parameter_packet_round_trip_and_checksum():
    """Catches a parser/encoder mismatch or a checksum that omits body bytes."""
    packet = ParameterCommand("camp-001", 3, 35.0, 0.0, 10.0, 680)
    assert packet.encode() == "P,camp-001,3,35,0,10,680,69\n"
    assert parse_command(packet.encode()) == packet


def test_parameter_packet_rejects_out_of_range_speed():
    """Catches an encoder that can emit a speed unsafe for the firmware."""
    with pytest.raises(ProtocolError, match="speed_max"):
        ParameterCommand("camp-001", 3, 35.0, 0.0, 10.0, 900).encode()


def test_ack_requires_matching_campaign_and_version():
    """Catches ACK parsing that loses the campaign/version correlation fields."""
    ack = parse_ack("A,camp-001,3,APPLIED,OK,30\n")
    assert ack.campaign_id == "camp-001"
    assert ack.version == 3


def test_command_parser_rejects_tampered_checksum():
    """Catches a command parser that accepts data altered after checksum creation."""
    with pytest.raises(ProtocolError, match="checksum"):
        parse_command("P,camp-001,3,35,0,10,680,00\n")


def test_run_command_round_trip_preserves_stop_action():
    """Catches a run-command parser that accepts only parameter frames."""
    command = RunCommand("camp-001", "run-007", "STOP")
    assert parse_command(command.encode()) == command


def test_status_parser_preserves_run_identity_and_tick():
    """Catches status parsing that loses the run identity or time evidence."""
    status = parse_status("S,camp-001,run-007,stopped,operator_stop,42,27\n")
    assert (status.campaign_id, status.run_id, status.tick_ms) == ("camp-001", "run-007", 42)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kp", KP_MIN - 0.1),
        ("kp", KP_MAX + 0.1),
        ("ki", KI_MIN - 0.1),
        ("ki", KI_MAX + 0.1),
        ("kd", KD_MIN - 0.1),
        ("kd", KD_MAX + 0.1),
    ],
)
def test_parameter_encoder_rejects_gain_outside_firmware_bounds(field, value):
    """Catches a PC-side encoder that emits gain values the firmware must reject."""
    values = {"kp": 35.0, "ki": 0.0, "kd": 10.0}
    values[field] = value
    with pytest.raises(ProtocolError, match=field):
        ParameterCommand("camp-001", 3, values["kp"], values["ki"], values["kd"], 680).encode()


@pytest.mark.parametrize(
    "baseline_kp,candidate_kp,should_pass",
    [
        (35.0, 40.0, True),
        (35.0, 40.1, False),
        (35.0, 30.0, True),
        (35.0, 29.9, False),
    ],
)
def test_parameter_update_kp_step(baseline_kp, candidate_kp, should_pass):
    """Catches a kp step validator that allows or blocks the exact +- KP_STEP_MAX."""
    baseline = ParameterCommand("camp-001", 1, baseline_kp, 0.0, 10.0, 680)
    candidate = ParameterCommand("camp-001", 2, candidate_kp, 0.0, 10.0, 680)
    if should_pass:
        validate_parameter_update(candidate, baseline)
    else:
        with pytest.raises(ProtocolError, match="kp step"):
            validate_parameter_update(candidate, baseline)


@pytest.mark.parametrize(
    "baseline_ki,candidate_ki,should_pass",
    [
        (0.0, 1.0, True),
        (0.0, 1.1, False),
        (2.0, 1.0, True),
        (2.0, 0.9, False),
    ],
)
def test_parameter_update_ki_step(baseline_ki, candidate_ki, should_pass):
    """Catches a ki step validator that allows or blocks the exact +- KI_STEP_MAX."""
    baseline = ParameterCommand("camp-001", 1, 35.0, baseline_ki, 10.0, 680)
    candidate = ParameterCommand("camp-001", 2, 35.0, candidate_ki, 10.0, 680)
    if should_pass:
        validate_parameter_update(candidate, baseline)
    else:
        with pytest.raises(ProtocolError, match="ki step"):
            validate_parameter_update(candidate, baseline)


@pytest.mark.parametrize(
    "baseline_kd,candidate_kd,should_pass",
    [
        (10.0, 13.0, True),
        (10.0, 13.1, False),
        (10.0, 7.0, True),
        (10.0, 6.9, False),
    ],
)
def test_parameter_update_kd_step(baseline_kd, candidate_kd, should_pass):
    """Catches a kd step validator that allows or blocks the exact +- KD_STEP_MAX."""
    baseline = ParameterCommand("camp-001", 1, 35.0, 0.0, baseline_kd, 680)
    candidate = ParameterCommand("camp-001", 2, 35.0, 0.0, candidate_kd, 680)
    if should_pass:
        validate_parameter_update(candidate, baseline)
    else:
        with pytest.raises(ProtocolError, match="kd step"):
            validate_parameter_update(candidate, baseline)


@pytest.mark.parametrize(
    "baseline_speed,candidate_speed,should_pass",
    [
        (680, 580, True),
        (680, 579, False),
        (680, 680, True),
    ],
)
def test_parameter_update_speed_step(baseline_speed, candidate_speed, should_pass):
    """Catches a speed step validator that allows or blocks the exact +- SPEED_STEP_MAX."""
    baseline = ParameterCommand("camp-001", 1, 35.0, 0.0, 10.0, baseline_speed)
    candidate = ParameterCommand("camp-001", 2, 35.0, 0.0, 10.0, candidate_speed)
    if should_pass:
        validate_parameter_update(candidate, baseline)
    else:
        with pytest.raises(ProtocolError, match="speed_max step"):
            validate_parameter_update(candidate, baseline)


def test_encoder_rejects_values_that_exceed_c_identifier_or_version_storage():
    """Catches Python frames C cannot represent in its fixed identifier/version fields."""
    with pytest.raises(ProtocolError, match="campaign_id"):
        ParameterCommand("c" * 17, 1, 35.0, 0.0, 10.0, 680).encode()
    with pytest.raises(ProtocolError, match="version"):
        ParameterCommand("camp-001", 2 ** 32, 35.0, 0.0, 10.0, 680).encode()


def test_command_parser_rejects_crlf_that_the_c_firmware_must_not_accept():
    """Catches cross-language acceptance of a non-canonical CRLF command frame."""
    with pytest.raises(ProtocolError, match="LF only"):
        parse_command("P,camp-001,3,35,0,10,680,69\r\n")


def test_ack_parser_rejects_version_that_cannot_fit_the_firmware_uint32():
    """Catches ACK parsing that accepts a version C can never safely represent."""
    with pytest.raises(ProtocolError, match="version"):
        parse_ack(frame("A,camp-001,4294967296,APPLIED,OK"))


def test_parameter_boundary_returns_a_result_for_pending_pressure_and_timeout_cancellation():
    """Catches a valid parameter command disappearing when a pending update is cancelled."""
    baseline = ParameterCommand("baseline", 1, 35.0, 0.0, 10.0, 680)
    first = ParameterCommand("camp-001", 2, 40.0, 0.0, 10.0, 680)
    second = ParameterCommand("camp-001", 3, 35.0, 0.0, 10.0, 680)
    boundary = RuntimeParameterBoundary(baseline)

    assert boundary.receive(first) is None
    assert boundary.receive(second) == ParameterAck("camp-001", 3, "REJECTED", "PENDING")
    boundary.request_rollback("TIMEOUT")
    assert boundary.apply_pending() == ParameterAck("camp-001", 2, "REJECTED", "TIMEOUT")
    assert boundary.active == baseline


@pytest.mark.parametrize("reason", ["STOP", "RESTORE_BASELINE", "TIMEOUT"])
def test_rollback_cancels_pending_and_restores_baseline(reason):
    """Catches a rollback that fails to cancel pending or restore the reference baseline."""
    baseline = ParameterCommand("baseline", 1, 35.0, 0.0, 10.0, 680)
    first = ParameterCommand("camp-001", 2, 40.0, 0.0, 10.0, 680)
    boundary = RuntimeParameterBoundary(baseline)

    assert boundary.receive(first) is None
    boundary.request_rollback(reason)
    ack = boundary.apply_pending()
    assert ack == ParameterAck("camp-001", 2, "REJECTED", reason)
    assert boundary.active == baseline
