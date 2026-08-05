# -*- coding: utf-8 -*-
"""0x02 health frame parser tests (firmware health baseline, Task 8).

TDD: RED = decode_health / PAYLOAD_LEN_MAX / FRAME_TYPE_HEALTH absent ->
      ImportError / assertion failure.  GREEN = all pass.

Cross-language golden lock (Task 11): the golden frame here is the same
golden_health_0x02.hex that test_health_frame.c asserts the C encoder
produces.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from real_world.frame_parser import (  # noqa: E402
    FrameParser,
    FRAME_TYPE_HEALTH,
    FRAME_TYPE_STATUS,
    FRAME_TYPE_TELEMETRY,
    PAYLOAD_LEN_HEALTH,
    PAYLOAD_LEN_STATUS,
    PAYLOAD_LEN_MAX,
    decode_health,
    decode_status,
    decode_telemetry,
)

GOLDEN_HEX = os.path.join(
    os.path.dirname(__file__), "fixtures", "golden_health_0x02.hex")


def load_golden():
    with io.open(GOLDEN_HEX, "r", encoding="ascii") as f:
        return bytes(int(b, 16) for b in f.read().split())


GOLDEN = load_golden()   # 111 bytes: AA55 02 6A + 106B payload + CD


def build_frame(ftype, payload):
    body = bytes([0xAA, 0x55, ftype, len(payload)]) + bytes(payload)
    cs = ftype ^ len(payload)
    for b in payload:
        cs ^= b
    return body + bytes([cs & 0xFF])


def test_golden_health_frame_parses_and_decodes():
    parser = FrameParser()
    results = parser.feed_buffer(GOLDEN)
    assert len(results) == 1, "golden 0x02 frame must parse"
    ftype, payload = results[0]
    assert ftype == FRAME_TYPE_HEALTH
    assert len(payload) == PAYLOAD_LEN_HEALTH

    d = decode_health(payload)
    assert d is not None
    # Spot check 8 fields required by plan Task 8 Step 8.1
    assert d["snapshot_tick_ms"] == 1000000
    assert d["loop_seq"] == 123456
    assert d["heartbeat_age_ms"] == 200
    assert d["uart_rx_bytes"] == 10000
    assert d["uart_tx_high_water"] == 48
    assert d["health_started"] == 10
    assert d["health_ok"] == 9
    assert d["health_last_duration_ms"] == 45
    # Full identity + health_* six items
    assert d["fw_schema_version"] == 1
    assert d["fw_build_id"] == 1
    assert d["reset_cause"] == 0x08
    assert d["motion_state"] == 1
    assert d["lease_active"] == 1
    assert d["heartbeat_last_reason"] == 2
    assert d["heartbeat_timeout_count"] == 3
    assert d["heartbeat_count"] == 10
    assert d["connection_generation"] == 1
    assert d["health_generated"] == 12
    assert d["health_dropped"] == 2
    assert d["health_failed"] == 1
    assert d["health_started"] == 10
    assert d["uart_tx_high_water"] == 48
    assert d["uart_rx_high_water"] == 64


def test_decode_health_wrong_length_returns_none():
    assert decode_health(b"") is None
    assert decode_health(b"\x01" * (PAYLOAD_LEN_HEALTH - 1)) is None
    assert decode_health(b"\x01" * (PAYLOAD_LEN_HEALTH + 1)) is None


def test_old_status_7_bytes_preserved():
    """(0x02, len==7) keeps routing to decode_status (legacy STATUS)."""
    parser = FrameParser()
    status_payload = bytes([0, 1, 2, 3, 4, 5, 6])   # 7 bytes
    results = parser.feed_buffer(build_frame(FRAME_TYPE_STATUS, status_payload))
    assert len(results) == 1
    ftype, payload = results[0]
    assert ftype == FRAME_TYPE_STATUS
    assert decode_status(payload) is not None


def test_bad_0x02_length_rejected():
    """(0x02, other non-7/106 len) -> frames_bad++ (never a valid frame)."""
    parser = FrameParser()
    results = parser.feed_buffer(build_frame(FRAME_TYPE_HEALTH, bytes(range(20))))
    assert results == []
    assert parser.frames_bad == 1
    assert parser.resync_count == 1


def test_len_over_106_rejected():
    """len > PAYLOAD_LEN_MAX(106) -> frames_bad++ (no persistent desync)."""
    parser = FrameParser()
    big_payload = bytes(range(107))
    results = parser.feed_buffer(build_frame(FRAME_TYPE_TELEMETRY, big_payload))
    assert results == []
    assert parser.frames_bad == 1
    # next valid frame still parses
    tele = build_frame(FRAME_TYPE_TELEMETRY, bytes(24))
    r2 = parser.feed_buffer(tele)
    assert len(r2) == 1 and r2[0][0] == FRAME_TYPE_TELEMETRY


def test_telemetry_still_decodes():
    """0x01 telemetry unchanged (29-byte frame, decode_telemetry)."""
    parser = FrameParser()
    payload = bytearray(24)
    payload[0:4] = bytes([1, 1, 1, 1])
    payload[4:6] = (650).to_bytes(2, "little", signed=True)
    payload[6:8] = (650).to_bytes(2, "little", signed=True)
    payload[8:10] = (650).to_bytes(2, "little", signed=True)
    payload[10:12] = (650).to_bytes(2, "little", signed=True)
    payload[12:16] = (0).to_bytes(4, "little", signed=True)
    payload[16:20] = (1234).to_bytes(4, "little")
    payload[20:24] = (0).to_bytes(4, "little", signed=True)
    results = parser.feed_buffer(build_frame(FRAME_TYPE_TELEMETRY, bytes(payload)))
    assert len(results) == 1
    assert results[0][0] == FRAME_TYPE_TELEMETRY
    d = decode_telemetry(results[0][1])
    assert d["tick_ms"] == 1234
    assert d["m1"] == 650


def test_three_concatenated_telemetry_frames_parse_individually():
    """A batched CIPSEND payload must preserve all 0x01 frame boundaries."""
    frames = []
    for tick in (100, 120, 140):
        payload = bytearray(24)
        payload[0:4] = bytes([1, 1, 1, 1])
        payload[4:6] = (650).to_bytes(2, "little", signed=True)
        payload[6:8] = (650).to_bytes(2, "little", signed=True)
        payload[8:10] = (650).to_bytes(2, "little", signed=True)
        payload[10:12] = (650).to_bytes(2, "little", signed=True)
        payload[16:20] = tick.to_bytes(4, "little")
        frames.append(build_frame(FRAME_TYPE_TELEMETRY, payload))

    parser = FrameParser()
    results = parser.feed_buffer(b"".join(frames))
    assert len(results) == 3
    assert parser.frames_ok == 3
    assert parser.frames_bad == 0
    assert [decode_telemetry(payload)["tick_ms"] for _, payload in results] == [
        100, 120, 140
    ]
