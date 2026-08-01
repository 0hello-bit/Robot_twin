"""Tests for capture helpers (Task 4B-4 fix, 离线可测)。

覆盖：
- 相机实际帧尺寸与标定 image_size 严格核对，不一致 fail closed（事实 #11）。
- 独立 run_id 输出目录；目标文件已存在时 fail closed（任务 C.5）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from v1_twin.v1_twin_capture import (
    CaptureConfigError,
    validate_frame_dimensions,
    resolve_run_output_dir,
)


def test_frame_dims_match_ok():
    # 实际 1280x720 与标定一致 → 通过
    validate_frame_dimensions((1280, 720), (1280, 720))


def test_frame_dims_mismatch_fails_closed():
    # DroidCam 实际返回 640x480，标定是 1280x720 → 必须 fail closed
    with pytest.raises(CaptureConfigError, match="frame size mismatch"):
        validate_frame_dimensions((640, 480), (1280, 720))


def test_frame_dims_swap_detected():
    with pytest.raises(CaptureConfigError):
        validate_frame_dimensions((720, 1280), (1280, 720))


def test_resolve_run_output_dir_creates_and_returns(tmp_path):
    d = resolve_run_output_dir(str(tmp_path), "sync_run_01",
                               ["raw_poses.json", "raw_telemetry.json"])
    assert os.path.isdir(d)
    assert os.path.isdir(os.path.join(str(tmp_path), "sync_run_01"))


def test_resolve_run_output_dir_fails_on_existing_artifact(tmp_path):
    run_dir = os.path.join(str(tmp_path), "sync_run_01")
    os.makedirs(run_dir)
    with open(os.path.join(run_dir, "raw_poses.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    with pytest.raises(CaptureConfigError, match="refusing to overwrite"):
        resolve_run_output_dir(str(tmp_path), "sync_run_01",
                               ["raw_poses.json", "raw_telemetry.json"])


def test_resolve_run_output_dir_rejects_unsafe_run_id(tmp_path):
    with pytest.raises(CaptureConfigError):
        resolve_run_output_dir(str(tmp_path), "a/b/c", [])
    with pytest.raises(CaptureConfigError):
        resolve_run_output_dir(str(tmp_path), "..", [])
    with pytest.raises(CaptureConfigError):
        resolve_run_output_dir(str(tmp_path), "", [])
