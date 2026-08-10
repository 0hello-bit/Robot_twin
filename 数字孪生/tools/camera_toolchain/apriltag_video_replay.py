"""Replay one retained 1080p video through bounded AprilTag candidates.

The replay is deliberately file-only.  It reuses the production PoseTracker,
observation profiles, calibration loader, and detector-parameter builder, but
never opens a camera, creates a socket, or controls the vehicle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence

import cv2
import numpy as np

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "simulation" / "digital_twin"))

try:
    from apriltag_diagnostic_matrix import _percentile
    from apriltag_parameter_matrix import (
        PARAMETER_VARIANTS,
        build_detector_parameters,
    )
    from capture_sync_run import (
        _load_calibration,
        _build_recovery_detector_parameters,
        create_pose_tracker,
        resolve_observation_profile,
    )
    from temporal_observation import TemporalObservationTracker
except ImportError:  # pragma: no cover - package import fallback
    from .apriltag_diagnostic_matrix import _percentile
    from .apriltag_parameter_matrix import (
        PARAMETER_VARIANTS,
        build_detector_parameters,
    )
    from .capture_sync_run import (
        _load_calibration,
        _build_recovery_detector_parameters,
        create_pose_tracker,
        resolve_observation_profile,
    )
    from .temporal_observation import TemporalObservationTracker

try:
    from pupil_apriltags import Detector as PupilAprilTagDetector
    PUPIL_IMPORT_ERROR = None
except (ImportError, OSError) as exc:  # pragma: no cover - environment dependent
    PupilAprilTagDetector = None
    PUPIL_IMPORT_ERROR = exc

from v1_twin.v1_twin_schema import V1Pose


DEFAULT_CALIBRATION_MANIFEST = (
    WORKSPACE_ROOT
    / "simulation"
    / "digital_twin"
    / "data"
    / "product"
    / "capture_manifests"
    / "c960_r3_1080p_exploratory_20260809"
    / "manifest.json"
)
SUPPORTED_FPS = 30.0
FPS_TOLERANCE = 0.5
MAX_PROCESSING_P95_MS = 33.333333
MIN_DETECTION_RATIO_IMPROVEMENT = 0.05
MAX_CANDIDATE_P95_FACTOR = 1.10
_SAFE_CANDIDATE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
TEMPORAL_OBSERVATION_CONFIGS = MappingProxyType({
    "none": None,
    "flow_short2": MappingProxyType({
        "max_prediction_gap_frames": 2,
    }),
    "flow_long60": MappingProxyType({
        "max_prediction_gap_frames": 60,
    }),
})
TEMPORAL_OBSERVATION_PROFILES = frozenset(TEMPORAL_OBSERVATION_CONFIGS)
REPLAY_PARAMETER_VARIANTS = frozenset(
    tuple(PARAMETER_VARIANTS)
    + ("pupil_roi", "fast_recovery", "fast_recovery_wide")
)
PUPIL_ROI_CONFIG = {
    "detector_backend": "pupil_apriltags",
    "families": "tag36h11",
    "nthreads": 4,
    "quad_decimate": 1.5,
    "roi_policy": "production_roi_then_one_full_frame_fallback",
}


def resolve_temporal_observation_config(
    name: str,
) -> Optional[dict[str, int]]:
    """Return a bounded offline temporal-observation configuration."""

    profile_name = str(name).strip()
    try:
        config = TEMPORAL_OBSERVATION_CONFIGS[profile_name]
    except KeyError:
        raise ValueError(
            "unsupported temporal observation profile: {0}".format(name)
        )
    if config is None:
        return None
    return dict(config)


def _build_replay_detector_parameters(parameter_variant: str):
    """Build the bounded detector parameters for one replay candidate."""
    if parameter_variant in {"fast_recovery", "fast_recovery_wide"}:
        return _build_recovery_detector_parameters(parameter_variant)
    return build_detector_parameters(parameter_variant)


def _float_percentile(values: Sequence[float], percentile: float) -> float:
    """Return a percentile without truncating non-time quantities."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("at least one value is required")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(percentile)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_video_path(video_path: str | Path) -> Path:
    if isinstance(video_path, int):
        raise ValueError("video file path is required; camera index is not allowed")
    raw = str(video_path).strip()
    if raw.isdigit():
        raise ValueError("video file path is required; camera index is not allowed")
    path = Path(raw).resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _validate_calibration_manifest(
    calibration_manifest: str | Path | None,
) -> Path:
    path = Path(calibration_manifest or DEFAULT_CALIBRATION_MANIFEST).resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _validate_max_frames(max_frames: int | None) -> Optional[int]:
    if max_frames is None:
        return None
    value = int(max_frames)
    if value <= 0:
        raise ValueError("max_frames must be positive")
    return value


