"""Offline tests for the explicit B3 observation profiles."""

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

import capture_sync_run
from v1_twin.v1_twin_calibration import CameraCalibration, HomographyTransform


def _identity_calibration():
    return CameraCalibration(
        camera_matrix=np.eye(3),
        dist_coeffs=np.zeros(5),
        image_size=(640, 480),
        reprojection_error_rms=0.0,
        reprojection_error_p95=0.0,
    )


def test_production_profile_keeps_existing_fallback():
    profile = capture_sync_run.resolve_observation_profile("production")

    assert profile["name"] == "production"
    assert profile["full_frame_fallback_scales"] == (2.0,)


def test_r1_profile_changes_only_full_frame_fallback():
    profile = capture_sync_run.resolve_observation_profile("r1_gray1x")

    assert profile["name"] == "r1_gray1x"
    assert profile["full_frame_fallback_scales"] == (1.0,)


def test_unknown_profile_is_rejected_before_capture():
    with pytest.raises(ValueError, match="unsupported observation profile"):
        capture_sync_run.resolve_observation_profile("unknown")


def test_main_rejects_unknown_profile_before_camera_or_tcp(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_sync_run.py",
            "--calibration-manifest",
            str(tmp_path / "manifest.json"),
            "--out",
            str(tmp_path),
            "--observation-profile",
            "unknown",
        ],
    )
    monkeypatch.setattr(
        capture_sync_run,
        "open_capture_camera",
        lambda *_args, **_kwargs: pytest.fail("camera must not open"),
    )
    monkeypatch.setattr(
        capture_sync_run,
        "connect_car",
        lambda *_args, **_kwargs: pytest.fail("TCP must not connect"),
    )

    assert capture_sync_run.main() == 2


def test_tracker_factory_preserves_detector_scales_and_changes_fallback_only():
    tracker = capture_sync_run.create_pose_tracker(
        _identity_calibration(),
        HomographyTransform(np.eye(3)),
        "r1_gray1x",
    )

    assert tracker._tag_id == 0
    assert tracker._scales == (1.0, 2.0, 3.0)
    assert tracker._fallback_scales == (1.0,)


def test_fast_recovery_wide_policy_expands_only_the_recovery_roi():
    policy = capture_sync_run.resolve_recovery_policy("fast_recovery_wide")
    tracker = capture_sync_run.create_pose_tracker(
        _identity_calibration(),
        HomographyTransform(np.eye(3)),
        recovery_policy="fast_recovery_wide",
        offline=True,
    )

    assert policy["roi_padding_px"] == 96.0
    assert tracker._roi_padding_px == 96.0
    assert tracker._scales == (1.0, 2.0, 3.0)
    assert tracker._roi_detect_scales == (1.0,)
    assert tracker._recovery_preprocess_modes == ("blue_clahe",)
    assert tracker._fallback_scales == (1.0,)


def test_live_factory_rejects_offline_recovery_policy():
    with pytest.raises(ValueError, match="offline"):
        capture_sync_run.create_pose_tracker(
            _identity_calibration(),
            HomographyTransform(np.eye(3)),
            recovery_policy="fast_recovery_wide",
        )


def test_live_factory_requires_explicit_experimental_opt_in_for_recovery_policy():
    tracker = capture_sync_run.create_pose_tracker(
        _identity_calibration(),
        HomographyTransform(np.eye(3)),
        recovery_policy="fast_recovery_wide",
        allow_experimental=True,
    )

    parameters = tracker._detector.getDetectorParameters()
    assert tracker._recovery_policy == "fast_recovery_wide"
    assert tracker._roi_padding_px == 96.0
    assert parameters.adaptiveThreshWinSizeMax == 53
    assert parameters.adaptiveThreshWinSizeStep == 5
    assert parameters.adaptiveThreshConstant == pytest.approx(3.0)


def test_sync_report_records_recovery_policy_from_diagnostics():
    actions = capture_sync_run._new_action_state()
    actions.update({
        "stop_sent": True,
        "stop_confirmed": True,
        "socket_closed": True,
        "camera_released": True,
        "reader_joined": True,
    })
    sync = {
        "coverage": 1.0,
        "p95_time_diff_ns": 1.0,
        "tolerance_ns": 1.0,
        "n_sync_frames": 1,
        "common_interval_start_ns": 1,
        "common_interval_end_ns": 2,
        "common_interval_duration_ns": 1,
        "n_common_poses": 1,
        "telemetry_interval_max_ns": 1,
        "telemetry_interval_p95_ns": 1,
        "n_telemetry_distinct": 1,
        "max_telemetry_reuse": 1,
        "verdict": "PASS",
        "gate_reason": "pass",
    }

    report = capture_sync_run.build_sync_report(
        host="offline",
        duration_s=1.0,
        run_id="run-recovery",
        camera_mode={"index": 0, "width": 1920, "height": 1080,
                     "fps": 30.0, "fourcc": "MJPG"},
        actions=actions,
        outcome="ok",
        n_poses=1,
        n_telemetry=1,
        clock={"a": 1.0, "b": 0.0, "n_samples": 1},
        residuals={"rms_ns": 0.0, "max_ns": 0.0},
        sync=sync,
        diagnostics={"recovery_policy": "fast_recovery_wide"},
    )

    assert report["recovery_policy"] == "fast_recovery_wide"


def test_sync_report_records_selected_observation_profile():
    actions = capture_sync_run._new_action_state()
    actions.update({
        "stop_sent": True,
        "stop_confirmed": True,
        "socket_closed": True,
        "camera_released": True,
        "reader_joined": True,
    })
    sync = {
        "coverage": 1.0,
        "p95_time_diff_ns": 1.0,
        "tolerance_ns": 1.0,
        "n_sync_frames": 1,
        "common_interval_start_ns": 1,
        "common_interval_end_ns": 2,
        "common_interval_duration_ns": 1,
        "n_common_poses": 1,
        "telemetry_interval_max_ns": 1,
        "telemetry_interval_p95_ns": 1,
        "n_telemetry_distinct": 1,
        "max_telemetry_reuse": 1,
        "verdict": "PASS",
        "gate_reason": "pass",
    }

    report = capture_sync_run.build_sync_report(
        host="offline",
        duration_s=1.0,
        run_id="run-profile",
        camera_mode={"index": 0, "width": 1920, "height": 1080,
                     "fps": 30.0, "fourcc": "MJPG"},
        actions=actions,
        outcome="ok",
        n_poses=1,
        n_telemetry=1,
        clock={"a": 1.0, "b": 0.0, "n_samples": 1},
        residuals={"rms_ns": 0.0, "max_ns": 0.0},
        sync=sync,
        observation_profile={
            "name": "r1_gray1x",
            "full_frame_fallback_scales": (1.0,),
        },
    )

    assert report["observation_profile"] == {
        "name": "r1_gray1x",
        "full_frame_fallback_scales": [1.0],
    }
