"""Offline summary and evidence classification for camera motion."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from .v1_twin_imu_control import V1ImuEvidenceReport
from .v1_twin_motion_observer import (
    MotionObservationQuality,
    V1CameraMotion,
    estimate_camera_motion,
)
from .v1_twin_schema import V1Pose


EVIDENCE_SOURCES = frozenset(("REAL_SYNC", "SYNTHETIC"))
SYNC_GATE_VERDICTS = frozenset((None, "PASS", "FAIL", "INSUFFICIENT EVIDENCE"))


def _percentile(values: Iterable[float], percentile: float) -> Optional[float]:
    ordered = sorted(float(value) for value in values)
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
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _optional_finite(value: Optional[float], name: str) -> None:
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError("{} must be finite when present".format(name))


@dataclass(frozen=True)
class V1CameraMotionEvidence:
    """Immutable summary of external whole-car camera motion."""

    evidence_status: str
    source: str
    sync_gate_verdict: Optional[str]
    record_count: int
    valid_count: int
    insufficient_count: int
    valid_ratio: float
    time_span_ns: Optional[int]
    planar_speed_mean_mm_s: Optional[float]
    planar_speed_p95_mm_s: Optional[float]
    abs_yaw_rate_p95_rad_s: Optional[float]
    imu_overlap_count: int
    camera_imu_delta_p95_rad: Optional[float]
    reason: str

    def __post_init__(self) -> None:
        if self.evidence_status not in ("VERIFIED", "INSUFFICIENT_EVIDENCE"):
            raise ValueError("unsupported evidence_status")
        if self.source not in EVIDENCE_SOURCES:
            raise ValueError("unsupported evidence source")
        if self.sync_gate_verdict not in SYNC_GATE_VERDICTS:
            raise ValueError("unsupported sync_gate_verdict")
        for name in (
            "record_count",
            "valid_count",
            "insufficient_count",
            "imu_overlap_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("{} must be a non-negative int".format(name))
        if self.valid_count + self.insufficient_count != self.record_count:
            raise ValueError("motion quality counts must add up to record_count")
        if not isinstance(self.valid_ratio, (int, float)) or isinstance(
            self.valid_ratio, bool
        ) or not math.isfinite(float(self.valid_ratio)) or not 0.0 <= self.valid_ratio <= 1.0:
            raise ValueError("valid_ratio must be finite and within [0, 1]")
        if self.time_span_ns is not None and (
            isinstance(self.time_span_ns, bool)
            or not isinstance(self.time_span_ns, int)
            or self.time_span_ns < 0
        ):
            raise ValueError("time_span_ns must be a non-negative int when present")
        for name in (
            "planar_speed_mean_mm_s",
            "planar_speed_p95_mm_s",
            "abs_yaw_rate_p95_rad_s",
            "camera_imu_delta_p95_rad",
        ):
            _optional_finite(getattr(self, name), name)
            value = getattr(self, name)
            if value is not None and value < 0.0 and name != "planar_speed_mean_mm_s":
                raise ValueError("{} must be >= 0".format(name))
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("reason must be non-empty")

    def to_dict(self) -> dict:
        return {
            "type": "V1CameraMotionEvidence",
            "evidence_status": self.evidence_status,
            "source": self.source,
            "sync_gate_verdict": self.sync_gate_verdict,
            "record_count": self.record_count,
            "valid_count": self.valid_count,
            "insufficient_count": self.insufficient_count,
            "valid_ratio": self.valid_ratio,
            "time_span_ns": self.time_span_ns,
            "planar_speed_mean_mm_s": self.planar_speed_mean_mm_s,
            "planar_speed_p95_mm_s": self.planar_speed_p95_mm_s,
            "abs_yaw_rate_p95_rad_s": self.abs_yaw_rate_p95_rad_s,
            "imu_overlap_count": self.imu_overlap_count,
            "camera_imu_delta_p95_rad": self.camera_imu_delta_p95_rad,
            "units": {
                "timestamp": "ns",
                "time_span": "ns",
                "planar_speed": "mm/s",
                "yaw_rate": "rad/s",
                "yaw_delta_residual": "rad",
            },
            "reason": self.reason,
        }


def build_camera_motion_evidence(
    poses: Iterable[V1Pose],
    *,
    source: str,
    sync_gate_verdict: Optional[str] = None,
    imu_report: Optional[V1ImuEvidenceReport] = None,
    max_gap_ns: int = 100_000_000,
) -> Tuple[Tuple[V1CameraMotion, ...], V1CameraMotionEvidence]:
    """Build camera derivatives and classify the evidence without calibration."""

    if source not in EVIDENCE_SOURCES:
        raise ValueError("source must be REAL_SYNC or SYNTHETIC")
    if sync_gate_verdict not in SYNC_GATE_VERDICTS:
        raise ValueError("unsupported sync_gate_verdict")
    if imu_report is not None and not isinstance(imu_report, V1ImuEvidenceReport):
        raise TypeError("imu_report must be V1ImuEvidenceReport or None")

    motions = estimate_camera_motion(poses, max_gap_ns=max_gap_ns)
    valid = tuple(
        motion
        for motion in motions
        if motion.quality is MotionObservationQuality.VALID
    )
    valid_speeds = tuple(m.planar_speed_mm_s for m in valid)
    valid_yaw_rates = tuple(abs(m.yaw_rate_rad_s) for m in valid)
    record_count = len(motions)
    valid_count = len(valid)
    insufficient_count = record_count - valid_count

    if source != "REAL_SYNC":
        reason = "source_not_real_sync"
    elif sync_gate_verdict != "PASS":
        reason = "sync_gate_not_pass"
    elif not motions:
        reason = "no_camera_motion_records"
    elif not valid:
        reason = "no_valid_camera_motion_records"
    else:
        reason = "real_sync_motion_summary_only"

    evidence_status = (
        "VERIFIED"
        if reason == "real_sync_motion_summary_only"
        else "INSUFFICIENT_EVIDENCE"
    )
    time_span_ns = (
        max(motion.timestamp_ns for motion in motions)
        - min(motion.timestamp_ns for motion in motions)
        if motions
        else None
    )
    report = V1CameraMotionEvidence(
        evidence_status=evidence_status,
        source=source,
        sync_gate_verdict=sync_gate_verdict,
        record_count=record_count,
        valid_count=valid_count,
        insufficient_count=insufficient_count,
        valid_ratio=valid_count / record_count if record_count else 0.0,
        time_span_ns=time_span_ns,
        planar_speed_mean_mm_s=(
            sum(valid_speeds) / len(valid_speeds) if valid_speeds else None
        ),
        planar_speed_p95_mm_s=_percentile(valid_speeds, 0.95),
        abs_yaw_rate_p95_rad_s=_percentile(valid_yaw_rates, 0.95),
        imu_overlap_count=imu_report.used_imu_count if imu_report else 0,
        camera_imu_delta_p95_rad=(
            imu_report.camera_imu_delta_p95_rad if imu_report else None
        ),
        reason=reason,
    )
    return motions, report
