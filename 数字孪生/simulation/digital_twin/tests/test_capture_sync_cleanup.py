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
from dataclasses import replace
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "tools", "camera_toolchain"))

import pytest
import numpy as np
import cv2

import capture_sync_run
from real_world.runtime_protocol import frame as protocol_frame
from v1_twin.v1_twin_pose_fusion import IMU_VALIDITY_REQUIRED
from v1_twin.v1_twin_schema import (
    V1Pose,
    V1SyncFrame,
    V1SyncQuality,
    V1TelemetryFrame,
)
from v1_twin.v1_twin_sync import ClockSync


@pytest.fixture(autouse=True)
def disable_quiet_clock_windows_for_legacy_session_fakes(monkeypatch):
    """Legacy cleanup fakes model P/R/H, not the new Q/T exchange path."""
    monkeypatch.setattr(capture_sync_run, "CLOCK_PREFLIGHT_EXCHANGES", 0)
    monkeypatch.setattr(capture_sync_run, "CLOCK_POSTFLIGHT_EXCHANGES", 0)


def test_capture_resolves_unspecified_camera_from_saved_config(monkeypatch):
    monkeypatch.setattr(
        capture_sync_run.camera_common,
        "get_camera_index",
        lambda preferred=None: 0,
    )

    assert capture_sync_run.resolve_camera_source(None) == 0
    assert capture_sync_run.resolve_camera_source("0") == 0
    assert capture_sync_run.resolve_camera_source("1") == 1


# ── Fake objects ────────────────────────────────────────────────────────

def _encode_telemetry_frame(tick_ms=0, yaw_deg=0.0, validity=None,
                            init_status=0):
    """编码一帧合法遥测（type=0x01, len=24, XOR checksum）。"""
    payload_len = 26 if validity is not None else 24
    payload = bytearray(payload_len)
    for i, v in enumerate((0, 0, 0, 0)):   # m1..m4
        struct.pack_into("<h", payload, 4 + 2 * i, v)
    struct.pack_into("<h", payload, 12, 0)       # error
    struct.pack_into("<h", payload, 14, 0)       # pid_output
    struct.pack_into("<I", payload, 16, tick_ms)
    struct.pack_into("<i", payload, 20, int(yaw_deg * 100.0))
    if validity is not None:
        payload[24] = validity
        payload[25] = init_status
    cs = 0x01 ^ payload_len
    for b in payload:
        cs ^= b
    return bytes([0xAA, 0x55, 0x01, payload_len]) + bytes(payload) + bytes([cs])


def _encode_health_frame(*, telemetry_generated=0, telemetry_overwritten=0,
                         telemetry_tx_started=0, telemetry_tx_ok=0,
                         telemetry_tx_failed=0, cipsend_started=0,
                         cipsend_completed=0, cipsend_ok=0,
                         cipsend_error=0, cipsend_prompt_timeout=0,
                         cipsend_sendok_timeout=0, cipsend_closed=0,
                         cipsend_last_duration_ms=0,
                         cipsend_max_duration_ms=0):
    payload = bytearray(106)
    payload[0] = 1
    payload[1] = 1
    struct.pack_into("<I", payload, 18, 1000)
    values = {
        30: telemetry_generated,
        32: telemetry_overwritten,
        34: telemetry_tx_started,
        36: telemetry_tx_ok,
        38: telemetry_tx_failed,
        40: cipsend_started,
        42: cipsend_completed,
        44: cipsend_ok,
        46: cipsend_error,
        48: cipsend_prompt_timeout,
        50: cipsend_sendok_timeout,
        52: cipsend_closed,
        54: cipsend_last_duration_ms,
        58: cipsend_max_duration_ms,
    }
    for offset, value in values.items():
        if offset in (54, 58):
            struct.pack_into("<I", payload, offset, value)
        else:
            struct.pack_into("<H", payload, offset, value)
    cs = 0x02 ^ len(payload)
    for byte in payload:
        cs ^= byte
    return bytes([0xAA, 0x55, 0x02, len(payload)]) + bytes(payload) + bytes([cs])


class FakeSocket:
    """可注入 socket：记录 recv/sendall/close 调用，可配置失败行为。"""

    def __init__(self, recv_data=b"", fail_start=False, fail_stop=False):
        self._recv_data = recv_data
        self._recv_sent = False
        self._start_seen = False
        self._pending_chunks = []
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
        if self._pending_chunks:
            return self._pending_chunks.pop(0)
        if not self._start_seen:
            raise socket.timeout()
        if not self._recv_sent:
            self._recv_sent = True
            return self._recv_data
        return b""   # EOF → reader thread breaks

    def sendall(self, data):
        self.sendall_calls += 1
        self.sent.append(data)
        if b"START" in data and self.fail_start:
            raise OSError("fake start failure")
        if b"START" in data:
            fields = data.decode("ascii").strip().split(",")
            self._start_seen = True
            self._pending_chunks.append(_encode_status_line(
                fields[1], fields[2], "RUNNING", "START", 1))
        if b"STOP" in data and self.fail_stop:
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
        if not self._start_seen:
            time.sleep(0.005)
            raise socket.timeout()
        if self._pending_chunks:
            return self._pending_chunks.pop(0)
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


