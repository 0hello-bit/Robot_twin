# -*- coding: utf-8 -*-
"""Permanent regression for the OLD-parser 0x02 compatibility boundary
(firmware health baseline, plan Task 8 Step 8.0; design §8.1).

The old parser (before this batch) had a hardcoded payload length cap of 64.
A new 0x02 frame (len=106 > 64) was rejected: no crash, no frame returned,
frames_bad+1, resync_count+1, and no persistent desync (the next 0x01 frame
still parsed).

This test reproduces the DOCUMENTED old rule by lowering PAYLOAD_LEN_MAX to
64 (the value it held before this batch), asserting the boundary, and then
asserting the NEW cap (106) accepts the golden 0x02 frame.  It is a metric
compatibility change: the old tool counts each 0x02 as a bad frame; we do
not claim full backward compatibility (design §8.1).
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import real_world.frame_parser as fp_module  # noqa: E402
from real_world.frame_parser import (  # noqa: E402
    FrameParser,
    FRAME_TYPE_TELEMETRY,
)

GOLDEN_HEX = os.path.join(
    os.path.dirname(__file__), "fixtures", "golden_health_0x02.hex")


def load_golden():
    with io.open(GOLDEN_HEX, "r", encoding="ascii") as f:
        return bytes(int(b, 16) for b in f.read().split())


def build_frame(ftype, payload):
    body = bytes([0xAA, 0x55, ftype, len(payload)]) + bytes(payload)
    cs = ftype ^ len(payload)
    for b in payload:
        cs ^= b
    return body + bytes([cs & 0xFF])


def test_old_cap_64_rejects_health_frame():
    """Reproduce the documented pre-batch rule (cap 64): reject, no crash,
    no persistent desync."""
    golden = load_golden()
    assert len(golden) == 111
    original_max = fp_module.PAYLOAD_LEN_MAX
    fp_module.PAYLOAD_LEN_MAX = 64   # documented old cap
    try:
        parser = FrameParser()
        results = parser.feed_buffer(golden)
        assert results == []
        stats = parser.get_stats()
        assert stats["frames_bad"] == 1
        assert stats["resync_count"] == 1
        # no persistent desync: next 0x01 still parses
        tele = build_frame(FRAME_TYPE_TELEMETRY, bytes(24))
        r2 = parser.feed_buffer(tele)
        assert len(r2) == 1 and r2[0][0] == FRAME_TYPE_TELEMETRY
    finally:
        fp_module.PAYLOAD_LEN_MAX = original_max


def test_new_cap_106_accepts_health_frame():
    """The new cap (106) accepts the golden 0x02 frame (new behaviour)."""
    golden = load_golden()
    parser = FrameParser()
    results = parser.feed_buffer(golden)
    assert len(results) == 1
    assert results[0][0] == 0x02
    assert len(results[0][1]) == 106
