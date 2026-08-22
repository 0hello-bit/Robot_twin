"""Tests for the clock exchange frames on the existing ASCII control path."""

from __future__ import annotations

import pytest

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "tools", "camera_toolchain"
    ),
)

from capture_sync_run import ClockExchangeCollector
from transport_soak import MixedStreamParser
from real_world.runtime_protocol import (
    ClockSyncProbe,
    ClockSyncReply,
    ProtocolError,
    frame,
    parse_clock_sync_reply,
)
from v1_twin.v1_twin_causal_sync import build_causal_sync_report


def test_clock_probe_uses_existing_xor_framing():
    packet = ClockSyncProbe(7).encode()

    assert packet == "Q,7,4A\n"


def test_clock_reply_round_trips_sequence_and_mcu_ticks():
    reply = parse_clock_sync_reply("T,7,1234,1235,4E\n")

    assert reply == ClockSyncReply(7, 1234, 1235)


def test_clock_reply_v3_round_trips_mcu_endpoint_uncertainty():
    reply = parse_clock_sync_reply(frame(
        "T,7,0000001234,0000001235,0000001236,0000001237,3,001000000,001000000"
    ))

    assert reply.timestamp_schema_version == 3
    assert reply.q_event_uncertainty_ns == 1_000_000
    assert reply.t_event_uncertainty_ns == 1_000_000


def test_clock_reply_rejects_tampered_checksum():
    with pytest.raises(ProtocolError, match="checksum"):
        parse_clock_sync_reply("T,7,1234,1235,00\n")


def test_clock_exchange_collector_marks_legacy_reply_unclassified():
    collector = ClockExchangeCollector()

    probe = collector.begin_probe(
        7, 1_000_000_000, sample_role="formal", included_in_fit=True
    )
    collector.complete_probe(
        ClockSyncReply(7, 1234, 1235),
        1_012_000_000,
    )

    assert probe == ClockSyncProbe(7).encode().encode("ascii")
    record = collector.records()[0]
    assert record["sequence"] == 7
    assert record["timestamp_schema_version"] == 1
    assert record["included_in_fit"] is False
    assert record["legacy_timestamp_semantics"] == "unclassified"
    assert "q_event_tick_ms" not in record
    assert record["legacy_first_tick_ms"] == 1234
    assert record["legacy_second_tick_ms"] == 1235


def test_clock_exchange_collector_emits_explicit_v2_event_identities():
    collector = ClockExchangeCollector()
    collector.begin_probe(
        7,
        1_000_000_000,
        sample_role="formal",
        included_in_fit=True,
    )
    reply = parse_clock_sync_reply(frame(
        "T,7,1234,1235,1236,1237,2"
    ))
    assert collector.complete_probe(reply, 1_012_000_000) is True

    record = collector.records()[0]
    assert record["q_event_tick_ms"] == 1234
    assert record["q_parse_done_tick_ms"] == 1235
    assert record["t_event_tick_ms"] == 1236
    assert record["t_payload_generated_tick_ms"] == 1237
    assert record["fit_requested"] is True
    assert record["included_in_fit"] is False
    assert record["fit_exclusion_reason"] == "uncertainty_unverified"
    assert record["q_parse_causal_parent_event_id"] == record["q_event_id"]
    assert record["t_payload_causal_parent_event_id"] == record["t_event_id"]
    assert len({
        record["q_event_id"],
        record["q_parse_event_id"],
        record["t_event_id"],
        record["t_payload_event_id"],
    }) == 4
    assert "mcu_rx_tick_ms" not in record
    assert "mcu_tx_tick_ms" not in record


def test_capture_v2_uncertainty_is_unknown_until_a_bound_is_verified():
    collector = ClockExchangeCollector()
    collector.begin_probe(
        8, 2_000_000_000, sample_role="formal", included_in_fit=True
    )
    reply = parse_clock_sync_reply(frame(
        "T,8,2234,2235,2236,2237,2"
    ))
    assert collector.complete_probe(reply, 2_012_000_000) is True

    record = collector.records()[0]
    assert record["q_event_uncertainty_ns"] is None
    assert record["t_event_uncertainty_ns"] is None
    assert record["pc_tx_event_uncertainty_ns"] is None
    assert record["pc_rx_event_uncertainty_ns"] is None
    report = build_causal_sync_report(collector.records())
    assert report["verdict"] == "INSUFFICIENT EVIDENCE"
    assert "uncertainty" in report["reason"]


