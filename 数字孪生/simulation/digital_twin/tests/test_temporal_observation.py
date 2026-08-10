"""Tests for the bounded offline temporal observation candidate."""

from __future__ import annotations

import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "tools", "camera_toolchain"
    ),
)

from apriltag_video_replay import summarize_trace  # noqa: E402
from temporal_observation import track_quad_with_optical_flow  # noqa: E402


def _textured_square(shift=(0, 0)) -> np.ndarray:
    frame = np.zeros((240, 320), dtype=np.uint8)
    x, y = 80 + int(shift[0]), 60 + int(shift[1])
    cv2.rectangle(frame, (x, y), (x + 100, y + 100), 255, -1)
    cv2.line(frame, (x + 10, y + 10), (x + 90, y + 90), 0, 3)
    cv2.line(frame, (x + 90, y + 10), (x + 10, y + 90), 0, 3)
    cv2.circle(frame, (x + 25, y + 75), 8, 0, -1)
    cv2.circle(frame, (x + 75, y + 25), 8, 0, -1)
    return frame


def test_optical_flow_tracks_a_quad_and_reports_quality():
    previous = _textured_square()
    current = _textured_square((12, 7))
    corners = np.asarray(
        [[80, 60], [180, 60], [180, 160], [80, 160]], dtype=np.float32
    )

    result = track_quad_with_optical_flow(previous, current, corners)

    assert result.valid is True
    assert result.tracked_ratio == pytest.approx(1.0)
    assert result.mean_error_px < 2.0
    assert result.corners is not None
    assert np.mean(result.corners - corners, axis=0) == pytest.approx(
        [12.0, 7.0], abs=1.5
    )


def test_optical_flow_rejects_a_frame_without_trackable_evidence():
    previous = _textured_square()
    current = np.zeros_like(previous)
    corners = np.asarray(
        [[80, 60], [180, 60], [180, 160], [80, 160]], dtype=np.float32
    )

    result = track_quad_with_optical_flow(previous, current, corners)

    assert result.valid is False
    assert result.corners is None
    assert result.reason in {
        "insufficient_tracked_corners",
        "flow_error_too_high",
        "invalid_tracked_geometry",
    }


def test_trace_summary_separates_decodes_from_temporal_predictions():
    trace = [
        {
            "frame_index": 0,
            "detected": True,
            "tag_decoded": True,
            "pose_output": True,
            "observation_kind": "decoded",
            "prediction_gap_frames": 0,
            "detect_elapsed_ns": 10,
        },
        {
            "frame_index": 1,
            "detected": False,
            "tag_decoded": False,
            "pose_output": True,
            "observation_kind": "flow_prediction",
            "prediction_gap_frames": 1,
            "detect_elapsed_ns": 20,
        },
        {
            "frame_index": 2,
            "detected": False,
            "tag_decoded": False,
            "pose_output": True,
            "observation_kind": "flow_prediction",
            "prediction_gap_frames": 2,
            "detect_elapsed_ns": 30,
        },
        {
            "frame_index": 3,
            "detected": False,
            "tag_decoded": False,
            "pose_output": False,
            "observation_kind": "missing",
            "prediction_gap_frames": 3,
            "detect_elapsed_ns": 40,
        },
        {
            "frame_index": 4,
            "detected": True,
            "tag_decoded": True,
            "pose_output": True,
            "observation_kind": "decoded",
            "prediction_gap_frames": 0,
            "reacquisition_correction": True,
            "reacquisition_position_correction_mm": 5.5,
            "reacquisition_yaw_correction_rad": 0.125,
            "detect_elapsed_ns": 50,
        },
    ]

    summary = summarize_trace(trace)

    assert summary["tag_decode_ratio"] == pytest.approx(2 / 5)
    assert summary["pose_output_ratio"] == pytest.approx(4 / 5)
    assert summary["predicted_pose_count"] == 2
    assert summary["max_prediction_gap_frames"] == 2
    assert summary["reacquisition_correction_count"] == 1
    assert summary["reacquisition_position_correction_p95_mm"] == pytest.approx(5.5)
    assert summary["reacquisition_yaw_correction_p95_rad"] == pytest.approx(0.125)
