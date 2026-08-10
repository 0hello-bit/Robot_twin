"""Bounded offline temporal observation on top of the existing pose tracker.

This module never replaces an AprilTag decode with a decode claim.  During a
short detector gap it may return a separately labelled optical-flow pose
prediction, with explicit quality and gap limits.  It is intended for offline
replay first; the production capture path does not import it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import cv2
import numpy as np


@dataclass(frozen=True)
class OpticalFlowQuadResult:
    """Quality result for tracking one previously decoded quadrilateral."""

    valid: bool
    corners: Optional[np.ndarray]
    tracked_ratio: float
    mean_error_px: Optional[float]
    max_error_px: Optional[float]
    scale_ratio: Optional[float]
    max_displacement_px: Optional[float]
    reason: str


def _as_gray(frame: Any) -> np.ndarray:
    image = np.asarray(frame)
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim != 2 or image.dtype != np.uint8:
        raise ValueError("optical-flow frames must be uint8 grayscale or BGR")
    return np.ascontiguousarray(image)


def _quad_area(corners: np.ndarray) -> float:
    points = np.asarray(corners, dtype=np.float64)
    return abs(float(cv2.contourArea(points.astype(np.float32))))


def _side_lengths(corners: np.ndarray) -> np.ndarray:
    points = np.asarray(corners, dtype=np.float64)
    return np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)


def _invalid_flow(
    reason: str,
    *,
    tracked_ratio: float = 0.0,
    mean_error_px: Optional[float] = None,
    max_error_px: Optional[float] = None,
    scale_ratio: Optional[float] = None,
    max_displacement_px: Optional[float] = None,
) -> OpticalFlowQuadResult:
    return OpticalFlowQuadResult(
        valid=False,
        corners=None,
        tracked_ratio=float(tracked_ratio),
        mean_error_px=mean_error_px,
        max_error_px=max_error_px,
        scale_ratio=scale_ratio,
        max_displacement_px=max_displacement_px,
        reason=reason,
    )


def track_quad_with_optical_flow(
    previous_frame: Any,
    current_frame: Any,
    previous_corners: Any,
    *,
    win_size: tuple[int, int] = (21, 21),
    max_level: int = 3,
    max_error_px: float = 20.0,
    max_scale_delta: float = 0.35,
    max_displacement_px: float = 180.0,
    min_tracked_ratio: float = 1.0,
) -> OpticalFlowQuadResult:
    """Track a decoded four-corner tag with strict geometric checks."""

    previous_gray = _as_gray(previous_frame)
    current_gray = _as_gray(current_frame)
    corners = np.asarray(previous_corners, dtype=np.float32)
    if corners.shape != (4, 2) or not np.isfinite(corners).all():
        raise ValueError("previous_corners must be a finite (4, 2) array")
    if max_error_px <= 0.0 or max_scale_delta <= 0.0:
        raise ValueError("flow quality limits must be positive")
    if max_displacement_px <= 0.0:
        raise ValueError("max_displacement_px must be positive")
    if not 0.0 < min_tracked_ratio <= 1.0:
        raise ValueError("min_tracked_ratio must be within (0, 1]")

    next_points, status, errors = cv2.calcOpticalFlowPyrLK(
        previous_gray,
        current_gray,
        corners.reshape(-1, 1, 2),
        None,
        winSize=win_size,
        maxLevel=int(max_level),
        criteria=(
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            30,
            0.01,
        ),
    )
    if next_points is None or status is None or errors is None:
        return _invalid_flow("insufficient_tracked_corners")

    tracked = status.reshape(-1).astype(bool)
    tracked_ratio = float(np.count_nonzero(tracked)) / 4.0
    if tracked_ratio < min_tracked_ratio:
        return _invalid_flow(
            "insufficient_tracked_corners", tracked_ratio=tracked_ratio
        )

    next_corners = next_points.reshape(4, 2).astype(np.float32)
    error_values = errors.reshape(-1).astype(float)
    valid_errors = error_values[tracked]
    if not np.isfinite(next_corners).all() or not np.isfinite(valid_errors).all():
        return _invalid_flow(
            "invalid_tracked_geometry", tracked_ratio=tracked_ratio
        )
    mean_error = float(np.mean(valid_errors))
    max_error = float(np.max(valid_errors))
    if mean_error > max_error_px or max_error > max_error_px * 2.0:
        return _invalid_flow(
            "flow_error_too_high",
            tracked_ratio=tracked_ratio,
            mean_error_px=mean_error,
            max_error_px=max_error,
        )

    displacements = np.linalg.norm(next_corners - corners, axis=1)
    max_displacement = float(np.max(displacements))
    if max_displacement > max_displacement_px:
        return _invalid_flow(
            "corner_displacement_too_high",
            tracked_ratio=tracked_ratio,
            mean_error_px=mean_error,
            max_error_px=max_error,
            max_displacement_px=max_displacement,
        )

    previous_area = _quad_area(corners)
    current_area = _quad_area(next_corners)
    previous_sides = _side_lengths(corners)
    current_sides = _side_lengths(next_corners)
    if (
        previous_area <= 1.0
        or current_area <= 1.0
        or not np.isfinite(current_sides).all()
        or float(np.min(current_sides)) <= 1.0
        or not cv2.isContourConvex(next_corners.reshape(-1, 1, 2))
    ):
        return _invalid_flow(
            "invalid_tracked_geometry",
            tracked_ratio=tracked_ratio,
            mean_error_px=mean_error,
            max_error_px=max_error,
            max_displacement_px=max_displacement,
        )

    scale_ratio = math.sqrt(current_area / previous_area)
    if not math.isfinite(scale_ratio) or abs(scale_ratio - 1.0) > max_scale_delta:
        return _invalid_flow(
            "scale_change_too_high",
            tracked_ratio=tracked_ratio,
            mean_error_px=mean_error,
            max_error_px=max_error,
            scale_ratio=scale_ratio,
            max_displacement_px=max_displacement,
        )

    return OpticalFlowQuadResult(
        valid=True,
        corners=next_corners,
        tracked_ratio=tracked_ratio,
        mean_error_px=mean_error,
        max_error_px=max_error,
        scale_ratio=scale_ratio,
        max_displacement_px=max_displacement,
        reason="valid",
    )


class TemporalObservationTracker:
    """Wrap an existing PoseTracker with bounded offline flow prediction."""

    def __init__(
        self,
        tracker: Any,
        *,
        max_prediction_gap_frames: int = 2,
        max_flow_error_px: float = 20.0,
        max_scale_delta: float = 0.35,
        max_displacement_px: float = 180.0,
    ) -> None:
        if max_prediction_gap_frames <= 0:
            raise ValueError("max_prediction_gap_frames must be positive")
        if max_flow_error_px <= 0.0:
            raise ValueError("max_flow_error_px must be positive")
        if max_scale_delta <= 0.0:
            raise ValueError("max_scale_delta must be positive")
        if max_displacement_px <= 0.0:
            raise ValueError("max_displacement_px must be positive")
        self._tracker = tracker
        self._max_prediction_gap_frames = int(max_prediction_gap_frames)
        self._max_flow_error_px = float(max_flow_error_px)
        self._max_scale_delta = float(max_scale_delta)
        self._max_displacement_px = float(max_displacement_px)
        self._previous_gray: Optional[np.ndarray] = None
        self._previous_corners: Optional[np.ndarray] = None
        self._prediction_gap_frames = 0
        self._last_predicted_pose: Optional[dict[str, float]] = None

    @staticmethod
    def _wrap_angle(angle_rad: float) -> float:
        return (float(angle_rad) + math.pi) % (2.0 * math.pi) - math.pi

    def process_frame(self, frame: Any, t_pc_ns: Optional[int] = None) -> dict[str, Any]:
        """Return decoded data or a separately labelled bounded prediction."""

        gray = _as_gray(frame)
        pose, diagnostics, raw_corners = (
            self._tracker.track_with_diagnostics_and_geometry(frame, t_pc_ns)
        )
        if pose is not None and raw_corners is not None:
            reacquisition = self._last_predicted_pose is not None
            position_correction = None
            yaw_correction = None
            if reacquisition:
                position_correction = math.hypot(
                    float(pose.x_mm) - self._last_predicted_pose["x_mm"],
                    float(pose.y_mm) - self._last_predicted_pose["y_mm"],
                )
                yaw_correction = self._wrap_angle(
                    float(pose.yaw_rad) - self._last_predicted_pose["yaw_rad"]
                )
            self._previous_gray = gray
            self._previous_corners = np.asarray(raw_corners, dtype=np.float32)
            self._prediction_gap_frames = 0
            self._last_predicted_pose = None
            return {
                "pose": pose,
                "predicted_pose": None,
                "diagnostics": diagnostics,
                "tag_decoded": True,
                "pose_output": True,
                "observation_kind": "decoded",
                "prediction_gap_frames": 0,
                "flow_valid": False,
                "flow_mean_error_px": None,
                "flow_max_error_px": None,
                "flow_scale_ratio": None,
                "reacquisition_correction": reacquisition,
                "reacquisition_position_correction_mm": position_correction,
                "reacquisition_yaw_correction_rad": yaw_correction,
            }

        base = {
            "pose": None,
            "predicted_pose": None,
            "diagnostics": diagnostics,
            "tag_decoded": False,
            "pose_output": False,
            "observation_kind": "missing",
            "prediction_gap_frames": self._prediction_gap_frames + 1,
            "flow_valid": False,
            "flow_mean_error_px": None,
            "flow_max_error_px": None,
            "flow_scale_ratio": None,
            "reacquisition_correction": False,
            "reacquisition_position_correction_mm": None,
            "reacquisition_yaw_correction_rad": None,
        }
        if (
            self._previous_gray is None
            or self._previous_corners is None
            or self._prediction_gap_frames >= self._max_prediction_gap_frames
        ):
            self._last_predicted_pose = None
            base["prediction_gap_frames"] = self._prediction_gap_frames + 1
            return base

        flow = track_quad_with_optical_flow(
            self._previous_gray,
            gray,
            self._previous_corners,
            max_error_px=self._max_flow_error_px,
            max_scale_delta=self._max_scale_delta,
            max_displacement_px=self._max_displacement_px,
        )
        if not flow.valid or flow.corners is None:
            self._last_predicted_pose = None
            return base

        self._previous_gray = gray
        self._previous_corners = flow.corners
        self._prediction_gap_frames += 1
        predicted_pose = self._tracker.project_raw_corners(flow.corners)
        decay = 1.0 - (
            self._prediction_gap_frames
            / float(self._max_prediction_gap_frames + 1)
        )
        predicted_pose["confidence"] = max(
            0.0,
            min(1.0, float(predicted_pose["confidence"]) * decay),
        )
        predicted_pose["source"] = "flow_prediction"
        self._last_predicted_pose = dict(predicted_pose)
        base.update(
            {
                "predicted_pose": predicted_pose,
                "pose_output": True,
                "observation_kind": "flow_prediction",
                "prediction_gap_frames": self._prediction_gap_frames,
                "flow_valid": True,
                "flow_mean_error_px": flow.mean_error_px,
                "flow_max_error_px": flow.max_error_px,
                "flow_scale_ratio": flow.scale_ratio,
                "flow_max_displacement_px": flow.max_displacement_px,
            }
        )
        return base
