"""Offline IMU evidence summary and control-shadow contracts.

This module deliberately stops before the hardware control boundary.  It
answers two narrow questions that are needed before an IMU can be allowed to
affect a real controller:

1. Is a synchronized fusion record eligible to influence a hypothetical turn?
2. What does a replayed set of fusion records actually establish?

The shadow decision is not sent to the STM32 and is not used by the existing
closed-loop plant predictor.  Real IMU sign, gain, and timing still require a
bounded hardware observation before firmware control can be changed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from .v1_twin_pose_fusion import (
    IMU_VALIDITY_DT_CLAMPED,
    IMU_VALIDITY_REQUIRED,
    V1PoseFusionRecord,
    V1PoseFusionQuality,
    wrap_angle_rad,
)
from real_world.frame_parser import MPU6050_INIT_STATUS_OK


EVIDENCE_SOURCES = frozenset(("REAL_SYNC", "SYNTHETIC"))


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError("{} must be numeric, not bool".format(name))
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("{} must be numeric".format(name)) from exc
    if not math.isfinite(result):
        raise ValueError("{} must be finite".format(name))
    return result


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


@dataclass(frozen=True)
class V1ImuEvidenceReport:
    """A bounded summary of fusion evidence, without a performance claim."""

    evidence_status: str
    source: str
    record_count: int
    used_imu_count: int
    camera_only_count: int
    insufficient_count: int
    imu_coverage: float
    camera_imu_delta_p95_rad: Optional[float]
    propagated_camera_residual_p95_rad: Optional[float]
    max_imu_gap_ns: Optional[int]
    monotonic_timestamps: bool
    reason_counts: Tuple[Tuple[str, int], ...]
    reason: str

    def __post_init__(self) -> None:
        if self.evidence_status not in ("VERIFIED", "INSUFFICIENT_EVIDENCE"):
            raise ValueError("unsupported evidence_status")
        if self.source not in EVIDENCE_SOURCES:
            raise ValueError("unsupported evidence source")
        for name in (
            "record_count",
            "used_imu_count",
            "camera_only_count",
            "insufficient_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("{} must be a non-negative int".format(name))
        if self.used_imu_count + self.camera_only_count + self.insufficient_count != self.record_count:
            raise ValueError("quality counts must add up to record_count")
        coverage = _finite(self.imu_coverage, "imu_coverage")
        if not 0.0 <= coverage <= 1.0:
            raise ValueError("imu_coverage must be within [0, 1]")
        for name in (
            "camera_imu_delta_p95_rad",
            "propagated_camera_residual_p95_rad",
        ):
            value = getattr(self, name)
            if value is not None and _finite(value, name) < 0.0:
                raise ValueError("{} must be >= 0".format(name))
        if self.max_imu_gap_ns is not None and (
            isinstance(self.max_imu_gap_ns, bool)
            or not isinstance(self.max_imu_gap_ns, int)
            or self.max_imu_gap_ns < 0
        ):
            raise ValueError("max_imu_gap_ns must be a non-negative int")
        if not isinstance(self.monotonic_timestamps, bool):
            raise ValueError("monotonic_timestamps must be bool")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("reason must be non-empty")
        for item in self.reason_counts:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not item[0]
                or isinstance(item[1], bool)
                or not isinstance(item[1], int)
                or item[1] <= 0
            ):
                raise ValueError("reason_counts must contain non-empty counted tuples")

    def to_dict(self) -> dict:
        return {
            "type": "V1ImuEvidenceReport",
            "evidence_status": self.evidence_status,
            "source": self.source,
            "record_count": self.record_count,
            "used_imu_count": self.used_imu_count,
            "camera_only_count": self.camera_only_count,
            "insufficient_count": self.insufficient_count,
            "imu_coverage": self.imu_coverage,
            "camera_imu_delta_p95_rad": self.camera_imu_delta_p95_rad,
            "propagated_camera_residual_p95_rad": self.propagated_camera_residual_p95_rad,
            "max_imu_gap_ns": self.max_imu_gap_ns,
            "monotonic_timestamps": self.monotonic_timestamps,
            "reason_counts": {key: value for key, value in self.reason_counts},
            "reason": self.reason,
        }


def summarize_imu_evidence(
    records: Iterable[V1PoseFusionRecord],
    *,
    source: str,
    sync_gate_verdict: Optional[str] = None,
) -> V1ImuEvidenceReport:
    """Summarize fusion records and fail closed outside a real sync source.

    ``VERIFIED`` means that a real synchronized record set satisfied the
    report's structural prerequisites.  It does not mean that the IMU is
    accurate, that the twin is calibrated, or that a car became faster.
    """

    if source not in EVIDENCE_SOURCES:
        raise ValueError("source must be REAL_SYNC or SYNTHETIC")
    materialized = tuple(records)
    if any(not isinstance(record, V1PoseFusionRecord) for record in materialized):
        raise TypeError("records must contain V1PoseFusionRecord values")

    record_count = len(materialized)
    used_imu_count = sum(
        record.quality is V1PoseFusionQuality.USED_IMU
        for record in materialized
    )
    camera_only_count = sum(
        record.quality is V1PoseFusionQuality.CAMERA_ONLY
        for record in materialized
    )
    insufficient_count = sum(
        record.quality is V1PoseFusionQuality.INSUFFICIENT_EVIDENCE
        for record in materialized
    )
    coverage = used_imu_count / record_count if record_count else 0.0
    monotonic = all(
        current.timestamp_ns > previous.timestamp_ns
        for previous, current in zip(materialized, materialized[1:])
    )
    gaps = [record.imu_gap_ns for record in materialized if record.imu_gap_ns is not None]
    reason_counter: Dict[str, int] = {}
    for record in materialized:
        if record.fallback_reason:
            reason_counter[record.fallback_reason] = (
                reason_counter.get(record.fallback_reason, 0) + 1
            )

    camera_imu_delta_residuals = []
    propagated_camera_residuals = []
    for previous, current in zip(materialized, materialized[1:]):
        if (
            previous.quality is V1PoseFusionQuality.USED_IMU
            and current.quality is V1PoseFusionQuality.USED_IMU
            and previous.camera_yaw_rad is not None
            and current.camera_yaw_rad is not None
            and previous.imu_yaw_rad is not None
            and current.imu_yaw_rad is not None
            and previous.imu_sign == current.imu_sign
        ):
            camera_delta = wrap_angle_rad(
                current.camera_yaw_rad - previous.camera_yaw_rad
            )
            imu_delta = wrap_angle_rad(
                (current.imu_yaw_rad - previous.imu_yaw_rad) * current.imu_sign
            )
            camera_imu_delta_residuals.append(
                abs(wrap_angle_rad(camera_delta - imu_delta))
            )
        if (
            current.camera_yaw_rad is not None
            and current.propagated_yaw_rad is not None
        ):
            propagated_camera_residuals.append(
                abs(wrap_angle_rad(
                    current.camera_yaw_rad - current.propagated_yaw_rad
                ))
            )

    if source != "REAL_SYNC":
        reason = "source_not_real_sync"
    elif sync_gate_verdict is not None and sync_gate_verdict != "PASS":
        reason = "sync_gate_not_pass"
    elif not materialized:
        reason = "no_records"
    elif not monotonic:
        reason = "non_monotonic_timestamps"
    elif used_imu_count == 0:
        reason = "no_usable_imu_records"
    else:
        reason = "real_sync_quality_summary_only"

    evidence_status = (
        "VERIFIED"
        if reason == "real_sync_quality_summary_only"
        else "INSUFFICIENT_EVIDENCE"
    )
    return V1ImuEvidenceReport(
        evidence_status=evidence_status,
        source=source,
        record_count=record_count,
        used_imu_count=used_imu_count,
        camera_only_count=camera_only_count,
        insufficient_count=insufficient_count,
        imu_coverage=coverage,
        camera_imu_delta_p95_rad=_percentile(camera_imu_delta_residuals, 0.95),
        propagated_camera_residual_p95_rad=_percentile(
            propagated_camera_residuals, 0.95
        ),
        max_imu_gap_ns=max(gaps) if gaps else None,
        monotonic_timestamps=monotonic,
        reason_counts=tuple(sorted(reason_counter.items())),
        reason=reason,
    )


@dataclass(frozen=True)
class V1ImuControlConfig:
    """Explicit, bounded parameters for a hypothetical yaw correction."""

    heading_gain_turn_per_rad: float = 80.0
    max_correction_turn: int = 120
    turn_limit: int = 600
    correction_sign: float = 1.0

    def __post_init__(self) -> None:
        gain = _finite(self.heading_gain_turn_per_rad, "heading_gain_turn_per_rad")
        if gain < 0.0:
            raise ValueError("heading_gain_turn_per_rad must be >= 0")
        for name in ("max_correction_turn", "turn_limit"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("{} must be a non-negative int".format(name))
        sign = _finite(self.correction_sign, "correction_sign")
        if sign not in (-1.0, 1.0):
            raise ValueError("correction_sign must be -1.0 or 1.0")
        if self.max_correction_turn > self.turn_limit:
            raise ValueError("max_correction_turn must not exceed turn_limit")


@dataclass(frozen=True)
class V1ImuControlDecision:
    """A hypothetical turn decision; it has no hardware side effect."""

    baseline_turn: int
    desired_yaw_rad: Optional[float]
    fused_yaw_rad: Optional[float]
    heading_error_rad: Optional[float]
    correction_turn: int
    applied_turn: int
    used_imu: bool
    quality: str
    reason: Optional[str]

    def to_dict(self) -> dict:
        return {
            "type": "V1ImuControlDecision",
            "baseline_turn": self.baseline_turn,
            "desired_yaw_rad": self.desired_yaw_rad,
            "fused_yaw_rad": self.fused_yaw_rad,
            "heading_error_rad": self.heading_error_rad,
            "correction_turn": self.correction_turn,
            "applied_turn": self.applied_turn,
            "used_imu": self.used_imu,
            "quality": self.quality,
            "reason": self.reason,
            "hardware_applied": False,
        }


class V1ImuControlShadow:
    """Apply a bounded yaw correction to a hypothetical turn signal."""

    def __init__(self, config: Optional[V1ImuControlConfig] = None) -> None:
        self.config = config or V1ImuControlConfig()

    def decide(
        self,
        baseline_turn: int,
        desired_yaw_rad: float,
        fusion_record: V1PoseFusionRecord,
    ) -> V1ImuControlDecision:
        if isinstance(baseline_turn, bool) or not isinstance(baseline_turn, int):
            raise TypeError("baseline_turn must be an int")
        if not isinstance(fusion_record, V1PoseFusionRecord):
            raise TypeError("fusion_record must be V1PoseFusionRecord")
        desired = _finite(desired_yaw_rad, "desired_yaw_rad")
        baseline = max(
            -self.config.turn_limit,
            min(self.config.turn_limit, baseline_turn),
        )
        reason = self._eligibility_reason(fusion_record)
        if reason is not None:
            return V1ImuControlDecision(
                baseline_turn=baseline,
                desired_yaw_rad=desired,
                fused_yaw_rad=fusion_record.fused_yaw_rad,
                heading_error_rad=None,
                correction_turn=0,
                applied_turn=baseline,
                used_imu=False,
                quality=fusion_record.quality.value,
                reason=reason,
            )

        fused = fusion_record.fused_yaw_rad
        assert fused is not None
        heading_error = wrap_angle_rad(desired - fused)
        correction = int(round(
            self.config.correction_sign
            * self.config.heading_gain_turn_per_rad
            * heading_error
        ))
        correction = max(
            -self.config.max_correction_turn,
            min(self.config.max_correction_turn, correction),
        )
        applied = max(
            -self.config.turn_limit,
            min(self.config.turn_limit, baseline + correction),
        )
        return V1ImuControlDecision(
            baseline_turn=baseline,
            desired_yaw_rad=desired,
            fused_yaw_rad=fused,
            heading_error_rad=heading_error,
            correction_turn=correction,
            applied_turn=applied,
            used_imu=True,
            quality=fusion_record.quality.value,
            reason=None,
        )

    @staticmethod
    def _eligibility_reason(record: V1PoseFusionRecord) -> Optional[str]:
        if record.quality is not V1PoseFusionQuality.USED_IMU:
            return record.fallback_reason or "imu_not_used"
        if not record.imu_validity_known:
            return "imu_validity_unknown"
        if record.imu_validity & IMU_VALIDITY_DT_CLAMPED:
            return "dt_clamped"
        if (record.imu_validity & IMU_VALIDITY_REQUIRED) != IMU_VALIDITY_REQUIRED:
            return "imu_not_fresh"
        if not record.imu_init_status_known:
            return "imu_init_status_unknown"
        if record.imu_init_status != MPU6050_INIT_STATUS_OK:
            return "imu_init_failed"
        if record.fused_yaw_rad is None or not math.isfinite(record.fused_yaw_rad):
            return "fused_yaw_missing"
        return None