def test_capture_v3_keeps_unbounded_pc_edges_out_of_causal_fit():
    collector = ClockExchangeCollector()
    collector.begin_probe(
        9, 2_000_000_000, sample_role="formal", included_in_fit=True
    )
    reply = parse_clock_sync_reply(frame(
        "T,9,0000002234,0000002235,0000002236,0000002237,3,001000000,001000000"
    ))

    assert collector.complete_probe(reply, 2_012_000_000) is True
    record = collector.records()[0]

    for field in ("q_event_uncertainty_ns", "t_event_uncertainty_ns"):
        assert isinstance(record[field], int)
        assert record[field] > 0
    assert record["pc_tx_event_uncertainty_ns"] is None
    assert record["pc_rx_event_uncertainty_ns"] is None
    assert record["included_in_fit"] is False
    assert record["fit_exclusion_reason"] == "uncertainty_unverified"
    report = build_causal_sync_report([record])
    assert report["fit_input_count"] == 0
    assert report["verdict"] == "INSUFFICIENT EVIDENCE"


def test_pc_endpoint_interval_admits_formal_v3_exchange():
    collector = ClockExchangeCollector()
    collector.begin_probe(
        10,
        pc_tx_interval_ns=(1_000, 1_100),
        sample_role="formal",
        included_in_fit=True,
    )
    reply = parse_clock_sync_reply(frame(
        "T,10,0000002234,0000002235,0000002236,0000002237,3,001000000,001000000"
    ))

    assert collector.complete_probe(
        reply,
        pc_rx_interval_ns=(2_000, 2_200),
    ) is True
    record = collector.records()[0]

    assert record["pc_tx_ns"] == 1_050
    assert record["pc_rx_ns"] == 2_100
    assert record["pc_tx_event_uncertainty_ns"] == 50
    assert record["pc_rx_event_uncertainty_ns"] == 100
    assert record["pc_tx_boundary_start_ns"] == 1_000
    assert record["pc_tx_boundary_end_ns"] == 1_100
    assert record["pc_rx_boundary_start_ns"] == 2_000
    assert record["pc_rx_boundary_end_ns"] == 2_200
    assert record["pc_endpoint_uncertainty_model"] == (
        "application_call_interval_midpoint_v1"
    )
    assert record["included_in_fit"] is True


def test_pc_endpoint_interval_rejects_malformed_bounds():
    collector = ClockExchangeCollector()

    with pytest.raises(ValueError, match="ordered"):
        collector.begin_probe(
            11,
            pc_tx_interval_ns=(2_000, 1_000),
            sample_role="formal",
            included_in_fit=True,
        )

    collector.begin_probe(
        11,
        pc_tx_interval_ns=(1_000, 1_000),
        sample_role="formal",
        included_in_fit=True,
    )
    reply = parse_clock_sync_reply(frame(
        "T,11,0000002234,0000002235,0000002236,0000002237,3,001000000,001000000"
    ))
    with pytest.raises(ValueError, match="ordered"):
        collector.complete_probe(reply, pc_rx_interval_ns=(3_000, 2_000))


def test_clock_exchange_collector_preserves_unmatched_sequence_evidence():
    collector = ClockExchangeCollector()
    collector.begin_probe(
        7, 1_000, sample_role="formal", included_in_fit=True
    )
    collector.complete_probe(ClockSyncReply(8, 10, 11), 2_000)

    evidence = collector.to_dict()

    assert evidence["records"] == []
    assert evidence["unmatched_replies"] == [8]
    assert evidence["pending_sequences"] == [7]


def test_existing_mixed_stream_parser_dispatches_clock_reply_lines():
    lines = []
    parser = MixedStreamParser(on_line=lines.append)

    for byte in "T,7,1234,1235,4E\n".encode("ascii"):
        parser.feed(byte)

    assert lines == ["T,7,1234,1235,4E\n"]
