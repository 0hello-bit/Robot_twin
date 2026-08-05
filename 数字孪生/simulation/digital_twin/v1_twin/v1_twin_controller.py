"""Firmware-equivalent line-following controller for Task 4B-5.

This module mirrors the PID portion of ``User/main.c`` without touching the
firmware.  Motor smoothing, curve overrides, line-loss recovery, and transport
are deliberately outside this small controller contract; the returned value
is the firmware's bounded integer ``target_turn``/``pid_output``.
"""

from __future__ import annotations

import math
import struct
from typing import Iterable, Sequence, Tuple


DEFAULT_KP = 35.0
DEFAULT_KI = 0.0
DEFAULT_KD = 10.0
DEFAULT_D_LIMIT = 0.8
DEFAULT_INTEGRAL_LIMIT = 100.0
DEFAULT_TURN_GAIN_K = 0.9
DEFAULT_TURN_LIMIT = 600
DEFAULT_LOOP_DT_S = 0.005


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError("{} must be numeric, not bool".format(name))
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("{} must be numeric".format(name)) from exc
    if not math.isfinite(result):
        raise ValueError("{} must be finite".format(name))
    return result


def _float32(value: float) -> float:
    """Round one operation to the STM32 C ``float`` representation."""
    try:
        return struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except OverflowError as exc:
        raise ValueError("value is outside float32 range") from exc


class V1Controller:
    """Stateful PID stepper matching the firmware's 5 ms control formula."""

    def __init__(
        self,
        kp: float = DEFAULT_KP,
        ki: float = DEFAULT_KI,
        kd: float = DEFAULT_KD,
        *,
        d_limit: float = DEFAULT_D_LIMIT,
        integral_limit: float = DEFAULT_INTEGRAL_LIMIT,
        turn_gain_k: float = DEFAULT_TURN_GAIN_K,
        turn_limit: int = DEFAULT_TURN_LIMIT,
    ) -> None:
        self.kp = _float32(_finite(kp, "kp"))
        self.ki = _float32(_finite(ki, "ki"))
        self.kd = _float32(_finite(kd, "kd"))
        self.d_limit = _float32(_finite(d_limit, "d_limit"))
        self.integral_limit = _float32(_finite(integral_limit, "integral_limit"))
        self.turn_gain_k = _float32(_finite(turn_gain_k, "turn_gain_k"))
        if self.d_limit < 0.0:
            raise ValueError("d_limit must be >= 0")
        if self.integral_limit < 0.0:
            raise ValueError("integral_limit must be >= 0")
        if self.turn_gain_k < 0.0:
            raise ValueError("turn_gain_k must be >= 0")
        if isinstance(turn_limit, bool) or not isinstance(turn_limit, int):
            raise ValueError("turn_limit must be an int")
        if turn_limit < 0:
            raise ValueError("turn_limit must be >= 0")
        self.turn_limit = turn_limit
        self.reset()

    def reset(self) -> None:
        """Reset the state that the firmware clears between controller runs."""
        self.previous_error = 0.0
        self.integral_error = 0.0
        self.last_derivative = 0.0
        self.last_raw_output = 0.0
        self.last_output = 0

    def step(self, error: float, dt_s: float = DEFAULT_LOOP_DT_S) -> int:
        """Advance one controller sample and return bounded integer turn output."""
        error_value = _float32(_finite(error, "error"))
        dt_value = _float32(_finite(dt_s, "dt_s"))
        if dt_value <= 0.0:
            raise ValueError("dt_s must be > 0")

        derivative = _float32(error_value - self.previous_error)
        derivative = max(-self.d_limit, min(self.d_limit, derivative))
        derivative = _float32(derivative)
        self.previous_error = error_value
        self.last_derivative = derivative

        integral_increment = _float32(error_value * dt_value)
        self.integral_error = _float32(self.integral_error + integral_increment)
        self.integral_error = max(
            -self.integral_limit,
            min(self.integral_limit, self.integral_error),
        )
        self.integral_error = _float32(self.integral_error)

        turn_gain = _float32(
            1.0 + _float32(abs(error_value) * self.turn_gain_k)
        )
        proportional = _float32(self.kp * error_value)
        integral = _float32(self.ki * self.integral_error)
        derivative_term = _float32(self.kd * derivative)
        pid_sum = _float32(_float32(proportional + integral) + derivative_term)
        raw_output = _float32(pid_sum * turn_gain)
        self.last_raw_output = raw_output

        # C's cast from a finite float to int truncates toward zero, matching
        # Python's int() for the finite values accepted above.
        output = int(raw_output)
        output = max(-self.turn_limit, min(self.turn_limit, output))
        self.last_output = output
        return output

    def run(self, samples: Iterable[Tuple[float, float]]) -> Tuple[int, ...]:
        """Run a sequence of ``(error, dt_s)`` samples from current state."""
        return tuple(self.step(error, dt_s) for error, dt_s in samples)

    def validate_against_firmware(
        self,
        samples: Sequence[Tuple[float, float]],
        expected_outputs: Sequence[int],
    ) -> dict:
        """Compare a batch with independently produced firmware outputs.

        The expected values are supplied by the caller (for example a Host-C
        fixture), so this method does not certify itself using a duplicate
        implementation hidden inside the production module.
        """
        if len(samples) != len(expected_outputs):
            raise ValueError("samples and expected_outputs must have equal length")
        self.reset()
        actual = self.run(samples)
        mismatches = []
        for index, (got, expected) in enumerate(zip(actual, expected_outputs)):
            if got != expected:
                mismatches.append({
                    "index": index,
                    "expected": int(expected),
                    "actual": int(got),
                })
        return {
            "passed": not mismatches,
            "sample_count": len(samples),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
        }
