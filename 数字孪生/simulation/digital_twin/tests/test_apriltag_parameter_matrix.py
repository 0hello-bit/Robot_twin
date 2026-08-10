"""Tests for the offline AprilTag detector-parameter matrix."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


TOOLS_ROOT = Path(__file__).resolve().parents[2] / ".." / "tools" / "camera_toolchain"
sys.path.insert(0, str(TOOLS_ROOT.resolve()))

try:
    from apriltag_parameter_matrix import (  # noqa: E402
        DEFAULT_BRANCHES,
        PARAMETER_VARIANTS,
        ROI_DEFAULT_BRANCHES,
        ROI_PARAMETER_VARIANTS,
        build_detector_parameters,
        run_parameter_matrix,
        run_roi_parameter_matrix,
    )
    _IMPORT_ERROR = None
except (ImportError, ModuleNotFoundError) as exc:
    DEFAULT_BRANCHES = None
    PARAMETER_VARIANTS = None
    build_detector_parameters = None
    run_parameter_matrix = None
    ROI_DEFAULT_BRANCHES = None
    ROI_PARAMETER_VARIANTS = None
    run_roi_parameter_matrix = None
    _IMPORT_ERROR = exc


def _require_implementation() -> None:
    assert _IMPORT_ERROR is None, "parameter matrix is not implemented: %s" % (
        _IMPORT_ERROR,
    )


def _write_small_jpeg(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((32, 48, 3), dtype=np.uint8)
    encoded, buffer = cv2.imencode(".jpg", image)
    assert encoded
    path.write_bytes(buffer.tobytes())
    return path


def test_parameter_variants_are_stable_and_default_matches_opencv() -> None:
    _require_implementation()
    assert PARAMETER_VARIANTS == (
        "default",
        "subpix",
        "contour",
        "adaptive_wide",
        "perimeter_relaxed",
    )
    assert DEFAULT_BRANCHES == (
        "opencv_gray_1x",
        "opencv_gray_2x",
        "opencv_blue_2x",
        "opencv_blue_clahe_2x",
    )
    default = build_detector_parameters("default")
    assert default.adaptiveThreshWinSizeMax == 23
    assert default.minMarkerPerimeterRate == pytest.approx(0.03)


def test_parameter_variants_create_independent_bounded_objects() -> None:
    _require_implementation()
    first = build_detector_parameters("subpix")
    second = build_detector_parameters("subpix")

    assert first is not second
    assert first.cornerRefinementMethod == cv2.aruco.CORNER_REFINE_SUBPIX
    assert (
        build_detector_parameters("contour").cornerRefinementMethod
        == cv2.aruco.CORNER_REFINE_CONTOUR
    )
    assert build_detector_parameters("adaptive_wide").adaptiveThreshWinSizeMax == 53
    assert build_detector_parameters("perimeter_relaxed").minMarkerPerimeterRate == pytest.approx(0.015)


def test_parameter_matrix_rejects_unknown_variant_and_branch(tmp_path: Path) -> None:
    _require_implementation()
    image_path = _write_small_jpeg(tmp_path / "frame.jpg")

    with pytest.raises(ValueError, match="unsupported parameter variant"):
        run_parameter_matrix([image_path], variants=("unknown",))
    with pytest.raises(ValueError, match="unsupported branch"):
        run_parameter_matrix([image_path], branches=("unknown",))


def test_parameter_matrix_report_separates_variant_and_branch(tmp_path: Path) -> None:
    _require_implementation()
    image_path = _write_small_jpeg(tmp_path / "frame.jpg")

    report = run_parameter_matrix(
        [image_path],
        branches=("opencv_gray_1x",),
        variants=("default", "subpix"),
    )

    assert report["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["parameter_variants"] == ["default", "subpix"]
    assert report["branches"] == ["opencv_gray_1x"]
    assert set(report["summaries"]) == {"default", "subpix"}
    assert report["summaries"]["default"]["opencv_gray_1x"]["image_count"] == 1


def test_roi_parameter_matrix_uses_explicit_bounds_and_keeps_full_frame_metadata(
    tmp_path: Path,
) -> None:
    _require_implementation()
    image_path = _write_small_jpeg(tmp_path / "frame.jpg")

    assert ROI_DEFAULT_BRANCHES == ("opencv_gray_1x", "opencv_blue_2x")
    assert ROI_PARAMETER_VARIANTS == ("default", "adaptive_wide")
    report = run_roi_parameter_matrix(
        [image_path],
        roi_bounds={str(image_path): (4, 5, 20, 25)},
        branches=("opencv_gray_1x",),
        variants=("default",),
    )

    record = report["records"][0]
    assert report["type"] == "V1B3AprilTagROIParameterMatrix"
    assert report["roi_policy"] == "EXPLICIT_RETAINED_BOUNDS"
    assert report["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert record["image_shape"] == [32, 48, 3]
    assert record["roi_bounds"] == [4, 5, 20, 25]
    assert record["roi_shape"] == [20, 16, 3]
    assert report["summaries"]["default"]["opencv_gray_1x"]["image_count"] == 1


def test_roi_parameter_matrix_requires_a_bound_for_every_image(
    tmp_path: Path,
) -> None:
    _require_implementation()
    image_path = _write_small_jpeg(tmp_path / "frame.jpg")

    with pytest.raises(ValueError, match="missing ROI bounds"):
        run_roi_parameter_matrix(
            [image_path],
            roi_bounds={},
            branches=("opencv_gray_1x",),
            variants=("default",),
        )
