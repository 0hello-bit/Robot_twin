"""TDD contract tests for camera-anchored IMU yaw fusion."""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from v1_twin.v1_twin_pose_fusion import (  # noqa: E402
    IMU_VALIDITY_DT_CLAMPED,
    IMU_VALIDITY_REQUIRED,
    V1PoseFusion,
    V1PoseFusionConfig,
    V1PoseFusionQuality,
    wrap_angle_rad,
)
from v1_twin.v1_twin_schema import V1Pose, V1TelemetryFrame  # noqa: E402


def make_pose(*, yaw=0.0, t=0, x=10.0, y=20.0):
    return V1Pose(
        x_mm=x,
        y_mm=y,
        yaw_rad=yaw,
        confidence=0.98,
        t_pc_ns=t,
    )


def make_telemetry(*, yaw=0.0, t=0, validity=IMU_VALIDITY_REQUIRED,
                   known=True):
    return V1TelemetryFrame(
        sensors=(1, 1, 0, 1),
        error=0.0,
        pid_output=0.0,
        pwm=(400, 400, 400, 400),
        tick_ms=t // 1_000_000,
        pc_recv_ns=t,
        yaw_rad=yaw,
        imu_yaw_deg_x100=int(round(math.degrees(yaw) * 100.0)),
        imu_validity=validity,
        imu_validity_known=known,
        imu_init_status=0,
        imu_init_status_known=known,
    )


def test_first_valid_pair_anchors_fused_yaw_to_camera_pose():
    fusion = V1PoseFusion()

    record = fusion.update(make_pose(yaw=1.2, t=100),
                           make_telemetry(yaw=-0.4, t=100))

    assert record.quality is V1PoseFusionQuality.USED_IMU
    assert record.fused_yaw_rad == pytest.approx(1.2)
    assert record.propagated_yaw_rad == pytest.approx(1.2)
    assert record.camera_x_mm == pytest.approx(10.0)
    assert record.camera_y_mm == pytest.approx(20.0)
    assert record.fallback_reason is None


def test_valid_imu_delta_propagates_during_camera_gap_without_position():
    fusion = V1PoseFusion()
    fusion.update(make_pose(yaw=0.2, t=0), make_telemetry(yaw=1.0, t=0))

    record = fusion.update(None, make_telemetry(yaw=1.5, t=10_000_000))

    assert record.quality is V1PoseFusionQuality.USED_IMU
    assert record.propagated_yaw_rad == pytest.approx(0.7)
    assert record.fused_yaw_rad == pytest.approx(0.7)
    assert record.camera_x_mm is None
    assert record.camera_y_mm is None


def test_camera_correction_removes_bounded_part_of_imu_drift():
    fusion = V1PoseFusion(V1PoseFusionConfig(correction_gain=0.5))
    fusion.update(make_pose(yaw=0.0, t=0), make_telemetry(yaw=0.0, t=0))

    record = fusion.update(make_pose(yaw=1.0, t=10_000_000),
                           make_telemetry(yaw=0.2, t=10_000_000))

    assert record.propagated_yaw_rad == pytest.approx(0.2)
    assert record.fused_yaw_rad == pytest.approx(0.6)
    assert record.camera_x_mm == pytest.approx(10.0)
    assert record.camera_y_mm == pytest.approx(20.0)


def test_invalid_imu_falls_back_to_camera_only_and_never_fabricates_position():
    fusion = V1PoseFusion()
    camera_only = fusion.update(
        make_pose(yaw=0.8, t=0),
        make_telemetry(yaw=0.1, t=0, known=False),
    )
    insufficient = fusion.update(
        None,
        make_telemetry(yaw=0.2, t=10_000_000, known=False),
    )

    assert camera_only.quality is V1PoseFusionQuality.CAMERA_ONLY
    assert camera_only.fused_yaw_rad == pytest.approx(0.8)
    assert camera_only.camera_x_mm == pytest.approx(10.0)
    assert camera_only.fallback_reason == "imu_validity_unknown"
    assert insufficient.quality is V1PoseFusionQuality.INSUFFICIENT_EVIDENCE
    assert insufficient.fused_yaw_rad is None
    assert insufficient.camera_x_mm is None
    assert insufficient.camera_y_mm is None


