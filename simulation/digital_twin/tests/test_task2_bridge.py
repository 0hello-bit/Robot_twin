"""Unit tests for Task 2: AckRegistry and CampaignTelemetry backward compat."""

from __future__ import annotations

import asyncio
import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from real_world.runtime_command_client import AckRegistry
from real_world.telemetry_protocol import CampaignTelemetry, TelemetryPacket
from real_world.data_logger import RealDataLogger


# ===========================================================================
# AckRegistry tests
# ===========================================================================

def test_register_and_deliver():
    reg = AckRegistry()
    ack = ("camp-001", 1, "APPLIED", "APPLIED")

    async def run():
        fut = reg.register("camp-001", 1)
        reg.deliver("camp-001", 1, ack)
        result = await asyncio.wait_for(fut, timeout=0.5)
        return result

    result = asyncio.run(run())
    assert result == ack
    assert reg.pending_count() == 0


def test_timeout_returns_none():
    reg = AckRegistry()

    async def run():
        fut = reg.register("camp-001", 1)
        try:
            result = await asyncio.wait_for(fut, timeout=0.1)
            return result
        except asyncio.TimeoutError:
            return None

    result = asyncio.run(run())
    assert result is None


def test_wrong_campaign_not_delivered():
    reg = AckRegistry()
    correct_ack = ("camp-001", 1, "APPLIED", "APPLIED")
    wrong_ack = ("other", 1, "REJECTED", "INHIBITED")

    async def run():
        fut = reg.register("camp-001", 1)
        # Deliver wrong ACK
        reg.deliver("other", 1, wrong_ack)
        # Wait briefly — should time out since correct ACK never arrives
        try:
            await asyncio.wait_for(fut, timeout=0.1)
            return "unexpected"
        except asyncio.TimeoutError:
            return None

    result = asyncio.run(run())
    assert result is None


def test_duplicate_register_raises():
    reg = AckRegistry()
    async def run():
        reg.register("dup", 1)
        raised = False
        try:
            reg.register("dup", 1)
        except RuntimeError:
            raised = True
        return raised
    raised = asyncio.run(run())
    assert raised


def test_pending_count():
    reg = AckRegistry()
    async def run():
        assert reg.pending_count() == 0
        reg.register("a", 1)
        assert reg.pending_count() == 1
        reg.deliver("a", 1, "done")
        assert reg.pending_count() == 0
    asyncio.run(run())


def test_fail_all():
    reg = AckRegistry()
    results = []

    async def run():
        f1 = reg.register("a", 1)
        f2 = reg.register("b", 2)
        reg.fail_all("disconnect test")
        for f in (f1, f2):
            try:
                await f
            except RuntimeError as e:
                results.append(("error", str(e)))
        return results

    results = asyncio.run(run())
    assert len(results) == 2
    for r in results:
        assert r[0] == "error"
        assert "disconnect" in r[1]
    assert reg.pending_count() == 0


def test_pending_count():
    reg = AckRegistry()
    async def run():
        assert reg.pending_count() == 0
        reg.register("a", 1)
        assert reg.pending_count() == 1
        reg.deliver("a", 1, "done")
        assert reg.pending_count() == 0
    asyncio.run(run())


# ===========================================================================
# CampaignTelemetry tests
# ===========================================================================

def test_campaign_telemetry_from_packet():
    pkt = TelemetryPacket()
    pkt.tick_ms = 12345
    pkt.s0 = 0
    pkt.s1 = 1
    pkt.s2 = 0
    pkt.s3 = 1
    pkt.error = -3
    pkt.pid_output = 150
    pkt.left_pwm = 200
    pkt.right_pwm = 220

    ct = CampaignTelemetry.from_telemetry_packet(
        pkt,
        campaign_id="camp-001",
        run_id="run-007",
        parameter_version=2,
        termination_reason="completed",
    )
    assert ct.campaign_id == "camp-001"
    assert ct.run_id == "run-007"
    assert ct.parameter_version == 2
    assert ct.termination_reason == "completed"
    assert ct.tick_ms == 12345
    assert ct.sensors == (0, 1, 0, 1)
    assert ct.error == -3.0
    assert ct.pid_output == 150.0
    assert ct.left_pwm == 200
    assert ct.right_pwm == 220


def test_campaign_telemetry_round_trip():
    ct = CampaignTelemetry(
        campaign_id="camp-001",
        run_id="run-007",
        parameter_version=2,
        termination_reason="completed",
        tick_ms=12345,
        sensors=(0, 1, 0, 1),
        error=-3.0,
        pid_output=150.0,
        left_pwm=200,
        right_pwm=220,
    )
    d = ct.to_dict()
    ct2 = CampaignTelemetry.from_dict(d)
    assert ct == ct2


