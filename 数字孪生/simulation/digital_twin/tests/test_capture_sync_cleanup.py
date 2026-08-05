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
import json
import socket
import struct
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "tools", "camera_toolchain"))

import pytest

import capture_sync_run
from real_world.runtime_protocol import frame as protocol_frame


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


def _encode_status_line(campaign="sync", run_id="run-1", state="STOPPED",
                        reason="STOP", tick_ms=0):
    return protocol_frame("S,{0},{1},{2},{3},{4}".format(
        campaign, run_id, state, reason, tick_ms)).encode("ascii")


class StopStatusSocket(FakeSocket):
    """Keep the reader alive and publish status only after STOP is sent."""

    def __init__(self, telemetry, status_chunks):
        super().__init__(recv_data=b"")
        self._chunks = [telemetry]
        self._status_chunks = list(status_chunks)

    def recv(self, n):
        if self._chunks:
            return self._chunks.pop(0)
        if self.closed:
            return b""
        time.sleep(0.005)
        raise socket.timeout()

    def sendall(self, data):
        result = super().sendall(data)
        if b"STOP" in data:
            self._chunks.extend(self._status_chunks)
        return result


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


def test_capture_waits_for_reader_to_quiesce_before_return(tracker):
    telemetry_frame = _encode_telemetry_frame(tick_ms=100)

    class SlowReaderSocket(FakeSocket):
        def __init__(self):
            super().__init__(recv_data=telemetry_frame)
            self.second_recv_started = threading.Event()
            self.reader_done = threading.Event()

        def recv(self, n):
            if self.recv_calls == 0:
                return super().recv(n)
            self.recv_calls += 1
            self.second_recv_started.set()
            time.sleep(0.15)
            self.reader_done.set()
            return b""

    class WaitForReaderCamera(FakeCamera):
        def __init__(self, sock):
            super().__init__()
            self.sock = sock

        def read(self):
            assert self.sock.second_recv_started.wait(0.5)
            return False, None

    sock = SlowReaderSocket()
    cap = WaitForReaderCamera(sock)
    _telemetry, _poses, actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock, cap, tracker, "run-8", 0.01, 0.5
        )
    )

    assert outcome == "ok"
    assert sock.reader_done.is_set()
    assert actions["reader_joined"] is True


def test_cleanup_base_exception_does_not_skip_socket_or_camera_release(tracker):
    class CleanupBaseException(BaseException):
        pass

    class StopInterruptSocket(FakeSocket):
        def sendall(self, data):
            if self.sendall_calls == 1:
                self.sendall_calls += 1
                self.sent.append(data)
                raise CleanupBaseException("stop cleanup interrupted")
            return super().sendall(data)

    sock = StopInterruptSocket(recv_data=b"")
    cap = FakeCamera()
    _telemetry, _poses, actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock, cap, tracker, "run-9", 0.01, 0.05
        )
    )

    assert outcome == "no_telemetry_timeout"
    assert actions["stop_attempted"] is True
    assert actions["stop_sent"] is False
    assert "stop cleanup interrupted" in actions["stop_error"]
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True


def test_capture_camera_entrypoint_locks_index1_720p30_mjpg(monkeypatch):
    calls = []

    def fake_open_camera(index, **kwargs):
        calls.append((index, kwargs))
        return object(), 1280, 720

    monkeypatch.setattr(capture_sync_run.camera_common,
                        "open_camera", fake_open_camera)
    cap, width, height = capture_sync_run.open_capture_camera(1)

    assert cap is not None
    assert (width, height) == (1280, 720)
    assert calls == [(1, {
        "width": 1280,
        "height": 720,
        "fps": 30.0,
        "fourcc": "MJPG",
        "backend": capture_sync_run.cv2.CAP_DSHOW,
    })]