def test_nonzero_init_status_rejects_otherwise_valid_imu():
    telemetry = V1TelemetryFrame(
        sensors=(1, 1, 0, 1),
        error=0.0,
        pid_output=0.0,
        pwm=(400, 400, 400, 400),
        tick_ms=0,
        pc_recv_ns=0,
        yaw_rad=0.2,
        imu_yaw_deg_x100=1146,
        imu_validity=IMU_VALIDITY_REQUIRED,
        imu_validity_known=True,
        imu_init_status=0x21,
        imu_init_status_known=True,
    )
    record = V1PoseFusion().update(make_pose(yaw=0.4, t=0), telemetry)
    assert record.quality is V1PoseFusionQuality.CAMERA_ONLY
    assert record.fallback_reason == "imu_init_failed"
    assert record.fused_yaw_rad == pytest.approx(0.4)


def test_dt_clamped_sample_is_not_used_for_fusion():
    fusion = V1PoseFusion()

    record = fusion.update(
        make_pose(yaw=0.4, t=0),
        make_telemetry(yaw=0.1, t=0,
                       validity=IMU_VALIDITY_REQUIRED | IMU_VALIDITY_DT_CLAMPED),
    )

    assert record.quality is V1PoseFusionQuality.CAMERA_ONLY
    assert record.fused_yaw_rad == pytest.approx(0.4)
    assert record.fallback_reason == "dt_clamped"


def test_camera_only_pose_remains_anchor_for_next_valid_imu_gap():
    fusion = V1PoseFusion()
    fusion.update(make_pose(yaw=0.0, t=0), make_telemetry(yaw=0.0, t=0))
    camera_only = fusion.update(
        make_pose(yaw=1.0, t=10),
        make_telemetry(yaw=0.0, t=10, known=False),
    )
    recovered = fusion.update(
        None, make_telemetry(yaw=0.1, t=20)
    )

    assert camera_only.quality is V1PoseFusionQuality.CAMERA_ONLY
    assert recovered.quality is V1PoseFusionQuality.USED_IMU
    assert recovered.fused_yaw_rad == pytest.approx(1.1)


def test_wraparound_uses_shortest_camera_residual():
    gain = 0.5
    fusion = V1PoseFusion(V1PoseFusionConfig(correction_gain=gain))
    start = math.pi - 0.1
    fusion.update(make_pose(yaw=start, t=0), make_telemetry(yaw=0.0, t=0))

    record = fusion.update(
        make_pose(yaw=-math.pi + 0.1, t=10_000_000),
        make_telemetry(yaw=0.0, t=10_000_000),
    )

    assert abs(abs(record.fused_yaw_rad) - math.pi) < 0.01
    assert abs(wrap_angle_rad(
        record.camera_yaw_rad - record.propagated_yaw_rad
    )) < 0.3


def test_non_monotonic_and_excessive_gap_are_explicit_failures():
    fusion = V1PoseFusion(V1PoseFusionConfig(max_imu_gap_ns=20))
    fusion.update(make_pose(yaw=0.0, t=100), make_telemetry(yaw=0.0, t=100))

    non_monotonic = fusion.update(
        make_pose(yaw=0.3, t=90), make_telemetry(yaw=0.1, t=90)
    )
    excessive_gap = fusion.update(
        None, make_telemetry(yaw=0.2, t=121)
    )

    assert non_monotonic.quality is V1PoseFusionQuality.CAMERA_ONLY
    assert non_monotonic.fallback_reason == "non_monotonic_timestamp"
    assert excessive_gap.quality is V1PoseFusionQuality.INSUFFICIENT_EVIDENCE
    assert excessive_gap.fallback_reason == "imu_gap_exceeded"


def test_explicit_aligned_timestamp_avoids_batched_receive_timestamp():
    fusion = V1PoseFusion()
    raw_receive_ns = 1_000_000_000
    first = make_telemetry(yaw=0.0, t=raw_receive_ns)
    second = make_telemetry(yaw=0.2, t=raw_receive_ns)

    fusion.update(
        make_pose(yaw=0.0, t=0),
        first,
        timestamp_ns=10_000_000,
    )
    record = fusion.update(
        make_pose(yaw=0.1, t=20_000_000),
        second,
        timestamp_ns=20_000_000,
    )

    assert record.quality is V1PoseFusionQuality.USED_IMU
    assert record.timestamp_ns == 20_000_000
    assert record.raw_pc_recv_ns == raw_receive_ns
