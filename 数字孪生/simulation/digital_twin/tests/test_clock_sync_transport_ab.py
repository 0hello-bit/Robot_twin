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
    assert observation["mcu_rx_tick_ms"] == 2000
    assert observation["mcu_tx_tick_ms"] == 2001


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
