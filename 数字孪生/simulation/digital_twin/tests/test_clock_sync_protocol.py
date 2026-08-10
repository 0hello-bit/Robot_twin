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
    parse_clock_sync_reply,
)


def test_clock_probe_uses_existing_xor_framing():
    packet = ClockSyncProbe(7).encode()

    assert packet == "Q,7,4A\n"


def test_clock_reply_round_trips_sequence_and_mcu_ticks():
    reply = parse_clock_sync_reply("T,7,1234,1235,4E\n")

    assert reply == ClockSyncReply(7, 1234, 1235)


def test_clock_reply_rejects_tampered_checksum():
    with pytest.raises(ProtocolError, match="checksum"):
        parse_clock_sync_reply("T,7,1234,1235,00\n")


def test_clock_exchange_collector_retains_t1_t2_t3_t4():
    collector = ClockExchangeCollector()

    probe = collector.begin_probe(7, 1_000_000_000)
    collector.complete_probe(
        ClockSyncReply(7, 1234, 1235),
        1_012_000_000,
    )

    assert probe == ClockSyncProbe(7).encode().encode("ascii")
    assert collector.records() == [{
        "sequence": 7,
        "pc_tx_ns": 1_000_000_000,
        "mcu_rx_tick_ms": 1234,
        "mcu_tx_tick_ms": 1235,
        "pc_rx_ns": 1_012_000_000,
    }]


def test_clock_exchange_collector_preserves_unmatched_sequence_evidence():
    collector = ClockExchangeCollector()
    collector.begin_probe(7, 1_000)
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
