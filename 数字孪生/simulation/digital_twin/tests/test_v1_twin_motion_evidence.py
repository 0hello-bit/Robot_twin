"""Offline contracts for summarized camera-motion evidence."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from v1_twin.v1_twin_imu_control import V1ImuEvidenceReport  # noqa: E402
from v1_twin.v1_twin_motion_evidence import (  # noqa: E402
    build_camera_motion_evidence,
)
from v1_twin.v1_twin_motion_observer import (  # noqa: E402
    MotionObservationQuality,
)
from v1_twin.v1_twin_schema import V1Pose  # noqa: E402


def _pose(timestamp_ns, *, x=0.0, y=0.0, yaw=0.0):
    return V1Pose(
        x_mm=x,
        y_mm=y,
        yaw_rad=yaw,
        confidence=0.98,
        t_pc_ns=timestamp_ns,
    )


def _imu_report(*, used_imu_count=2, camera_imu_delta_p95_rad=0.03):
    return V1ImuEvidenceReport(
        evidence_status="VERIFIED",
        source="REAL_SYNC",
        record_count=used_imu_count,
        used_imu_count=used_imu_count,
        camera_only_count=0,
        insufficient_count=0,
        imu_coverage=1.0,
        camera_imu_delta_p95_rad=camera_imu_delta_p95_rad,
        propagated_camera_residual_p95_rad=None,
        max_imu_gap_ns=20_000_000,
        monotonic_timestamps=True,
        reason_counts=(),
        reason="real_sync_quality_summary_only",
    )


def test_real_sync_report_summarizes_valid_camera_motion_without_calibrating_imu():
    motions, report = build_camera_motion_evidence(
        (_pose(0), _pose(100_000_000, x=100.0, yaw=0.2)),
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
        imu_report=_imu_report(),
    )

    assert motions[1].source == "CAMERA_POSE_DERIVATIVE"
    assert report.evidence_status == "VERIFIED"
    assert report.valid_count == 1
    assert report.planar_speed_mean_mm_s == pytest.approx(1000.0)
    assert report.camera_imu_delta_p95_rad == pytest.approx(0.03)


def test_failed_sync_gate_cannot_promote_camera_motion_to_verified():
    _, report = build_camera_motion_evidence(
        (_pose(0), _pose(100_000_000, x=100.0)),
        source="REAL_SYNC",
        sync_gate_verdict="FAIL",
    )

    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.reason == "sync_gate_not_pass"


def test_synthetic_and_invalid_intervals_fail_closed():
    motions, report = build_camera_motion_evidence(
        (_pose(0), _pose(0, x=100.0)),
        source="SYNTHETIC",
        sync_gate_verdict="PASS",
    )

    assert motions[1].quality is MotionObservationQuality.INSUFFICIENT_EVIDENCE
    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.reason == "source_not_real_sync"


def test_empty_real_sync_input_is_insufficient_evidence():
    _, report = build_camera_motion_evidence(
        (),
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
    )

    assert report.record_count == 0
    assert report.valid_count == 0
    assert report.reason == "no_camera_motion_records"
    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"


def test_valid_motion_summary_uses_only_valid_intervals():
    _, report = build_camera_motion_evidence(
        (
            _pose(0),
            _pose(100_000_000, x=100.0),
            _pose(100_000_000, x=200.0),
        ),
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
    )

    assert report.record_count == 3
    assert report.valid_count == 1
    assert report.insufficient_count == 2
    assert report.valid_ratio == pytest.approx(1.0 / 3.0)
    assert report.planar_speed_p95_mm_s == pytest.approx(1000.0)


def test_non_monotonic_tail_keeps_time_span_non_negative():
    _, report = build_camera_motion_evidence(
        (
            _pose(100),
            _pose(200, x=100.0),
            _pose(50, x=200.0),
        ),
        source="SYNTHETIC",
        sync_gate_verdict="PASS",
    )

    assert report.time_span_ns == 150
    assert report.insufficient_count == 2


def test_invalid_source_and_imu_report_are_rejected():
    with pytest.raises(ValueError, match="source"):
        build_camera_motion_evidence((), source="CAMERA")
    with pytest.raises(TypeError, match="V1ImuEvidenceReport"):
        build_camera_motion_evidence(
            (_pose(0),),
            source="SYNTHETIC",
            imu_report=object(),
        )


def test_invalid_motion_gap_configuration_is_rejected():
    with pytest.raises(ValueError, match="max_gap_ns"):
        build_camera_motion_evidence(
            (_pose(0),),
            source="SYNTHETIC",
            max_gap_ns=0,
        )