def test_sync_report_preserves_camera_mode_and_cleanup_evidence():
    report = capture_sync_run.build_sync_report(
        host="192.168.110.236",
        duration_s=0.5,
        run_id="sync-1",
        camera_mode={
            "index": 1,
            "width": 1280,
            "height": 720,
            "fps": 30.0,
            "fourcc": "MJPG",
        },
        actions={
            "start_sent": True,
            "stop_attempted": True,
            "stop_sent": True,
            "stop_confirmed": True,
            "socket_closed": True,
            "camera_released": True,
            "reader_joined": True,
        },
        outcome="ok",
        n_poses=12,
        n_telemetry=18,
        clock={"a": 1.0, "b": 2.0, "n_samples": 18},
        residuals={"rms_ns": 3.0, "max_ns": 4.0},
        sync={
            "coverage": 1.0,
            "p95_time_diff_ns": 5,
            "tolerance_ns": 33300000,
            "n_sync_frames": 12,
            "common_interval_start_ns": 10,
            "common_interval_end_ns": 20,
            "common_interval_duration_ns": 10,
            "n_common_poses": 12,
            "telemetry_interval_max_ns": 20,
            "telemetry_interval_p95_ns": 15,
            "n_telemetry_distinct": 12,
            "max_telemetry_reuse": 1,
            "verdict": "PASS",
            "gate_reason": "all gates passed",
        },
    )

    assert report["camera"]["actual"] == {
        "index": 1,
        "width": 1280,
        "height": 720,
        "fps": 30.0,
        "fourcc": "MJPG",
    }
    assert report["actions"]["stop_sent"] is True
    assert report["actions"]["reader_joined"] is True
    assert report["session_outcome"] == "ok"
    assert report["telemetry_yaw_unit"] == "radian"


def test_overall_gate_rejects_unconfirmed_stop_even_when_sync_passes():
    verdict, reason = capture_sync_run.evaluate_capture_gate(
        "PASS",
        {
            "stop_confirmed": False,
            "socket_closed": True,
            "camera_released": True,
            "reader_joined": True,
        },
        "ok",
    )

    assert verdict == "FAIL"
    assert "stop_confirmed" in reason


def test_stop_confirmation_accepts_only_matching_status_after_stop(tracker):
    telemetry = _encode_telemetry_frame(tick_ms=100)
    status = _encode_status_line("sync", "run-stop", "STOPPED", "STOP", 101)
    sock = StopStatusSocket(telemetry, [status[:4], status[4:]])
    cap = FakeCamera()

    _telemetry, _poses, actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock, cap, tracker, "run-stop", 0.01, 0.2,
            stop_confirm_timeout_s=0.2,
        )
    )

    assert outcome == "ok"
    assert actions["stop_confirmed"] is True
    assert actions["stop_status"]["run_id"] == "run-stop"
    assert actions["stop_status"]["state"] == "STOPPED"
    assert actions["stop_status"]["reason"] == "STOP"
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True
    assert actions["reader_joined"] is True


@pytest.mark.parametrize(
    "campaign,run_id,state,reason",
    [
        ("other", "run-stop", "STOPPED", "STOP"),
        ("sync", "other", "STOPPED", "STOP"),
        ("sync", "run-stop", "RUNNING", "START"),
        ("sync", "run-stop", "STOPPED", "TIMEOUT"),
    ],
)
def test_stop_confirmation_rejects_wrong_status_or_timeout(
        tracker, campaign, run_id, state, reason):
    telemetry = _encode_telemetry_frame(tick_ms=100)
    status = _encode_status_line(campaign, run_id, state, reason, 101)
    sock = StopStatusSocket(telemetry, [status])
    cap = FakeCamera()

    _telemetry, _poses, actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock, cap, tracker, "run-stop", 0.01, 0.2,
            stop_confirm_timeout_s=0.03,
        )
    )

    assert outcome == "ok"
    assert actions["stop_confirmed"] is False
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True
    assert actions["reader_joined"] is True


