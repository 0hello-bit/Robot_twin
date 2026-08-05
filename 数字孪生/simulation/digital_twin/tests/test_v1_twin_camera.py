"""Tests for CameraSource 抽象与 Gate 0 统计逻辑 (Task 4B-1)。

不依赖真实摄像头：
- CameraSource 抽象契约用 Fake 实现测试；
- compute_camera_stats 用合成时间戳序列测试（纯函数）；
- verify_gate0 通过注入 Fake 源做端到端统计流水线测试。
Gate 0 真机 10 分钟录制由独立脚本执行（自动验收 gate）。
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from v1_twin.v1_twin_camera import (
    CameraSource,
    CameraStats,
    CameraError,
    OpenCVCameraSource,
    compute_camera_stats,
    verify_gate0,
)


# ============================================================
# Fake 摄像头源（无硬件）
# ============================================================


class FakeCamera(CameraSource):
    """按固定周期产帧的假摄像头。

    时间戳时钟与 `OpenCVCameraSource` 实现一致使用 `time.perf_counter_ns()`
    （本平台 `monotonic_ns()` 量化 ~15.6ms，10ms 周期下会碰撞、破坏单调性）。
    """

    def __init__(self, period_s=0.02):
        self._period = period_s
        self._started = False

    def start(self):
        self._started = True

    def stop(self):
        self._started = False

    def read(self):
        if not self._started:
            raise CameraError("not started")
        time.sleep(self._period)
        return ("frame", time.perf_counter_ns(), True)


# ============================================================
# 抽象契约
# ============================================================


def test_camera_source_is_abstract():
    with pytest.raises(TypeError):
        CameraSource()  # type: ignore[abstract]


def test_fake_camera_implements_contract():
    cam = FakeCamera(period_s=0.001)
    cam.start()
    frame, ts, ok = cam.read()
    assert ok is True
    assert frame == "frame"
    assert isinstance(ts, int) and ts > 0
    cam.stop()
    with pytest.raises(CameraError):
        cam.read()  # stop 后不可读


def test_opencv_camera_read_before_start_raises():
    cam = OpenCVCameraSource(source=0)
    with pytest.raises(CameraError):
        cam.read()


def test_opencv_camera_applies_explicit_usb_capture_mode(monkeypatch):
    import v1_twin.v1_twin_camera as camera_module

    opened = []

    class FakeCapture:
        def __init__(self, source, backend):
            opened.append((source, backend))
            self.set_calls = []

        def isOpened(self):
            return True

        def set(self, prop, value):
            self.set_calls.append((prop, value))
            return True

        def get(self, prop):
            values = {
                camera_module.cv2.CAP_PROP_FRAME_WIDTH: 1280,
                camera_module.cv2.CAP_PROP_FRAME_HEIGHT: 720,
                camera_module.cv2.CAP_PROP_FPS: 30.0,
                camera_module.cv2.CAP_PROP_FOURCC:
                    camera_module.cv2.VideoWriter_fourcc(*"MJPG"),
            }
            return values.get(prop, 0)

        def release(self):
            pass

    fake_capture = None

    def make_capture(source, backend):
        nonlocal fake_capture
        fake_capture = FakeCapture(source, backend)
        return fake_capture

    monkeypatch.setattr(camera_module.cv2, "VideoCapture", make_capture)

    cam = OpenCVCameraSource(
        source=1,
        width=1280,
        height=720,
        backend=camera_module.cv2.CAP_DSHOW,
        fps=30.0,
        fourcc="MJPG",
    )
    cam.start()

    assert opened == [(1, camera_module.cv2.CAP_DSHOW)]
    assert fake_capture is not None
    assert fake_capture.set_calls == [
        (
            camera_module.cv2.CAP_PROP_FOURCC,
            camera_module.cv2.VideoWriter_fourcc(*"MJPG"),
        ),
        (camera_module.cv2.CAP_PROP_FRAME_WIDTH, 1280),
        (camera_module.cv2.CAP_PROP_FRAME_HEIGHT, 720),
        (camera_module.cv2.CAP_PROP_FPS, 30.0),
    ]


def test_opencv_camera_rejects_driver_fps_mismatch(monkeypatch):
    import v1_twin.v1_twin_camera as camera_module

    class FakeCapture:
        def __init__(self, source, backend):
            self.released = False

        def isOpened(self):
            return True

        def set(self, prop, value):
            return True

        def get(self, prop):
            if prop == camera_module.cv2.CAP_PROP_FRAME_WIDTH:
                return 1280
            if prop == camera_module.cv2.CAP_PROP_FRAME_HEIGHT:
                return 720
            if prop == camera_module.cv2.CAP_PROP_FPS:
                return 22.63
            if prop == camera_module.cv2.CAP_PROP_FOURCC:
                return camera_module.cv2.VideoWriter_fourcc(*"MJPG")
            return 0

        def release(self):
            self.released = True

    fake_capture = None

    def make_capture(source, backend):
        nonlocal fake_capture
        fake_capture = FakeCapture(source, backend)
        return fake_capture

    monkeypatch.setattr(camera_module.cv2, "VideoCapture", make_capture)
    cam = OpenCVCameraSource(
        source=1,
        width=1280,
        height=720,
        backend=camera_module.cv2.CAP_DSHOW,
        fps=30.0,
        fourcc="MJPG",
    )

    with pytest.raises(CameraError, match="requested fps 30.0, got 22.63"):
        cam.start()
    assert fake_capture is not None and fake_capture.released is True


# ============================================================
# 统计逻辑（纯函数）
# ============================================================

_NOMINAL_30FPS_NS = int(1e9 / 30)


def _steady_timestamps(n=300, period_ns=_NOMINAL_30FPS_NS):
    """等间隔递增时间戳序列，模拟 30fps。"""
    return [1_000_000_000 + i * period_ns for i in range(n)]


def test_stats_empty_sequence():
    stats = compute_camera_stats([], _NOMINAL_30FPS_NS, duration_s=0.0)
    assert stats.frame_count == 0
    assert stats.effective_fps == 0.0
    assert stats.timestamps_monotonic is True


def test_stats_steady_sequence_is_monotonic_and_full_rate():
    ts = _steady_timestamps()
    stats = compute_camera_stats(ts, _NOMINAL_30FPS_NS, duration_s=10.0)
    assert stats.timestamps_monotonic is True
    assert stats.dropped_frames == 0
    assert stats.drop_rate_pct == 0.0
    assert stats.effective_fps == pytest.approx(30.0, rel=0.01)


def test_stats_detects_gap_as_dropped_frames():
    ts = _steady_timestamps(period_ns=_NOMINAL_30FPS_NS)
    # 从等间隔序列中移除 3 帧（indices 150..152）→ 该处缺口 = 4 个标称周期 = 丢 3 帧
    del ts[150:153]
    stats = compute_camera_stats(ts, _NOMINAL_30FPS_NS, duration_s=10.0)
    assert stats.dropped_frames == 3
    assert stats.drop_rate_pct > 0.0
    assert stats.timestamps_monotonic is True


def test_stats_rejects_non_monotonic_timestamps():
    ts = _steady_timestamps()
    ts[50] = ts[49]  # 等值 → 非严格递增
    stats = compute_camera_stats(ts, _NOMINAL_30FPS_NS, duration_s=10.0)
    assert stats.timestamps_monotonic is False
    # 单调性失败必须导致 Gate 0 FAIL（由调用方判定，此处验证标志位）
    assert not (stats.effective_fps >= 20.0 and stats.timestamps_monotonic)


def test_stats_decreasing_timestamps_rejected():
    ts = _steady_timestamps()
    ts[10], ts[11] = ts[11], ts[10]  # 递减
    stats = compute_camera_stats(ts, _NOMINAL_30FPS_NS, duration_s=10.0)
    assert stats.timestamps_monotonic is False


# ============================================================
# verify_gate0 端到端（注入 Fake 源）
# ============================================================


def test_verify_gate0_runs_with_fake_source(tmp_path):
    fake = FakeCamera(period_s=0.01)
    stats = verify_gate0(
        source=fake,
        duration_s=0.3,
        out_dir=str(tmp_path),
        save_frames=False,
    )
    assert isinstance(stats, CameraStats)
    assert stats.frame_count >= 15  # 0.3s @ ~100fps
    assert stats.timestamps_monotonic is True
    assert stats.duration_s >= 0.25


def test_verify_gate0_fake_sequence_meets_gate_threshold():
    fake = FakeCamera(period_s=0.01)  # ~100fps > 20fps
    stats = verify_gate0(source=fake, duration_s=0.3, save_frames=False)
    assert stats.effective_fps >= 20.0
    assert stats.drop_rate_pct <= 5.0
    assert stats.timestamps_monotonic is True


# ============================================================
# 内容有效性测试 (Task 4B-1 Reacceptance — RED → GREEN)
# ============================================================

import numpy as np


class ContentFakeCamera(CameraSource):
    """支持注入帧内容和分辨率的假摄像头，用于内容有效性测试。"""

    def __init__(
        self,
        frames=None,
        actual_width=640,
        actual_height=480,
        requested_width=0,
        requested_height=0,
    ):
        """
        frames: list of callables or static frame values;
                each callable receives (index) and returns an np.ndarray
        """
        self._frames = frames or []
        self._actual_width = actual_width
        self._actual_height = actual_height
        self._requested_width = requested_width
        self._requested_height = requested_height
        self._started = False
        self._idx = 0

    @property
    def actual_width(self):
        return self._actual_width

    @property
    def actual_height(self):
        return self._actual_height

    @property
    def requested_width(self):
        return self._requested_width

    @property
    def requested_height(self):
        return self._requested_height

    def start(self):
        self._started = True
        self._idx = 0

    def stop(self):
        self._started = False

    def read(self):
        if not self._started:
            raise CameraError("not started")
        if self._idx >= len(self._frames):
            return (None, time.perf_counter_ns(), False)
        f = self._frames[self._idx]
        frame = f(self._idx) if callable(f) else f
        self._idx += 1
        time.sleep(0.005)
        return (frame, time.perf_counter_ns(), True)


def _make_normal_frame():
    """生成一个非黑、非空、有纹理的合成帧 (100x100 BGR)。"""
    img = np.ones((100, 100, 3), dtype=np.uint8) * 128
    img[30:70, 30:70, :] = 255  # 白色矩形
    return img


def _make_black_frame():
    """全黑帧 (100x100 BGR)。"""
    return np.zeros((100, 100, 3), dtype=np.uint8)


def _make_near_black_frame(mean_val=3):
    """近乎全黑帧（模拟 DroidCam 启动画面）。"""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[0:5, 0:5, :] = mean_val  # 极小量非零像素
    return img


def _make_varying_frame(idx):
    """生成内容各异的正常帧（每帧有唯一像素标记）。"""
    img = np.ones((100, 100, 3), dtype=np.uint8) * 128
    img[30:70, 30:70, :] = 255  # 白色矩形
    img[0, 0, 0] = idx % 256    # 唯一标记确保每帧哈希不同
    return img


# 内容有效性纯函数测试

def test_is_frame_black_detects_all_black():
    """RED: is_frame_black 不存在时应 ImportError。"""
    from v1_twin.v1_twin_camera import is_frame_black
    black = _make_black_frame()
    assert is_frame_black(black) is True


def test_is_frame_black_detects_near_black():
    """RED: 近乎全黑帧应被识别为无效。"""
    from v1_twin.v1_twin_camera import is_frame_black
    near_black = _make_near_black_frame(mean_val=3)
    assert is_frame_black(near_black) is True


def test_is_frame_black_passes_normal_frame():
    """RED: 正常帧不应被识别为黑帧。"""
    from v1_twin.v1_twin_camera import is_frame_black
    normal = _make_normal_frame()
    assert is_frame_black(normal) is False


def test_is_frame_stale_detects_repeated_frame():
    """相同帧应被识别为 stale（通过哈希比较）。"""
    from v1_twin.v1_twin_camera import is_frame_stale, _frame_hash
    frame = _make_normal_frame()
    assert is_frame_stale(frame, _frame_hash(frame)) is True


def test_is_frame_stale_passes_different_frame():
    """不同帧不应被识别为 stale（哈希不同）。"""
    from v1_twin.v1_twin_camera import is_frame_stale, _frame_hash
    f1 = _make_normal_frame()
    f2 = np.ones((100, 100, 3), dtype=np.uint8) * 200
    assert is_frame_stale(f2, _frame_hash(f1)) is False


def test_is_frame_stale_handles_none_previous():
    """无前一帧时不报 stale（prev_hash=None）。"""
    from v1_twin.v1_twin_camera import is_frame_stale
    frame = _make_normal_frame()
    assert is_frame_stale(frame, None) is False


# gate0 warm-up + content validity 集成测试

def test_gate0_warmup_rejects_black_startup_frames(tmp_path):
    """RED: gate0 应在 warm-up 阶段丢弃全黑/启动帧，不计入计时区间。"""
    from v1_twin.v1_twin_camera import verify_gate0

    # 前 5 帧全黑（模拟 DroidCam 启动页），后续正常且各异
    frames = (
        [_make_black_frame()] * 5
        + [_make_varying_frame(i) for i in range(50)]
    )
    fake = ContentFakeCamera(frames=frames)
    stats = verify_gate0(
        source=fake,
        duration_s=0.5,
        out_dir=str(tmp_path),
        save_frames=False,
        warmup_required=True,
    )
    # 0.5s @ ~200fps (5ms/帧) → 应该有正常帧被计入
    assert stats.warmup_frames_discarded >= 5, "黑帧应在 warm-up 被丢弃"
    assert stats.frame_count > 0, "warm-up 后应有有效帧"
    assert stats.frame_count <= 50, "黑帧不应进入计时区间"


def test_gate0_warmup_rejects_stale_repeated_frames(tmp_path):
    """gate0 warm-up 应丢弃连续重复帧（冻结/卡死）。"""
    from v1_twin.v1_twin_camera import verify_gate0

    frozen = _make_normal_frame()
    # 前 8 帧完全相同（超过 STALE_THRESHOLD=5 才触发丢弃），后续正常且各异
    frames = (
        [lambda i, f=frozen: np.copy(f) for _ in range(8)]
        + [lambda i: _make_varying_frame(i) for _ in range(50)]
    )
    fake = ContentFakeCamera(frames=frames)
    stats = verify_gate0(
        source=fake,
        duration_s=0.5,
        out_dir=str(tmp_path),
        save_frames=False,
        warmup_required=True,
    )
    # warm-up 应丢弃冻结帧（达到 STALE_THRESHOLD 后被丢弃）
    assert stats.warmup_frames_discarded > 0, "冻结帧应在 warm-up 被丢弃"
    assert stats.frame_count > 0, "warm-up 后应有有效帧"


def test_gate0_resolution_mismatch_reported(tmp_path):
    """RED: 实际分辨率与请求不符时应 report 并 FAIL。"""
    from v1_twin.v1_twin_camera import verify_gate0

    frames = [_make_normal_frame() for _ in range(30)]
    fake = ContentFakeCamera(
        frames=frames,
        actual_width=640,
        actual_height=480,
        requested_width=1280,
        requested_height=720,
    )
    stats = verify_gate0(
        source=fake,
        duration_s=0.3,
        out_dir=str(tmp_path),
        save_frames=False,
        width=1280,
        height=720,
        warmup_required=False,   # 合成帧全相同，跳过 warm-up
    )
    assert hasattr(stats, "resolution_match"), "stats 应有 resolution_match 字段"
    assert stats.resolution_match is False, (
        "640x480 != 1280x720 → resolution_match 应为 False"
    )


def test_gate0_resolution_match_passes_when_correct(tmp_path):
    """RED: 实际分辨率与请求一致时应 PASS。"""
    from v1_twin.v1_twin_camera import verify_gate0

    frames = [_make_normal_frame() for _ in range(30)]
    fake = ContentFakeCamera(
        frames=frames,
        actual_width=1280,
        actual_height=720,
        requested_width=1280,
        requested_height=720,
    )
    stats = verify_gate0(
        source=fake,
        duration_s=0.3,
        out_dir=str(tmp_path),
        save_frames=False,
        width=1280,
        height=720,
        warmup_required=False,   # 合成帧全相同，跳过 warm-up
    )
    assert stats.resolution_match is True


def test_gate0_content_invalid_frames_counted(tmp_path):
    """RED: 正式计时区间内的无效帧应被统计但不计入有效帧数。"""
    from v1_twin.v1_twin_camera import verify_gate0

    # 正常帧中混入黑帧
    frames = [_make_normal_frame() for _ in range(20)]
    frames.insert(10, _make_black_frame())  # 在正常帧中间插入黑帧
    frames.insert(15, _make_black_frame())

    fake = ContentFakeCamera(frames=frames)
    stats = verify_gate0(
        source=fake,
        duration_s=0.3,
        out_dir=str(tmp_path),
        save_frames=False,
        warmup_required=False,
    )
    assert hasattr(stats, "invalid_content_frames"), "stats 应有 invalid_content_frames 字段"
    assert stats.invalid_content_frames >= 2, "应检测到至少 2 帧无效内容"
    # 有效帧数应小于总帧数
    assert stats.frame_count + stats.invalid_content_frames >= len(frames) - 2
