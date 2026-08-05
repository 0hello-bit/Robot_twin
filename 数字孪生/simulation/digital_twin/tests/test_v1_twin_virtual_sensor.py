"""Offline geometry contracts for the firmware-compatible virtual sensors."""

from __future__ import annotations

import math

import pytest

from v1_twin.v1_twin_schema import V1Pose, V1SensorModelConfig, V1TrackMap
from v1_twin.v1_twin_virtual_sensor import V1VirtualSensor


CONFIG = V1SensorModelConfig(
    lateral_offsets_mm=(-15.0, -5.0, 5.0, 15.0),
    sensor_bar_fore_aft_mm=0.0,
)


def _pose(x=0.0, y=0.0, yaw=0.0):
    return V1Pose(x, y, yaw, confidence=1.0, t_pc_ns=0,
                  source="simulated")


def _track(points, width=2.0):
    return V1TrackMap(mask=((0,),), centerline_mm=tuple(points),
                      width_mm=width)


def test_left_outer_sensor_is_black_and_error_is_negative():
    reading = V1VirtualSensor(CONFIG).read(
        _pose(), _track(((-100.0, -15.0), (100.0, -15.0)))
    )

    assert reading.sensors == (1, 0, 0, 0)
    assert reading.error == pytest.approx(-2.5)
    assert reading.line_lost is False
    assert reading.black_count == 1


def test_right_inner_sensor_is_black_and_error_is_positive():
    reading = V1VirtualSensor(CONFIG).read(
        _pose(), _track(((-100.0, 5.0), (100.0, 5.0)))
    )

    assert reading.sensors == (0, 0, 1, 0)
    assert reading.error == pytest.approx(0.45)


def test_multiple_black_sensors_use_firmware_weighted_position():
    reading = V1VirtualSensor(CONFIG).read(
        _pose(), _track(((-100.0, -10.0), (100.0, -10.0)), width=12.0)
    )

    assert reading.sensors == (1, 1, 0, 0)
    assert reading.error == pytest.approx(-2.0)
    assert reading.black_count == 2


def test_all_black_preserves_previous_error_and_line_loss_is_explicit():
    sensor = V1VirtualSensor(CONFIG)
    all_black = sensor.read(_pose(), _track(((-100.0, 0.0), (100.0, 0.0)),
                                             width=40.0),
                            previous_error=-0.7)
    lost = sensor.read(_pose(y=100.0),
                       _track(((-100.0, 0.0), (100.0, 0.0))))

    assert all_black.sensors == (1, 1, 1, 1)
    assert all_black.error == pytest.approx(-0.7)
    assert all_black.line_lost is False
    assert lost.sensors == (0, 0, 0, 0)
    assert lost.error == pytest.approx(0.0)
    assert lost.line_lost is True


def test_sensor_offsets_rotate_with_pose():
    reading = V1VirtualSensor(CONFIG).read(
        _pose(yaw=math.pi / 2.0),
        _track(((15.0, -100.0), (15.0, 100.0))),
    )

    assert reading.sensors == (1, 0, 0, 0)


def test_empty_centerline_is_rejected():
    track = V1TrackMap(mask=((0,),), centerline_mm=tuple(), width_mm=2.0)
    with pytest.raises(ValueError, match="centerline"):
        V1VirtualSensor(CONFIG).read(_pose(), track)