def test_overall_gate_rejects_cleanup_or_reader_not_converged():
    verdict, reason = capture_sync_run.evaluate_capture_gate(
        "PASS",
        {
            "stop_confirmed": True,
            "socket_closed": True,
            "camera_released": True,
            "reader_joined": False,
        },
        "ok",
    )

    assert verdict == "FAIL"
    assert "reader_joined" in reason


def test_read_camera_mode_records_actual_directshow_settings():
    class ModeCamera:
        def get(self, prop):
            values = {
                capture_sync_run.cv2.CAP_PROP_FRAME_WIDTH: 1280,
                capture_sync_run.cv2.CAP_PROP_FRAME_HEIGHT: 720,
                capture_sync_run.cv2.CAP_PROP_FPS: 30.0,
                capture_sync_run.cv2.CAP_PROP_FOURCC: (
                    capture_sync_run.cv2.VideoWriter_fourcc(*"MJPG")
                ),
            }
            return values[prop]

    assert capture_sync_run.read_camera_mode(
        ModeCamera(), 1, 1280, 720
    ) == {
        "index": 1,
        "width": 1280,
        "height": 720,
        "fps": 30.0,
        "fourcc": "MJPG",
    }


def test_connect_car_closes_socket_when_connect_fails():
    class FailingSocket:
        def __init__(self):
            self.timeouts = []
            self.close_calls = 0

        def settimeout(self, value):
            self.timeouts.append(value)

        def connect(self, _address):
            raise OSError("offline connect failure")

        def close(self):
            self.close_calls += 1

    sock = FailingSocket()
    with pytest.raises(OSError, match="offline connect failure"):
        capture_sync_run.connect_car(
            "192.168.110.236", 8888, socket_factory=lambda *_: sock
        )
    assert sock.close_calls == 1
    assert sock.timeouts == [3.0]


def test_session_failure_report_is_structured_and_nonpassing():
    report = capture_sync_run.build_session_failure_report(
        host="192.168.110.236",
        duration_s=0.5,
        run_id="sync-2",
        camera_mode={
            "index": 1,
            "width": 1280,
            "height": 720,
            "fps": 30.0,
            "fourcc": "MJPG",
        },
        actions={"start_sent": True, "stop_sent": False},
        outcome="no_telemetry_timeout",
        reason="no telemetry",
        n_poses=0,
        n_telemetry=0,
    )

    assert report["verdict"] == "FAIL"
    assert report["session_outcome"] == "no_telemetry_timeout"
    assert report["failure_reason"] == "no telemetry"
    assert report["missing_artifacts"] == [
        "raw_poses.json", "raw_telemetry.json"
    ]
    assert report["actions"]["stop_sent"] is False


def test_main_connect_failure_releases_open_camera_and_publishes_report(
        tmp_path, monkeypatch):
    cap = FakeCamera()
    monkeypatch.setattr(capture_sync_run, "make_run_id", lambda: "sync-test")
    monkeypatch.setattr(
        capture_sync_run, "open_capture_camera",
        lambda _index: (cap, 1280, 720),
    )
    monkeypatch.setattr(
        capture_sync_run, "read_camera_mode",
        lambda *_args: {
            "index": 1, "width": 1280, "height": 720,
            "fps": 30.0, "fourcc": "MJPG",
        },
    )
    monkeypatch.setattr(
        capture_sync_run, "_load_calibration",
        lambda _directory: (SimpleNamespace(image_size=(1280, 720)), object()),
    )
    monkeypatch.setattr(
        capture_sync_run, "connect_car",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("offline connect failure")
        ),
    )
    monkeypatch.setattr(
        sys, "argv", [
            "capture_sync_run.py", "--duration", "0.5",
            "--out", str(tmp_path),
        ],
    )

    assert capture_sync_run.main() == 1
    assert cap.release_calls == 1
    report_path = tmp_path / "sync-test" / "sync_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["session_outcome"] == "connect_failed"
    assert report["verdict"] == "FAIL"


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
