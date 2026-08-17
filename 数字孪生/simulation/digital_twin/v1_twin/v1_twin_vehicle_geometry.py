"""Versioned vehicle body geometry derived from an observed AprilTag pose."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


DEFAULT_VEHICLE_BODY_PROFILE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "product"
    / "vehicle_geometry"
    / "vehicle_body_profile_v1.json"
)


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _positive(value: Any, name: str) -> float:
    result = _finite(value, name)
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _point(value: Sequence[Any], name: str) -> tuple[float, float]:
    if len(value) != 2:
        raise ValueError(f"{name} must contain two coordinates")
    return (_finite(value[0], f"{name}[0]"), _finite(value[1], f"{name}[1]"))


@dataclass(frozen=True)
class VehicleBodyProfile:
    profile_id: str
    schema_version: str
    length_mm: float
    width_mm: float
    tag_to_center_forward_mm: float
    tag_to_center_left_mm: float
    source: str
    validation_status: str
    calibration_status: str
    coordinate_frame: str
    source_run_id: Optional[str] = None
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "length_mm", _positive(self.length_mm, "length_mm"))
        object.__setattr__(self, "width_mm", _positive(self.width_mm, "width_mm"))
        object.__setattr__(
            self,
            "tag_to_center_forward_mm",
            _finite(self.tag_to_center_forward_mm, "tag_to_center_forward_mm"),
        )
        object.__setattr__(
            self,
            "tag_to_center_left_mm",
            _finite(self.tag_to_center_left_mm, "tag_to_center_left_mm"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "length_mm": self.length_mm,
            "width_mm": self.width_mm,
            "tag_to_center_forward_mm": self.tag_to_center_forward_mm,
            "tag_to_center_left_mm": self.tag_to_center_left_mm,
            "source": self.source,
            "validation_status": self.validation_status,
            "calibration_status": self.calibration_status,
            "coordinate_frame": self.coordinate_frame,
            "source_run_id": self.source_run_id,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VehicleBodyProfile":
        return cls(**{key: data[key] for key in (
            "profile_id", "schema_version", "length_mm", "width_mm",
            "tag_to_center_forward_mm", "tag_to_center_left_mm", "source",
            "validation_status", "calibration_status", "coordinate_frame",
        )}, source_run_id=data.get("source_run_id"), note=data.get("note", ""))


@dataclass(frozen=True)
class VehicleBodyRectangle:
    anchor_x_mm: float
    anchor_y_mm: float
    center_x_mm: float
    center_y_mm: float
    yaw_rad: float
    length_mm: float
    width_mm: float
    tag_to_center_forward_mm: float
    tag_to_center_left_mm: float
    corners_mm: tuple[tuple[float, float], ...]
    confidence: float
    profile_id: str
    source: str
    validation_status: str
    calibration_status: str
    coordinate_frame: str
    tag_corners_px: Optional[tuple[tuple[float, float], ...]] = None

    def __post_init__(self) -> None:
        for name in (
            "anchor_x_mm", "anchor_y_mm", "center_x_mm", "center_y_mm",
            "yaw_rad", "length_mm", "width_mm", "tag_to_center_forward_mm",
            "tag_to_center_left_mm", "confidence",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.length_mm <= 0 or self.width_mm <= 0:
            raise ValueError("rectangle length and width must be positive")
        if len(self.corners_mm) != 4:
            raise ValueError("corners_mm must contain four corners")
        object.__setattr__(
            self, "corners_mm", tuple(_point(point, "corners_mm") for point in self.corners_mm)
        )
        if self.tag_corners_px is not None:
            if len(self.tag_corners_px) != 4:
                raise ValueError("tag_corners_px must contain four corners")
            object.__setattr__(
                self,
                "tag_corners_px",
                tuple(_point(point, "tag_corners_px") for point in self.tag_corners_px),
            )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "anchor_x_mm": self.anchor_x_mm,
            "anchor_y_mm": self.anchor_y_mm,
            "center_x_mm": self.center_x_mm,
            "center_y_mm": self.center_y_mm,
            "yaw_rad": self.yaw_rad,
            "length_mm": self.length_mm,
            "width_mm": self.width_mm,
            "tag_to_center_forward_mm": self.tag_to_center_forward_mm,
            "tag_to_center_left_mm": self.tag_to_center_left_mm,
            "corners_mm": [list(point) for point in self.corners_mm],
            "confidence": self.confidence,
            "profile_id": self.profile_id,
            "source": self.source,
            "validation_status": self.validation_status,
            "calibration_status": self.calibration_status,
            "coordinate_frame": self.coordinate_frame,
            "tag_corners_px": (
                None if self.tag_corners_px is None
                else [list(point) for point in self.tag_corners_px]
            ),
        }
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VehicleBodyRectangle":
        return cls(
            **{key: data[key] for key in (
                "anchor_x_mm", "anchor_y_mm", "center_x_mm", "center_y_mm",
                "yaw_rad", "length_mm", "width_mm", "tag_to_center_forward_mm",
                "tag_to_center_left_mm", "corners_mm", "confidence", "profile_id",
                "source", "validation_status", "calibration_status", "coordinate_frame",
            )},
            tag_corners_px=data.get("tag_corners_px"),
        )


def _pose_value(pose: Any, name: str) -> Any:
    if isinstance(pose, Mapping):
        return pose[name]
    return getattr(pose, name)


def derive_vehicle_body_rectangle(
    pose: Any,
    profile: VehicleBodyProfile,
    tag_corners_px: Optional[Sequence[Sequence[Any]]] = None,
) -> VehicleBodyRectangle:
    """Derive a body rectangle in the profile's relative plane frame."""
    anchor_x = _finite(_pose_value(pose, "x_mm"), "x_mm")
    anchor_y = _finite(_pose_value(pose, "y_mm"), "y_mm")
    yaw = _finite(_pose_value(pose, "yaw_rad"), "yaw_rad")
    confidence = _finite(_pose_value(pose, "confidence"), "confidence")
    forward = (math.cos(yaw), math.sin(yaw))
    left = (-math.sin(yaw), math.cos(yaw))
    center_x = anchor_x + profile.tag_to_center_forward_mm * forward[0] + profile.tag_to_center_left_mm * left[0]
    center_y = anchor_y + profile.tag_to_center_forward_mm * forward[1] + profile.tag_to_center_left_mm * left[1]
    half_length = profile.length_mm / 2.0
    half_width = profile.width_mm / 2.0

    def corner(length_sign: float, left_sign: float) -> tuple[float, float]:
        return (
            center_x + length_sign * half_length * forward[0] + left_sign * half_width * left[0],
            center_y + length_sign * half_length * forward[1] + left_sign * half_width * left[1],
        )

    corners = (corner(1, 1), corner(1, -1), corner(-1, -1), corner(-1, 1))
    normalized_tag_corners = (
        None if tag_corners_px is None
        else tuple(_point(point, "tag_corners_px") for point in tag_corners_px)
    )
    return VehicleBodyRectangle(
        anchor_x_mm=anchor_x,
        anchor_y_mm=anchor_y,
        center_x_mm=center_x,
        center_y_mm=center_y,
        yaw_rad=yaw,
        length_mm=profile.length_mm,
        width_mm=profile.width_mm,
        tag_to_center_forward_mm=profile.tag_to_center_forward_mm,
        tag_to_center_left_mm=profile.tag_to_center_left_mm,
        corners_mm=corners,
        confidence=confidence,
        profile_id=profile.profile_id,
        source=profile.source,
        validation_status=profile.validation_status,
        calibration_status=profile.calibration_status,
        coordinate_frame=profile.coordinate_frame,
        tag_corners_px=normalized_tag_corners,
    )


def load_default_vehicle_body_profile() -> VehicleBodyProfile:
    with DEFAULT_VEHICLE_BODY_PROFILE_PATH.open("r", encoding="utf-8") as handle:
        return VehicleBodyProfile.from_dict(json.load(handle))
