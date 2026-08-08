"""Offline B3 camera-observation quality gate.

This module evaluates retained frame-index records only. It does not run a
detector, infer missing poses, or promote a failed real run to readiness.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence


SCHEMA_VERSION = 1
EVIDENCE_SOURCES = frozenset(("REAL_SYNC", "SYNTHETIC"))
SYNC_GATE_VERDICTS = frozenset((None, "PASS", "FAIL", "INSUFFICIENT EVIDENCE"))
CAPTURE_VERDICTS = frozenset((None, "PASS", "FAIL", "INSUFFICIENT EVIDENCE"))
DEFAULT_EXPECTED_FPS = 30.0
DEFAULT_MIN_DETECTION_RATIO = 0.95
DEFAULT_MAX_POSE_GAP_FRAMES = 2.0


def _percentile(values: Iterable[int], percentile: float) -> Optional[int]:
    ordered = sorted(int(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return int(round(
        ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    ))


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("{0} must be a non-negative int".format(name))
    return int(value)


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError("{0} must be a bool".format(name))
    return value


@dataclass(frozen=True)
class B3ObservationGateConfig:
    """Declared screening thresholds for a 30 fps observation stream."""

    expected_fps: float = DEFAULT_EXPECTED_FPS
    min_detection_ratio: float = DEFAULT_MIN_DETECTION_RATIO
    max_pose_gap_frames: float = DEFAULT_MAX_POSE_GAP_FRAMES

    def __post_init__(self) -> None:
        if (
            isinstance(self.expected_fps, bool)
            or not isinstance(self.expected_fps, (int, float))
            or not math.isfinite(float(self.expected_fps))
            or self.expected_fps <= 0.0
        ):
            raise ValueError("expected_fps must be finite and > 0")
        if (
            isinstance(self.min_detection_ratio, bool)
            or not isinstance(self.min_detection_ratio, (int, float))
            or not math.isfinite(float(self.min_detection_ratio))
            or not 0.0 <= self.min_detection_ratio <= 1.0
        ):
            raise ValueError(
                "min_detection_ratio must be finite and within [0, 1]"
            )
        if (
            isinstance(self.max_pose_gap_frames, bool)
            or not isinstance(self.max_pose_gap_frames, (int, float))
            or not math.isfinite(float(self.max_pose_gap_frames))
            or self.max_pose_gap_frames <= 0.0
        ):
            raise ValueError(
                "max_pose_gap_frames must be finite and > 0"
            )

    @property
    def frame_period_ns(self) -> float:
        return 1_000_000_000.0 / float(self.expected_fps)

    def to_dict(self) -> dict[str, float]:
        return {
            "expected_fps": float(self.expected_fps),
            "min_detection_ratio": float(self.min_detection_ratio),
            "max_pose_gap_frames": float(self.max_pose_gap_frames),
            "frame_period_ns": self.frame_period_ns,
        }


@dataclass(frozen=True)
class B3ObservationGateReport:
    """Derived observation metrics and evidence classification."""

    evidence_status: str
    verdict: str
    source: str
    sync_gate_verdict: Optional[str]
    capture_verdict: Optional[str]
    run_id: Optional[str]
    frame_record_count: int
    camera_frame_count: int
    read_failure_count: int
    pose_frame_count: int
    detection_ratio: float
    failure_counts: dict[str, int]
    max_pose_gap_ns: Optional[int]
    max_pose_gap_frames: Optional[float]
    processing_p95_ns: Optional[int]
    processing_budget_ns: int
    processing_p95_over_budget: Optional[bool]
    processing_timing_missing_count: int
    reasons: tuple[str, ...]
    config: B3ObservationGateConfig

    def __post_init__(self) -> None:
        if self.evidence_status not in ("VERIFIED", "INSUFFICIENT_EVIDENCE"):
            raise ValueError("unsupported evidence_status")
        if self.verdict not in ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE"):
            raise ValueError("unsupported verdict")
        if self.source not in EVIDENCE_SOURCES:
            raise ValueError("unsupported source")
        if self.sync_gate_verdict not in SYNC_GATE_VERDICTS:
            raise ValueError("unsupported sync_gate_verdict")
        if self.capture_verdict not in CAPTURE_VERDICTS:
            raise ValueError("unsupported capture_verdict")
        for name in (
            "frame_record_count",
            "camera_frame_count",
            "read_failure_count",
            "pose_frame_count",
            "processing_budget_ns",
            "processing_timing_missing_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("{0} must be a non-negative int".format(name))
        if self.camera_frame_count + self.read_failure_count != self.frame_record_count:
            raise ValueError("frame counts do not add up")
        if (
            isinstance(self.detection_ratio, bool)
            or not isinstance(self.detection_ratio, (int, float))
            or not math.isfinite(float(self.detection_ratio))
            or not 0.0 <= self.detection_ratio <= 1.0
        ):
            raise ValueError("detection_ratio must be finite and within [0, 1]")
        for name in ("max_pose_gap_ns", "processing_p95_ns"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError("{0} must be a non-negative int when present".format(name))
        if self.max_pose_gap_frames is not None and (
            isinstance(self.max_pose_gap_frames, bool)
            or not isinstance(self.max_pose_gap_frames, (int, float))
            or not math.isfinite(float(self.max_pose_gap_frames))
            or self.max_pose_gap_frames < 0.0
        ):
            raise ValueError("max_pose_gap_frames must be finite and >= 0")
        if self.processing_p95_over_budget is not None and not isinstance(
            self.processing_p95_over_budget, bool
        ):
            raise ValueError("processing_p95_over_budget must be bool or None")
        if not isinstance(self.reasons, tuple) or any(
            not isinstance(reason, str) or not reason for reason in self.reasons
        ):
            raise ValueError("reasons must be a tuple of non-empty strings")
        if self.evidence_status == "INSUFFICIENT_EVIDENCE" and self.verdict != "INSUFFICIENT_EVIDENCE":
            raise ValueError("insufficient evidence must use insufficient verdict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "type": "B3ObservationGateReport",
            "evidence_status": self.evidence_status,
            "verdict": self.verdict,
            "source": self.source,
            "sync_gate_verdict": self.sync_gate_verdict,
            "capture_verdict": self.capture_verdict,
            "run_id": self.run_id,
            "frame_record_count": self.frame_record_count,
            "camera_frame_count": self.camera_frame_count,
            "read_failure_count": self.read_failure_count,
            "pose_frame_count": self.pose_frame_count,
            "detection_ratio": self.detection_ratio,
            "failure_counts": dict(sorted(self.failure_counts.items())),
            "max_pose_gap_ns": self.max_pose_gap_ns,
            "max_pose_gap_frames": self.max_pose_gap_frames,
            "processing_p95_ns": self.processing_p95_ns,
            "processing_budget_ns": self.processing_budget_ns,
            "processing_p95_over_budget": self.processing_p95_over_budget,
            "processing_timing_missing_count": self.processing_timing_missing_count,
            "reasons": list(self.reasons),
            "config": self.config.to_dict(),
            "units": {
                "timestamp": "ns",
                "pose_gap": "ns",
                "processing_time": "ns",
                "frame_gap": "frames",
                "detection_ratio": "ratio",
            },
        }


def load_frame_index(path: str | Path) -> list[dict[str, Any]]:
    """Load frame-index JSONL without altering the source artifact."""

    records: list[dict[str, Any]] = []
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "invalid JSON at line {0}: {1}".format(line_number, exc)
                    ) from exc
                if not isinstance(value, dict):
                    raise ValueError(
                        "frame-index line {0} must be a JSON object".format(
                            line_number
                        )
                    )
                records.append(value)
    except OSError as exc:
        raise ValueError("unable to read frame index: {0}".format(exc)) from exc
    return records


def _pose_detected(record: Mapping[str, Any]) -> bool:
    if "pose_detected" in record:
        return _require_bool(record["pose_detected"], "pose_detected")
    if "pose_present" in record:
        return _require_bool(record["pose_present"], "pose_present")
    raise ValueError("frame record requires pose_detected or pose_present")


def _validate_record(record: Mapping[str, Any]) -> tuple[int, bool, bool, Optional[int], Optional[int], Optional[str]]:
    if not isinstance(record, Mapping):
        raise ValueError("frame record must be an object")
    frame_index = _require_non_negative_int(record.get("frame_index"), "frame_index")
    read_ok = _require_bool(record.get("read_ok"), "read_ok")
    detected = _pose_detected(record)
    raw_timestamp = record.get("t_pc_ns")
    if read_ok or raw_timestamp is not None:
        timestamp_ns = _require_non_negative_int(raw_timestamp, "t_pc_ns")
    else:
        timestamp_ns = None
    elapsed = record.get("detect_elapsed_ns")
    if elapsed is not None:
        elapsed = _require_non_negative_int(elapsed, "detect_elapsed_ns")
    reason = record.get("failure_reason")
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise ValueError("failure_reason must be a non-empty string or null")
    if not read_ok and detected:
        raise ValueError("read failure cannot contain a detected pose")
    return frame_index, read_ok, detected, timestamp_ns, elapsed, reason


def evaluate_observation_gate(
    records: Sequence[Mapping[str, Any]],
    *,
    source: str,
    sync_gate_verdict: Optional[str],
    capture_verdict: Optional[str] = None,
    run_id: Optional[str] = None,
    config: Optional[B3ObservationGateConfig] = None,
) -> B3ObservationGateReport:
    """Evaluate observation continuity and classify retained evidence."""

    if source not in EVIDENCE_SOURCES:
        raise ValueError("source must be REAL_SYNC or SYNTHETIC")
    if sync_gate_verdict not in SYNC_GATE_VERDICTS:
        raise ValueError("unsupported sync_gate_verdict")
    if capture_verdict not in CAPTURE_VERDICTS:
        raise ValueError("unsupported capture_verdict")
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        raise ValueError("run_id must be a non-empty string when present")
    config = config or B3ObservationGateConfig()

    parsed = [_validate_record(record) for record in records]
    if parsed and parsed[0][0] != 0:
        raise ValueError("frame_index must start at 0")
    previous_frame_index: Optional[int] = None
    camera_count = 0
    pose_count = 0
    read_failure_count = 0
    pose_timestamps: list[tuple[int, int]] = []
    processing_times: list[int] = []
    processing_timing_missing_count = 0
    failure_counts: dict[str, int] = {}
    previous_read_timestamp: Optional[int] = None

    for frame_index, read_ok, detected, timestamp_ns, elapsed, reason in parsed:
        if previous_frame_index is not None and frame_index != previous_frame_index + 1:
            raise ValueError("frame_index must be contiguous")
        previous_frame_index = frame_index
        if read_ok:
            if timestamp_ns is None:
                raise ValueError("readable frame requires t_pc_ns")
            if (
                previous_read_timestamp is not None
                and timestamp_ns <= previous_read_timestamp
            ):
                raise ValueError("readable frame timestamp must be strictly increasing")
            previous_read_timestamp = timestamp_ns
            camera_count += 1
            if elapsed is not None:
                processing_times.append(elapsed)
            else:
                processing_timing_missing_count += 1
            if detected:
                pose_count += 1
                pose_timestamps.append((frame_index, timestamp_ns))
        else:
            read_failure_count += 1
        if reason is not None:
            failure_counts[reason] = failure_counts.get(reason, 0) + 1

    for (_, previous_timestamp), (_, timestamp) in zip(
        pose_timestamps, pose_timestamps[1:]
    ):
        if timestamp <= previous_timestamp:
            raise ValueError("detected pose timestamp must be strictly increasing")

    max_pose_gap_ns: Optional[int] = None
    max_pose_gap_frames: Optional[float] = None
    if len(pose_timestamps) >= 2:
        max_pose_gap_ns = max(
            current_timestamp - previous_timestamp
            for (_, previous_timestamp), (_, current_timestamp) in zip(
                pose_timestamps, pose_timestamps[1:]
            )
        )
        max_pose_gap_frames = max_pose_gap_ns / config.frame_period_ns

    processing_p95_ns = _percentile(processing_times, 0.95)
    processing_over_budget = (
        processing_p95_ns > config.frame_period_ns
        if processing_p95_ns is not None
        else None
    )
    detection_ratio = pose_count / camera_count if camera_count else 0.0
    common_kwargs = {
        "source": source,
        "sync_gate_verdict": sync_gate_verdict,
        "capture_verdict": capture_verdict,
        "run_id": run_id,
        "frame_record_count": len(parsed),
        "camera_frame_count": camera_count,
        "read_failure_count": read_failure_count,
        "pose_frame_count": pose_count,
        "detection_ratio": detection_ratio,
        "failure_counts": failure_counts,
        "max_pose_gap_ns": max_pose_gap_ns,
        "max_pose_gap_frames": max_pose_gap_frames,
        "processing_p95_ns": processing_p95_ns,
        "processing_budget_ns": int(round(config.frame_period_ns)),
        "processing_p95_over_budget": processing_over_budget,
        "processing_timing_missing_count": processing_timing_missing_count,
        "config": config,
    }

    if source != "REAL_SYNC":
        return B3ObservationGateReport(
            evidence_status="INSUFFICIENT_EVIDENCE",
            verdict="INSUFFICIENT_EVIDENCE",
            reasons=("source_not_real_sync",),
            **common_kwargs,
        )
    if capture_verdict != "PASS":
        return B3ObservationGateReport(
            evidence_status="INSUFFICIENT_EVIDENCE",
            verdict="INSUFFICIENT_EVIDENCE",
            reasons=("capture_verdict_not_pass",),
            **common_kwargs,
        )
    if sync_gate_verdict != "PASS":
        return B3ObservationGateReport(
            evidence_status="INSUFFICIENT_EVIDENCE",
            verdict="INSUFFICIENT_EVIDENCE",
            reasons=("sync_gate_not_pass",),
            **common_kwargs,
        )
    if processing_timing_missing_count:
        return B3ObservationGateReport(
            evidence_status="INSUFFICIENT_EVIDENCE",
            verdict="INSUFFICIENT_EVIDENCE",
            reasons=("detector_timing_incomplete",),
            **common_kwargs,
        )
    if not parsed or camera_count == 0:
        return B3ObservationGateReport(
            evidence_status="INSUFFICIENT_EVIDENCE",
            verdict="INSUFFICIENT_EVIDENCE",
            reasons=("no_readable_camera_frames",),
            **common_kwargs,
        )
    if pose_count < 2:
        return B3ObservationGateReport(
            evidence_status="INSUFFICIENT_EVIDENCE",
            verdict="INSUFFICIENT_EVIDENCE",
            reasons=("insufficient_pose_frames",),
            **common_kwargs,
        )
    if processing_p95_ns is None:
        return B3ObservationGateReport(
            evidence_status="INSUFFICIENT_EVIDENCE",
            verdict="INSUFFICIENT_EVIDENCE",
            reasons=("detector_timing_missing",),
            **common_kwargs,
        )

    reasons: list[str] = []
    if detection_ratio < config.min_detection_ratio:
        reasons.append("detection_ratio_below_threshold")
    if (
        max_pose_gap_frames is None
        or max_pose_gap_frames > config.max_pose_gap_frames
    ):
        reasons.append("max_pose_gap_exceeded")
    if processing_over_budget:
        reasons.append("detector_processing_over_budget")

    return B3ObservationGateReport(
        evidence_status="VERIFIED",
        verdict="PASS" if not reasons else "FAIL",
        reasons=tuple(reasons),
        **common_kwargs,
    )
