"""Tests for the offline same-frame AprilTag diagnostic matrix."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


TOOLS_ROOT = Path(__file__).resolve().parents[2] / ".." / "tools" / "camera_toolchain"
sys.path.insert(0, str(TOOLS_ROOT.resolve()))

try:
    from apriltag_diagnostic_matrix import (  # noqa: E402
        BRANCH_NAMES,
        build_branch_result,
        load_image,
        run_matrix,
        summarize_branch_results,
    )
    _IMPORT_ERROR = None
except (ImportError, ModuleNotFoundError) as exc:  # RED until the module is ready.
    BRANCH_NAMES = None
    build_branch_result = None
    load_image = None
    run_matrix = None
    summarize_branch_results = None
    _IMPORT_ERROR = exc


def _require_implementation() -> None:
    assert _IMPORT_ERROR is None, "diagnostic module is not implemented: %s" % (
        _IMPORT_ERROR,
    )


def test_branch_result_contains_detection_and_timing_contract() -> None:
    _require_implementation()
    assert build_branch_result is not None
    result = build_branch_result(
        branch="opencv_gray_1x",
        image_path="frame.jpg",
        image_shape=(1080, 1920, 3),
        elapsed_ns=1234,
        ids=[0, 7],
        rejected_count=2,
        target_id=0,
    )

    assert result["branch"] == "opencv_gray_1x"
    assert result["image"] == "frame.jpg"
    assert result["target_id"] == 0
    assert result["ids"] == [0, 7]
    assert result["target_detected"] is True
    assert result["rejected_count"] == 2
    assert result["elapsed_ns"] == 1234


def test_summary_counts_each_input_once_and_computes_ratio_and_p95() -> None:
    _require_implementation()
    assert build_branch_result is not None
    assert summarize_branch_results is not None
    results = [
        build_branch_result(
            branch="opencv_gray_1x",
            image_path="a.jpg",
            image_shape=(10, 10),
            elapsed_ns=10,
            ids=[],
            rejected_count=1,
            target_id=0,
        ),
        build_branch_result(
            branch="opencv_gray_1x",
            image_path="b.jpg",
            image_shape=(10, 10),
            elapsed_ns=20,
            ids=[0],
            rejected_count=0,
            target_id=0,
        ),
    ]

    summary = summarize_branch_results(results)

    assert summary == {
        "branch": "opencv_gray_1x",
        "image_count": 2,
        "detected_count": 1,
        "detection_ratio": 0.5,
        "rejected_candidate_total": 1,
        "processing_p95_ns": 20,
    }


def test_branch_names_are_explicit_and_stable() -> None:
    _require_implementation()
    assert BRANCH_NAMES is not None
    assert BRANCH_NAMES == (
        "opencv_gray_1x",
        "opencv_gray_2x",
        "opencv_gray_3x",
        "opencv_blue_2x",
        "opencv_green_2x",
        "opencv_red_2x",
        "opencv_blue_clahe_2x",
        "opencv_blue_unsharp_2x",
        "opencv_gray_clahe_2x",
        "opencv_adaptive_2x",
        "pupil_gray_1x",
        "pupil_gray_2x",
    )


def test_summary_rejects_mixed_branches() -> None:
    _require_implementation()
    assert build_branch_result is not None
    assert summarize_branch_results is not None
    first = build_branch_result(
        branch="opencv_gray_1x",
        image_path="a.jpg",
        image_shape=(10, 10),
        elapsed_ns=10,
        ids=[],
        rejected_count=0,
        target_id=0,
    )
    second = build_branch_result(
        branch="opencv_gray_2x",
        image_path="a.jpg",
        image_shape=(10, 10),
        elapsed_ns=10,
        ids=[],
        rejected_count=0,
        target_id=0,
    )

    with pytest.raises(ValueError, match="same branch"):
        summarize_branch_results([first, second])


def test_load_image_supports_unicode_windows_paths(tmp_path: Path) -> None:
    _require_implementation()
    assert load_image is not None
    path = tmp_path / "中文" / "frame.jpg"
    path.parent.mkdir()
    image = np.full((12, 16, 3), 127, dtype=np.uint8)
    encoded, buffer = cv2.imencode(".jpg", image)
    assert encoded
    path.write_bytes(buffer.tobytes())

    loaded = load_image(path)

    assert loaded.shape == image.shape
    assert loaded.dtype == np.uint8


def test_run_matrix_reads_unicode_windows_paths(tmp_path: Path) -> None:
    _require_implementation()
    assert run_matrix is not None
    path = tmp_path / "中文" / "frame.jpg"
    path.parent.mkdir()
    image = np.zeros((32, 48, 3), dtype=np.uint8)
    encoded, buffer = cv2.imencode(".jpg", image)
    assert encoded
    path.write_bytes(buffer.tobytes())

    report = run_matrix(
        [path],
        target_id=0,
        branches=("opencv_gray_1x",),
    )

    assert report["images"][0]["shape"] == [32, 48, 3]
    assert report["records"][0]["error"] is None