def _validate_candidate(candidate: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate must be a mapping")
    name = str(candidate.get("name", "")).strip()
    profile = str(candidate.get("observation_profile", "")).strip()
    variant = str(candidate.get("parameter_variant", "")).strip()
    temporal = str(candidate.get("temporal_observation", "none")).strip()
    if not name or not _SAFE_CANDIDATE_NAME.fullmatch(name):
        raise ValueError("candidate name must contain only ASCII letters, digits, . _ -")
    resolve_observation_profile(profile)
    if variant not in REPLAY_PARAMETER_VARIANTS:
        raise ValueError("unsupported parameter variant: {0}".format(variant))
    if temporal not in TEMPORAL_OBSERVATION_PROFILES:
        raise ValueError(
            "unsupported temporal observation profile: {0}".format(temporal)
        )
    return {
        "name": name,
        "observation_profile": profile,
        "parameter_variant": variant,
        "temporal_observation": temporal,
    }


def _validate_candidates(
    candidates: Sequence[Mapping[str, str]],
) -> tuple[dict[str, str], ...]:
    if not candidates:
        raise ValueError("at least one candidate is required")
    normalized = tuple(_validate_candidate(candidate) for candidate in candidates)
    names = [candidate["name"] for candidate in normalized]
    if len(set(names)) != len(names):
        raise ValueError("candidate names must be unique")
    if not any(
        candidate["observation_profile"] == "production"
        and candidate["parameter_variant"] == "default"
        and candidate["temporal_observation"] == "none"
        for candidate in normalized
    ):
        raise ValueError("production/default baseline candidate is required")
    return normalized


class _PupilRoiTracker:
    """Offline-only Pupil detector using the production ROI geometry."""

    def __init__(self, projection_tracker, target_id):
        if PupilAprilTagDetector is None:
            raise RuntimeError(
                "pupil_apriltags dependency unavailable: {0}".format(
                    PUPIL_IMPORT_ERROR
                )
            )
        self._projection_tracker = projection_tracker
        self._target_id = int(target_id)
        self._detector = PupilAprilTagDetector(
            families=PUPIL_ROI_CONFIG["families"],
            nthreads=PUPIL_ROI_CONFIG["nthreads"],
            quad_decimate=PUPIL_ROI_CONFIG["quad_decimate"],
        )

    def _detect_region(self, gray, offset_x, offset_y):
        detections = self._detector.detect(np.ascontiguousarray(gray))
        for detection in detections:
            if int(detection.tag_id) != self._target_id:
                continue
            corners = np.asarray(detection.corners, dtype=float)
            if corners.shape != (4, 2) or not np.isfinite(corners).all():
                continue
            corners = corners + np.asarray(
                [float(offset_x), float(offset_y)], dtype=float
            )
            return corners, len(detections)
        return None, len(detections)

    def _pose_from_corners(self, corners, t_pc_ns):
        projection = self._projection_tracker.project_raw_corners(corners)
        timestamp = (
            int(t_pc_ns)
            if t_pc_ns is not None
            else time.monotonic_ns()
        )
        return V1Pose(
            x_mm=projection["x_mm"],
            y_mm=projection["y_mm"],
            yaw_rad=projection["yaw_rad"],
            confidence=projection["confidence"],
            t_pc_ns=timestamp,
            source="camera",
        )

    def _update_production_roi_state(self, corners):
        self._projection_tracker._last_raw_center = np.asarray(
            corners, dtype=float
        ).mean(axis=0)
        self._projection_tracker._last_raw_side_px = float(
            np.linalg.norm(np.asarray(corners, dtype=float)[0]
                           - np.asarray(corners, dtype=float)[1])
        )

    def _detect_with_diagnostics(self, frame):
        started_ns = time.perf_counter_ns()
        gray = frame
        if getattr(frame, "ndim", 0) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if getattr(gray, "ndim", 0) != 2:
            raise ValueError("Pupil replay requires a grayscale or BGR frame")

        roi_bounds = self._projection_tracker._roi_bounds(gray)
        search_regions = []
        detected_corners = None
        detection_count = 0
        fallback_used = False
        error = None
        try:
            if roi_bounds is not None:
                search_regions.append("roi")
                x0, y0, x1, y1 = roi_bounds
                detected_corners, detection_count = self._detect_region(
                    gray[y0:y1, x0:x1], x0, y0
                )
            if detected_corners is None:
                if roi_bounds is not None:
                    fallback_used = True
                    search_regions.append("full_frame")
                else:
                    search_regions.append("full_frame")
                detected_corners, detection_count = self._detect_region(
                    gray, 0, 0
                )
        except BaseException as exc:  # noqa: BLE001 - report replay errors
            error = repr(exc)

        if detected_corners is not None:
            self._update_production_roi_state(detected_corners)
            side_px = float(np.linalg.norm(
                detected_corners[0] - detected_corners[1]
            ))
            diagnostics = {
                "detector_backend": PUPIL_ROI_CONFIG["detector_backend"],
                "attempted_scales": [
                    float(PUPIL_ROI_CONFIG["quad_decimate"])
                ],
                "matched_scale": None,
                "tag_side_px": side_px,
                "failure_reason": None,
                "rejected_candidate_count": 0,
                "rejected_candidate_counts": [],
                "detect_elapsed_ns": time.perf_counter_ns() - started_ns,
                "search_mode": (
                    "roi_then_full" if fallback_used
                    else ("roi" if roi_bounds is not None else "full_frame")
                ),
                "search_regions": search_regions,
                "roi_bounds": (
                    list(roi_bounds) if roi_bounds is not None else None
                ),
                "full_frame_fallback": fallback_used,
                "pupil_detection_count": int(detection_count),
                "pupil_quad_decimate": float(
                    PUPIL_ROI_CONFIG["quad_decimate"]
                ),
            }
            return detected_corners, diagnostics

        diagnostics = {
            "detector_backend": PUPIL_ROI_CONFIG["detector_backend"],
            "attempted_scales": [float(PUPIL_ROI_CONFIG["quad_decimate"])],
            "matched_scale": None,
            "tag_side_px": None,
            "failure_reason": (
                "pupil_detector_error" if error
                else "target_tag_not_found"
            ),
            "rejected_candidate_count": 0,
            "rejected_candidate_counts": [],
            "detect_elapsed_ns": time.perf_counter_ns() - started_ns,
            "search_mode": (
                "roi_then_full" if fallback_used
                else ("roi" if roi_bounds is not None else "full_frame")
            ),
            "search_regions": search_regions,
            "roi_bounds": (
                list(roi_bounds) if roi_bounds is not None else None
            ),
            "full_frame_fallback": fallback_used,
            "pupil_detection_count": int(detection_count),
            "pupil_quad_decimate": float(PUPIL_ROI_CONFIG["quad_decimate"]),
        }
        if error:
            diagnostics["error"] = error
        return None, diagnostics

    def track_with_diagnostics_and_geometry(self, frame, t_pc_ns=None):
        corners, diagnostics = self._detect_with_diagnostics(frame)
        if corners is None:
            return None, diagnostics, None
        return (
            self._pose_from_corners(corners, t_pc_ns),
            diagnostics,
            np.asarray(corners, dtype=float),
        )

    def track_with_diagnostics(self, frame, t_pc_ns=None):
        pose, diagnostics, _corners = self.track_with_diagnostics_and_geometry(
            frame, t_pc_ns
        )
        return pose, diagnostics


def _fourcc_to_string(value: float) -> str:
    number = int(round(float(value)))
    if number <= 0:
        return ""
    chars = "".join(chr((number >> (8 * index)) & 0xFF) for index in range(4))
    return chars if all(32 <= ord(char) <= 126 for char in chars) else ""


def _open_video(path: Path) -> tuple[cv2.VideoCapture, dict[str, Any]]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError("unable to open video file: {0}".format(path))
    width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    reported_frame_count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    fourcc = _fourcc_to_string(capture.get(cv2.CAP_PROP_FOURCC))
    if (width, height) != (1920, 1080):
        capture.release()
        raise ValueError(
            "video must be 1920x1080, got {0}x{1}".format(width, height)
        )
    if abs(fps - SUPPORTED_FPS) > FPS_TOLERANCE:
        capture.release()
        raise ValueError("video must be 30fps, got {0}".format(fps))
    if fourcc != "MJPG":
        capture.release()
        raise ValueError("video must report MJPG FourCC, got {0!r}".format(fourcc))
    return capture, {
        "path": str(path),
        "sha256": _sha256(path),
        "width": width,
        "height": height,
        "fps": fps,
        "fourcc": fourcc,
        "reported_frame_count": reported_frame_count,
        "decoded_frame_count": 0,
        "frame_count_matches_reported": None,
        "file_size_bytes": path.stat().st_size,
    }


def _trace_record(
    frame_index: int,
    detected: bool,
    detect_elapsed_ns: int,
    diagnostics: Mapping[str, Any],
    temporal: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    roi_bounds = diagnostics.get("roi_bounds")
    if roi_bounds is not None:
        roi_bounds = [int(value) for value in roi_bounds]
    attempted_scales = [
        float(value) for value in diagnostics.get("attempted_scales", [])
    ]
    matched_scale = diagnostics.get("matched_scale")
    tag_side_px = diagnostics.get("tag_side_px")
    temporal = temporal or {}
    tag_decoded = bool(temporal.get("tag_decoded", detected))
    pose_output = bool(temporal.get("pose_output", detected))
    return {
        "frame_index": int(frame_index),
        "detected": bool(detected),
        "detector_backend": diagnostics.get("detector_backend", "opencv_aruco"),
        "recovery_policy": diagnostics.get(
            "recovery_policy", "production"
        ),
        "detect_elapsed_ns": int(detect_elapsed_ns),
        "failure_reason": (
            None if detected else diagnostics.get("failure_reason")
        ),
        "error": diagnostics.get("error"),
        "rejected_candidate_count": int(
            diagnostics.get("rejected_candidate_count", 0)
        ),
        "attempted_scales": attempted_scales,
        "matched_scale": None if matched_scale is None else float(matched_scale),
        "search_mode": diagnostics.get("search_mode"),
        "search_regions": list(diagnostics.get("search_regions", [])),
        "roi_bounds": roi_bounds,
        "full_frame_fallback": bool(
            diagnostics.get("full_frame_fallback", False)
        ),
        "tag_side_px": None if tag_side_px is None else float(tag_side_px),
        "tag_decoded": tag_decoded,
        "pose_output": pose_output,
        "observation_kind": temporal.get(
            "observation_kind", "decoded" if detected else "missing"
        ),
        "prediction_gap_frames": int(
            temporal.get("prediction_gap_frames", 0)
        ),
        "flow_valid": bool(temporal.get("flow_valid", False)),
        "flow_mean_error_px": temporal.get("flow_mean_error_px"),
        "flow_max_error_px": temporal.get("flow_max_error_px"),
        "flow_scale_ratio": temporal.get("flow_scale_ratio"),
        "flow_max_displacement_px": temporal.get("flow_max_displacement_px"),
        "predicted_pose": temporal.get("predicted_pose"),
        "reacquisition_correction": bool(
            temporal.get("reacquisition_correction", False)
        ),
        "reacquisition_position_correction_mm": temporal.get(
            "reacquisition_position_correction_mm"
        ),
        "reacquisition_yaw_correction_rad": temporal.get(
            "reacquisition_yaw_correction_rad"
        ),
    }


def summarize_trace(trace: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize a frame trace without confusing gaps and missed frames."""

    if not trace:
        raise ValueError("at least one trace record is required")
    ordered = sorted(trace, key=lambda record: int(record["frame_index"]))
    decoded_count = len(ordered)
    decoded_indices = [
        int(record["frame_index"])
        for record in ordered
        if bool(record.get("tag_decoded", record.get("detected")))
    ]
    pose_indices = [
        int(record["frame_index"])
        for record in ordered
        if bool(record.get("pose_output", record.get("detected")))
    ]
    intervals = [
        right - left
        for left, right in zip(decoded_indices, decoded_indices[1:])
    ]
    max_missed = 0
    current_missed = 0
    max_pose_missed = 0
    current_pose_missed = 0
    for record in ordered:
        if bool(record.get("tag_decoded", record.get("detected"))):
            current_missed = 0
        else:
            current_missed += 1
            max_missed = max(max_missed, current_missed)
        if bool(record.get("pose_output", record.get("detected"))):
            current_pose_missed = 0
        else:
            current_pose_missed += 1
            max_pose_missed = max(max_pose_missed, current_pose_missed)
    elapsed = [int(record["detect_elapsed_ns"]) for record in ordered]
    failures = Counter(
        str(record.get("failure_reason"))
        for record in ordered
        if not bool(record.get("detected")) and record.get("failure_reason")
    )
    errors = [
        str(record["error"])
        for record in ordered
        if record.get("error")
    ]
    flow_errors = [
        float(record["flow_mean_error_px"])
        for record in ordered
        if record.get("flow_valid")
        and record.get("flow_mean_error_px") is not None
    ]
    flow_scales = [
        float(record["flow_scale_ratio"])
        for record in ordered
        if record.get("flow_valid")
        and record.get("flow_scale_ratio") is not None
    ]
    return {
        "decoded_frame_count": decoded_count,
        "detected_count": len(decoded_indices),
        "detection_ratio": len(decoded_indices) / float(decoded_count),
        "max_detection_interval_frames": float(max(intervals, default=0.0)),
        "max_consecutive_missed_frames": int(max_missed),
        "tag_decode_ratio": len(decoded_indices) / float(decoded_count),
        "tag_decode_count": len(decoded_indices),
        "pose_output_count": len(pose_indices),
        "pose_output_ratio": len(pose_indices) / float(decoded_count),
        "max_pose_output_interval_frames": float(
            max(
                (
                    right - left
                    for left, right in zip(pose_indices, pose_indices[1:])
                ),
                default=0.0,
            )
        ),
        "max_consecutive_pose_output_missed_frames": int(max_pose_missed),
        "predicted_pose_count": sum(
            1
            for record in ordered
            if record.get("observation_kind") == "flow_prediction"
        ),
        "max_prediction_gap_frames": max(
            (
                int(record.get("prediction_gap_frames", 0))
                for record in ordered
                if record.get("observation_kind") == "flow_prediction"
            ),
            default=0,
        ),
        "reacquisition_correction_count": sum(
            1 for record in ordered if record.get("reacquisition_correction")
        ),
        "flow_valid_count": sum(
            1 for record in ordered if record.get("flow_valid")
        ),
        "flow_mean_error_p95_px": _float_percentile(flow_errors, 0.95)
        if flow_errors
        else None,
        "flow_scale_ratio_min": min(flow_scales) if flow_scales else None,
        "flow_scale_ratio_max": max(flow_scales) if flow_scales else None,
        "reacquisition_position_correction_p95_mm": _float_percentile(
            [
                float(record["reacquisition_position_correction_mm"])
                for record in ordered
                if record.get("reacquisition_position_correction_mm")
                is not None
            ],
            0.95,
        )
        if any(
            record.get("reacquisition_position_correction_mm") is not None
            for record in ordered
        )
        else None,
        "reacquisition_yaw_correction_p95_rad": _float_percentile(
            [
                abs(float(record["reacquisition_yaw_correction_rad"]))
                for record in ordered
                if record.get("reacquisition_yaw_correction_rad")
                is not None
            ],
            0.95,
        )
        if any(
            record.get("reacquisition_yaw_correction_rad") is not None
            for record in ordered
        )
        else None,
        "processing_p95_ms": float(_percentile(elapsed, 0.95)) / 1_000_000.0,
        "rejected_candidate_total": sum(
            int(record.get("rejected_candidate_count", 0)) for record in ordered
        ),
        "failure_reason_counts": dict(sorted(failures.items())),
        "errors": errors,
    }


def _build_replay_report(
    *,
    video: dict[str, Any],
    candidate: dict[str, str],
    summary: dict[str, Any],
    trace: list[dict[str, Any]],
    calibration: dict[str, Any],
    max_frames: int | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": "V1B3AprilTagVideoReplay",
        "source": "1080P_VIDEO_REPLAY",
        "evidence_status": "INSUFFICIENT_EVIDENCE",
        "timebase": "DERIVED_FROM_VIDEO_FPS",
        "video": dict(video),
        "candidate": dict(candidate),
        "calibration": dict(calibration),
        "max_frames": max_frames,
        "summary": dict(summary),
        "trace": trace,
    }


def _pupil_candidate_metadata(profile_name, temporal_observation, target_id=0):
    candidate = {
        "name": "replay",
        "observation_profile": profile_name,
        "parameter_variant": "pupil_roi",
        "temporal_observation": temporal_observation,
    }
    candidate.update(PUPIL_ROI_CONFIG)
    candidate["target_id"] = int(target_id)
    candidate["evidence_status"] = "INSUFFICIENT_EVIDENCE"
    return candidate


def _pupil_unavailable_report(
    path, profile_name, temporal_observation, target_id, calibration, error,
    max_frames
):
    capture, video = _open_video(path)
    capture.release()
    video["decoded_frame_count"] = 0
    summary = {
        "decoded_frame_count": 0,
        "detected_count": 0,
        "detection_ratio": 0.0,
        "max_detection_interval_frames": 0.0,
        "max_consecutive_missed_frames": 0,
        "tag_decode_ratio": 0.0,
        "tag_decode_count": 0,
        "pose_output_count": 0,
        "pose_output_ratio": 0.0,
        "max_pose_output_interval_frames": 0.0,
        "max_consecutive_pose_output_missed_frames": 0,
        "predicted_pose_count": 0,
        "max_prediction_gap_frames": 0,
        "reacquisition_correction_count": 0,
        "flow_valid_count": 0,
        "flow_mean_error_p95_px": None,
        "flow_scale_ratio_min": None,
        "flow_scale_ratio_max": None,
        "reacquisition_position_correction_p95_mm": None,
        "reacquisition_yaw_correction_p95_rad": None,
        "processing_p95_ms": 0.0,
        "rejected_candidate_total": 0,
        "failure_reason_counts": {"pupil_dependency_unavailable": 0},
        "errors": [str(error)],
    }
    return _build_replay_report(
        video=video,
        candidate=_pupil_candidate_metadata(
            profile_name, temporal_observation, target_id
        ),
        summary=summary,
        trace=[],
        calibration=calibration,
        max_frames=max_frames,
    )


def replay_video(
    video_path: str | Path,
    *,
    observation_profile: str = "production",
    parameter_variant: str = "default",
    temporal_observation: str = "none",
    target_id: int = 0,
    max_frames: int | None = None,
    calibration_manifest: str | Path | None = None,
) -> dict[str, Any]:
    """Replay one local video through one fresh stateful tracker."""

    profile = resolve_observation_profile(observation_profile)
    if parameter_variant not in REPLAY_PARAMETER_VARIANTS:
        raise ValueError(
            "unsupported parameter variant: {0}".format(parameter_variant)
        )
    temporal_config = resolve_temporal_observation_config(temporal_observation)
    selected_max_frames = _validate_max_frames(max_frames)
    path = _validate_video_path(video_path)
    manifest_path = _validate_calibration_manifest(calibration_manifest)
    calib, homography, calibration_evidence = _load_calibration(manifest_path)
    pupil_candidate = parameter_variant == "pupil_roi"
    fast_recovery_candidate = parameter_variant in {
        "fast_recovery", "fast_recovery_wide",
    }
    recovery_policy = (
        parameter_variant if fast_recovery_candidate else "production"
    )
    if pupil_candidate and PupilAprilTagDetector is None:
        return _pupil_unavailable_report(
            path,
            profile["name"],
            temporal_observation,
            int(target_id),
            calibration_evidence,
            RuntimeError(
                "pupil_apriltags dependency unavailable: {0}".format(
                    PUPIL_IMPORT_ERROR
                )
            ),
            selected_max_frames,
        )
    if pupil_candidate:
        projection_tracker = create_pose_tracker(
            calib,
            homography,
            profile["name"],
            detector_parameters=build_detector_parameters("default"),
            tag_id=int(target_id),
        )
        tracker = _PupilRoiTracker(projection_tracker, target_id)
    else:
        detector_parameters = _build_replay_detector_parameters(
            parameter_variant
        )
        tracker = create_pose_tracker(
            calib,
            homography,
            profile["name"],
            detector_parameters=detector_parameters,
            tag_id=int(target_id),
            recovery_policy=recovery_policy,
            offline=True,
        )
    temporal_tracker = (
        TemporalObservationTracker(tracker, **temporal_config)
        if temporal_config is not None
        else None
    )

    capture, video = _open_video(path)
    trace: list[dict[str, Any]] = []
    try:
        while selected_max_frames is None or len(trace) < selected_max_frames:
            decoded, frame = capture.read()
            if not decoded:
                break
            if frame is None or frame.shape[:2] != (1080, 1920):
                raise ValueError("decoded video frame is not 1920x1080")
            frame_index = len(trace)
            derived_time_ns = int(
                round((frame_index + 1) * 1_000_000_000.0 / video["fps"])
            )
            started_ns = time.perf_counter_ns()
            temporal_result = None
            if temporal_tracker is None:
                pose, diagnostics = tracker.track_with_diagnostics(
                    frame, t_pc_ns=derived_time_ns
                )
            else:
                temporal_result = temporal_tracker.process_frame(
                    frame, t_pc_ns=derived_time_ns
                )
                pose = temporal_result["pose"]
                diagnostics = temporal_result["diagnostics"]
            detect_elapsed_ns = time.perf_counter_ns() - started_ns
            trace.append(_trace_record(
                frame_index,
                pose is not None,
                detect_elapsed_ns,
                diagnostics,
                temporal_result,
            ))
    finally:
        capture.release()

    video["decoded_frame_count"] = len(trace)
    reported_frame_count = int(video["reported_frame_count"])
    if reported_frame_count > 0:
        video["frame_count_matches_reported"] = (
            len(trace) == reported_frame_count
        )
        if selected_max_frames is None and not video["frame_count_matches_reported"]:
            raise ValueError(
                "decoded frame count {0} does not match reported count {1}".format(
                    len(trace), reported_frame_count
                )
            )
    else:
        video["frame_count_matches_reported"] = None
    if not trace:
        raise ValueError("video contains no decodable frames")
    summary = summarize_trace(trace)
    summary["replay_complete"] = (
        video["frame_count_matches_reported"] is True
    )
    return _build_replay_report(
        video=video,
        candidate=(
            _pupil_candidate_metadata(
                profile["name"], temporal_observation, target_id
            )
            if pupil_candidate
            else {
                "name": "replay",
                "observation_profile": profile["name"],
                "parameter_variant": parameter_variant,
                "temporal_observation": temporal_observation,
                "detector_backend": "opencv_aruco",
                "recovery_policy": recovery_policy,
            }
        ),
        summary=summary,
        trace=trace,
        calibration=calibration_evidence,
        max_frames=selected_max_frames,
    )


def evaluate_candidate_selection(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply the fixed offline rule to one candidate and its baseline."""

    baseline_ratio = float(baseline["detection_ratio"])
    candidate_ratio = float(candidate["detection_ratio"])
    baseline_gap = float(baseline["max_detection_interval_frames"])
    candidate_gap = float(candidate["max_detection_interval_frames"])
    baseline_missed = int(baseline["max_consecutive_missed_frames"])
    candidate_missed = int(candidate["max_consecutive_missed_frames"])
    baseline_p95 = float(baseline["processing_p95_ms"])
    candidate_p95 = float(candidate["processing_p95_ms"])
    checks = {
        "detection_ratio_improvement": candidate_ratio - baseline_ratio
        >= MIN_DETECTION_RATIO_IMPROVEMENT,
        "detection_ratio_meets_b3": candidate_ratio >= 0.95,
        "gap_not_worse": candidate_gap <= baseline_gap,
        "max_detection_interval_meets_b3": candidate_gap <= 2.0,
        "missed_frames_not_worse": candidate_missed <= baseline_missed,
        "gap_or_missed_strictly_better": (
            candidate_gap < baseline_gap or candidate_missed < baseline_missed
        ),
        "processing_p95_within_baseline_factor": candidate_p95
        <= baseline_p95 * MAX_CANDIDATE_P95_FACTOR,
        "processing_p95_within_frame_budget": candidate_p95
        <= MAX_PROCESSING_P95_MS,
        "candidate_has_no_errors": not candidate.get("errors"),
        "candidate_replay_complete": bool(
            candidate.get("replay_complete", True)
        ),
    }
    qualified = all(checks.values())
    return {
        "verdict": (
            "QUALIFIED_FOR_ONE_REAL_AB" if qualified else "NOT_JUSTIFIED"
        ),
        "checks": checks,
        "reason": (
            "all offline candidate thresholds met"
            if qualified
            else "candidate did not meet every offline threshold"
        ),
    }


def compare_video_candidates(
    video_path: str | Path,
    *,
    candidates: Sequence[Mapping[str, str]],
    target_id: int = 0,
    max_frames: int | None = None,
    calibration_manifest: str | Path | None = None,
    trace_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run every candidate on one video and return a JSON-safe report."""

    path = _validate_video_path(video_path)
    selected = _validate_candidates(candidates)
    selected_max_frames = _validate_max_frames(max_frames)
    manifest_path = _validate_calibration_manifest(calibration_manifest)
    if trace_dir is not None:
        trace_root = Path(trace_dir).resolve()
        trace_root.mkdir(parents=True, exist_ok=True)
    else:
        trace_root = None

    runs: list[dict[str, Any]] = []
    for candidate in selected:
        run = replay_video(
            path,
            observation_profile=candidate["observation_profile"],
            parameter_variant=candidate["parameter_variant"],
            temporal_observation=candidate["temporal_observation"],
            target_id=target_id,
            max_frames=selected_max_frames,
            calibration_manifest=manifest_path,
        )
        replay_candidate = dict(run["candidate"])
        replay_candidate.update(candidate)
        run["candidate"] = replay_candidate
        if trace_root is not None:
            trace_path = trace_root / (
                "{0}_{1}.jsonl".format(
                    candidate["name"], run["video"]["sha256"][:12]
                )
            )
            _write_trace(trace_path, run["trace"])
            run["trace_path"] = str(trace_path)
        runs.append(run)

    frame_counts = {int(run["summary"]["decoded_frame_count"]) for run in runs}
    video_hashes = {str(run["video"]["sha256"]) for run in runs}
    comparison_valid = len(frame_counts) == 1 and len(video_hashes) == 1
    summaries = []
    for run in runs:
        summary = dict(run["summary"])
        summary.update(run["candidate"])
        summaries.append(summary)

    baseline_run = next(
        (
            run
            for run in runs
            if run["candidate"]["observation_profile"] == "production"
            and run["candidate"]["parameter_variant"] == "default"
            and run["candidate"]["temporal_observation"] == "none"
        ),
        None,
    )
    if not comparison_valid:
        selection = {
            "verdict": "INVALID_COMPARISON",
            "reason": "candidate runs did not decode the same video frame stream",
        }
    elif baseline_run is None:
        selection = {
            "verdict": "NOT_JUSTIFIED",
            "reason": "production/default baseline is missing",
        }
    else:
        qualified = []
        for run in runs:
            if run is baseline_run:
                continue
            decision = evaluate_candidate_selection(
                baseline_run["summary"], run["summary"]
            )
            run["selection"] = decision
            if decision["verdict"] == "QUALIFIED_FOR_ONE_REAL_AB":
                qualified.append(run["candidate"]["name"])
        selection = {
            "verdict": (
                "QUALIFIED_FOR_ONE_REAL_AB" if qualified else "NOT_JUSTIFIED"
            ),
            "candidate": qualified[0] if qualified else None,
            "qualified_candidates": qualified,
            "reason": (
                "one or more candidates met all offline thresholds"
                if qualified
                else "candidate did not meet the offline thresholds"
            ),
        }

    return {
        "schema_version": 1,
        "type": "V1B3AprilTagVideoReplay",
        "source": "1080P_VIDEO_REPLAY",
        "evidence_status": "INSUFFICIENT_EVIDENCE",
        "timebase": "DERIVED_FROM_VIDEO_FPS",
        "videos": [dict(runs[0]["video"])],
        "calibration": dict(runs[0]["calibration"]),
        "candidates": runs,
        "summaries": summaries,
        "comparison_valid": comparison_valid,
        "selection": selection,
    }


def _write_trace(path: Path, trace: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise ValueError("refusing to overwrite existing trace: {0}".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for record in trace:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    if path.exists():
        raise ValueError("refusing to overwrite existing report: {0}".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=".{0}.".format(path.name), suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise ValueError("refusing to overwrite existing report: {0}".format(path))
        os.replace(temp_name, path)
    except BaseException:
        try:
            Path(temp_name).unlink()
        except FileNotFoundError:
            pass
        raise


def _parse_candidate_spec(spec: str) -> dict[str, str]:
    values = str(spec).split(":")
    if len(values) not in (3, 4):
        raise ValueError(
            "candidate must use name:observation_profile:parameter_variant[:temporal_observation]"
        )
    return {
        "name": values[0],
        "observation_profile": values[1],
        "parameter_variant": values[2],
        "temporal_observation": values[3] if len(values) == 4 else "none",
    }


def _public_report(report: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(report)
    candidates = []
    for run in report["candidates"]:
        candidate = dict(run["candidate"])
        if "trace_path" in run:
            candidate["trace_path"] = run["trace_path"]
        if "selection" in run:
            candidate["selection"] = run["selection"]
        candidates.append(candidate)
    output["candidates"] = candidates
    return output


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay one 1080p MJPG video through bounded AprilTag candidates."
    )
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--candidate",
        action="append",
        dest="candidate_specs",
        help="name:observation_profile:parameter_variant",
    )
    parser.add_argument("--target-id", type=int, default=0)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--calibration-manifest")
    args = parser.parse_args(argv)

    try:
        video_path = _validate_video_path(args.video)
        output_path = Path(args.output).resolve()
        if output_path.exists():
            raise ValueError("refusing to overwrite existing report: {0}".format(output_path))
        manifest_path = _validate_calibration_manifest(args.calibration_manifest)
        candidates = tuple(
            _parse_candidate_spec(spec) for spec in (args.candidate_specs or [])
        ) or ({
            "name": "production",
            "observation_profile": "production",
            "parameter_variant": "default",
        },)
        selected = _validate_candidates(candidates)
        selected_max_frames = _validate_max_frames(args.max_frames)
        video_hash = _sha256(video_path)
        trace_root = output_path.parent
        trace_paths = [
            trace_root / "{0}_{1}.jsonl".format(candidate["name"], video_hash[:12])
            for candidate in selected
        ]
        existing_traces = [path for path in trace_paths if path.exists()]
        if existing_traces:
            raise ValueError(
                "refusing to overwrite existing trace: {0}".format(existing_traces[0])
            )
        report = compare_video_candidates(
            video_path,
            candidates=selected,
            target_id=args.target_id,
            max_frames=selected_max_frames,
            calibration_manifest=manifest_path,
            trace_dir=trace_root,
        )
        _write_report(output_path, _public_report(report))
    except (OSError, ValueError, RuntimeError) as exc:
        print("error: {0}".format(exc))
        return 1

    print("video replay report: {0}".format(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
