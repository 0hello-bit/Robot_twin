"""Tests for explicit clock-event identity and timestamp provenance."""

from __future__ import annotations

import pytest

from v1_twin.clock_event_identity import (
    CLOCK_DOMAIN_MCU_MONOTONIC_MS,
    CLOCK_DOMAIN_PC_MONOTONIC_NS,
    EVENT_PC_Q_SENT,
    EVENT_PC_T_RECEIVED,
    EVENT_Q_PARSE_DONE,
    EVENT_Q_UART_RX_ISR,
    EVENT_T_PAYLOAD_GENERATED,
    EVENT_T_TRANSACTION_STARTED,
    OBSERVED_BOUNDARY,
    ClockEvent,
    ClockExchangeIdentity,
    build_clock_event,
)
from v1_twin.v1_twin_causal_sync import ClockExchangeSample, build_causal_sync_report
from real_world.runtime_protocol import frame, parse_clock_sync_reply


def _v2_record(sequence=1):
    identity = ClockExchangeIdentity(transport="tcp", sequence=sequence)
    tick_ms = 1_000 + sequence * 10
    pc_tx_ns = tick_ms * 1_000_000
    return {
        "capture_id": "local",
        "observation_id": identity.exchange_id,
        "sequence": sequence,
        "pc_tx_ns": pc_tx_ns,
        "pc_tx_event_id": identity.event(EVENT_PC_Q_SENT),
        "pc_tx_event_kind": EVENT_PC_Q_SENT,
        "pc_tx_event_clock_domain": CLOCK_DOMAIN_PC_MONOTONIC_NS,
        "pc_tx_event_validity": "observed_boundary",
        "pc_tx_event_uncertainty_ns": 1_000_000,
        "pc_tx_event_observed_ns": pc_tx_ns,
        "pc_tx_event_data_age_ns": 0,
        "q_event_id": identity.event(EVENT_Q_UART_RX_ISR),
        "q_event_tick_ms": tick_ms,
        "q_event_observed_tick_ms": tick_ms,
        "q_event_data_age_ms": 0,
        "q_event_kind": EVENT_Q_UART_RX_ISR,
        "q_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "q_event_validity": "observed_boundary",
        "q_event_uncertainty_ns": 1_000_000,
        "q_parse_event_id": identity.event(EVENT_Q_PARSE_DONE),
        "q_parse_causal_parent_event_id": identity.event(EVENT_Q_UART_RX_ISR),
        "q_parse_done_tick_ms": tick_ms + 1,
        "q_parse_event_kind": EVENT_Q_PARSE_DONE,
        "q_parse_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "q_parse_event_validity": "reported_boundary",
        "q_parse_event_uncertainty_ns": 1_000_000,
        "q_parse_event_observed_tick_ms": None,
        "q_parse_event_data_age_ms": None,
        "q_parse_role": "diagnostic_only",
        "t_event_id": identity.event(EVENT_T_TRANSACTION_STARTED),
        "t_event_tick_ms": tick_ms + 2,
        "t_event_observed_tick_ms": tick_ms + 2,
        "t_event_data_age_ms": 0,
        "t_event_kind": EVENT_T_TRANSACTION_STARTED,
        "t_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "t_event_validity": "observed_boundary",
        "t_event_uncertainty_ns": 1_000_000,
        "t_payload_event_id": identity.event(EVENT_T_PAYLOAD_GENERATED),
        "t_payload_causal_parent_event_id": identity.event(
            EVENT_T_TRANSACTION_STARTED
        ),
        "t_payload_generated_tick_ms": tick_ms + 3,
        "t_payload_event_kind": EVENT_T_PAYLOAD_GENERATED,
        "t_payload_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "t_payload_event_validity": "reported_boundary",
        "t_payload_event_uncertainty_ns": 1_000_000,
        "t_payload_event_observed_tick_ms": None,
        "t_payload_event_data_age_ms": None,
        "t_payload_role": "diagnostic_only",
        "pc_rx_ns": pc_tx_ns + 10_000_000,
        "pc_rx_event_id": identity.event(EVENT_PC_T_RECEIVED),
        "pc_rx_event_kind": EVENT_PC_T_RECEIVED,
        "pc_rx_event_clock_domain": CLOCK_DOMAIN_PC_MONOTONIC_NS,
        "pc_rx_event_validity": "observed_boundary",
        "pc_rx_event_uncertainty_ns": 1_000_000,
        "pc_rx_event_observed_ns": pc_tx_ns + 10_000_000,
        "pc_rx_event_data_age_ns": 0,
        "timestamp_schema_version": 2,
        "sample_role": "formal",
        "included_in_fit": True,
    }


