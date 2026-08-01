"""Task 4B-4 fix (Codex review remediation — Gap 3): START 后清理完整性。

离线测试，使用 fake socket/camera，**不连接真车或摄像头**，**不运行真实
capture_sync_run.main()**。只调用可注入的 `run_sync_capture_session()` /
`cleanup_session()`。

覆盖（修复前 RED — 旧代码没有 session/cleanup API，ImportError）：
  1. START 已发出但无遥测（超时）：STOP attempt、socket close、camera
     release 都恰好执行一次。
  2. START 已发出但采集期间异常：STOP attempt、socket close、camera
     release 都恰好执行一次。
  3. STOP 发送失败仍继续关闭 socket 和相机。
  4. START 发送失败时不假称已经 STOP（动作状态如实报告）。
  5. cleanup_session 幂等：重复调用不重复执行。
"""

from __future__ import annotations

import os
import socket
import struct
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                ".embeddedskills", "build", "v1_task4b4"))

import pytest

import capture_sync_run


# ── Fake objects ────────────────────────────────────────────────────────

def _encode_telemetry_frame(tick_ms=0, yaw_deg=0.0):
    """编码一帧合法遥测（type=0x01, len=24, XOR checksum）。"""
    payload = bytearray(24)
    for i, v in enumerate((0, 0, 0, 0)):   # m1..m4
        struct.pack_into("<h", payload, 4 + 2 * i, v)
    struct.pack_into("<h", payload, 12, 0)       # error
    struct.pack_into("<h", payload, 14, 0)       # pid_output
    struct.pack_into("<I", payload, 16, tick_ms)
    struct.pack_into("<i", payload, 20, int(yaw_deg * 100.0))
    cs = 0x01 ^ 24
    for b in payload:
        cs ^= b
    return bytes([0xAA, 0x55, 0x01, 24]) + bytes(payload) + bytes([cs])


class FakeSocket:
    """可注入 socket：记录 recv/sendall/close 调用，可配置失败行为。"""

    def __init__(self, recv_data=b"", fail_start=False, fail_stop=False):
        self._recv_data = recv_data
        self._recv_sent = False
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.sendall_calls = 0
        self.sent = []
        self.recv_calls = 0
        self.close_calls = 0
        self.closed = False

    def settimeout(self, _timeout):
        pass

    def recv(self, _n):
        self.recv_calls += 1
        if not self._recv_sent:
            self._recv_sent = True
            return self._recv_data
        return b""   # EOF → reader thread breaks

    def sendall(self, data):
        self.sendall_calls += 1
        self.sent.append(data)
        if self.sendall_calls == 1 and self.fail_start:
            raise OSError("fake start failure")
        if self.sendall_calls == 2 and self.fail_stop:
            raise OSError("fake stop failure")
        return None

    def close(self):
        self.close_calls += 1
        self.closed = True


class FakeCamera:
    """可注入 camera：记录 read/release 调用，可配置异常。"""

    def __init__(self, read_exc=None):
        self.read_exc = read_exc
        self.read_calls = 0
        self.release_calls = 0

    def get(self, _prop):
        return 1280 if _prop == 3 else 720   # width/height

    def read(self):
        self.read_calls += 1
        if self.read_exc is not None:
            raise self.read_exc
        return False, None

    def release(self):
        self.release_calls += 1


class DummyTracker:
    def track(self, frame, t_pc_ns=None):
        return None


@pytest.fixture
def tracker():
    return DummyTracker()


# ── Scenario 1: START sent, no telemetry → timeout, cleanup exactly once ──

def test_no_telemetry_timeout_cleans_up_once(tracker):
    sock = FakeSocket(recv_data=b"")
    cap = FakeCamera()
    telemetry, poses, actions, outcome = capture_sync_run.run_sync_capture_session(
        sock, cap, tracker, "run-1", duration_s=0.01, wait_timeout_s=0.05)

    assert outcome == "no_telemetry_timeout"
    assert actions["start_sent"] is True
    assert actions["stop_attempted"] is True
    assert actions["stop_sent"] is True
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True
    assert sock.close_calls == 1
    assert cap.release_calls == 1
    # STOP 恰好一次
    stop_cmds = [d for d in sock.sent if b"STOP" in d]
    assert len(stop_cmds) == 1


# ── Scenario 2: START sent, exception during collection ─────────────────

def test_collect_exception_cleans_up_once(tracker):
    sock = FakeSocket(recv_data=_encode_telemetry_frame(tick_ms=100))
    cap = FakeCamera(read_exc=RuntimeError("fake read failure"))
    telemetry, poses, actions, outcome = capture_sync_run.run_sync_capture_session(
        sock, cap, tracker, "run-1", duration_s=0.1, wait_timeout_s=0.5)

    assert outcome == "collect_error"
    assert actions["start_sent"] is True
    assert actions["collect_error"] is not None
    assert len(telemetry) >= 1            # 遥测确实到达，进入采集阶段
    assert actions["stop_attempted"] is True
    assert actions["stop_sent"] is True
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True
    assert sock.close_calls == 1
    assert cap.release_calls == 1


# ── Scenario 3: STOP send fails → socket + camera still closed/released ──

def test_stop_failure_still_closes_socket_and_camera(tracker):
    sock = FakeSocket(recv_data=b"", fail_stop=True)
    cap = FakeCamera()
    telemetry, poses, actions, outcome = capture_sync_run.run_sync_capture_session(
        sock, cap, tracker, "run-1", duration_s=0.01, wait_timeout_s=0.05)

    assert outcome == "no_telemetry_timeout"
    assert actions["stop_attempted"] is True
    assert actions["stop_sent"] is False
    assert actions["stop_error"] is not None
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True
    assert sock.close_calls == 1
    assert cap.release_calls == 1


# ── Scenario 4: START send fails → no false STOP claim ──────────────────

def test_start_failure_no_false_stop_claim(tracker):
    sock = FakeSocket(recv_data=b"", fail_start=True)
    cap = FakeCamera()
    telemetry, poses, actions, outcome = capture_sync_run.run_sync_capture_session(
        sock, cap, tracker, "run-1", duration_s=0.01, wait_timeout_s=0.05)

    assert outcome == "start_failed"
    assert actions["start_sent"] is False
    assert actions["start_error"] is not None
    assert actions["stop_attempted"] is False
    assert actions["stop_sent"] is False
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True
    assert sock.close_calls == 1
    assert cap.release_calls == 1
    # 不得有 STOP 帧被发送
    assert not any(b"STOP" in d for d in sock.sent)


# ── Scenario 5: cleanup_session is idempotent ────────────────────────────

def test_cleanup_idempotent():
    sock = FakeSocket()
    cap = FakeCamera()
    actions = capture_sync_run._new_action_state()
    actions["start_sent"] = True

    capture_sync_run.cleanup_session(sock, cap, "run-1", actions)
    capture_sync_run.cleanup_session(sock, cap, "run-1", actions)

    assert actions["cleaned_up"] is True
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True
    assert sock.close_calls == 1
    assert cap.release_calls == 1
    assert actions["stop_sent"] is True
