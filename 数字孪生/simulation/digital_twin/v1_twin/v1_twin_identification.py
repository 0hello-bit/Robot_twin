"""Software-only system-identification scaffolding for Task 4B-6.

This module fits the deliberately small shared-wheel-gain plant on supplied
velocity samples and emits explicit identifiability/coverage diagnostics.  A
fit from real synchronized frames remains exploratory until the later
calibration/holdout gates; this module never freezes or certifies a model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Sequence, Tuple

import numpy as np

from .v1_twin_plant import (
    DEFAULT_MIX_MATRIX,
    DEFAULT_PWM_LIMIT,
    V1PlantParameters,
)
from .v1_twin_schema import V1SyncFrame, V1SyncQuality


PARAMETER_COUNT = 7  # four wheel gains + three body biases
MIN_SAMPLES_FOR_FIT = 20
MIN_RANGE_FRACTION = 0.60


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


def _tuple_numeric(values: Sequence[object], count: int, name: str) -> Tuple[float, ...]:
    if len(values) != count:
        raise ValueError("{} must have exactly {} entries".format(name, count))
    return tuple(_finite(value, "{}[{}]".format(name, i)) for i, value in enumerate(values))


@dataclass(frozen=True)
class V1VelocitySample:
    """One PWM command and the measured body velocity over ``dt_s``."""

    pwm: Tuple[float, float, float, float]
    velocity: Tuple[float, float, float]
    dt_s: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "pwm", _tuple_numeric(self.pwm, 4, "pwm"))
        object.__setattr__(self, "velocity", _tuple_numeric(self.velocity, 3, "velocity"))
        dt = _finite(self.dt_s, "dt_s")
        if dt <= 0.0:
            raise ValueError("dt_s must be > 0")
        object.__setattr__(self, "dt_s", dt)


@dataclass(frozen=True)
class V1WheelCoverage:
    min_pwm: float
    max_pwm: float
    range_fraction: float
    nonzero_count: int
    nonzero_fraction: float
    histogram: Tuple[int, ...]


@dataclass(frozen=True)
class V1CoverageReport:
    verdict: str
    sample_count: int
    per_wheel: Tuple[V1WheelCoverage, ...]
    nonzero_counts: Tuple[int, int, int, int]
    all_zero_fraction: float
    joint_nonzero_patterns: Tuple[Tuple[str, int], ...]
    pairwise_nonzero_counts: Tuple[Tuple[int, int, int, int], ...]
    stop_fraction: float
    straight_fraction: float
    turn_fraction: float
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "sample_count": self.sample_count,
            "per_wheel": [item.__dict__ for item in self.per_wheel],
            "nonzero_counts": list(self.nonzero_counts),
            "all_zero_fraction": self.all_zero_fraction,
            "joint_nonzero_patterns": [list(item) for item in self.joint_nonzero_patterns],
            "pairwise_nonzero_counts": [list(row) for row in self.pairwise_nonzero_counts],
            "stop_fraction": self.stop_fraction,
            "straight_fraction": self.straight_fraction,
            "turn_fraction": self.turn_fraction,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class V1IdentifiabilityReport:
    parameter_count: int
    rank: int
    condition_number: float
    fisher_min_eigenvalue: float
    fisher_max_eigenvalue: float

    @property
    def identifiable(self) -> bool:
        return self.rank == self.parameter_count and math.isfinite(self.condition_number)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter_count": self.parameter_count,
            "rank": self.rank,
            "condition_number": self.condition_number,
            "fisher_min_eigenvalue": self.fisher_min_eigenvalue,
            "fisher_max_eigenvalue": self.fisher_max_eigenvalue,
            "identifiable": self.identifiable,
        }


@dataclass(frozen=True)
class V1IdentificationReport:
    verdict: str
    evidence_level: str
    parameters: V1PlantParameters | None
    residual_rms: float
    fit_error_max_relative: float | None
    identifiability: V1IdentifiabilityReport
    coverage: V1CoverageReport
    sample_count: int
    reason: str = ""

    @property
    def parameter_error_max_relative(self) -> float | None:
        """Backward-compatible name for the synthetic recovery diagnostic."""
        return self.fit_error_max_relative

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "evidence_level": self.evidence_level,
            "parameters": None if self.parameters is None else self.parameters.__dict__,
            "residual_rms": self.residual_rms,
            "fit_error_max_relative": self.fit_error_max_relative,
            "identifiability": self.identifiability.to_dict(),
            "coverage": self.coverage.to_dict(),
            "sample_count": self.sample_count,
            "reason": self.reason,
        }


class V1Identification:
    """Fit and diagnose the exploratory four-wheel plant."""

    @staticmethod
    def coverage_report(
        samples: Sequence[V1VelocitySample],
        *,
        pwm_limit: float = DEFAULT_PWM_LIMIT,
        bins: int = 10,
    ) -> V1CoverageReport:
        limit = _finite(pwm_limit, "pwm_limit")
        if limit <= 0.0:
            raise ValueError("pwm_limit must be > 0")
        if isinstance(bins, bool) or not isinstance(bins, int) or bins < 1:
            raise ValueError("bins must be a positive int")
        samples = tuple(samples)
        if any(not isinstance(sample, V1VelocitySample) for sample in samples):
            raise TypeError("samples must contain V1VelocitySample values")

        if not samples:
            empty = tuple(
                V1WheelCoverage(0.0, 0.0, 0.0, 0, 0.0, tuple(0 for _ in range(bins)))
                for _ in range(4)
            )
            return V1CoverageReport(
                verdict="INSUFFICIENT_EVIDENCE",
                sample_count=0,
                per_wheel=empty,
                nonzero_counts=(0, 0, 0, 0),
                all_zero_fraction=1.0,
                joint_nonzero_patterns=(),
                pairwise_nonzero_counts=tuple((0, 0, 0, 0) for _ in range(4)),
                stop_fraction=1.0,
                straight_fraction=0.0,
                turn_fraction=0.0,
                reason="no PWM samples were supplied",
            )

        pwm = np.asarray([sample.pwm for sample in samples], dtype=float)
        per_wheel = []
        nonzero_counts = []
        for wheel in range(4):
            values = pwm[:, wheel]
            if np.any(np.abs(values) > limit):
                raise ValueError("pwm sample exceeds pwm_limit")
            min_value = float(values.min())
            max_value = float(values.max())
            range_fraction = min(1.0, max(0.0, (max_value - min_value) / (2.0 * limit)))
            nonzero = int(np.count_nonzero(np.abs(values) > 1e-12))
            nonzero_counts.append(nonzero)
            histogram, _ = np.histogram(values, bins=bins, range=(-limit, limit))
            per_wheel.append(V1WheelCoverage(
                min_pwm=min_value,
                max_pwm=max_value,
                range_fraction=range_fraction,
                nonzero_count=nonzero,
                nonzero_fraction=nonzero / len(samples),
                histogram=tuple(int(x) for x in histogram),
            ))

        patterns: Dict[str, int] = {}
        pairwise = [[0 for _ in range(4)] for _ in range(4)]
        state_counts = {"stop": 0, "straight": 0, "turn": 0}
        mix = np.asarray(DEFAULT_MIX_MATRIX, dtype=float).reshape(3, 4)
        state_threshold = max(1.0, 0.02 * limit)
        for sample in samples:
            pattern = "".join("1" if abs(value) > 1e-12 else "0" for value in sample.pwm)
            patterns[pattern] = patterns.get(pattern, 0) + 1
            active = [abs(value) > 1e-12 for value in sample.pwm]
            for i in range(4):
                for j in range(4):
                    if active[i] and active[j]:
                        pairwise[i][j] += 1
            proxy = mix @ np.asarray(sample.pwm, dtype=float)
            if not any(active):
                state_counts["stop"] += 1
            elif abs(proxy[1]) <= state_threshold and abs(proxy[2]) <= state_threshold:
                state_counts["straight"] += 1
            else:
                state_counts["turn"] += 1
        all_zero = patterns.get("0000", 0) / len(samples)

        reasons = []
        if len(samples) < MIN_SAMPLES_FOR_FIT:
            reasons.append("fewer than {} samples".format(MIN_SAMPLES_FOR_FIT))
        if any(item.range_fraction < MIN_RANGE_FRACTION for item in per_wheel):
            reasons.append("one or more wheels cover less than 60% of the signed PWM range")
        if any(count == 0 for count in nonzero_counts):
            reasons.append("at least one wheel has no nonzero excitation")
        verdict = "PASS" if not reasons else "INSUFFICIENT_EVIDENCE"
        return V1CoverageReport(
            verdict=verdict,
            sample_count=len(samples),
            per_wheel=tuple(per_wheel),
            nonzero_counts=tuple(nonzero_counts),  # type: ignore[arg-type]
            all_zero_fraction=float(all_zero),
            joint_nonzero_patterns=tuple(sorted(patterns.items())),
            pairwise_nonzero_counts=tuple(tuple(row) for row in pairwise),
            stop_fraction=state_counts["stop"] / len(samples),
            straight_fraction=state_counts["straight"] / len(samples),
            turn_fraction=state_counts["turn"] / len(samples),
            reason="; ".join(reasons),
        )

    @classmethod
    def identify(
        cls,
        samples: Sequence[V1VelocitySample],
        *,
        deadzone: Sequence[object] = (0.0, 0.0, 0.0, 0.0),
        delay_steps: int = 0,
        pwm_limit: float = DEFAULT_PWM_LIMIT,
        mix_matrix: Sequence[object] = DEFAULT_MIX_MATRIX,
        evidence_level: str = "REAL_SYNC",
    ) -> V1IdentificationReport:
        samples = tuple(samples)
        if any(not isinstance(sample, V1VelocitySample) for sample in samples):
            raise TypeError("samples must contain V1VelocitySample values")
        deadzone_tuple = _tuple_numeric(deadzone, 4, "deadzone")
        matrix = _tuple_numeric(mix_matrix, 12, "mix_matrix")
        limit = _finite(pwm_limit, "pwm_limit")
        if limit <= 0.0:
            raise ValueError("pwm_limit must be > 0")
        if any(zone < 0.0 or zone > limit for zone in deadzone_tuple):
            raise ValueError("deadzone values must be within [0, pwm_limit]")
        if isinstance(delay_steps, bool) or not isinstance(delay_steps, int) or delay_steps < 0:
            raise ValueError("delay_steps must be a non-negative int")
        coverage = cls.coverage_report(samples, pwm_limit=pwm_limit)
        x, y = cls._design_matrix(samples, deadzone_tuple, matrix, limit)
        ident = cls._identifiability(x)
        if len(samples) < MIN_SAMPLES_FOR_FIT or not ident.identifiable:
            reason = "insufficient samples or rank-deficient excitation"
            return V1IdentificationReport(
                verdict="INSUFFICIENT_EVIDENCE",
                evidence_level=evidence_level,
                parameters=None,
                residual_rms=math.inf,
                fit_error_max_relative=None,
                identifiability=ident,
                coverage=coverage,
                sample_count=len(samples),
                reason=reason,
            )

        coefficients, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
        prediction = x @ coefficients
        residual_rms = float(np.sqrt(np.mean((prediction - y) ** 2)))
        params = V1PlantParameters(
            wheel_gains=tuple(float(value) for value in coefficients[:4]),
            body_bias=tuple(float(value) for value in coefficients[4:7]),
            deadzone=deadzone_tuple,
            delay_steps=delay_steps,
            pwm_limit=limit,
            mix_matrix=matrix,
        )
        if evidence_level == "SYNTHETIC_ONLY":
            verdict = "EXPLORATORY_PASS" if coverage.verdict == "PASS" else "INSUFFICIENT_EVIDENCE"
            reason = "synthetic recovery only; parameters are not frozen"
        else:
            verdict = "INSUFFICIENT_EVIDENCE"
            reason = "real synchronized data fit is exploratory; 4B-7/4B-8 holdout gates are pending"
        return V1IdentificationReport(
            verdict=verdict,
            evidence_level=evidence_level,
            parameters=params,
            residual_rms=residual_rms,
            fit_error_max_relative=None,
            identifiability=ident,
            coverage=coverage,
            sample_count=len(samples),
            reason=reason,
        )

    @classmethod
    def synthetic_recovery(
        cls,
        samples: Sequence[V1VelocitySample],
        expected: V1PlantParameters,
    ) -> V1IdentificationReport:
        """Fit synthetic samples and compare against independently known params."""
        if not isinstance(expected, V1PlantParameters):
            raise TypeError("expected must be a V1PlantParameters")
        report = cls.identify(
            samples,
            deadzone=expected.deadzone,
            delay_steps=expected.delay_steps,
            pwm_limit=expected.pwm_limit,
            mix_matrix=expected.mix_matrix,
            evidence_level="SYNTHETIC_ONLY",
        )
        if report.parameters is None:
            return report
        expected_values = (*expected.wheel_gains, *expected.body_bias)
        fitted_values = (*report.parameters.wheel_gains, *report.parameters.body_bias)
        relative_errors = [
            abs(fitted - truth) / max(abs(truth), 1.0)
            for fitted, truth in zip(fitted_values, expected_values)
        ]
        return V1IdentificationReport(
            verdict=report.verdict,
            evidence_level=report.evidence_level,
            parameters=report.parameters,
            residual_rms=report.residual_rms,
            fit_error_max_relative=max(relative_errors),
            identifiability=report.identifiability,
            coverage=report.coverage,
            sample_count=report.sample_count,
            reason=report.reason,
        )

    @classmethod
    def from_sync_frames(
        cls,
        frames: Sequence[V1SyncFrame],
        **kwargs,
    ) -> V1IdentificationReport:
        if hasattr(frames, "sync_frames"):
            frames = frames.sync_frames  # type: ignore[assignment]
        samples = cls.velocity_samples_from_sync_frames(frames)
        return cls.identify(samples, **kwargs)

    @staticmethod
    def velocity_samples_from_sync_frames(
        frames: Sequence[V1SyncFrame],
    ) -> Tuple[V1VelocitySample, ...]:
        """Estimate body velocity from consecutive pose timestamps.

        The current telemetry contract makes yaw optional for legacy data.  A
        missing yaw therefore yields no fabricated omega; the caller receives
        an explicit error instead of a silently incomplete model.
        """
        valid = [
            frame for frame in frames
            if isinstance(frame, V1SyncFrame)
            and frame.sync_quality is not V1SyncQuality.MISSING
        ]
        valid.sort(key=lambda frame: frame.pose.t_pc_ns)
        if len(valid) < 2:
            return ()
        samples = []
        previous = valid[0]
        for current in valid[1:]:
            dt = (current.pose.t_pc_ns - previous.pose.t_pc_ns) / 1_000_000_000.0
            if dt <= 0.0:
                previous = current
                continue
            if not previous.telemetry.yaw_known or not current.telemetry.yaw_known:
                raise ValueError("sync frames must contain yaw_rad for omega estimation")
            dx = current.pose.x_mm - previous.pose.x_mm
            dy = current.pose.y_mm - previous.pose.y_mm
            yaw = previous.pose.yaw_rad
            cos_yaw = math.cos(yaw)
            sin_yaw = math.sin(yaw)
            vx = (cos_yaw * dx + sin_yaw * dy) / dt
            vy = (-sin_yaw * dx + cos_yaw * dy) / dt
            dyaw = current.pose.yaw_rad - previous.pose.yaw_rad
            dyaw = (dyaw + math.pi) % (2.0 * math.pi) - math.pi
            omega = dyaw / dt
            samples.append(V1VelocitySample(
                pwm=current.telemetry.pwm,
                velocity=(vx, vy, omega),
                dt_s=dt,
            ))
            previous = current
        return tuple(samples)

    @staticmethod
    def _design_matrix(
        samples: Sequence[V1VelocitySample],
        deadzone: Tuple[float, ...],
        matrix: Tuple[float, ...],
        pwm_limit: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        rows = []
        targets = []
        for sample in samples:
            effective = []
            for value, zone in zip(sample.pwm, deadzone):
                if abs(value) > pwm_limit:
                    raise ValueError("pwm sample exceeds pwm_limit")
                effective.append(
                    math.copysign(max(abs(value) - zone, 0.0), value)
                    if value != 0.0 else 0.0
                )
            for axis in range(3):
                row = [matrix[axis * 4 + wheel] * effective[wheel] for wheel in range(4)]
                row.extend(1.0 if bias_axis == axis else 0.0 for bias_axis in range(3))
                rows.append(row)
                targets.append(sample.velocity[axis])
        if not rows:
            return np.empty((0, PARAMETER_COUNT)), np.empty((0,))
        return np.asarray(rows, dtype=float), np.asarray(targets, dtype=float)

    @staticmethod
    def _identifiability(x: np.ndarray) -> V1IdentifiabilityReport:
        if x.size == 0:
            return V1IdentifiabilityReport(PARAMETER_COUNT, 0, math.inf, 0.0, 0.0)
        rank = int(np.linalg.matrix_rank(x))
        # PWM columns and bias columns have different physical scales.  Report
        # the condition number after column normalization so the diagnostic
        # measures excitation geometry rather than units alone.
        column_norms = np.linalg.norm(x, axis=0)
        column_norms[column_norms == 0.0] = 1.0
        x_scaled = x / column_norms
        try:
            condition = float(np.linalg.cond(x_scaled))
        except np.linalg.LinAlgError:
            condition = math.inf
        fisher = (x_scaled.T @ x_scaled) / max(1, x.shape[0])
        eigvals = np.linalg.eigvalsh(fisher)
        return V1IdentifiabilityReport(
            parameter_count=PARAMETER_COUNT,
            rank=rank,
            condition_number=condition,
            fisher_min_eigenvalue=float(max(0.0, eigvals[0])),
            fisher_max_eigenvalue=float(max(0.0, eigvals[-1])),
        )