def test_analysis_worker_drops_only_analysis_work_when_queue_is_full():
    started = threading.Event()
    released = threading.Event()

    class BlockingTracker:
        def track(self, frame, t_pc_ns=None):
            started.set()
            assert released.wait(0.5)
            return None

    worker = capture_sync_run._AnalysisWorker(
        BlockingTracker(), queue_size=1
    )
    worker.start()
    try:
        assert worker.submit("frame-1", 7, 123456789)
        assert started.wait(0.5)
        assert worker.submit("frame-2", 8, 123456790)
        assert not worker.submit("frame-3", 9, 123456791)
        released.set()

        deadline = time.monotonic() + 0.5
        results = []
        while time.monotonic() < deadline and not results:
            results.extend(worker.drain_results())
            if not results:
                time.sleep(0.005)
    finally:
        released.set()
        worker.stop(timeout_s=0.5)

    assert worker.summary["submitted_frames"] == 2
    assert worker.summary["dropped_frames"] == 1
    assert results
    assert results[0]["frame_index"] == 7
    assert results[0]["t_pc_ns"] == 123456789


def test_analysis_worker_records_tracker_errors_without_raising():
    class ErrorTracker:
        def track(self, frame, t_pc_ns=None):
            raise RuntimeError("detector failed")

    worker = capture_sync_run._AnalysisWorker(ErrorTracker(), queue_size=1)
    worker.start()
    try:
        assert worker.submit("frame", 3, 222)
        deadline = time.monotonic() + 0.5
        results = []
        while time.monotonic() < deadline and not results:
            results.extend(worker.drain_results())
            if not results:
                time.sleep(0.005)
    finally:
        worker.stop(timeout_s=0.5)

    assert results[0]["analysis_status"] == "error"
    assert "detector failed" in results[0]["analysis_error"]
    assert worker.summary["worker_errors"][0]["frame_index"] == 3


def test_analysis_worker_marks_blocked_work_incomplete_at_join_deadline():
    started = threading.Event()
    released = threading.Event()

    class BlockingTracker:
        def track(self, frame, t_pc_ns=None):
            started.set()
            released.wait(1.0)
            return None

    worker = capture_sync_run._AnalysisWorker(
        BlockingTracker(), queue_size=1
    )
    worker.start()
    assert worker.submit("frame", 4, 333)
    assert started.wait(0.5)
    try:
        worker.stop(timeout_s=0.01)
        assert worker.summary["incomplete_frames"] == 1
        assert worker.summary["worker_alive"] is True
    finally:
        released.set()
        worker.stop(timeout_s=0.5)


def test_capture_writes_frames_while_analysis_is_slow():
    class SlowTracker:
        def __init__(self):
            self.started = threading.Event()
            self.released = threading.Event()

        def track_with_diagnostics(self, frame, t_pc_ns=None):
            self.started.set()
            assert self.released.wait(1.0)
            return None, {
                "failure_reason": "no_markers",
                "detect_elapsed_ns": 10_000_000,
            }

    tracker = SlowTracker()

    class FastImageCamera(FakeCamera):
        def read(self):
            self.read_calls += 1
            if self.read_calls == 2:
                assert tracker.started.wait(1.0)
            if self.read_calls >= capture_sync_run.ANALYSIS_QUEUE_SIZE + 3:
                tracker.released.set()
            return True, np.zeros((2, 2, 3), dtype=np.uint8)

    class RecordingVideoWriter:
        def __init__(self):
            self.frames = []
            self.release_calls = 0

        def write(self, frame):
            self.frames.append(frame)

        def release(self):
            self.release_calls += 1

    writer = RecordingVideoWriter()
    frame_index = []
    diagnostics = {}
    video_evidence = {}
    _telemetry, _poses, _actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            FakeSocket(recv_data=_encode_telemetry_frame(tick_ms=100)),
            FastImageCamera(),
            tracker,
            "slow-analysis",
            0.05,
            0.5,
            frame_index=frame_index,
            diagnostics=diagnostics,
            video_writer=writer,
            video_evidence=video_evidence,
        )
    )

    assert outcome == "ok"
    assert video_evidence["frames_written"] == len(frame_index)
    assert diagnostics["analysis"]["captured_frames"] == len(frame_index)
    assert diagnostics["analysis"]["dropped_frames"] >= 1
    summary = diagnostics["analysis"]
    assert summary["analysis_eligible_frames"] == len(frame_index)
    assert summary["analysis_skipped_frames"] == 0
    assert summary["captured_frames"] == (
        summary["submitted_frames"]
        + summary["dropped_frames"]
        + summary["analysis_skipped_frames"]
    )
    assert summary["analysis_complete"] is False
    assert summary["dropped_frames_do_not_advance_tracker"] is True
    assert all(
        record["analysis_status"] in {
            "processed", "dropped", "incomplete", "error"
        }
        for record in frame_index
    )
    assert writer.release_calls == 1


