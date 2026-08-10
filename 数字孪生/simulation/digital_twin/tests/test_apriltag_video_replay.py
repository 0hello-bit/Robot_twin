"""Offline tests for the bounded AprilTag video replay benchmark."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "tools", "camera_toolchain"
    ),
)

from apriltag_video_replay import (  # noqa: E402
    compare_video_candidates,
    evaluate_candidate_selection,
    resolve_temporal_observation_config,
    replay_video,
    summarize_trace,
)


def _write_mjpeg_video(path: Path, frame_count: int = 4) -> Path:
    size = (1920, 1080)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        30.0,
        size,
    )
    assert writer.isOpened()
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    tag = cv2.aruco.generateImageMarker(dictionary, 0, 240)
    for index in range(frame_count):
        frame = np.full((size[1], size[0], 3), 255, dtype=np.uint8)
        if index != 2:
            frame[420:660, 840:1080] = cv2.cvtColor(tag, cv2.COLOR_GRAY2BGR)
        writer.write(frame)
    writer.release()
    return path


def test_replay_rejects_camera_index_before_opening_capture(monkeypatch):
    import apriltag_video_replay

    monkeypatch.setattr(
        apriltag_video_replay.cv2,
        "VideoCapture",
        lambda *_args, **_kwargs: pytest.fail("camera-style input must be rejected"),
    )

    with pytest.raises(ValueError, match="video file"):
        replay_video("0")


def test_replay_rejects_unknown_profile_and_variant_before_opening_capture(
    monkeypatch, tmp_path: Path
):
    import apriltag_video_replay

    monkeypatch.setattr(
        apriltag_video_replay.cv2,
        "VideoCapture",
        lambda *_args, **_kwargs: pytest.fail("invalid selection must fail closed"),
    )
    video_path = tmp_path / "input.mkv"

    with pytest.raises(ValueError, match="unsupported observation profile"):
        replay_video(video_path, observation_profile="unknown")
    with pytest.raises(ValueError, match="unsupported parameter variant"):
        replay_video(video_path, parameter_variant="unknown")


def test_replay_decodes_real_mjpeg_video_and_records_trace(tmp_path: Path):
    video_path = _write_mjpeg_video(tmp_path / "input.mkv")

    result = replay_video(video_path, max_frames=4)

    assert result["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["timebase"] == "DERIVED_FROM_VIDEO_FPS"
    assert result["video"]["width"] == 1920
    assert result["video"]["height"] == 1080
    assert result["video"]["fps"] == pytest.approx(30.0)
    assert result["video"]["fourcc"] == "MJPG"
    assert result["video"]["decoded_frame_count"] == 4
    assert result["summary"]["decoded_frame_count"] == 4
    assert len(result["trace"]) == 4
    assert result["trace"][0]["frame_index"] == 0
    assert result["trace"][0]["detected"] is True
    assert result["summary"]["replay_complete"] is True


def test_replay_marks_truncated_prefix_incomplete(tmp_path: Path):
    video_path = _write_mjpeg_video(tmp_path / "input.mkv", frame_count=4)

    result = replay_video(video_path, max_frames=2)

    assert result["video"]["frame_count_matches_reported"] is False
    assert result["summary"]["replay_complete"] is False


def test_replay_accepts_pupil_roi_candidate_and_reports_backend(tmp_path: Path):
    video_path = _write_mjpeg_video(tmp_path / "input.mkv", frame_count=1)

    result = replay_video(
        video_path,
        parameter_variant="pupil_roi",
        max_frames=1,
    )

    assert result["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["candidate"]["parameter_variant"] == "pupil_roi"
    assert result["candidate"]["detector_backend"] == "pupil_apriltags"
    assert result["trace"][0]["detector_backend"] == "pupil_apriltags"


def test_replay_accepts_fast_recovery_candidate_and_reports_policy(tmp_path: Path):
    video_path = _write_mjpeg_video(tmp_path / "input.mkv", frame_count=1)

    result = replay_video(
        video_path,
        parameter_variant="fast_recovery",
        max_frames=1,
    )

    assert result["candidate"]["parameter_variant"] == "fast_recovery"
    assert result["candidate"]["recovery_policy"] == "fast_recovery"
    assert result["trace"][0]["recovery_policy"] == "fast_recovery"


def test_replay_accepts_fast_recovery_wide_candidate_and_reports_policy(
    tmp_path: Path,
):
    video_path = _write_mjpeg_video(tmp_path / "input.mkv", frame_count=1)

    result = replay_video(
        video_path,
        parameter_variant="fast_recovery_wide",
        max_frames=1,
    )

    assert result["candidate"]["parameter_variant"] == "fast_recovery_wide"
    assert result["candidate"]["recovery_policy"] == "fast_recovery_wide"
    assert result["trace"][0]["recovery_policy"] == "fast_recovery_wide"


def test_compare_uses_a_fresh_tracker_for_each_candidate(tmp_path: Path):
    video_path = _write_mjpeg_video(tmp_path / "input.mkv", frame_count=2)

    result = compare_video_candidates(
        video_path,
        candidates=(
            {
                "name": "production",
                "observation_profile": "production",
                "parameter_variant": "default",
            },
            {
                "name": "subpix",
                "observation_profile": "production",
                "parameter_variant": "subpix",
            },
        ),
        max_frames=2,
    )

    assert result["selection"]["verdict"] == "NOT_JUSTIFIED"
    assert len(result["summaries"]) == 2
    for candidate in result["candidates"]:
        assert candidate["trace"][0]["roi_bounds"] is None


def test_trace_summary_distinguishes_frame_gap_and_missed_frames():
    trace = [
        {"frame_index": 0, "detected": True, "detect_elapsed_ns": 10},
        {"frame_index": 1, "detected": False, "detect_elapsed_ns": 20},
        {"frame_index": 2, "detected": False, "detect_elapsed_ns": 30},
        {"frame_index": 3, "detected": True, "detect_elapsed_ns": 40},
        {"frame_index": 4, "detected": False, "detect_elapsed_ns": 50},
        {"frame_index": 5, "detected": False, "detect_elapsed_ns": 60},
        {"frame_index": 6, "detected": False, "detect_elapsed_ns": 70},
    ]

    summary = summarize_trace(trace)

    assert summary["detection_ratio"] == pytest.approx(2 / 7)
    assert summary["max_detection_interval_frames"] == pytest.approx(3.0)
    assert summary["max_consecutive_missed_frames"] == 3
    assert summary["processing_p95_ms"] == pytest.approx(0.000067, abs=0.00001)


def test_trace_summary_preserves_detector_errors():
    summary = summarize_trace([
        {
            "frame_index": 0,
            "detected": False,
            "detect_elapsed_ns": 10,
            "failure_reason": "detector_error",
            "error": "decoder failed",
        },
    ])

    assert summary["errors"] == ["decoder failed"]


def test_candidate_selection_requires_all_thresholds():
    baseline = {
        "detection_ratio": 0.90,
        "max_detection_interval_frames": 4.0,
        "max_consecutive_missed_frames": 3,
        "processing_p95_ms": 30.0,
    }
    qualified = {
        "detection_ratio": 0.96,
        "max_detection_interval_frames": 2.0,
        "max_consecutive_missed_frames": 1,
        "processing_p95_ms": 31.0,
    }
    regression = dict(qualified, processing_p95_ms=34.0)

    assert evaluate_candidate_selection(baseline, qualified)["verdict"] == (
        "QUALIFIED_FOR_ONE_REAL_AB"
    )
    assert evaluate_candidate_selection(baseline, regression)["verdict"] == (
        "NOT_JUSTIFIED"
    )


def test_candidate_selection_requires_absolute_b3_thresholds():
    baseline = {
        "detection_ratio": 0.57,
        "max_detection_interval_frames": 13.0,
        "max_consecutive_missed_frames": 12,
        "processing_p95_ms": 111.0,
    }
    candidate = {
        "detection_ratio": 0.86,
        "max_detection_interval_frames": 5.0,
        "max_consecutive_missed_frames": 4,
        "processing_p95_ms": 31.0,
    }

    assert evaluate_candidate_selection(baseline, candidate)["verdict"] == (
        "NOT_JUSTIFIED"
    )


def test_candidate_selection_rejects_incomplete_replay():
    baseline = {
        "detection_ratio": 0.57,
        "max_detection_interval_frames": 13.0,
        "max_consecutive_missed_frames": 12,
        "processing_p95_ms": 111.0,
        "replay_complete": True,
    }
    candidate = {
        "detection_ratio": 1.0,
        "max_detection_interval_frames": 1.0,
        "max_consecutive_missed_frames": 0,
        "processing_p95_ms": 10.0,
        "replay_complete": False,
    }

    decision = evaluate_candidate_selection(baseline, candidate)

    assert decision["verdict"] == "NOT_JUSTIFIED"
    assert decision["checks"]["candidate_replay_complete"] is False


def test_temporal_profiles_keep_long_bridge_explicit_and_bounded():
    assert resolve_temporal_observation_config("none") is None
    assert resolve_temporal_observation_config("flow_short2") == {
        "max_prediction_gap_frames": 2,
    }
    assert resolve_temporal_observation_config("flow_long60") == {
        "max_prediction_gap_frames": 60,
    }
    with pytest.raises(ValueError, match="unsupported temporal observation"):
        resolve_temporal_observation_config("flow_unbounded")
