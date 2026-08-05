# -*- coding: utf-8 -*-
"""Production wifi_bridge (real_world) joint (frame_type, payload_len)
dispatch for 0x02 (firmware health baseline, Round 2 item 1 / plan Task 8).

Rules locked:
  (0x02, len==7)   -> decode_status (legacy STATUS preserved)
  (0x02, len==106) -> decode_health, NEVER broadcast as car_status
  (0x02, other)    -> rejected (never car_status)
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from real_world.frame_parser import (  # noqa: E402
    FRAME_TYPE_HEALTH,
    FRAME_TYPE_STATUS,
    FRAME_TYPE_TELEMETRY,
    PAYLOAD_LEN_HEALTH,
    PAYLOAD_LEN_STATUS,
)
from real_world.wifi_bridge import WifiBridge  # noqa: E402

GOLDEN_HEX = os.path.join(
    os.path.dirname(__file__), "fixtures", "golden_health_0x02.hex")


def load_golden():
    with io.open(GOLDEN_HEX, "r", encoding="ascii") as f:
        return bytes(int(b, 16) for b in f.read().split())


GOLDEN = load_golden()
HEALTH_PAYLOAD = GOLDEN[4:4 + PAYLOAD_LEN_HEALTH]
STATUS_PAYLOAD_7 = bytes([0, 1, 2, 3, 4, 5, 6])


def test_health_106_goes_to_health_not_status():
    bridge = WifiBridge()
    bridge._process_binary_frame((FRAME_TYPE_HEALTH, HEALTH_PAYLOAD))
    h = bridge.get_latest_health()
    assert h is not None
    assert h["snapshot_tick_ms"] == 1000000
    assert h["health_ok"] == 9
    # NEVER broadcast as car_status
    assert bridge.get_latest_status() is None


def test_status_7_preserved_as_status():
    bridge = WifiBridge()
    bridge._process_binary_frame((FRAME_TYPE_STATUS, STATUS_PAYLOAD_7))
    assert bridge.get_latest_status() is not None
    assert bridge.get_latest_health() is None


def test_bad_0x02_length_never_car_status():
    bridge = WifiBridge()
    bridge._process_binary_frame((FRAME_TYPE_HEALTH, b"\x00" * 20))
    assert bridge.get_latest_health() is None
    assert bridge.get_latest_status() is None
    # rejected -> error counter increments
    assert bridge._error_count == 1


def test_telemetry_unchanged():
    bridge = WifiBridge()
    payload = bytearray(24)
    payload[0:4] = bytes([1, 1, 1, 1])
    payload[4:6] = (650).to_bytes(2, "little", signed=True)
    payload[6:8] = (650).to_bytes(2, "little", signed=True)
    payload[8:10] = (650).to_bytes(2, "little", signed=True)
    payload[10:12] = (650).to_bytes(2, "little", signed=True)
    payload[12:16] = (0).to_bytes(4, "little", signed=True)
    payload[16:20] = (1234).to_bytes(4, "little")
    payload[20:24] = (0).to_bytes(4, "little", signed=True)
    bridge._process_binary_frame((FRAME_TYPE_TELEMETRY, bytes(payload)))
    assert bridge.get_latest() is not None
    assert bridge.get_latest().tick_ms == 1234