def test_capture_pc_clock_uses_high_resolution_perf_counter(monkeypatch):
    sentinel = 1_691_234_567_890_123
    monkeypatch.setattr(
        capture_sync_run,
        "_last_capture_pc_clock_ns",
        None,
    )
    monkeypatch.setattr(
        capture_sync_run.time,
        "perf_counter_ns",
        lambda: sentinel,
    )

    assert capture_sync_run.capture_pc_clock_ns() == sentinel


def test_capture_pc_clock_makes_repeated_reads_strictly_increasing(monkeypatch):
    readings = iter((100, 100, 99, 101))
    monkeypatch.setattr(capture_sync_run, "_last_capture_pc_clock_ns", None)
    monkeypatch.setattr(
        capture_sync_run.time,
        "perf_counter_ns",
        lambda: next(readings),
    )

    assert [capture_sync_run.capture_pc_clock_ns() for _ in range(4)] == [
        100, 101, 102, 103,
    ]


def test_capture_uses_shared_pc_clock_for_camera_and_telemetry_timestamps(
        monkeypatch):
    sentinel = 1_691_234_567_890_123
    monkeypatch.setattr(
        capture_sync_run,
        "capture_pc_clock_ns",
        lambda: sentinel,
    )

    class DiagnosticTracker:
        def track_with_diagnostics(self, frame, t_pc_ns=None):
            return None, {
                "failure_reason": "no_markers",
                "detect_elapsed_ns": 42,
            }

    class OneFrameCamera(FakeCamera):
        def read(self):
            self.read_calls += 1
            return True, object()

    frame_index = []
    telemetry, _poses, _actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            FakeSocket(recv_data=_encode_telemetry_frame(tick_ms=100)),
            OneFrameCamera(),
            DiagnosticTracker(),
            "run-clock-domain",
            0.01,
            0.5,
            frame_index=frame_index,
        )
    )

    assert outcome == "ok"
    assert telemetry[0].pc_recv_ns == sentinel
    assert frame_index[0]["t_pc_ns"] == sentinel


def test_capture_persists_pose_tracker_diagnostics_per_frame():
    class DiagnosticTracker:
        def track_with_diagnostics(self, frame, t_pc_ns=None):
            return None, {
                "attempted_scales": [1.0, 2.0],
                "matched_scale": None,
                "tag_side_px": None,
                "failure_reason": "no_markers",
                "detect_elapsed_ns": 42,
            }

    class OneFrameCamera(FakeCamera):
        def read(self):
            self.read_calls += 1
            return True, object()

    sock = FakeSocket(recv_data=_encode_telemetry_frame(tick_ms=100))
    frame_index = []
    _telemetry, _poses, _actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock,
            OneFrameCamera(),
            DiagnosticTracker(),
            "run-camera-diag",
            0.01,
            0.5,
            frame_index=frame_index,
        )
    )

    assert outcome == "ok"
    assert frame_index
    assert frame_index[0]["detect_elapsed_ns"] == 42
    assert frame_index[0]["failure_reason"] == "no_markers"


