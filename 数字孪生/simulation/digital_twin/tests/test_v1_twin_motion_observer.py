"""Offline contracts for camera-derived body-motion observations."""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from v1_twin.v1_twin_schema import V1Pose  # noqa: E402
from v1_twin.v1_twin_motion_observer import (  # noqa: E402
    MotionObservationQuality,
    estimate_camera_motion,
)


def _pose(*, x=0.0, y=0.0, yaw=0.0, timestamp_ns=0):
    return V1Pose(
        x_mm=x,
        y_mm=y,
        yaw_rad=yaw,
        confidence=0.98,
        t_pc_ns=timestamp_ns,
    )


def test_valid_adjacent_poses_produce_planar_speed_and_yaw_rate():
    records = estimate_camera_motion(
        (
            _pose(timestamp_ns=0),
            _pose(x=100.0, yaw=0.2, timestamp_ns=100_000_000),
        )
    )

    assert records[0].quality is MotionObservationQuality.INSUFFICIENT_EVIDENCE
    assert records[0].reason == "no_previous_pose"
    current = records[1]
    assert current.quality is MotionObservationQuality.VALID
    assert current.dt_s == pytest.approx(0.1)
    assert current.dx_mm == pytest.approx(100.0)
    assert current.dy_mm == pytest.approx(0.0)
    assert current.world_vx_mm_s == pytest.approx(1000.0)
    assert current.world_vy_mm_s == pytest.approx(0.0)
    assert current.planar_speed_mm_s == pytest.approx(1000.0)
    assert current.yaw_rate_rad_s == pytest.approx(2.0)


def test_first_pose_is_not_fabricated_as_zero_velocity():
    record = estimate_camera_motion((_pose(timestamp_ns=123),))[0]

    assert record.dt_s is None
    assert record.planar_speed_mm_s is None
    assert record.yaw_rate_rad_s is None


def test_non_monotonic_timestamp_resets_predecessor_and_fails_closed():
    records = estimate_camera_motion(
        (
            _pose(timestamp_ns=0),
            _pose(x=100.0, timestamp_ns=0),
            _pose(x=200.0, timestamp_ns=100_000_000),
        )
    )

    assert records[1].quality is MotionObservationQuality.INSUFFICIENT_EVIDENCE
    assert records[1].reason == "non_monotonic_timestamp"
    assert records[1].planar_speed_mm_s is None
    assert records[2].quality is MotionObservationQuality.INSUFFICIENT_EVIDENCE
    assert records[2].reason == "no_previous_pose"


def test_excessive_gap_is_rejected_and_does_not_bridge_the_gap():
    records = estimate_camera_motion(
        (
            _pose(timestamp_ns=0),
            _pose(x=100.0, timestamp_ns=100_000_000),
            _pose(x=110.0, timestamp_ns=120_000_000),
        ),
        max_gap_ns=50_000_000,
    )

    assert records[1].reason == "pose_gap_exceeded"
    assert records[1].planar_speed_mm_s is None
    assert records[2].reason == "no_previous_pose"


def test_yaw_rate_uses_shortest_angle_delta_and_does_not_mutate_input():
    start = _pose(yaw=math.pi - 0.1, timestamp_ns=0)
    end = _pose(yaw=-math.pi + 0.1, timestamp_ns=100_000_000)
    before = (start.to_dict(), end.to_dict())

    record = estimate_camera_motion((start, end))[1]

    assert record.yaw_rate_rad_s == pytest.approx(2.0)
    assert (start.to_dict(), end.to_dict()) == before


def test_invalid_configuration_and_input_are_rejected():
    with pytest.raises(ValueError, match="max_gap_ns"):
        estimate_camera_motion((), max_gap_ns=0)
    with pytest.raises(TypeError, match="V1Pose"):
        estimate_camera_motion((object(),))
