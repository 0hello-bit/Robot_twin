"""Offline motion observations derived from calibrated camera poses.

This module estimates whole-car planar motion from the external camera pose
stream.  The result is not wheel speed or motor RPM, and it never feeds the
STM32 controller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Tuple

from .v1_twin_pose_fusion import wrap_angle_rad
from .v1_twin_schema import V1Pose


class MotionObservationQuality(Enum):
    """Whether a camera-pose derivative is usable for offline evidence."""

    VALID = "VALID"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class V1CameraMotion:
    """One external whole-car motion observation.

    Position is in the calibrated floor frame.  Velocity is a finite
    difference in that same world frame; no vehicle-axis convention is
    assumed until the camera/vehicle mounting is calibrated.
    """

    timestamp_ns: int
    dt_s: Optional[float]
    dx_mm: Optional[float]
    dy_mm: Optional[float]
    world_vx_mm_s: Optional[float]
    world_vy_mm_s: Optional[float]
    planar_speed_mm_s: Optional[float]
    yaw_rate_rad_s: Optional[float]
    quality: MotionObservationQuality
    reason: Optional[str]
    source: str = "CAMERA_POSE_DERIVATIVE"

    def __post_init__(self) -> None:
        if isinstance(self.timestamp_ns, bool) or not isinstance(
            self.timestamp_ns, int
        ) or self.timestamp_ns < 0:
            raise ValueError("timestamp_ns must be a non-negative int")
        if not isinstance(self.quality, MotionObservationQuality):
            raise TypeError("quality must be MotionObservationQuality")
        if self.source != "CAMERA_POSE_DERIVATIVE":
            raise ValueError("source must be CAMERA_POSE_DERIVATIVE")
        for name in (
            "dt_s",
            "dx_mm",
            "dy_mm",
            "world_vx_mm_s",
            "world_vy_mm_s",
            "planar_speed_mm_s",
            "yaw_rate_rad_s",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError("{} must be finite when present".format(name))
        if self.dt_s is not None and self.dt_s <= 0.0:
            raise ValueError("dt_s must be positive when present")
        if self.reason is not None and (
            not isinstance(self.reason, str) or not self.reason
        ):
            raise ValueError("reason must be a non-empty string when present")
        if self.quality is MotionObservationQuality.VALID:
            if any(
                getattr(self, name) is None
                for name in (
                    "dt_s",
                    "dx_mm",
                    "dy_mm",
                    "world_vx_mm_s",
                    "world_vy_mm_s",
                    "planar_speed_mm_s",
                    "yaw_rate_rad_s",
                )
            ):
                raise ValueError("valid observations require all derivatives")
            if self.reason is not None:
                raise ValueError("valid observations cannot have a reason")

    def to_dict(self) -> dict:
        return {
            "type": "V1CameraMotion",
            "timestamp_ns": self.timestamp_ns,
            "dt_s": self.dt_s,
            "dx_mm": self.dx_mm,
            "dy_mm": self.dy_mm,
            "world_vx_mm_s": self.world_vx_mm_s,
            "world_vy_mm_s": self.world_vy_mm_s,
            "planar_speed_mm_s": self.planar_speed_mm_s,
            "yaw_rate_rad_s": self.yaw_rate_rad_s,
            "quality": self.quality.value,
            "reason": self.reason,
            "source": self.source,
            "units": {
                "timestamp": "ns",
                "dt": "s",
                "delta_position": "mm",
                "velocity": "mm/s",
                "yaw_rate": "rad/s",
            },
        }


def _insufficient(timestamp_ns: int, reason: str) -> V1CameraMotion:
    return V1CameraMotion(
        timestamp_ns=timestamp_ns,
        dt_s=None,
        dx_mm=None,
        dy_mm=None,
        world_vx_mm_s=None,
        world_vy_mm_s=None,
        planar_speed_mm_s=None,
        yaw_rate_rad_s=None,
        quality=MotionObservationQuality.INSUFFICIENT_EVIDENCE,
        reason=reason,
    )


def estimate_camera_motion(
    poses: Iterable[V1Pose],
    *,
    max_gap_ns: int = 100_000_000,
) -> Tuple[V1CameraMotion, ...]:
    """Estimate external whole-car motion from adjacent camera poses.

    A rejected timestamp becomes a new gap boundary.  The next pose therefore
    cannot be paired across an invalid or missing interval.
    """

    if isinstance(max_gap_ns, bool) or not isinstance(max_gap_ns, int):
        raise ValueError("max_gap_ns must be a positive int")
    if max_gap_ns <= 0:
        raise ValueError("max_gap_ns must be a positive int")

    records = []
    previous: Optional[V1Pose] = None
    for current in poses:
        if not isinstance(current, V1Pose):
            raise TypeError("poses must contain V1Pose values")
        if previous is None:
            records.append(_insufficient(current.t_pc_ns, "no_previous_pose"))
            previous = current
            continue

        dt_ns = current.t_pc_ns - previous.t_pc_ns
        if dt_ns <= 0:
            records.append(
                _insufficient(current.t_pc_ns, "non_monotonic_timestamp")
            )
            previous = None
            continue
        if dt_ns > max_gap_ns:
            records.append(_insufficient(current.t_pc_ns, "pose_gap_exceeded"))
            previous = None
            continue

        dt_s = dt_ns / 1_000_000_000.0
        dx_mm = current.x_mm - previous.x_mm
        dy_mm = current.y_mm - previous.y_mm
        world_vx_mm_s = dx_mm / dt_s
        world_vy_mm_s = dy_mm / dt_s
        planar_speed_mm_s = math.hypot(world_vx_mm_s, world_vy_mm_s)
        yaw_delta_rad = wrap_angle_rad(current.yaw_rad - previous.yaw_rad)
        yaw_rate_rad_s = yaw_delta_rad / dt_s
        records.append(
            V1CameraMotion(
                timestamp_ns=current.t_pc_ns,
                dt_s=dt_s,
                dx_mm=dx_mm,
                dy_mm=dy_mm,
                world_vx_mm_s=world_vx_mm_s,
                world_vy_mm_s=world_vy_mm_s,
                planar_speed_mm_s=planar_speed_mm_s,
                yaw_rate_rad_s=yaw_rate_rad_s,
                quality=MotionObservationQuality.VALID,
                reason=None,
            )
        )
        previous = current

    return tuple(records)
