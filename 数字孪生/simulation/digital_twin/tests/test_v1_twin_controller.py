"""Offline contract tests for the firmware-equivalent 4B-5 controller."""

from __future__ import annotations

import math
import struct

import pytest

from v1_twin.v1_twin_controller import V1Controller


def _firmware_reference(samples, kp, ki, kd):
    def f32(value):
        return struct.unpack("<f", struct.pack("<f", float(value)))[0]

    kp, ki, kd = f32(kp), f32(ki), f32(kd)
    integral = f32(0.0)
    previous = f32(0.0)
    outputs = []
    for error, dt_s in samples:
        error = f32(error)
        dt_s = f32(dt_s)
        derivative = f32(error - previous)
        derivative = max(-0.8, min(0.8, derivative))
        derivative = f32(derivative)
        previous = error
        integral = f32(integral + f32(error * dt_s))
        integral = max(-100.0, min(100.0, integral))
        integral = f32(integral)
        turn_gain = f32(1.0 + f32(abs(error) * f32(0.9)))
        raw_sum = f32(f32(kp * error) + f32(ki * integral))
        raw_sum = f32(raw_sum + f32(kd * derivative))
        raw = f32(raw_sum * turn_gain)
        outputs.append(max(-600, min(600, int(raw))))
    return outputs


@pytest.mark.parametrize(
    "kp,ki,kd",
    [(35.0, 0.0, 10.0), (20.0, 0.5, 4.0), (0.0, 2.0, 0.0)],
)
def test_controller_matches_independent_firmware_oracle(kp, ki, kd):
    samples = [
        (-2.5, 0.005),
        (-0.45, 0.005),
        (0.45, 0.005),
        (2.5, 0.005),
        (0.0, 0.010),
    ]
    expected = _firmware_reference(samples, kp, ki, kd)
    controller = V1Controller(kp=kp, ki=ki, kd=kd)

    actual = [controller.step(error, dt_s) for error, dt_s in samples]

    assert actual == expected
    assert all(isinstance(value, int) for value in actual)


def test_controller_limits_derivative_integral_and_output():
    controller = V1Controller(kp=0.0, ki=10.0, kd=1000.0)

    first = controller.step(100.0, 1.0)
    second = controller.step(-100.0, 1.0)

    assert first == 600
    assert second == -600
    assert controller.integral_error == pytest.approx(0.0)
    assert controller.last_derivative == pytest.approx(-0.8)


def test_controller_reset_discards_history():
    controller = V1Controller(kp=0.0, ki=1.0, kd=1.0)
    controller.step(10.0, 0.5)
    assert controller.integral_error != 0.0

    controller.reset()

    assert controller.integral_error == 0.0
    assert controller.previous_error == 0.0
    assert controller.last_derivative == 0.0
    assert controller.step(1.0, 0.005) == 1


def test_validate_against_firmware_returns_structured_report():
    samples = [(-2.5, 0.005), (0.45, 0.005), (2.5, 0.005)]
    expected = _firmware_reference(samples, 35.0, 0.0, 10.0)
    controller = V1Controller()

    report = controller.validate_against_firmware(samples, expected)

    assert report == {
        "passed": True,
        "sample_count": 3,
        "mismatch_count": 0,
        "mismatches": [],
    }


def test_controller_rejects_non_finite_or_non_positive_dt():
    controller = V1Controller()
    for error, dt_s in [(0.0, 0.0), (0.0, -0.001), (math.nan, 0.005),
                        (0.0, math.inf)]:
        with pytest.raises(ValueError):
            controller.step(error, dt_s)


def test_controller_matches_c_float32_rounding_at_integer_boundary():
    controller = V1Controller(
        kp=64.67341392609393,
        ki=0.34459354618645754,
        kd=-39.71365849734059,
    )

    # The STM32 evaluates this expression with 32-bit float operands.  The
    # correctly truncated C result is -432; double-only arithmetic yields -431.
    assert controller.step(-2.5297027918029604, 0.005802159071989879) == -432
