"""Offline regression tests for quiet-window causal clock sampling."""

from __future__ import annotations

import os
import socket
import sys
import time

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "tools", "camera_toolchain"
    ),
)

import capture_sync_run
from real_world.runtime_protocol import frame as protocol_frame


def _encode_telemetry_frame(tick_ms=100):
    payload = bytearray(24)
    payload[16:20] = int(tick_ms).to_bytes(4, "little")
    checksum = 0x01 ^ len(payload)
    for value in payload:
        checksum ^= value
    return bytes([0xAA, 0x55, 0x01, len(payload)]) + bytes(payload) + bytes([checksum])


def _status(campaign, run_id, state, reason, tick_ms=0):
    return protocol_frame(
        "S,{0},{1},{2},{3},{4}".format(
            campaign, run_id, state, reason, int(tick_ms)
        )
    ).encode("ascii")


class QuietClockSocket:
    """Fake socket that answers Q immediately and records command order."""

    def __init__(self):
        self.sent = []
        self.pending = []
        self.start_seen = False
        self.closed = False
        self.telemetry_sent = False

    def settimeout(self, _timeout):
        pass

    def sendall(self, data):
        data = bytes(data)
        self.sent.append(data)
        text = data.decode("ascii")
        if text.startswith("Q,"):
            sequence = int(text.split(",")[1])
            rx_tick = 1_000 + sequence
            self.pending.append(
                protocol_frame(
                    "T,{0},{1},{2}".format(sequence, rx_tick, rx_tick)
                ).encode("ascii")
            )
        elif ",START," in text:
            fields = text.strip().split(",")
            self.start_seen = True
            self.pending.append(_status(fields[1], fields[2], "RUNNING", "START"))
            self.pending.append(_encode_telemetry_frame())
        elif ",STOP," in text:
            fields = text.strip().split(",")
            self.pending.append(_status(fields[1], fields[2], "STOPPED", "STOP"))

    def recv(self, _size):
        if self.pending:
            return self.pending.pop(0)
        if not self.start_seen:
            raise socket.timeout()
        if not self.telemetry_sent:
            self.telemetry_sent = True
            return _encode_telemetry_frame(101)
        if self.closed:
            return b""
        time.sleep(0.001)
        raise socket.timeout()

    def close(self):
        self.closed = True


class OneFrameCamera:
    def read(self):
        return False, None

    def release(self):
        pass


class NoopTracker:
    def track(self, _frame, t_pc_ns=None):
        return None


def test_causal_clock_probes_stay_outside_motion_window(monkeypatch):
    monkeypatch.setattr(capture_sync_run, "CLOCK_PREFLIGHT_EXCHANGES", 2)
    monkeypatch.setattr(capture_sync_run, "CLOCK_POSTFLIGHT_EXCHANGES", 2)
    monkeypatch.setattr(capture_sync_run, "CLOCK_QUIET_PROBE_TIMEOUT_S", 0.5)

    sock = QuietClockSocket()
    diagnostics = {}
    _telemetry, _poses, actions, outcome = capture_sync_run.run_sync_capture_session(
        sock,
        OneFrameCamera(),
        NoopTracker(),
        "run-quiet-clock",
        0.01,
        0.5,
        diagnostics=diagnostics,
    )

    assert outcome == "ok"
    assert actions["start_sent"] is True
    assert actions["stop_confirmed"] is True

    phase = "before_start"
    for raw in sock.sent:
        text = raw.decode("ascii")
        if ",START," in text:
            phase = "during_run"
        elif ",STOP," in text:
            phase = "after_stop"
        elif text.startswith("Q,"):
            assert phase in {"before_start", "after_stop"}

    records = diagnostics["clock_exchanges"]["records"]
    assert [record["phase"] for record in records] == [
        "pre_start_quiet",
        "pre_start_quiet",
        "post_stop_quiet",
        "post_stop_quiet",
    ]