def test_campaign_telemetry_legacy_load():
    """Legacy dict without campaign fields must load without error."""
    legacy = {
        "tick_ms": 100,
        "sensors": [1, 1, 0, 1],
        "error": 0.5,
        "pid_output": 42.0,
        "left_pwm": 180,
        "right_pwm": 180,
    }
    ct = CampaignTelemetry.from_dict(legacy)
    assert ct.campaign_id == ""
    assert ct.run_id == ""
    assert ct.parameter_version == 0
    assert ct.termination_reason == ""
    assert ct.tick_ms == 100


# ===========================================================================
# RealDataLogger campaign extension tests
# ===========================================================================

def test_data_logger_campaign_save_and_is_campaign(tmp_path):
    import tempfile
    logger = RealDataLogger()
    logger.start_campaign_run("camp-001", "run-001", parameter_version=2)
    logger.on_telemetry(TelemetryPacket())
    logger.on_telemetry(TelemetryPacket())

    filepath = os.path.join(tempfile.gettempdir(), "test_campaign_log.json")
    try:
        logger.save_campaign(filepath)
        with open(filepath, "r") as f:
            data = json.load(f)
        assert RealDataLogger.is_campaign_json(data)
        assert data["_campaign_meta"]["campaign_id"] == "camp-001"
        assert data["_campaign_meta"]["run_id"] == "run-001"
        assert data["_campaign_meta"]["parameter_version"] == 2
        assert "saved_at" in data["_campaign_meta"]
        assert len(data["data"]) == 2
    finally:
        if os.path.isfile(filepath):
            os.remove(filepath)


def test_data_logger_legacy_json_not_campaign(tmp_path):
    import tempfile
    filepath = os.path.join(tempfile.gettempdir(), "test_legacy_log.json")
    try:
        legacy = {
            "name": "old_session",
            "source": "real_stm32",
            "data": [{"tick_ms": 1}],
        }
        with open(filepath, "w") as f:
            json.dump(legacy, f)
        with open(filepath, "r") as f:
            data = json.load(f)
        assert not RealDataLogger.is_campaign_json(data)
    finally:
        if os.path.isfile(filepath):
            os.remove(filepath)


# ===========================================================================
# LiveWifiBridge._handle_client websockets compatibility
# ===========================================================================

class _MockWebSocket:
    """Minimal mock that captures send and close for handler tests.

    __aiter__/__anext__ let the handler's 'async for message in websocket'
    loop exit immediately (no real messages to receive).
    """
    def __init__(self, request_path="/live"):
        self.request = type("Req", (), {"path": request_path})()
        self.closed_code = None
        self.closed_reason = None
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code=1000, reason=""):
        if self.closed_code is None:
            self.closed_code = code
            self.closed_reason = reason

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def test_handler_accepts_old_two_arg_path():
    """Old websockets API: handler(websocket, path) with valid path."""
    from web_showcase.live_wifi_bridge import LiveWifiBridge
    bridge = LiveWifiBridge()
    ws = _MockWebSocket("/live")
    asyncio.run(bridge._handle_client(ws, "/live"))
    assert ws.closed_code is None, "should not close for /live"
    assert len(ws.sent) >= 1, "should have sent hello/bootstrap"
    assert json.loads(ws.sent[0]).get("type") == "hello", \
        "first message type should be 'hello', got: {0}".format(ws.sent[0][:80])


def test_handler_accepts_new_one_arg_no_path():
    """New websockets 17+ API: handler(websocket) — path from request.path."""
    from web_showcase.live_wifi_bridge import LiveWifiBridge
    bridge = LiveWifiBridge()
    ws = _MockWebSocket("/live")
    asyncio.run(bridge._handle_client(ws))
    assert ws.closed_code is None, "should not close for /live via request.path"
    assert len(ws.sent) >= 1, "should have sent hello/bootstrap"
    assert json.loads(ws.sent[0]).get("type") == "hello", \
        "first message type should be 'hello', got: {0}".format(ws.sent[0][:80])


def test_handler_rejects_invalid_path_old_style():
    """Old API: invalid path should close with 1008."""
    from web_showcase.live_wifi_bridge import LiveWifiBridge
    bridge = LiveWifiBridge()
    ws = _MockWebSocket("/invalid")
    asyncio.run(bridge._handle_client(ws, "/invalid"))
    assert ws.closed_code == 1008
    assert "Use /live" in (ws.closed_reason or "")
    assert len(ws.sent) == 0, "should not send anything on invalid path"


def test_handler_rejects_invalid_path_new_style():
    """New API: invalid request.path should close with 1008."""
    from web_showcase.live_wifi_bridge import LiveWifiBridge
    bridge = LiveWifiBridge()
    ws = _MockWebSocket("/invalid")
    asyncio.run(bridge._handle_client(ws))
    assert ws.closed_code == 1008
    assert "Use /live" in (ws.closed_reason or "")
    assert len(ws.sent) == 0, "should not send anything on invalid path"