def test_exchange_identity_does_not_collapse_distinct_event_boundaries():
    identity = ClockExchangeIdentity(transport="tcp", sequence=7)

    q_rx = identity.event(EVENT_Q_UART_RX_ISR)
    q_parse = identity.event(EVENT_Q_PARSE_DONE)
    t_start = identity.event(EVENT_T_TRANSACTION_STARTED)
    t_payload = identity.event(EVENT_T_PAYLOAD_GENERATED)

    assert len({q_rx, q_parse, t_start, t_payload}) == 4
    assert q_rx.startswith("tcp:clock:7:")
    assert q_parse != q_rx


def test_exchange_identity_is_unique_across_capture_scopes():
    first = ClockExchangeIdentity(
        transport="tcp", capture_id="capture-a", sequence=7
    )
    second = ClockExchangeIdentity(
        transport="tcp", capture_id="capture-b", sequence=7
    )

    assert first.exchange_id != second.exchange_id
    assert first.event(EVENT_Q_UART_RX_ISR) != second.event(EVENT_Q_UART_RX_ISR)


def test_delayed_parse_boundary_is_not_an_uart_receive_event():
    parse_event = build_clock_event(
        sequence=7,
        event_kind=EVENT_Q_PARSE_DONE,
        event_time=2_000,
        source_id="STM32_UART1",
        observed_time=2_125,
        data_age=125,
        uncertainty=1_000_000,
        validity="delayed_boundary",
        causal_parent_id="tcp:clock:7:q_uart_rx_isr_observed",
    )

    assert parse_event.event_kind == EVENT_Q_PARSE_DONE
    assert parse_event.event_time != 1_875
    assert parse_event.data_age == 125
    assert parse_event.validity == "delayed_boundary"
    assert parse_event.causal_parent_id.endswith(EVENT_Q_UART_RX_ISR)


def test_event_requires_domain_and_nonnegative_uncertainty():
    with pytest.raises(ValueError, match="clock_domain"):
        ClockEvent(
            event_id="tcp:clock:1:q_uart_rx_isr_observed",
            sequence=1,
            source_id="STM32_UART1",
            event_kind=EVENT_Q_UART_RX_ISR,
            clock_domain="",
            event_time=1,
            observed_time=1,
            data_age=0,
            validity="observed_boundary",
            uncertainty=None,
            causal_parent_id=None,
        )


def test_event_id_must_match_its_named_boundary():
    with pytest.raises(ValueError, match="event_id"):
        ClockEvent(
            event_id="tcp:clock:1:q_parse_done",
            sequence=1,
            source_id="STM32_UART1",
            event_kind=EVENT_Q_UART_RX_ISR,
            clock_domain=CLOCK_DOMAIN_MCU_MONOTONIC_MS,
            event_time=1,
            observed_time=1,
            data_age=0,
            validity="observed_boundary",
            uncertainty=1_000_000,
            causal_parent_id=None,
        )


def test_event_id_must_match_its_capture_scope():
    with pytest.raises(ValueError, match="event_id"):
        ClockEvent(
            event_id="tcp:clock:1:capture-b:q_uart_rx_isr_observed",
            sequence=1,
            source_id="STM32_UART1",
            event_kind=EVENT_Q_UART_RX_ISR,
            clock_domain=CLOCK_DOMAIN_MCU_MONOTONIC_MS,
            event_time=1,
            observed_time=1,
            data_age=0,
            validity="observed_boundary",
            uncertainty=1_000_000,
            causal_parent_id=None,
        )


def test_observed_boundary_requires_exact_observation_age():
    with pytest.raises(ValueError, match="observed_boundary"):
        ClockEvent(
            event_id="tcp:clock:1:q_uart_rx_isr_observed",
            sequence=1,
            source_id="STM32_UART1",
            event_kind=EVENT_Q_UART_RX_ISR,
            clock_domain=CLOCK_DOMAIN_MCU_MONOTONIC_MS,
            event_time=1,
            observed_time=None,
            data_age=None,
            validity="observed_boundary",
            uncertainty=1_000_000,
            causal_parent_id=None,
        )