def test_capture_saves_bounded_failure_thumbnail_and_relative_path(tmp_path):
    class DiagnosticTracker:
        def track_with_diagnostics(self, frame, t_pc_ns=None):
            return None, {
                "attempted_scales": [1.0, 2.0],
                "matched_scale": None,
                "tag_side_px": None,
                "failure_reason": "candidates_rejected",
                "rejected_candidate_count": 2,
                "rejected_candidate_counts": [1, 1],
                "detect_elapsed_ns": 42,
            }

    class ImageCamera(FakeCamera):
        def read(self):
            self.read_calls += 1
            return True, np.full((1080, 1920, 3), 127, dtype=np.uint8)

    sock = FakeSocket(recv_data=_encode_telemetry_frame(tick_ms=100))
    frame_index = []
    diagnostics = {}
    failure_dir = tmp_path / "failed_frames"
    _telemetry, _poses, _actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock,
            ImageCamera(),
            DiagnosticTracker(),
            "run-fail-frame",
            0.01,
            0.5,
            frame_index=frame_index,
            diagnostics=diagnostics,
            failure_frame_dir=failure_dir,
            max_failure_frame_thumbnails=2,
        )
    )

    assert outcome == "ok"
    saved = list(failure_dir.glob("*.jpg"))
    assert 1 <= len(saved) <= 2
    assert frame_index[0]["failure_frame_path"].startswith("failed_frames/")
    assert frame_index[0]["failure_frame_path"].endswith(".jpg")
    saved_image = cv2.imdecode(
        np.fromfile(str(saved[0]), dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert saved_image.shape[:2] == (1080, 1920)
    summary = diagnostics["failure_frame_summary"]
    assert summary["max_width"] == 1920
    assert summary["jpeg_quality"] == 95
    assert summary["saved"] == len(saved)
    assert summary["by_reason"]["candidates_rejected"] > 0
    assert summary["saved_by_reason"]["candidates_rejected"] == len(saved)


def test_capture_fails_closed_when_read_frame_shape_is_not_1080p(tracker):
    class MismatchedImageCamera(FakeCamera):
        def read(self):
            self.read_calls += 1
            return True, np.full((360, 640, 3), 127, dtype=np.uint8)

    sock = FakeSocket(recv_data=_encode_telemetry_frame(tick_ms=100))
    frame_index = []
    diagnostics = {}
    cap = MismatchedImageCamera()

    _telemetry, _poses, actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock,
            cap,
            tracker,
            "run-shape",
            0.01,
            0.5,
            frame_index=frame_index,
            diagnostics=diagnostics,
            expected_frame_size=(1920, 1080),
        )
    )

    assert outcome == "camera_frame_dimensions_mismatch"
    assert actions["stop_attempted"] is True
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True
    assert frame_index[0]["frame_width"] == 640
    assert frame_index[0]["frame_height"] == 360
    assert diagnostics["frame_shape_counts"] == {"640x360": 1}


def test_capture_preserves_current_imu_telemetry_fields(tracker):
    sock = FakeSocket(
        recv_data=_encode_telemetry_frame(
            tick_ms=100,
            yaw_deg=-12.34,
            validity=0x0F,
            init_status=0x21,
        )
    )
    cap = FakeCamera()

    telemetry, _poses, _actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock, cap, tracker, "run-imu", 0.01, 0.5
        )
    )

    assert outcome == "ok"
    assert len(telemetry) == 1
    assert telemetry[0].imu_yaw_deg_x100 == -1234
    assert telemetry[0].imu_validity == 0x0F
    assert telemetry[0].imu_validity_known is True
    assert telemetry[0].imu_init_status == 0x21
    assert telemetry[0].imu_init_status_known is True


def test_capture_writes_each_frame_and_releases_video_writer(tracker):
    class ImageCamera(FakeCamera):
        def read(self):
            self.read_calls += 1
            return True, np.full((1080, 1920, 3), 127, dtype=np.uint8)

    class RecordingVideoWriter:
        def __init__(self):
            self.frames = []
            self.release_calls = 0

        def write(self, frame):
            self.frames.append(tuple(frame.shape))

        def release(self):
            self.release_calls += 1

    writer = RecordingVideoWriter()
    frame_index = []
    video_evidence = {}
    _telemetry, _poses, _actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            FakeSocket(recv_data=_encode_telemetry_frame(tick_ms=100)),
            ImageCamera(),
            tracker,
            "run-video-writer",
            0.01,
            0.5,
            frame_index=frame_index,
            video_writer=writer,
            video_evidence=video_evidence,
            expected_frame_size=(1920, 1080),
        )
    )

    assert outcome == "ok"
    assert len(writer.frames) == len(frame_index)
    assert all(shape == (1080, 1920, 3) for shape in writer.frames)
    assert writer.release_calls == 1
    assert video_evidence["frames_written"] == len(frame_index)
    assert video_evidence["write_errors"] == []
    assert video_evidence["released"] is True


def test_capture_video_writer_failure_stops_and_releases_everything(tracker):
    class ImageCamera(FakeCamera):
        def read(self):
            self.read_calls += 1
            return True, np.full((1080, 1920, 3), 127, dtype=np.uint8)

    class FailingVideoWriter:
        def __init__(self):
            self.release_calls = 0

        def write(self, _frame):
            raise OSError("video disk full")

        def release(self):
            self.release_calls += 1

    writer = FailingVideoWriter()
    video_evidence = {}
    sock = FakeSocket(recv_data=_encode_telemetry_frame(tick_ms=100))
    cap = ImageCamera()
    _telemetry, _poses, actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock,
            cap,
            tracker,
            "run-vwf",
            0.01,
            0.5,
            video_writer=writer,
            video_evidence=video_evidence,
            expected_frame_size=(1920, 1080),
        )
    )

    assert outcome == "video_write_failed"
    assert video_evidence["frames_written"] == 0
    assert len(video_evidence["write_errors"]) == 1
    assert writer.release_calls == 1
    assert video_evidence["released"] is True
    assert actions["start_sent"] is True
    assert actions["stop_sent"] is True
    assert actions["socket_closed"] is True
    assert actions["camera_released"] is True


