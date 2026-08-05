"""Offline contracts for the Task 4B-6 low-parameter vehicle plant."""

from __future__ import annotations

import math

import pytest

from v1_twin.v1_twin_plant import (
    V1BodyVelocity,
    V1Plant,
    V1PlantParameters,
)
from v1_twin.v1_twin_identification import V1VelocitySample
from v1_twin.v1_twin_schema import V1Pose


def test_four_signed_pwm_channels_map_to_body_velocity():
    params = V1PlantParameters(
        wheel_gains=(2.0, 2.0, 2.0, 2.0),
        body_bias=(1.0, -2.0, 0.5),
        deadzone=(10.0, 10.0, 10.0, 10.0),
    )
    velocity = V1Plant(params).step((110, 90, 70, 50), 0.01)

    assert isinstance(velocity, V1BodyVelocity)
    # Canonical mecanum mix: vx=sum/4, vy=(-w0+w1+w2-w3)/4,
    # omega=(-w0+w1-w2+w3)/4 before wheel gains and bias.
    assert velocity.vx_mm_s == pytest.approx(141.0)
    assert velocity.vy_mm_s == pytest.approx(-2.0)
    assert velocity.omega_rad_s == pytest.approx(-19.5)


def test_deadzone_is_signed_and_delay_uses_previous_command():
    params = V1PlantParameters(
        wheel_gains=(1.0, 1.0, 1.0, 1.0),
        deadzone=(10.0, 10.0, 10.0, 10.0),
        delay_steps=1,
    )
    plant = V1Plant(params)

    first = plant.step((100, 100, 100, 100), 0.01)
    second = plant.step((-100, -100, -100, -100), 0.01)

    assert first == V1BodyVelocity(0.0, 0.0, 0.0)
    assert second.vx_mm_s == pytest.approx(90.0)
    assert second.vy_mm_s == pytest.approx(0.0)
    assert second.omega_rad_s == pytest.approx(0.0)


def test_predict_integrates_body_velocity_into_metric_poses():
    params = V1PlantParameters(wheel_gains=(1.0, 1.0, 1.0, 1.0))
    plant = V1Plant(params)
    initial = V1Pose(0.0, 0.0, math.pi / 2.0, 1.0, 0, source="simulated")

    poses = plant.predict(
        [((100, 100, 100, 100), 0.5), ((0, 0, 0, 0), 0.5)],
        initial_pose=initial,
    )

    assert len(poses) == 2
    assert poses[0].x_mm == pytest.approx(0.0, abs=1e-9)
    assert poses[0].y_mm == pytest.approx(50.0)
    assert poses[0].t_pc_ns == 500_000_000
    assert poses[1].x_mm == pytest.approx(0.0, abs=1e-9)
    assert poses[1].y_mm == pytest.approx(50.0)


def test_invalid_pwm_and_dt_are_rejected():
    plant = V1Plant(V1PlantParameters())
    with pytest.raises(ValueError, match="four"):
        plant.step((1, 2, 3), 0.01)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="pwm"):
        plant.step((1000, 0, 0, 0), 0.01)
    with pytest.raises(ValueError, match="dt_s"):
        plant.step((0, 0, 0, 0), 0.0)


def test_identify_accepts_reusable_velocity_sample_interface():
    samples = tuple(
        V1VelocitySample((0, 0, 0, 0), (0.0, 0.0, 0.0), 0.02)
        for _ in range(5)
    )

    report = V1Plant.identify(samples)

    assert report.verdict == "INSUFFICIENT_EVIDENCE"
    assert report.parameters is None