def test_causal_parent_must_stay_in_the_same_exchange_scope():
    with pytest.raises(ValueError, match="causal_parent_id"):
        build_clock_event(
            sequence=7,
            event_kind=EVENT_Q_PARSE_DONE,
            event_time=2_000,
            source_id="STM32_UART1",
            observed_time=None,
            data_age=None,
            uncertainty=1_000_000,
            validity="reported_boundary",
            causal_parent_id=(
                "tcp:clock:7:capture-b:" + EVENT_Q_UART_RX_ISR
            ),
            capture_id="capture-a",
        )


def test_reported_boundary_requires_its_named_causal_parent():
    record = _v2_record()
    record["q_parse_causal_parent_event_id"] = record["t_event_id"]

    with pytest.raises(ValueError, match="causal parent"):
        ClockExchangeSample.from_dict(record)


def test_reported_boundary_requires_parent_identity_in_the_record():
    record = _v2_record()
    record.pop("q_parse_causal_parent_event_id")

    with pytest.raises(ValueError, match="causal parent"):
        ClockExchangeSample.from_dict(record)


def test_build_clock_event_preserves_an_explicit_clock_domain():
    event = build_clock_event(
        sequence=1,
        event_kind=EVENT_PC_Q_SENT,
        event_time=10,
        source_id="PC",
        observed_time=10,
        data_age=0,
        uncertainty=1,
        validity=OBSERVED_BOUNDARY,
        causal_parent_id=None,
        clock_domain=CLOCK_DOMAIN_PC_MONOTONIC_NS,
    )

    assert event.clock_domain == CLOCK_DOMAIN_PC_MONOTONIC_NS


def test_causal_sample_requires_all_event_identities():
    record = _v2_record()
    record.pop("t_payload_event_id")

    with pytest.raises(ValueError, match="event identity"):
        ClockExchangeSample.from_dict(record)


def test_causal_report_fails_closed_for_missing_event_identity():
    record = _v2_record()
    record.pop("q_parse_event_id")

    report = build_causal_sync_report([record])

    assert report["verdict"] == "INSUFFICIENT EVIDENCE"
    assert report["sample_count"] == 0
    assert report["unclassified_record_count"] == 1


def test_v2_event_marks_payload_generation_as_observation_only():
    event = build_clock_event(
        sequence=3,
        event_kind=EVENT_T_PAYLOAD_GENERATED,
        event_time=3_300,
        source_id="STM32_UART1",
        observed_time=3_600,
        data_age=300,
        uncertainty=1_000_000,
        validity="delayed_boundary",
        causal_parent_id="tcp:clock:3:t_cipsend_transaction_started",
    )

    assert event.clock_domain == CLOCK_DOMAIN_MCU_MONOTONIC_MS
    assert event.validity == "delayed_boundary"
    assert event.data_age == 300


def test_clock_reply_exposes_all_named_boundaries_and_schema_version():
    reply = parse_clock_sync_reply(frame(
        "T,0000000007,0000001234,0000001235,0000001236,0000001237,2"
    ))

    assert reply.sequence == 7
    assert reply.q_uart_rx_isr_tick_ms == 1234
    assert reply.q_parse_done_tick_ms == 1235
    assert reply.t_transaction_started_tick_ms == 1236
    assert reply.t_payload_generated_tick_ms == 1237
    assert reply.timestamp_schema_version == 2
    assert reply.legacy_first_tick_ms is None
    assert reply.legacy_second_tick_ms is None
    assert not hasattr(reply, "mcu_rx_tick_ms")
    assert not hasattr(reply, "mcu_tx_tick_ms")


def test_legacy_clock_reply_is_explicitly_unclassified():
    reply = parse_clock_sync_reply("T,7,1234,1235,4E\n")

    assert reply.timestamp_schema_version == 1
    assert reply.q_uart_rx_isr_tick_ms is None
    assert reply.event_timestamp_valid is False
    assert reply.q_uart_rx_isr_tick_ms is None
    assert reply.t_transaction_started_tick_ms is None
    assert reply.legacy_first_tick_ms == 1234
    assert reply.legacy_second_tick_ms == 1235
