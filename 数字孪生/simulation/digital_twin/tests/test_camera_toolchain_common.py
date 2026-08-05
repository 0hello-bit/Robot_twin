from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOLCHAIN_DIR = ROOT / "tools" / "camera_toolchain"


def _load_camera_common():
    spec = importlib.util.spec_from_file_location(
        "camera_common_under_test", TOOLCHAIN_DIR / "camera_common.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_saved_camera_index_is_c960_index_1():
    config = json.loads((TOOLCHAIN_DIR / "camera_config.json").read_text("utf-8"))
    assert config["index"] == 1


def test_open_camera_requests_c960_720p30_mjpg_dshow(monkeypatch):
    camera_common = _load_camera_common()
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
            if prop == camera_common.cv2.CAP_PROP_FRAME_WIDTH:
                return 1280
            if prop == camera_common.cv2.CAP_PROP_FRAME_HEIGHT:
                return 720
            if prop == camera_common.cv2.CAP_PROP_FPS:
                return 30.0
            if prop == camera_common.cv2.CAP_PROP_FOURCC:
                return camera_common.cv2.VideoWriter_fourcc(*"MJPG")
            return 0

    fake_capture = None

    def make_capture(source, backend):
        nonlocal fake_capture
        fake_capture = FakeCapture(source, backend)
        return fake_capture

    monkeypatch.setattr(camera_common.cv2, "VideoCapture", make_capture)

    _, width, height = camera_common.open_camera(1)

    assert opened == [(1, camera_common.cv2.CAP_DSHOW)]
    assert (width, height) == (1280, 720)
    assert fake_capture is not None
    assert fake_capture.set_calls == [
        (
            camera_common.cv2.CAP_PROP_FOURCC,
            camera_common.cv2.VideoWriter_fourcc(*"MJPG"),
        ),
        (camera_common.cv2.CAP_PROP_FRAME_WIDTH, 1280),
        (camera_common.cv2.CAP_PROP_FRAME_HEIGHT, 720),
        (camera_common.cv2.CAP_PROP_FPS, 30.0),
    ]


def test_gate0_runner_imports_without_external_pythonpath():
    runner = TOOLCHAIN_DIR / "run_gate0_usb.py"
    command = (
        "import runpy; "
        f"runpy.run_path({str(runner)!r}, run_name='camera_runner_import_test')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_get_camera_index_reports_ambiguity(monkeypatch):
    """R2: 多个有效摄像头且无保存索引匹配 → 报歧义，不静默选第一个。"""
    camera_common = _load_camera_common()
    monkeypatch.setattr(camera_common, "detect_camera_indices", lambda max_index=6: [0, 1, 3])
    monkeypatch.setattr(camera_common, "_load_saved_index", lambda: None)
    with pytest.raises(SystemExit):
        camera_common.get_camera_index()


def test_get_camera_index_single_valid_returns_and_saves(monkeypatch, tmp_path):
    """R2: 唯一有效索引 → 返回并持久化。"""
    camera_common = _load_camera_common()
    monkeypatch.setattr(camera_common, "detect_camera_indices", lambda max_index=6: [3])
    monkeypatch.setattr(camera_common, "_load_saved_index", lambda: None)
    monkeypatch.setattr(camera_common, "CONFIG_PATH", str(tmp_path / "camera_config.json"))
    idx = camera_common.get_camera_index()
    assert idx == 3
    saved = json.loads((tmp_path / "camera_config.json").read_text("utf-8"))
    assert saved["index"] == 3


def test_detect_camera_indices_requires_readable_frames(monkeypatch):
    """R2: 可打开但读帧失败/纯黑的索引不得进入候选（仅 isOpened 不算成功）。"""
    camera_common = _load_camera_common()

    class FakeFailCapture:
        def __init__(self, source, backend):
            pass

        def isOpened(self):
            return True

        def read(self):
            return False, None

        def release(self):
            pass

    monkeypatch.setattr(camera_common.cv2, "VideoCapture", FakeFailCapture)
    assert camera_common.detect_camera_indices(max_index=3) == []