def test_open_capture_video_writer_uses_validated_mjpg_mode(tmp_path, monkeypatch):
    calls = []

    class OpenWriter:
        def isOpened(self):
            return True

        def release(self):
            pass

    def fake_video_writer(path, fourcc, fps, size, is_color=True):
        calls.append((path, fourcc, fps, size, is_color))
        return OpenWriter()

    monkeypatch.setattr(capture_sync_run.cv2, "VideoWriter", fake_video_writer)
    path = tmp_path / "camera.avi"
    writer = capture_sync_run.open_capture_video_writer(
        path,
        {"width": 1920, "height": 1080, "fps": 30.0, "fourcc": "MJPG"},
    )

    assert isinstance(writer, OpenWriter)
    assert calls == [
        (str(path), capture_sync_run.cv2.VideoWriter_fourcc(*"MJPG"),
         30.0, (1920, 1080), True)
    ]


def test_open_capture_video_writer_fails_closed_when_backend_cannot_open(
        tmp_path, monkeypatch):
    class ClosedWriter:
        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.setattr(
        capture_sync_run.cv2,
        "VideoWriter",
        lambda *_args, **_kwargs: ClosedWriter(),
    )

    with pytest.raises(RuntimeError, match="unable to open capture video"):
        capture_sync_run.open_capture_video_writer(
            tmp_path / "camera.avi",
            {"width": 1920, "height": 1080, "fps": 30.0, "fourcc": "MJPG"},
        )


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
            self.second_recv_started.set()
            if not self.reader_done.is_set():
                time.sleep(0.15)
                self.reader_done.set()
            return super().recv(n)

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
            if b"STOP" in data:
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


