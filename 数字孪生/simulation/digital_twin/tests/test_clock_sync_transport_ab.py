"""Offline tests for the bounded TCP/UDP ClockSync transport probe."""

from __future__ import annotations

import os
import sys

import pytest


SHAKEDOWN = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "tools",
    "shakedown_toolchain",
)
sys.path.insert(0, SHAKEDOWN)

from clock_sync_transport_ab import (  # noqa: E402
    ClockSyncReplyLedger,
    TcpClockSyncStream,
    build_arg_parser,
    build_udp_smoke_verdict,
)
from real_world.runtime_protocol import ClockSyncProbe, frame  # noqa: E402
from v1_twin.v1_twin_causal_sync import build_causal_sync_report  # noqa: E402


def test_timeout_then_late_reply_is_not_rematched():
    ledger = ClockSyncReplyLedger("udp")
    ledger.begin(100, 1_000_000_000)
    ledger.timeout(100, 1_050_000_000)

    outcome = ledger.receive(
        frame("T,100,2000,2001"), 1_300_000_000
    )

    assert outcome == "late_reply"
    observation = ledger.observations()[0]
    assert observation["sequence"] == 100
    assert observation["matched"] is False
    assert observation["late_reply"] is True
    assert observation["pc_rx_ns"] == 1_300_000_000
    assert observation["timestamp_schema_version"] == 1
    assert observation["event_semantics"] == "legacy_unclassified"
    assert observation["included_in_fit"] is False
    assert observation["legacy_first_tick_ms"] == 2000
    assert observation["legacy_second_tick_ms"] == 2001


def test_duplicate_reply_is_counted_without_creating_a_second_observation():
    ledger = ClockSyncReplyLedger("tcp")
    ledger.begin(101, 2_000_000_000)

    reply = frame("T,101,3000,3002")
    assert ledger.receive(reply, 2_020_000_000) == "matched"
    assert ledger.receive(reply, 2_025_000_000) == "duplicate"

    observations = ledger.observations()
    assert len(observations) == 1
    assert observations[0]["duplicate_count"] == 1
    assert observations[0]["rtt_total_ns"] == 20_000_000
    assert observations[0]["rtt_transport_ns"] == 18_000_000


def test_unknown_reply_is_retained_separately():
    ledger = ClockSyncReplyLedger("udp")

    assert ledger.receive(
        frame("T,999,10,11"), 4_000_000_000
    ) == "unknown"
    assert ledger.unmatched_replies()[0]["sequence"] == 999
    assert ledger.observations() == []


def test_invalid_reply_is_reported_without_mutating_pending_probe():
    ledger = ClockSyncReplyLedger("tcp")
    ledger.begin(102, 5_000_000_000)

    with pytest.raises(ValueError, match="checksum"):
        ledger.receive("T,102,4000,4001,00\n", 5_010_000_000)

    assert ledger.pending_sequences() == [102]


def test_summary_keeps_timeout_and_late_reply_in_sent_denominator():
    ledger = ClockSyncReplyLedger("udp")
    ledger.begin(103, 6_000_000_000)
    ledger.timeout(103, 6_010_000_000)

    summary = ledger.summary()

    assert summary["sent_count"] == 1
    assert summary["matched_count"] == 0
    assert summary["lost_count"] == 1


