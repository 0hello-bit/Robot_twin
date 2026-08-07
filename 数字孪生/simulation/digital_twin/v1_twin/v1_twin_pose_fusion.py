"""Pure, camera-anchored IMU yaw fusion for offline twin evidence.

The camera remains the global pose source.  IMU data is only allowed to
propagate yaw across short, valid gaps; it never produces position and never
feeds the line-following controller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from real_world.frame_parser import MPU6050_INIT_STATUS_OK
from .v1_twin_schema import V1Pose, V1TelemetryFrame


IMU_VALIDITY_INIT = 0x01
IMU_VALIDITY_BIAS = 0x02
IMU_VALIDITY_READ = 0x04
IMU_VALIDITY_UPDATED = 0x08
IMU_VALIDITY_DT_CLAMPED = 0x10
IMU_VALIDITY_REQUIRED = (
    IMU_VALIDITY_INIT
    | IMU_VALIDITY_BIAS
    | IMU_VALIDITY_READ
    | IMU_VALIDITY_UPDATED
)


def wrap_angle_rad(angle_rad: float) -> float:
    """Return an angle in [-pi, pi), rejecting non-finite input."""

    if not math.isfinite(angle_rad):
        raise ValueError("angle_rad must be finite")
    return (angle_rad + math.pi) % (2.0 * math.pi) - math.pi


class V1PoseFusionQuality(Enum):
    USED_IMU = "USED_IMU"
    CAMERA_ONLY = "CAMERA_ONLY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class V1PoseFusionConfig:
    """Explicit fusion parameters; no sign or gain is inferred from a run."""

    imu_sign: float = 1.0
    correction_gain: float = 0.25
    max_imu_gap_ns: int = 100_000_000

    def __post_init__(self) -> None:
        if self.imu_sign not in (-1.0, 1.0):
            raise ValueError("imu_sign must be -1.0 or 1.0")
        if not math.isfinite(self.correction_gain):
            raise ValueError("correction_gain must be finite")
        if not 0.0 <= self.correction_gain <= 1.0:
            raise ValueError("correction_gain must be within [0, 1]")
        if isinstance(self.max_imu_gap_ns, bool) or not isinstance(
            self.max_imu_gap_ns, int
        ) or self.max_imu_gap_ns <= 0:
            raise ValueError("max_imu_gap_ns must be a positive int")


@dataclass(frozen=True)
class V1PoseFusionRecord:
    """One immutable fusion decision and its evidence boundary."""

    timestamp_ns: int
    raw_pc_recv_ns: int
    camera_timestamp_ns: Optional[int]
    camera_x_mm: Optional[float]
    camera_y_mm: Optional[float]
    camera_yaw_rad: Optional[float]
    imu_yaw_rad: Optional[float]
    propagated_yaw_rad: Optional[float]
    fused_yaw_rad: Optional[float]
    quality: V1PoseFusionQuality
    fallback_reason: Optional[str]
    imu_validity: int
    imu_validity_known: bool
    imu_init_status: int
    imu_init_status_known: bool
    imu_gap_ns: Optional[int]
    imu_sign: float
    correction_gain: float

    def __post_init__(self) -> None:
        if isinstance(self.timestamp_ns, bool) or not isinstance(
            self.timestamp_ns, int
        ) or self.timestamp_ns < 0:
            raise ValueError("timestamp_ns must be a non-negative int")
        if isinstance(self.raw_pc_recv_ns, bool) or not isinstance(
            self.raw_pc_recv_ns, int
        ) or self.raw_pc_recv_ns < 0:
            raise ValueError("raw_pc_recv_ns must be a non-negative int")
        if self.camera_timestamp_ns is not None and (
            isinstance(self.camera_timestamp_ns, bool)
            or not isinstance(self.camera_timestamp_ns, int)
            or self.camera_timestamp_ns < 0
        ):
            raise ValueError("camera_timestamp_ns must be a non-negative int")
        for name in (
            "camera_x_mm",
            "camera_y_mm",
            "camera_yaw_rad",
            "imu_yaw_rad",
            "propagated_yaw_rad",
            "fused_yaw_rad",
        ):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError("{0} must be finite when present".format(name))
        if not isinstance(self.quality, V1PoseFusionQuality):
            raise ValueError("quality must be V1PoseFusionQuality")
        if isinstance(self.imu_validity, bool) or not isinstance(
            self.imu_validity, int
        ) or not 0 <= self.imu_validity <= 0xFF:
            raise ValueError("imu_validity must fit uint8")
        if not isinstance(self.imu_validity_known, bool):
            raise ValueError("imu_validity_known must be bool")
        if isinstance(self.imu_init_status, bool) or not isinstance(
            self.imu_init_status, int
        ) or not 0 <= self.imu_init_status <= 0xFF:
            raise ValueError("imu_init_status must fit uint8")
        if not isinstance(self.imu_init_status_known, bool):
            raise ValueError("imu_init_status_known must be bool")
        if self.imu_gap_ns is not None and (
            isinstance(self.imu_gap_ns, bool)
            or not isinstance(self.imu_gap_ns, int)
            or self.imu_gap_ns < 0
        ):
            raise ValueError("imu_gap_ns must be a non-negative int")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "V1PoseFusionRecord",
            "timestamp_ns": self.timestamp_ns,
            "raw_pc_recv_ns": self.raw_pc_recv_ns,
            "camera_timestamp_ns": self.camera_timestamp_ns,
            "camera_x_mm": self.camera_x_mm,
            "camera_y_mm": self.camera_y_mm,
            "camera_yaw_rad": self.camera_yaw_rad,
            "imu_yaw_rad": self.imu_yaw_rad,
            "propagated_yaw_rad": self.propagated_yaw_rad,
            "fused_yaw_rad": self.fused_yaw_rad,
            "quality": self.quality.value,
            "fallback_reason": self.fallback_reason,
            "imu_validity": self.imu_validity,
            "imu_validity_known": self.imu_validity_known,
            "imu_init_status": self.imu_init_status,
            "imu_init_status_known": self.imu_init_status_known,
            "imu_gap_ns": self.imu_gap_ns,
            "imu_sign": self.imu_sign,
            "correction_gain": self.correction_gain,
        }


class V1PoseFusion:
    """State machine for synchronized camera pose and IMU observations."""

    def __init__(self, config: Optional[V1PoseFusionConfig] = None) -> None:
        self.config = config or V1PoseFusionConfig()
        self._previous_imu_yaw_rad: Optional[float] = None
        self._previous_timestamp_ns: Optional[int] = None
        self._fused_yaw_rad: Optional[float] = None

    def update(
        self,
        pose: Optional[V1Pose],
        telemetry: V1TelemetryFrame,
        *,
        timestamp_ns: Optional[int] = None,
    ) -> V1PoseFusionRecord:
        """Consume one synchronized pair; input objects are never mutated."""

        if pose is not None and not isinstance(pose, V1Pose):
            raise TypeError("pose must be V1Pose or None")
        if not isinstance(telemetry, V1TelemetryFrame):
            raise TypeError("telemetry must be V1TelemetryFrame")

        if timestamp_ns is None:
            timestamp_ns = telemetry.pc_recv_ns
        elif isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, int):
            raise TypeError("timestamp_ns must be an int or None")
        elif timestamp_ns < 0:
            raise ValueError("timestamp_ns must be a non-negative int")
        camera_yaw = pose.yaw_rad if pose is not None else None
        imu_yaw = telemetry.imu_yaw_rad
        if imu_yaw is not None and not math.isfinite(imu_yaw):
            imu_yaw = None

        reason = self._eligibility_reason(telemetry, imu_yaw, timestamp_ns)
        gap_ns: Optional[int] = None
        if self._previous_timestamp_ns is not None:
            if timestamp_ns <= self._previous_timestamp_ns:
                reason = reason or "non_monotonic_timestamp"
            else:
                gap_ns = timestamp_ns - self._previous_timestamp_ns
                if gap_ns > self.config.max_imu_gap_ns:
                    reason = reason or "imu_gap_exceeded"

        if reason is not None:
            record = self._fallback_record(
                pose=pose,
                telemetry=telemetry,
                imu_yaw=imu_yaw,
                gap_ns=gap_ns,
                reason=reason,
                timestamp_ns=timestamp_ns,
            )
            if reason == "imu_gap_exceeded" and pose is not None and imu_yaw is not None:
                self._anchor(pose, telemetry, imu_yaw, timestamp_ns)
            return record

        if self._previous_imu_yaw_rad is None or self._fused_yaw_rad is None:
            if pose is None:
                return self._record(
                    pose=None,
                    telemetry=telemetry,
                    imu_yaw=imu_yaw,
                    propagated_yaw=None,
                    fused_yaw=None,
                    quality=V1PoseFusionQuality.INSUFFICIENT_EVIDENCE,
                    fallback_reason="camera_pose_missing_anchor",
                    gap_ns=gap_ns,
                    timestamp_ns=timestamp_ns,
                )
            self._anchor(pose, telemetry, imu_yaw, timestamp_ns)
            return self._record(
                pose=pose,
                telemetry=telemetry,
                imu_yaw=imu_yaw,
                propagated_yaw=pose.yaw_rad,
                fused_yaw=pose.yaw_rad,
                quality=V1PoseFusionQuality.USED_IMU,
                fallback_reason=None,
                gap_ns=gap_ns,
                timestamp_ns=timestamp_ns,
            )

        delta_rad = wrap_angle_rad(imu_yaw - self._previous_imu_yaw_rad)
        propagated_yaw = wrap_angle_rad(
            self._fused_yaw_rad + self.config.imu_sign * delta_rad
        )
        if pose is None:
            fused_yaw = propagated_yaw
        else:
            residual = wrap_angle_rad(pose.yaw_rad - propagated_yaw)
            fused_yaw = wrap_angle_rad(
                propagated_yaw + self.config.correction_gain * residual
            )

        self._previous_imu_yaw_rad = imu_yaw
        self._previous_timestamp_ns = timestamp_ns
        self._fused_yaw_rad = fused_yaw
        return self._record(
            pose=pose,
            telemetry=telemetry,
            imu_yaw=imu_yaw,
            propagated_yaw=propagated_yaw,
            fused_yaw=fused_yaw,
            quality=V1PoseFusionQuality.USED_IMU,
            fallback_reason=None,
            gap_ns=gap_ns,
            timestamp_ns=timestamp_ns,
        )

    def _eligibility_reason(
        self,
        telemetry: V1TelemetryFrame,
        imu_yaw: Optional[float],
        timestamp_ns: int,
    ) -> Optional[str]:
        if not telemetry.imu_validity_known:
            return "imu_validity_unknown"
        if imu_yaw is None:
            return "imu_yaw_missing"
        if telemetry.imu_validity & IMU_VALIDITY_DT_CLAMPED:
            return "dt_clamped"
        if (telemetry.imu_validity & IMU_VALIDITY_REQUIRED) != IMU_VALIDITY_REQUIRED:
            return "imu_not_fresh"
        if not telemetry.imu_init_status_known:
            return "imu_init_status_unknown"
        if telemetry.imu_init_status != MPU6050_INIT_STATUS_OK:
            return "imu_init_failed"
        if timestamp_ns < 0:
            return "invalid_timestamp"
        return None

    def _anchor(
        self,
        pose: V1Pose,
        telemetry: V1TelemetryFrame,
        imu_yaw: float,
        timestamp_ns: int,
    ) -> None:
        self._previous_imu_yaw_rad = imu_yaw
        self._previous_timestamp_ns = timestamp_ns
        self._fused_yaw_rad = wrap_angle_rad(pose.yaw_rad)

    def _fallback_record(
        self,
        pose: Optional[V1Pose],
        telemetry: V1TelemetryFrame,
        imu_yaw: Optional[float],
        gap_ns: Optional[int],
        reason: str,
        timestamp_ns: int,
    ) -> V1PoseFusionRecord:
        if pose is None:
            return self._record(
                pose=None,
                telemetry=telemetry,
                imu_yaw=imu_yaw,
                propagated_yaw=None,
                fused_yaw=None,
                quality=V1PoseFusionQuality.INSUFFICIENT_EVIDENCE,
                fallback_reason=reason,
                gap_ns=gap_ns,
                timestamp_ns=timestamp_ns,
            )
        if (
            self._previous_timestamp_ns is None
            or timestamp_ns > self._previous_timestamp_ns
        ):
            # Camera-only is still a real global yaw observation. Keep it as
            # the next propagation anchor without accepting the IMU sample.
            self._fused_yaw_rad = wrap_angle_rad(pose.yaw_rad)
        return self._record(
            pose=pose,
            telemetry=telemetry,
            imu_yaw=imu_yaw,
            propagated_yaw=None,
            fused_yaw=wrap_angle_rad(pose.yaw_rad),
            quality=V1PoseFusionQuality.CAMERA_ONLY,
            fallback_reason=reason,
            gap_ns=gap_ns,
            timestamp_ns=timestamp_ns,
        )

    def _record(
        self,
        pose: Optional[V1Pose],
        telemetry: V1TelemetryFrame,
        imu_yaw: Optional[float],
        propagated_yaw: Optional[float],
        fused_yaw: Optional[float],
        quality: V1PoseFusionQuality,
        fallback_reason: Optional[str],
        gap_ns: Optional[int],
        timestamp_ns: int,
    ) -> V1PoseFusionRecord:
        return V1PoseFusionRecord(
            timestamp_ns=timestamp_ns,
            raw_pc_recv_ns=telemetry.pc_recv_ns,
            camera_timestamp_ns=pose.t_pc_ns if pose is not None else None,
            camera_x_mm=pose.x_mm if pose is not None else None,
            camera_y_mm=pose.y_mm if pose is not None else None,
            camera_yaw_rad=pose.yaw_rad if pose is not None else None,
            imu_yaw_rad=imu_yaw,
            propagated_yaw_rad=propagated_yaw,
            fused_yaw_rad=fused_yaw,
            quality=quality,
            fallback_reason=fallback_reason,
            imu_validity=telemetry.imu_validity,
            imu_validity_known=telemetry.imu_validity_known,
            imu_init_status=telemetry.imu_init_status,
            imu_init_status_known=telemetry.imu_init_status_known,
            imu_gap_ns=gap_ns,
            imu_sign=self.config.imu_sign,
            correction_gain=self.config.correction_gain,
        )
