"""Tests for the causal PC/MCU clock-exchange evidence contract."""

from __future__ import annotations

import pytest

from v1_twin.v1_twin_causal_sync import (
    CausalClockFit,
    CausalSyncPolicy,
    ClockExchangeSample,
    evaluate_causal_sync,
)


def test_exchange_sample_round_trips_all_four_timestamps():
    sample = ClockExchangeSample.from_dict({
        "sequence": 7,
        "pc_tx_ns": 10_000_000_000,
        "mcu_rx_tick_ms": 1234,
        "mcu_tx_tick_ms": 1235,
        "pc_rx_ns": 10_012_000_000,
    })

    assert sample.to_dict() == {
        "sequence": 7,
        "pc_tx_ns": 10_000_000_000,
        "mcu_rx_tick_ms": 1234,
        "mcu_tx_tick_ms": 1235,
        "pc_rx_ns": 10_012_000_000,
    }


def test_exchange_sample_rejects_missing_receive_timestamp():
    with pytest.raises(ValueError, match="pc_rx_ns"):
        ClockExchangeSample.from_dict({
            "sequence": 1,
            "pc_tx_ns": 100,
            "mcu_rx_tick_ms": 1,
            "mcu_tx_tick_ms": 1,
        })


def test_exchange_sample_rejects_negative_round_trip_order():
    with pytest.raises(ValueError, match="pc_rx_ns"):
        ClockExchangeSample.from_dict({
            "sequence": 1,
            "pc_tx_ns": 200,
            "mcu_rx_tick_ms": 1,
            "mcu_tx_tick_ms": 1,
            "pc_rx_ns": 100,
        })


def _exchange_samples(*, one_way_delay_ns=5_000_000, extra_delay_ns=0):
    """Build exchanges for pc_ns = tick_ms * 1e6 + 500_000."""
    samples = []
    for sequence in range(12):
        mcu_rx = 10_000 + sequence * 100
        mcu_tx = mcu_rx + 1
        mapping_rx = mcu_rx * 1_000_000 + 500_000
        mapping_tx = mcu_tx * 1_000_000 + 500_000
        samples.append(ClockExchangeSample(
            sequence=sequence,
            pc_tx_ns=mapping_rx - one_way_delay_ns,
            mcu_rx_tick_ms=mcu_rx,
            mcu_tx_tick_ms=mcu_tx,
            pc_rx_ns=mapping_tx + one_way_delay_ns + extra_delay_ns,
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