def test_v2_ledger_keeps_each_boundary_identity_and_delay_diagnostic_only():
    ledger = ClockSyncReplyLedger("tcp")
    ledger.begin(107, 7_000_000_000)

    reply = frame("T,107,2000,2001,2002,2003,2")
    assert ledger.receive(reply, 7_010_000_000) == "matched"

    observation = ledger.observations()[0]
    assert "mcu_rx_tick_ms" not in observation
    assert "mcu_tx_tick_ms" not in observation
    assert observation["q_event_id"] == (
        "tcp:clock:107:q_uart_rx_isr_observed"
    )
    assert observation["q_parse_event_id"] == (
        "tcp:clock:107:q_parse_done"
    )
    assert observation["t_event_id"] == (
        "tcp:clock:107:t_cipsend_transaction_started"
    )
    assert observation["t_payload_event_id"] == (
        "tcp:clock:107:t_payload_generated"
    )
    assert observation["q_parse_causal_parent_event_id"] == observation["q_event_id"]
    assert observation["t_payload_causal_parent_event_id"] == observation["t_event_id"]
    assert len({
        observation["q_event_id"],
        observation["q_parse_event_id"],
        observation["t_event_id"],
        observation["t_payload_event_id"],
    }) == 4
    assert observation["q_parse_role"] == "diagnostic_only"
    assert observation["t_payload_role"] == "diagnostic_only"
    assert observation["fit_requested"] is True
    assert observation["included_in_fit"] is False
    assert observation["fit_exclusion_reason"] == "uncertainty_unverified"
    assert observation["q_parse_delay_from_q_event_ms"] == 1
    assert observation["t_payload_delay_from_t_event_ms"] == 1

    causal_records = ledger.causal_records()
    assert causal_records == []


def test_v2_reported_boundaries_are_not_zero_age_observations():
    ledger = ClockSyncReplyLedger("tcp")
    ledger.begin(109, 9_000_000_000)

    reply = frame("T,109,4000,4003,4005,4008,2")
    assert ledger.receive(reply, 9_010_000_000) == "matched"

    observation = ledger.observations()[0]
    assert observation["q_parse_event_validity"] == "reported_boundary"
    assert observation["q_parse_event_observed_tick_ms"] is None
    assert observation["q_parse_event_data_age_ms"] is None
    assert observation["t_payload_event_validity"] == "reported_boundary"
    assert observation["t_payload_event_observed_tick_ms"] is None
    assert observation["t_payload_event_data_age_ms"] is None
    assert observation["q_parse_role"] == "diagnostic_only"
    assert observation["t_payload_role"] == "diagnostic_only"


def test_v2_uncertainty_is_unknown_until_a_bound_is_verified():
    ledger = ClockSyncReplyLedger("tcp")
    ledger.begin(110, 10_000_000_000)

    assert ledger.receive(
        frame("T,110,5000,5002,5004,5006,2"), 10_010_000_000
    ) == "matched"
    observation = ledger.observations()[0]
    assert observation["pc_tx_event_uncertainty_ns"] is None
    assert observation["q_event_uncertainty_ns"] is None
    assert observation["t_event_uncertainty_ns"] is None
    assert observation["pc_rx_event_uncertainty_ns"] is None
    assert build_causal_sync_report(ledger.causal_records())["verdict"] == (
        "INSUFFICIENT EVIDENCE"
    )


def test_causal_records_reject_wrong_reported_parent_even_with_uncertainty():
    ledger = ClockSyncReplyLedger("tcp")
    ledger.begin(113, 13_000_000_000)
    assert ledger.receive(
        frame("T,113,8000,8002,8004,8006,2"), 13_010_000_000
    ) == "matched"

    observation = ledger._observations[0]
    observation["pc_tx_event_uncertainty_ns"] = 1_000_000
    observation["q_event_uncertainty_ns"] = 1_000_000
    observation["t_event_uncertainty_ns"] = 1_000_000
    observation["pc_rx_event_uncertainty_ns"] = 1_000_000
    observation["included_in_fit"] = True
    observation["q_parse_causal_parent_event_id"] = observation["t_event_id"]

    assert ledger.causal_records() == []


def test_udp_records_never_become_causal_input():
    ledger = ClockSyncReplyLedger("udp")
    ledger.begin(112, 12_000_000_000)
    assert ledger.receive(
        frame("T,112,7000,7002,7004,7006,2"), 12_010_000_000
    ) == "matched"

    # Exercise the transport boundary independently of the uncertainty gate.
    observation = ledger._observations[0]
    for field in (
        "pc_tx_event_uncertainty_ns",
        "q_event_uncertainty_ns",
        "t_event_uncertainty_ns",
        "pc_rx_event_uncertainty_ns",
    ):
        observation[field] = 1_000_000
    assert ledger.causal_records() == []


