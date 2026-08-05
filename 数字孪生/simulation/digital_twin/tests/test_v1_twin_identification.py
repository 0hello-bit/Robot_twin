"""Offline contracts for Task 4B-6 identification and coverage diagnostics."""

from __future__ import annotations

import math

import numpy as np
import pytest

from v1_twin.v1_twin_identification import (
    V1Identification,
    V1VelocitySample,
)
from v1_twin.v1_twin_plant import V1Plant, V1PlantParameters
from v1_twin.v1_twin_schema import V1Pose, V1SyncFrame, V1SyncQuality, V1TelemetryFrame


KNOWN = V1PlantParameters(
    wheel_gains=(1.20, 0.85, 1.05, 0.95),
    body_bias=(2.0, -1.5, 0.25),
    deadzone=(12.0, 10.0, 8.0, 11.0),
)


def _synthetic_samples(n: int = 160):
    rng = np.random.default_rng(20260805)
    plant = V1Plant(KNOWN)
    samples = []
    for _ in range(n):
        pwm = tuple(int(x) for x in rng.integers(-600, 601, size=4))
        velocity = plant.step(pwm, 0.02)
        samples.append(
            V1VelocitySample(
                pwm=pwm,
                velocity=(velocity.vx_mm_s, velocity.vy_mm_s, velocity.omega_rad_s),
                dt_s=0.02,
            )
        )
    return samples


def test_synthetic_identification_recovers_shared_wheel_gains_and_bias():
    report = V1Identification.synthetic_recovery(_synthetic_samples(), KNOWN)

    assert report.verdict == "EXPLORATORY_PASS"
    assert report.evidence_level == "SYNTHETIC_ONLY"
    assert report.parameters is not None
    assert report.parameter_error_max_relative <= 0.05
    assert report.residual_rms <= 1e-9
    assert report.identifiability.rank == report.identifiability.parameter_count
    assert report.identifiability.condition_number < 100.0

    fitted = report.parameters
    assert fitted.wheel_gains == pytest.approx(KNOWN.wheel_gains, rel=0.05)
    assert fitted.body_bias == pytest.approx(KNOWN.body_bias, rel=0.05, abs=0.05)


def test_coverage_report_is_explicit_and_detects_all_zero_and_narrow_data():
    samples = [
        V1VelocitySample((0, 0, 0, 0), (0.0, 0.0, 0.0), 0.02),
        V1VelocitySample((10, 0, 0, 0), (0.0, 0.0, 0.0), 0.02),
        V1VelocitySample((0, 10, 0, 0), (0.0, 0.0, 0.0), 0.02),
    ]
    coverage = V1Identification.coverage_report(samples)

    assert coverage.verdict == "INSUFFICIENT_EVIDENCE"
    assert coverage.all_zero_fraction > 0.0
    assert any(item.range_fraction < 0.60 for item in coverage.per_wheel)
    assert coverage.reason


def test_coverage_report_passes_wide_four_channel_excitation():
    samples = []
    for value in (-600, -300, 0, 300, 600):
        for wheel in range(4):
            pwm = [0, 0, 0, 0]
            pwm[wheel] = value
            samples.append(V1VelocitySample(tuple(pwm), (0.0, 0.0, 0.0), 0.02))
    coverage = V1Identification.coverage_report(samples)

    assert coverage.verdict == "PASS"
    assert all(item.range_fraction >= 0.60 for item in coverage.per_wheel)
    assert coverage.all_zero_fraction == pytest.approx(0.2)
    assert coverage.nonzero_counts == (4, 4, 4, 4)
    assert coverage.pairwise_nonzero_counts[0][0] == 4
    assert coverage.pairwise_nonzero_counts[0][1] == 0
    assert coverage.stop_fraction == pytest.approx(0.2)
    assert coverage.stop_fraction + coverage.straight_fraction + coverage.turn_fraction == pytest.approx(1.0)


def test_identification_reports_insufficient_evidence_instead_of_fabricating_fit():
    samples = [
        V1VelocitySample((0, 0, 0, 0), (0.0, 0.0, 0.0), 0.02)
        for _ in range(5)
    ]

    report = V1Identification.identify(samples)

    assert report.verdict == "INSUFFICIENT_EVIDENCE"
    assert report.parameters is None
    assert report.identifiability.rank < report.identifiability.parameter_count
    assert report.coverage.verdict == "INSUFFICIENT_EVIDENCE"


def test_real_sync_fit_remains_insufficient_evidence_until_holdout_gates():
    report = V1Identification.identify(_synthetic_samples())

    assert report.parameters is not None
    assert report.verdict == "INSUFFICIENT_EVIDENCE"
    assert "4B-7/4B-8" in report.reason


def test_velocity_samples_reject_nonfinite_values():
    with pytest.raises(ValueError):
        V1VelocitySample((0, 0, 0, 0), (math.nan, 0.0, 0.0), 0.02)


def test_sync_frames_estimate_body_velocity_from_independent_timestamps():
    first = V1SyncFrame(
        pose=V1Pose(0.0, 0.0, 0.0, 1.0, 0, source="simulated"),
        telemetry=V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (0, 0, 0, 0), 0, 0, 0.0),
        sync_quality=V1SyncQuality.OK,
    )
    second = V1SyncFrame(
        pose=V1Pose(100.0, 20.0, 0.0, 1.0, 1_000_000_000, source="simulated"),
        telemetry=V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (200, 100, 0, 50), 1000, 1_000_000_000, 0.0),
        sync_quality=V1SyncQuality.DEGRADED,
    )

    samples = V1Identification.velocity_samples_from_sync_frames((second, first))

    assert len(samples) == 1
    assert samples[0].pwm == pytest.approx((200.0, 100.0, 0.0, 50.0))
    assert samples[0].velocity == pytest.approx((100.0, 20.0, 0.0))
    assert samples[0].dt_s == pytest.approx(1.0)


def test_sync_frames_refuse_to_fabricate_omega_without_yaw():
    first = V1SyncFrame(
        pose=V1Pose(0.0, 0.0, 0.0, 1.0, 0, source="simulated"),
        telemetry=V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (0, 0, 0, 0), 0, 0),
        sync_quality=V1SyncQuality.OK,
    )
    second = V1SyncFrame(
        pose=V1Pose(1.0, 0.0, 0.0, 1.0, 1_000_000_000, source="simulated"),
        telemetry=V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (1, 1, 1, 1), 1000, 1_000_000_000),
        sync_quality=V1SyncQuality.OK,
    )

    with pytest.raises(ValueError, match="yaw_rad"):
        V1Identification.velocity_samples_from_sync_frames((first, second))
