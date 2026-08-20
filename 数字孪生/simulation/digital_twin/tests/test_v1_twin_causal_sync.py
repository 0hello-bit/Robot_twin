"""Tests for the causal PC/MCU clock-exchange evidence contract."""

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
    ClockExchangeIdentity,
)
from v1_twin.v1_twin_causal_sync import (
    CausalClockFit,
    CausalSyncPolicy,
    ClockExchangeSample,
    evaluate_causal_sync,
)


def _record(sequence=7, *, pc_rx_ns=None):
    identity = ClockExchangeIdentity(
        transport="tcp", capture_id="test-causal", sequence=sequence
    )
    q_tick = 1_200 + sequence * 10
    pc_tx_ns = q_tick * 1_000_000
    return {
        "capture_id": "test-causal",
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
        "q_event_tick_ms": q_tick,
        "q_event_observed_tick_ms": q_tick,
        "q_event_data_age_ms": 0,
        "q_event_kind": EVENT_Q_UART_RX_ISR,
        "q_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "q_event_validity": "observed_boundary",
        "q_event_uncertainty_ns": 1_000_000,
        "q_parse_event_id": identity.event(EVENT_Q_PARSE_DONE),
        "q_parse_causal_parent_event_id": identity.event(EVENT_Q_UART_RX_ISR),
        "q_parse_done_tick_ms": q_tick + 1,
        "q_parse_event_kind": EVENT_Q_PARSE_DONE,
        "q_parse_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "q_parse_event_validity": "reported_boundary",
        "q_parse_event_uncertainty_ns": 1_000_000,
        "q_parse_event_observed_tick_ms": None,
        "q_parse_event_data_age_ms": None,
        "q_parse_role": "diagnostic_only",
        "t_event_id": identity.event(EVENT_T_TRANSACTION_STARTED),
        "t_event_tick_ms": q_tick + 2,
        "t_event_observed_tick_ms": q_tick + 2,
        "t_event_data_age_ms": 0,
        "t_event_kind": EVENT_T_TRANSACTION_STARTED,
        "t_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "t_event_validity": "observed_boundary",
        "t_event_uncertainty_ns": 1_000_000,
        "t_payload_event_id": identity.event(EVENT_T_PAYLOAD_GENERATED),
        "t_payload_causal_parent_event_id": identity.event(
            EVENT_T_TRANSACTION_STARTED
        ),
        "t_payload_generated_tick_ms": q_tick + 3,
        "t_payload_event_kind": EVENT_T_PAYLOAD_GENERATED,
        "t_payload_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "t_payload_event_validity": "reported_boundary",
        "t_payload_event_uncertainty_ns": 1_000_000,
        "t_payload_event_observed_tick_ms": None,
        "t_payload_event_data_age_ms": None,
        "t_payload_role": "diagnostic_only",
        "pc_rx_ns": pc_tx_ns + 10_000_000 if pc_rx_ns is None else pc_rx_ns,
        "pc_rx_event_id": identity.event(EVENT_PC_T_RECEIVED),
        "pc_rx_event_kind": EVENT_PC_T_RECEIVED,
        "pc_rx_event_clock_domain": CLOCK_DOMAIN_PC_MONOTONIC_NS,
        "pc_rx_event_validity": "observed_boundary",
        "pc_rx_event_uncertainty_ns": 1_000_000,
        "pc_rx_event_observed_ns": pc_tx_ns + 10_000_000 if pc_rx_ns is None else pc_rx_ns,
        "pc_rx_event_data_age_ns": 0,
        "timestamp_schema_version": 2,
    }


def test_exchange_sample_round_trips_all_four_timestamps():
    record = _record()
    sample = ClockExchangeSample.from_dict(record)

    assert sample.to_dict() == record


def test_reported_boundary_uncertainty_can_remain_unknown():
    record = _record()
    record["q_parse_event_uncertainty_ns"] = None
    record["t_payload_event_uncertainty_ns"] = None

    sample = ClockExchangeSample.from_dict(record)

    assert sample.q_parse_event_uncertainty_ns is None
    assert sample.t_payload_event_uncertainty_ns is None
    assert sample.to_dict() == record


def test_exchange_sample_rejects_missing_receive_timestamp():
    record = _record(sequence=1)
    record.pop("pc_rx_ns")
    with pytest.raises(ValueError, match="pc_rx_ns"):
        ClockExchangeSample.from_dict(record)


def test_exchange_sample_rejects_negative_round_trip_order():
    record = _record(sequence=1, pc_rx_ns=100)
    with pytest.raises(ValueError, match="pc_rx_ns"):
        ClockExchangeSample.from_dict(record)


def _exchange_samples(*, one_way_delay_ns=5_000_000, extra_delay_ns=0):
    """Build exchanges for pc_ns = tick_ms * 1e6 + 500_000."""
    samples = []
    for sequence in range(1, 13):
        mcu_rx = 10_000 + (sequence - 1) * 100
        mcu_tx = mcu_rx + 1
        mapping_rx = mcu_rx * 1_000_000 + 500_000
        mapping_tx = mcu_tx * 1_000_000 + 500_000
        samples.append(ClockExchangeSample(
            sequence=sequence,
            pc_tx_ns=mapping_rx - one_way_delay_ns,
            q_event_tick_ms=mcu_rx,
            q_event_observed_tick_ms=mcu_rx,
            q_event_data_age_ms=0,
            q_parse_done_tick_ms=mcu_rx + 1,
            q_parse_event_observed_tick_ms=None,
            t_event_tick_ms=mcu_tx,
            t_event_observed_tick_ms=mcu_tx,
            t_event_data_age_ms=0,
            t_payload_generated_tick_ms=mcu_tx,
            t_payload_event_observed_tick_ms=None,
            t_payload_event_data_age_ms=None,
            pc_rx_ns=mapping_tx + one_way_delay_ns + extra_delay_ns,
            pc_tx_event_uncertainty_ns=1_000_000,
            q_event_uncertainty_ns=1_000_000,
            t_event_uncertainty_ns=1_000_000,
            pc_rx_event_uncertainty_ns=1_000_000,
            pc_tx_event_observed_ns=mapping_rx - one_way_delay_ns,
            pc_rx_event_observed_ns=mapping_tx + one_way_delay_ns + extra_delay_ns,
        ))
    return samples


def test_causal_fit_recovers_mapping_and_reports_rtt():
    fit = CausalClockFit.fit(_exchange_samples())

    assert fit.tick_to_pc_ns(10_500) == pytest.approx(
        10_500_500_000, abs=1
    )
    assert fit.metrics()["rtt_p95_ns"] == pytest.approx(10_000_000, abs=1)
    assert fit.metrics()["residual_rms_ns"] == pytest.approx(0, abs=1)


def test_causal_gate_does_not_pass_without_enough_exchanges():
    fit = CausalClockFit.fit(_exchange_samples()[:3])

    result = evaluate_causal_sync(fit, CausalSyncPolicy())

    assert result.verdict == "INSUFFICIENT EVIDENCE"
    assert "exchanges" in result.reason


def test_causal_gate_fails_when_rtt_policy_is_exceeded():
    fit = CausalClockFit.fit(
        _exchange_samples(one_way_delay_ns=5_000_000, extra_delay_ns=30_000_000)
    )

    result = evaluate_causal_sync(
        fit,
        CausalSyncPolicy(max_rtt_p95_ns=20_000_000),
    )

    assert result.verdict == "FAIL"
    assert "rtt_p95_ns" in result.reason
