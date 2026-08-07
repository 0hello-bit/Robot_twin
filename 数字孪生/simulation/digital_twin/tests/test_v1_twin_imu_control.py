"""Offline contracts for IMU evidence reporting and control shadow decisions."""

from __future__ import annotations

import math

import pytest

from v1_twin.v1_twin_imu_control import (
    V1ImuControlConfig,
    V1ImuControlShadow,
    V1ImuEvidenceReport,
    summarize_imu_evidence,
)
from v1_twin.v1_twin_pose_fusion import (
    IMU_VALIDITY_REQUIRED,
    V1PoseFusion,
)
from v1_twin.v1_twin_schema import V1Pose, V1TelemetryFrame


def _pose(*, yaw: float, timestamp_ns: int) -> V1Pose:
    return V1Pose(
        x_mm=10.0,
        y_mm=20.0,
        yaw_rad=yaw,
        confidence=0.98,
        t_pc_ns=timestamp_ns,
    )


def _telemetry(*, yaw: float, timestamp_ns: int, known: bool = True) -> V1TelemetryFrame:
    return V1TelemetryFrame(
        sensors=(1, 1, 0, 1),
        error=0.0,
        pid_output=0.0,
        pwm=(400, 400, 400, 400),
        tick_ms=timestamp_ns // 1_000_000,
        pc_recv_ns=timestamp_ns,
        yaw_rad=yaw,
        imu_yaw_deg_x100=int(round(math.degrees(yaw) * 100.0)),
        imu_validity=IMU_VALIDITY_REQUIRED,
        imu_validity_known=known,
        imu_init_status=0,
        imu_init_status_known=known,
    )


def _records(*, known: bool = True):
    fusion = V1PoseFusion()
    result = []
    for timestamp_ns, yaw in ((0, 0.0), (10_000_000, 0.1), (20_000_000, 0.2)):
        result.append(
            fusion.update(
                _pose(yaw=yaw, timestamp_ns=timestamp_ns),
                _telemetry(yaw=yaw, timestamp_ns=timestamp_ns, known=known),
            )
        )
    return tuple(result)


def test_valid_imu_changes_the_hypothetical_turn_decision():
    record = _records()[0]
    shadow = V1ImuControlShadow(
        V1ImuControlConfig(
            heading_gain_turn_per_rad=100.0,
            max_correction_turn=80,
        )
    )

    decision = shadow.decide(
        baseline_turn=100,
        desired_yaw_rad=0.7,
        fusion_record=record,
    )

    assert decision.used_imu is True
    assert decision.heading_error_rad == pytest.approx(0.7)
    assert decision.correction_turn == 70
    assert decision.applied_turn == 170
    assert decision.reason is None


def test_invalid_imu_fails_closed_to_the_baseline_turn():
    record = _records(known=False)[0]
    decision = V1ImuControlShadow().decide(
        baseline_turn=100,
        desired_yaw_rad=0.7,
        fusion_record=record,
    )

    assert decision.used_imu is False
    assert decision.heading_error_rad is None
    assert decision.correction_turn == 0
    assert decision.applied_turn == 100
    assert decision.reason == "imu_validity_unknown"


def test_shadow_correction_is_bounded_and_turn_output_is_saturated():
    record = _records()[0]
    shadow = V1ImuControlShadow(
        V1ImuControlConfig(
            heading_gain_turn_per_rad=1000.0,
            max_correction_turn=40,
            turn_limit=600,
        )
    )

    decision = shadow.decide(
        baseline_turn=590,
        desired_yaw_rad=2.0,
        fusion_record=record,
    )

    assert decision.correction_turn == 40
    assert decision.applied_turn == 600


def test_shadow_decision_is_deterministic_for_identical_inputs():
    record = _records()[1]
    shadow = V1ImuControlShadow()
    first = shadow.decide(25, 0.4, record).to_dict()
    second = shadow.decide(25, 0.4, record).to_dict()

    assert first == second


def test_synthetic_fusion_records_never_become_verified_real_evidence():
    report = summarize_imu_evidence(_records(), source="SYNTHETIC")

    assert isinstance(report, V1ImuEvidenceReport)
    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.record_count == 3
    assert report.used_imu_count == 3
    assert report.imu_coverage == pytest.approx(1.0)
    assert report.camera_imu_delta_p95_rad == pytest.approx(0.0)
    assert report.reason == "source_not_real_sync"


def test_real_sync_report_requires_monotonic_used_imu_records():
    report = summarize_imu_evidence(_records(), source="REAL_SYNC")

    assert report.evidence_status == "VERIFIED"
    assert report.monotonic_timestamps is True
    assert report.used_imu_count == 3
    assert report.propagated_camera_residual_p95_rad == pytest.approx(0.0)


def test_real_sync_report_is_insufficient_when_capture_sync_gate_fails():
    report = summarize_imu_evidence(
        _records(), source="REAL_SYNC", sync_gate_verdict="FAIL"
    )

    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.reason == "sync_gate_not_pass"


def test_real_sync_report_is_insufficient_when_timestamps_regress():
    records = list(_records())
    records[2] = records[2].__class__(
        **{
            **records[2].__dict__,
            "timestamp_ns": 5_000_000,
        }
    )

    report = summarize_imu_evidence(tuple(records), source="REAL_SYNC")

    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.monotonic_timestamps is False
    assert report.reason == "non_monotonic_timestamps"
