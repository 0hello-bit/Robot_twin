"""Tests for the camera-only static AprilTag capture contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


TOOLS_ROOT = Path(__file__).resolve().parents[2] / ".." / "tools" / "camera_toolchain"
sys.path.insert(0, str(TOOLS_ROOT.resolve()))

try:
    from capture_static_apriltag import (  # noqa: E402
        build_capture_report,
        frame_filename,
    )
    _IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # RED until the capture module exists.
    build_capture_report = None
    frame_filename = None
    _IMPORT_ERROR = exc


def _require_implementation() -> None:
    assert _IMPORT_ERROR is None, "capture module is not implemented: %s" % (
        _IMPORT_ERROR,
    )


def test_frame_filename_is_zero_padded_and_stable() -> None:
    _require_implementation()
    assert frame_filename is not None
    assert frame_filename(0) == "frame_000000.jpg"
    assert frame_filename(99) == "frame_000099.jpg"


def test_capture_report_records_actual_mode_and_timestamp_quality() -> None:
    _require_implementation()
    assert build_capture_report is not None
    report = build_capture_report(
        output_dir="static_run",
        requested_width=1920,
        requested_height=1080,
        requested_fps=30.0,
        actual_width=1920,
        actual_height=1080,
        actual_fps=30.0,
        actual_fourcc="MJPG",
        frame_paths=["frame_000000.jpg", "frame_000001.jpg"],
        timestamps_ns=[100, 200],
        read_failures=0,
    )

    assert report["camera_mode"] == "1920x1080/MJPG/30.0"
    assert report["frame_count"] == 2
    assert report["read_failures"] == 0
    assert report["timestamps_strictly_increasing"] is True
    assert report["capture_verdict"] == "PASS"


def test_capture_report_fails_mode_or_timestamp_gate() -> None:
    _require_implementation()
    assert build_capture_report is not None
    report = build_capture_report(
        output_dir="static_run",
        requested_width=1920,
        requested_height=1080,
        requested_fps=30.0,
        actual_width=1280,
        actual_height=720,
        actual_fps=30.0,
        actual_fourcc="MJPG",
        frame_paths=["frame_000000.jpg", "frame_000001.jpg"],
        timestamps_ns=[100, 100],
        read_failures=1,
    )

    assert report["capture_verdict"] == "FAIL"
    assert report["mode_matches_request"] is False
    assert report["timestamps_strictly_increasing"] is False
