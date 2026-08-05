"""Tests for StreamDemuxer: ASCII lines + AA55 binary separation."""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from real_world.stream_demuxer import StreamDemuxer
from real_world.runtime_protocol import ParameterAck, RunStatus, frame, parse_ack, parse_status


def _a_line(camp: str, ver: int, outcome: str, reason: str) -> bytes:
    return frame("A,{0},{1},{2},{3}".format(camp, ver, outcome, reason)).encode("ascii")


def _s_line(camp: str, run: str, state: str, reason: str, tick: int) -> bytes:
    return frame("S,{0},{1},{2},{3},{4}".format(camp, run, state, reason, tick)).encode("ascii")


_AA55_BINARY_24 = b"\xAA\x55" + bytes(22)


def test_ascii_a_line_is_detected():
    lines = []
    d = StreamDemuxer(on_ascii_line=lines.append)
    for b in _a_line("camp-001", 2, "APPLIED", "APPLIED"):
        d.feed(b)
    assert len(lines) == 1
    assert lines[0] == _a_line("camp-001", 2, "APPLIED", "APPLIED").decode("ascii")


def test_ascii_s_line_is_detected():
    lines = []
    d = StreamDemuxer(on_ascii_line=lines.append)
    for b in _s_line("camp-001", "run-001", "running", "ok", 42):
        d.feed(b)
    assert len(lines) == 1
    status = parse_status(lines[0])
    assert isinstance(status, RunStatus)
    assert status.campaign_id == "camp-001"
    assert status.run_id == "run-001"


def test_multiple_ascii_lines():
    lines = []
    d = StreamDemuxer(on_ascii_line=lines.append)
    data = _a_line("camp-001", 1, "APPLIED", "APPLIED") + _s_line("camp-001", "run-001", "done", "finish", 100)
    for b in data:
        d.feed(b)
    assert len(lines) == 2
    assert lines[0].startswith("A,")
    assert lines[1].startswith("S,")


def test_aa55_binary_bytes_do_not_corrupt_ascii_line():
    lines = []
    d = StreamDemuxer(on_ascii_line=lines.append)
    data = _AA55_BINARY_24 + _a_line("camp-001", 2, "APPLIED", "APPLIED")
    for b in data:
        d.feed(b)
    assert len(lines) == 1
    assert lines[0].startswith("A,")


def test_mixed_ascii_and_binary():
    lines = []
    d = StreamDemuxer(on_ascii_line=lines.append)
    data = _s_line("camp-001", "run-001", "running", "ok", 42) + _AA55_BINARY_24 + _a_line("camp-001", 3, "REJECTED", "PARAM_BOUNDS")
    for b in data:
        d.feed(b)
    assert len(lines) == 2
    assert "camp-001" in lines[0]
    assert "camp-001" in lines[1]


def test_partial_line_flushed_on_binary():
    lines = []
    d = StreamDemuxer(on_ascii_line=lines.append)
    data = b"A,camp-001,2" + _AA55_BINARY_24 + b",APPLIED,APPLIED,27\n"
    for b in data:
        d.feed(b)
    assert len(lines) == 1


def test_non_printable_byte_flushes_and_does_not_corrupt():
    lines = []
    d = StreamDemuxer(on_ascii_line=lines.append)
    data = b"garbage\x01\x02\x03" + _a_line("camp-001", 1, "APPLIED", "APPLIED")
    for b in data:
        d.feed(b)
    assert len(lines) == 1
    assert lines[0].startswith("A,")


def test_parse_status_from_demuxed_line():
    lines = []
    d = StreamDemuxer(on_ascii_line=lines.append)
    for b in _s_line("camp-001", "run-007", "stopped", "STOP", 1234):
        d.feed(b)
    assert len(lines) == 1
    status = parse_status(lines[0])
    assert isinstance(status, RunStatus)
    assert status.campaign_id == "camp-001"
    assert status.run_id == "run-007"
    assert status.state == "stopped"
    assert status.reason == "STOP"
    assert status.tick_ms == 1234
