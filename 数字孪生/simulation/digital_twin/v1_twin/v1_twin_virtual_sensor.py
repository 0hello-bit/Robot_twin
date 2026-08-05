"""Geometry-based virtual TCRT5000 sensor bar for Task 4B-5."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

from .v1_twin_schema import V1Pose, V1SensorModelConfig, V1TrackMap


@dataclass(frozen=True)
class VirtualSensorReading:
    """One deterministic sensor-bar observation in firmware bit semantics."""

    sensors: Tuple[int, int, int, int]
    error: float
    line_lost: bool
    black_count: int
    sensor_points_mm: Tuple[Tuple[float, float], ...]


class V1VirtualSensor:
    """Project four sensor locations onto a metric centerline polyline.

    The configured lateral offsets are ordered ``sensor0`` (left outer) to
    ``sensor3`` (right outer), with positive local lateral coordinates pointing
    to the right.  Pose yaw rotates the local forward/right frame into world
    coordinates.  A point is black when its distance to the centerline is at
    most half the metric track width.
    """

    _SINGLE_SENSOR_ERRORS = (-2.5, -0.45, 0.45, 2.5)

    def __init__(self, config: V1SensorModelConfig) -> None:
        if not isinstance(config, V1SensorModelConfig):
            raise TypeError("config must be a V1SensorModelConfig")
        self.config = config

    def read(
        self,
        pose: V1Pose,
        track_map: V1TrackMap,
        previous_error: float = 0.0,
    ) -> VirtualSensorReading:
        if not isinstance(pose, V1Pose):
            raise TypeError("pose must be a V1Pose")
        if not isinstance(track_map, V1TrackMap):
            raise TypeError("track_map must be a V1TrackMap")
        if not track_map.centerline_mm:
            raise ValueError("track_map centerline must not be empty")
        try:
            previous = float(previous_error)
        except (TypeError, ValueError) as exc:
            raise ValueError("previous_error must be numeric") from exc
        if not math.isfinite(previous):
            raise ValueError("previous_error must be finite")

        cos_yaw = math.cos(pose.yaw_rad)
        sin_yaw = math.sin(pose.yaw_rad)
        points = []
        black_bits = []
        radius_sq = (track_map.width_mm * 0.5) ** 2
        for lateral in self.config.lateral_offsets_mm:
            # Local forward=(1,0), right=(0,1), then rotate by yaw.
            world_x = (
                pose.x_mm
                + self.config.sensor_bar_fore_aft_mm * cos_yaw
                - lateral * sin_yaw
            )
            world_y = (
                pose.y_mm
                + self.config.sensor_bar_fore_aft_mm * sin_yaw
                + lateral * cos_yaw
            )
            point = (world_x, world_y)
            points.append(point)
            black_bits.append(
                1 if self._distance_sq_to_centerline(point, track_map) <= radius_sq
                else 0
            )

        sensors = tuple(black_bits)
        black_count = sum(sensors)
        if black_count == 0:
            error = 0.0
        elif black_count == 4:
            # Firmware holds its filtered error when all four inputs are black.
            error = previous
        elif black_count == 1:
            index = sensors.index(1)
            error = self._SINGLE_SENSOR_ERRORS[index]
        else:
            position = (
                -3 * sensors[0]
                - sensors[1]
                + sensors[2]
                + 3 * sensors[3]
            )
            error = position / black_count

        return VirtualSensorReading(
            sensors=sensors,
            error=float(error),
            line_lost=black_count == 0,
            black_count=black_count,
            sensor_points_mm=tuple(points),
        )

    @staticmethod
    def _distance_sq_to_centerline(
        point: Tuple[float, float], track_map: V1TrackMap
    ) -> float:
        """Return the squared distance to the nearest polyline segment."""
        px, py = point
        centerline = track_map.centerline_mm
        if len(centerline) == 1:
            dx = px - centerline[0][0]
            dy = py - centerline[0][1]
            return dx * dx + dy * dy

        best = math.inf
        for (ax, ay), (bx, by) in zip(centerline, centerline[1:]):
            vx = bx - ax
            vy = by - ay
            length_sq = vx * vx + vy * vy
            if length_sq == 0.0:
                t = 0.0
            else:
                t = ((px - ax) * vx + (py - ay) * vy) / length_sq
                t = max(0.0, min(1.0, t))
            nearest_x = ax + t * vx
            nearest_y = ay + t * vy
            dx = px - nearest_x
            dy = py - nearest_y
            best = min(best, dx * dx + dy * dy)
        return best