def test_v1_ledger_is_replay_evidence_only_and_never_formal_causal_input():
    ledger = ClockSyncReplyLedger("tcp")
    ledger.begin(108, 8_000_000_000)

    assert ledger.receive(frame("T,108,3000,3001"), 8_010_000_000) == "matched"

    observation = ledger.observations()[0]
    assert observation["timestamp_schema_version"] == 1
    assert observation["event_semantics"] == "legacy_unclassified"
    assert observation["included_in_fit"] is False
    assert ledger.causal_records() == []


def test_v1_rtt_is_kept_in_legacy_replay_summary_only():
    ledger = ClockSyncReplyLedger("tcp")
    ledger.begin(111, 11_000_000_000)

    assert ledger.receive(frame("T,111,6000,6001"), 11_010_000_000) == "matched"
    summary = ledger.summary()
    assert summary["matched_count"] == 0
    assert summary["legacy_replay"]["matched_count"] == 1
    assert summary["legacy_replay"]["transport_rtt_sample_count"] == 1


def test_tcp_status_line_does_not_create_a_fake_clock_reply():
    lines = []
    parser = TcpClockSyncStream(
        lambda line, _arrival_ns: lines.append(line)
    )

    parser.feed(b"S,none,none,STOPPED,TIMEOUT,0,5D\n", 7_000_000_000)

    assert lines == []


def test_udp_smoke_passes_only_for_one_valid_q_and_matching_t():
    payload = ClockSyncProbe(104).encode().encode("ascii")
    result = {
        "transport": "udp",
        "count_requested": 1,
        "connection_error": None,
        "parse_errors": [],
        "raw_io": {
            "n_send": 1,
            "n_recv": 1,
            "events": [{
                "dir": "TX",
                "bytes_hex": payload.hex(),
                "sequence": 104,
            }],
        },
        "ledger": {
            "summary": {"sent_count": 1, "matched_count": 1},
        },
    }

    verdict = build_udp_smoke_verdict(result, control_commands_sent=[])

    assert verdict["verdict"] == "PASS"
    assert verdict["roundtrip"] == "VERIFIED"
    assert verdict["internal_boundary"] == "INSUFFICIENT EVIDENCE"


def test_udp_smoke_rejects_anything_other_than_one_q():
    payload = ClockSyncProbe(105).encode().encode("ascii")
    result = {
        "transport": "udp",
        "count_requested": 1,
        "connection_error": None,
        "parse_errors": [],
        "raw_io": {
            "n_send": 2,
            "n_recv": 0,
            "events": [{
                "dir": "TX",
                "bytes_hex": payload.hex(),
                "sequence": 105,
            }, {
                "dir": "TX",
                "bytes_hex": payload.hex(),
                "sequence": 105,
            }],
        },
        "ledger": {
            "summary": {"sent_count": 1, "matched_count": 0},
        },
    }

    verdict = build_udp_smoke_verdict(result, control_commands_sent=[])

    assert verdict["verdict"] == "INVALID"
    assert verdict["roundtrip"] == "INSUFFICIENT EVIDENCE"


def test_udp_smoke_marks_a_valid_single_q_without_t_as_roundtrip_failure():
    payload = ClockSyncProbe(106).encode().encode("ascii")
    result = {
        "transport": "udp",
        "count_requested": 1,
        "connection_error": None,
        "parse_errors": [],
        "raw_io": {
            "n_send": 1,
            "n_recv": 0,
            "events": [{
                "dir": "TX",
                "bytes_hex": payload.hex(),
                "sequence": 106,
            }],
        },
        "ledger": {
            "summary": {"sent_count": 1, "matched_count": 0},
        },
    }

    verdict = build_udp_smoke_verdict(result, control_commands_sent=[])

    assert verdict["verdict"] == "FAIL"
    assert verdict["roundtrip"] == "FAIL"
    assert verdict["internal_boundary"] == "INSUFFICIENT EVIDENCE"


def test_smoke_mode_defaults_to_one_udp_probe():
    args = build_arg_parser().parse_args(["--smoke"])

    assert args.smoke is True
    assert args.transport is None
    assert args.count is None