def test_capture_camera_entrypoint_locks_index1_1080p30_mjpg(monkeypatch):
    calls = []

    def fake_open_camera(index, **kwargs):
        calls.append((index, kwargs))
        return object(), 1920, 1080

    monkeypatch.setattr(capture_sync_run.camera_common,
                        "open_camera", fake_open_camera)
    cap, width, height = capture_sync_run.open_capture_camera(1)

    assert cap is not None
    assert (width, height) == (1920, 1080)
    assert calls == [(1, {
        "width": 1920,
        "height": 1080,
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
        diagnostics={
            "video_evidence": {
                "enabled": True,
                "path": "camera.avi",
                "frames_written": 12,
                "write_errors": [],
                "released": True,
            },
        },
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
    assert report["video_evidence"]["frames_written"] == 12


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
        "pose.jsonl", "telemetry.jsonl", "frame_index.jsonl"
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
        lambda _manifest: (
            SimpleNamespace(image_size=(1280, 720)), object(), {}
        ),
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
            "--calibration-manifest", str(tmp_path / "manifest.json"),
            "--out", str(tmp_path),
        ],
    )

    assert capture_sync_run.main() == 1
    assert cap.release_calls == 1
    report_path = tmp_path / "sync-test" / "sync_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["session_outcome"] == "connect_failed"
    assert report["verdict"] == "FAIL"


def test_main_video_writer_failure_happens_before_start(tmp_path, monkeypatch):
    class FullHdCamera(FakeCamera):
        def get(self, prop):
            return 1920 if prop == 3 else 1080

    cap = FullHdCamera()
    sock = FakeSocket()
    monkeypatch.setattr(capture_sync_run, "make_run_id", lambda: "sync-vwf")
    monkeypatch.setattr(
        capture_sync_run,
        "open_capture_camera",
        lambda _index: (cap, 1920, 1080),
    )
    monkeypatch.setattr(
        capture_sync_run,
        "read_camera_mode",
        lambda *_args: {
            "index": 1,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "fourcc": "MJPG",
        },
    )
    monkeypatch.setattr(
        capture_sync_run,
        "_load_calibration",
        lambda _manifest: (
            SimpleNamespace(image_size=(1920, 1080)), object(), {}
        ),
    )
    monkeypatch.setattr(
        capture_sync_run,
        "connect_car",
        lambda *_args, **_kwargs: sock,
    )
    monkeypatch.setattr(
        capture_sync_run,
        "open_capture_video_writer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("offline writer open failure")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_sync_run.py",
            "--duration",
            "0.5",
            "--calibration-manifest",
            str(tmp_path / "manifest.json"),
            "--out",
            str(tmp_path),
            "--record-video",
        ],
    )

    assert capture_sync_run.main() == 1
    assert sock.sent == []
    assert sock.close_calls == 1
    assert cap.release_calls == 1
    report = json.loads(
        (tmp_path / "sync-vwf" / "sync_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["session_outcome"] == "video_setup_failed"
    assert report["actions"]["start_sent"] is False
    assert report["video_evidence"]["open_error"]


def test_main_does_not_open_video_writer_without_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_sync_run, "make_run_id", lambda: "sync-no-video")
    monkeypatch.setattr(
        capture_sync_run,
        "_load_calibration",
        lambda _manifest: (
            SimpleNamespace(image_size=(1920, 1080)), object(), {}
        ),
    )
    monkeypatch.setattr(
        capture_sync_run,
        "open_capture_video_writer",
        lambda *_args, **_kwargs: pytest.fail(
            "default capture must not open a video writer"
        ),
    )
    monkeypatch.setattr(
        capture_sync_run,
        "open_capture_camera",
        lambda _index: (_ for _ in ()).throw(
            RuntimeError("camera unavailable")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_sync_run.py",
            "--duration",
            "0.5",
            "--calibration-manifest",
            str(tmp_path / "manifest.json"),
            "--out",
            str(tmp_path),
        ],
    )

    assert capture_sync_run.main() == 1


def test_write_capture_artifacts_publishes_b3_jsonl_and_legacy_json(tmp_path):
    out_dir = tmp_path / "sync-run"
    out_dir.mkdir()
    poses = [_fusion_pose(100), _fusion_pose(200)]
    telemetry = [_fusion_telemetry(110), _fusion_telemetry(210)]
    frame_index = [
        {"frame_index": 0, "t_pc_ns": 90, "read_ok": True,
         "pose_detected": True},
    ]

    capture_sync_run.write_capture_artifacts(
        out_dir,
        poses,
        telemetry,
        frame_index,
        diagnostics={
            "failure_frame_summary": {
                "enabled": True,
                "directory": "failed_frames",
                "max_saved": 12,
                "sample_stride": 30,
                "saved": 1,
                "observed": 3,
                "by_reason": {"no_markers": 3},
                "saved_by_reason": {"no_markers": 1},
                "save_errors": [],
            },
        },
    )

    assert json.loads((out_dir / "raw_poses.json").read_text()) == [
        pose.to_dict() for pose in poses
    ]
    assert [json.loads(line) for line in
            (out_dir / "pose.jsonl").read_text().splitlines()] == [
        pose.to_dict() for pose in poses
    ]
    assert [json.loads(line) for line in
            (out_dir / "telemetry.jsonl").read_text().splitlines()] == [
        telemetry_frame.to_dict() for telemetry_frame in telemetry
    ]
    assert [json.loads(line) for line in
            (out_dir / "frame_index.jsonl").read_text().splitlines()] == [
        {"frame_index": 0, "t_pc_ns": 90, "read_ok": True,
         "pose_detected": True},
    ]
    failure_summary = json.loads(
        (out_dir / "failure_frame_summary.json").read_text(encoding="utf-8")
    )
    assert failure_summary["saved"] == 1
    assert failure_summary["by_reason"] == {"no_markers": 3}
    assert (out_dir / "fusion.jsonl").read_text(encoding="utf-8") == ""


def test_failure_frame_thumbnail_writes_jpeg_under_unicode_path(tmp_path):
    output_dir = tmp_path / "失败帧"
    frame = np.full((24, 32, 3), 127, dtype=np.uint8)

    relative_path, error = capture_sync_run._save_failure_frame_thumbnail(
        frame,
        frame_index=7,
        reason="candidates_rejected",
        failure_frame_dir=output_dir,
    )

    assert error is None
    assert relative_path == "失败帧/frame_000007_candidates_rejected.jpg"
    image_path = output_dir / "frame_000007_candidates_rejected.jpg"
    assert image_path.is_file()
    assert cv2.imdecode(
        np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR
    ) is not None


def test_failure_frame_encode_error_identifies_encoder(monkeypatch, tmp_path):
    frame = np.full((24, 32, 3), 127, np.uint8)

    monkeypatch.setattr(
        capture_sync_run.cv2,
        "imencode",
        lambda *args, **kwargs: (False, None),
    )

    relative_path, error = capture_sync_run._save_failure_frame_thumbnail(
        frame,
        frame_index=7,
        reason="candidates_rejected",
        failure_frame_dir=tmp_path / "failed_frames",
    )

    assert relative_path is None
    assert error.startswith("cv2.imencode returned false")
    assert "shape=(24, 32, 3)" in error


def _fusion_pose(t_pc_ns=100):
    return V1Pose(
        x_mm=10.0,
        y_mm=20.0,
        yaw_rad=0.2,
        confidence=0.98,
        t_pc_ns=t_pc_ns,
    )


def _fusion_telemetry(t_pc_ns=100, *, legacy=False):
    return V1TelemetryFrame(
        sensors=(1, 1, 0, 1),
        error=0.0,
        pid_output=0.0,
        pwm=(400, 400, 400, 400),
        tick_ms=t_pc_ns // 1_000_000,
        pc_recv_ns=t_pc_ns,
        yaw_rad=None if legacy else 0.1,
        imu_yaw_deg_x100=None if legacy else 573,
        imu_validity=0 if legacy else IMU_VALIDITY_REQUIRED,
        imu_validity_known=not legacy,
        imu_init_status=0,
        imu_init_status_known=not legacy,
    )


def test_fusion_artifact_is_additive_and_records_units(tmp_path):
    from v1_twin.v1_twin_pose_fusion import V1PoseFusion

    out_dir = tmp_path / "fusion-run"
    out_dir.mkdir()
    pose = _fusion_pose()
    pose2 = V1Pose(
        x_mm=110.0,
        y_mm=20.0,
        yaw_rad=0.2,
        confidence=0.98,
        t_pc_ns=100_000_100,
    )
    telemetry = _fusion_telemetry()
    fusion_record = V1PoseFusion().update(pose, telemetry)

    capture_sync_run.write_capture_artifacts(
        out_dir,
        [pose, pose2],
        [telemetry, _fusion_telemetry(100_000_100)],
        [{"frame_index": 0, "t_pc_ns": 90}],
        fusion_records=[fusion_record],
    )

    fusion_records = [
        json.loads(line)
        for line in (out_dir / "fusion.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert len(fusion_records) == 1
    assert fusion_records[0]["quality"] == "USED_IMU"
    assert fusion_records[0]["imu_yaw_wire_unit"] == "degrees_x100"
    assert fusion_records[0]["imu_yaw_model_unit"] == "radians"
    imu_evidence = json.loads((out_dir / "imu_evidence.json").read_text(
        encoding="utf-8"
    ))
    assert imu_evidence["source"] == "SYNTHETIC"
    assert imu_evidence["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert imu_evidence["used_imu_count"] == 1
    assert imu_evidence["reason"] == "source_not_real_sync"
    camera_records = [
        json.loads(line)
        for line in (out_dir / "camera_motion.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert camera_records[1]["source"] == "CAMERA_POSE_DERIVATIVE"
    assert camera_records[1]["units"]["velocity"] == "mm/s"
    motion_evidence = json.loads(
        (out_dir / "motion_evidence.json").read_text(encoding="utf-8")
    )
    assert motion_evidence["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert motion_evidence["reason"] == "source_not_real_sync"
    assert [json.loads(line) for line in
            (out_dir / "pose.jsonl").read_text().splitlines()] == [
        pose.to_dict(), pose2.to_dict(),
    ]
    assert [json.loads(line) for line in
            (out_dir / "telemetry.jsonl").read_text().splitlines()] == [
        telemetry.to_dict(),
        _fusion_telemetry(100_000_100).to_dict(),
    ]


def test_motion_evidence_cannot_promote_failed_real_sync_gate(tmp_path):
    out_dir = tmp_path / "failed-sync-run"
    out_dir.mkdir()
    pose = _fusion_pose()
    pose2 = V1Pose(
        x_mm=110.0,
        y_mm=20.0,
        yaw_rad=0.2,
        confidence=0.98,
        t_pc_ns=100_000_100,
    )

    capture_sync_run.write_capture_artifacts(
        out_dir,
        [pose, pose2],
        [_fusion_telemetry(), _fusion_telemetry(100_000_100)],
        [],
        fusion_evidence_source="REAL_SYNC",
        sync_gate_verdict="FAIL",
    )

    report = json.loads(
        (out_dir / "motion_evidence.json").read_text(encoding="utf-8")
    )
    assert report["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["reason"] == "sync_gate_not_pass"
    imu_report = json.loads(
        (out_dir / "imu_evidence.json").read_text(encoding="utf-8")
    )
    assert imu_report["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert imu_report["reason"] == "sync_gate_not_pass"


def test_legacy_telemetry_generates_camera_only_fusion_evidence():
    legacy = V1SyncFrame(
        pose=_fusion_pose(),
        telemetry=_fusion_telemetry(legacy=True),
        sync_quality=V1SyncQuality.OK,
    )

    records = capture_sync_run.build_fusion_records((legacy,))

    assert len(records) == 1
    assert records[0].quality.value == "CAMERA_ONLY"
    assert records[0].fallback_reason == "imu_validity_unknown"
    assert records[0].imu_validity_known is False


def test_fusion_records_use_clock_aligned_time_and_skip_reused_telemetry():
    clock = ClockSync()
    for tick in range(0, 5_000, 20):
        clock.add_sample(tick, 1_000_000 * tick + 500_000)
    clock.fit()

    raw_receive_ns = 1_000_000_000
    first_telemetry = replace(
        _fusion_telemetry(raw_receive_ns),
        tick_ms=1_000,
    )
    second_telemetry = replace(
        _fusion_telemetry(raw_receive_ns),
        tick_ms=1_020,
    )
    frames = (
        V1SyncFrame(
            pose=_fusion_pose(t_pc_ns=1_000_000_000),
            telemetry=first_telemetry,
            sync_quality=V1SyncQuality.OK,
        ),
        V1SyncFrame(
            pose=_fusion_pose(t_pc_ns=1_020_000_000),
            telemetry=second_telemetry,
            sync_quality=V1SyncQuality.OK,
        ),
        V1SyncFrame(
            pose=_fusion_pose(t_pc_ns=1_021_000_000),
            telemetry=second_telemetry,
            sync_quality=V1SyncQuality.OK,
        ),
    )

    records = capture_sync_run.build_fusion_records(frames, clock)

    assert len(records) == 2
    assert [record.timestamp_ns for record in records] == [
        round(clock.tick_to_pc_ns(1_000)),
        round(clock.tick_to_pc_ns(1_020)),
    ]
    assert all(record.raw_pc_recv_ns == raw_receive_ns for record in records)
    assert all(record.quality.value == "USED_IMU" for record in records)


def test_load_calibration_uses_explicit_manifest_and_reports_profile(
        tmp_path, monkeypatch):
    monkeypatch.setattr(capture_sync_run, "_WORKSPACE_ROOT", tmp_path)
    intrinsics_path = tmp_path / "c960_intrinsics.json"
    profile_path = tmp_path / "c960_profile.json"
    manifest_path = tmp_path / "manifest.json"
    intrinsics_path.write_text(json.dumps({
        "camera": "EMEET SmartCam C960",
        "calibration": {
            "type": "CameraCalibration",
            "camera_matrix": [[1000.0, 0.0, 640.0],
                               [0.0, 1000.0, 360.0],
                               [0.0, 0.0, 1.0]],
            "dist_coeffs": [[0.0, 0.0, 0.0, 0.0, 0.0]],
            "image_size": [1280, 720],
            "reprojection_error_rms_px": 1.0,
            "reprojection_error_p95_px": 1.5,
        },
    }), encoding="utf-8")
    profile_path.write_text(json.dumps({
        "calibration_id": "c960-test-profile",
        "quality": "EXPLORATORY_RELATIVE_ONLY",
        "camera": {"model": "EMEET SmartCam C960", "image_size": [1280, 720]},
        "ground_transform": {
            "type": "HomographyTransform",
            "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        },
    }), encoding="utf-8")
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "intrinsics_path": intrinsics_path.name,
        "profile_path": profile_path.name,
    }), encoding="utf-8")

    calibration, homography, evidence = capture_sync_run._load_calibration(
        manifest_path
    )

    assert calibration.image_size == (1280, 720)
    assert homography.to_dict()["type"] == "HomographyTransform"
    assert evidence["calibration_id"] == "c960-test-profile"
    assert evidence["quality"] == "EXPLORATORY_RELATIVE_ONLY"
    assert len(evidence["intrinsics_sha256"]) == 64
    assert len(evidence["profile_sha256"]) == 64


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


def test_active_capture_sends_reused_heartbeat_command(tracker):
    sock = FakeSocket(recv_data=_encode_telemetry_frame(tick_ms=100))
    cap = FakeCamera()
    _telemetry, _poses, actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock, cap, tracker, "run-1", duration_s=0.45, wait_timeout_s=0.5
        )
    )

    assert outcome == "ok"
    assert actions.get("heartbeat_sent", 0) >= 2
    heartbeat_cmds = [data for data in sock.sent if data.startswith(b"H,")]
    assert heartbeat_cmds
    assert all(b"H,sync,run-1," in data for data in heartbeat_cmds)


# ── Scenario 3: STOP send fails → socket + camera still closed/released ──

def test_capture_records_health_and_raw_io_diagnostics(tracker):
    telemetry = _encode_telemetry_frame(tick_ms=100)
    health = _encode_health_frame(
        telemetry_generated=120,
        telemetry_overwritten=7,
        telemetry_tx_started=40,
        telemetry_tx_ok=39,
        telemetry_tx_failed=1,
        cipsend_started=45,
        cipsend_completed=44,
        cipsend_ok=42,
        cipsend_error=1,
        cipsend_prompt_timeout=1,
        cipsend_last_duration_ms=90,
        cipsend_max_duration_ms=220,
    )
    status = _encode_status_line("sync", "run-diag", "STOPPED", "STOP", 101)
    sock = StopStatusSocket(telemetry + health, [status])
    cap = FakeCamera()
    diagnostics = {}

    _telemetry, _poses, actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock, cap, tracker, "run-diag", 0.01, 0.2,
            diagnostics=diagnostics,
        )
    )

    assert outcome == "ok"
    assert actions["stop_confirmed"] is True
    assert len(diagnostics["health_frames"]) == 1
    observed = diagnostics["health_frames"][0]
    assert observed["telemetry_generated"] == 120
    assert observed["telemetry_overwritten"] == 7
    assert observed["telemetry_tx_started"] == 40
    assert observed["telemetry_tx_ok"] == 39
    assert observed["telemetry_tx_failed"] == 1
    assert observed["cipsend_max_duration_ms"] == 220
    assert diagnostics["raw_io"]["n_send"] >= 3
    assert diagnostics["raw_io"]["n_recv"] >= 1


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
