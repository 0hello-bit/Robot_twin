"""Low-parameter four-wheel vehicle plant for Task 4B-6.

The model deliberately stays below the formal 4B-7/4B-8 boundary.  It is a
deterministic, software-testable interface for later identification from
synchronised runs; it does not claim that its default parameters describe the
physical car.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

from .v1_twin_schema import V1Pose


PWM_COUNT = 4
BODY_AXIS_COUNT = 3
DEFAULT_PWM_LIMIT = 650.0

# Wheel order is the telemetry order M1..M4.  This is the canonical signed
# mecanum mix used by the exploratory model.  The coefficients are kept in the
# parameters object so a later calibration can reject or replace the assumed
# wheel-order convention with explicit evidence.
DEFAULT_MIX_MATRIX: Tuple[float, ...] = (
    0.25, 0.25, 0.25, 0.25,    # vx
   -0.25, 0.25, 0.25, -0.25,    # vy
   -0.25, 0.25, -0.25, 0.25,    # omega
)


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


def _tuple_finite(values: Sequence[object], count: int, name: str) -> Tuple[float, ...]:
    if len(values) != count:
        raise ValueError("{} must have exactly {} entries".format(name, count))
    return tuple(_finite(value, "{}[{}]".format(name, i)) for i, value in enumerate(values))


@dataclass(frozen=True)
class V1BodyVelocity:
    """Body-frame velocity in mm/s, mm/s, and rad/s respectively."""

    vx_mm_s: float
    vy_mm_s: float
    omega_rad_s: float

    def __post_init__(self) -> None:
        _finite(self.vx_mm_s, "vx_mm_s")
        _finite(self.vy_mm_s, "vy_mm_s")
        _finite(self.omega_rad_s, "omega_rad_s")

    def as_tuple(self) -> Tuple[float, float, float]:
        return (float(self.vx_mm_s), float(self.vy_mm_s), float(self.omega_rad_s))


@dataclass(frozen=True)
class V1PlantParameters:
    """Small parameter set used by the exploratory plant.

    ``wheel_gains`` are shared across the three rows of the fixed mix matrix;
    ``body_bias`` is a three-axis additive offset.  A per-wheel deadzone and a
    command delay are explicit because both are common in this firmware path.
    ``mix_matrix`` is recorded with the parameters to make wheel-order
    assumptions auditable instead of hiding them in the implementation.
    """

    wheel_gains: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    body_bias: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    deadzone: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    delay_steps: int = 0
    pwm_limit: float = DEFAULT_PWM_LIMIT
    mix_matrix: Tuple[float, ...] = DEFAULT_MIX_MATRIX

    def __post_init__(self) -> None:
        object.__setattr__(self, "wheel_gains", _tuple_finite(self.wheel_gains, 4, "wheel_gains"))
        object.__setattr__(self, "body_bias", _tuple_finite(self.body_bias, 3, "body_bias"))
        object.__setattr__(self, "deadzone", _tuple_finite(self.deadzone, 4, "deadzone"))
        object.__setattr__(self, "mix_matrix", _tuple_finite(self.mix_matrix, 12, "mix_matrix"))
        limit = _finite(self.pwm_limit, "pwm_limit")
        if limit <= 0.0:
            raise ValueError("pwm_limit must be > 0")
        object.__setattr__(self, "pwm_limit", limit)
        if isinstance(self.delay_steps, bool) or not isinstance(self.delay_steps, int):
            raise ValueError("delay_steps must be an int")
        if self.delay_steps < 0:
            raise ValueError("delay_steps must be >= 0")
        if any(value < 0.0 or value > limit for value in self.deadzone):
            raise ValueError("deadzone values must be within [0, pwm_limit]")


class V1Plant:
    """Stateful PWM-to-body-velocity model with deterministic pose integration."""

    def __init__(self, parameters: V1PlantParameters | None = None) -> None:
        if parameters is None:
            parameters = V1PlantParameters()
        if not isinstance(parameters, V1PlantParameters):
            raise TypeError("parameters must be a V1PlantParameters")
        self.parameters = parameters
        self.reset()

    def reset(self) -> None:
        """Clear the command-delay state."""
        self._delay_buffer: list[Tuple[float, float, float, float]] = []

    def step(self, pwm: Sequence[object], dt_s: float) -> V1BodyVelocity:
        """Convert one signed four-channel PWM command to body velocity."""
        command = self._validate_pwm(pwm)
        dt = _finite(dt_s, "dt_s")
        if dt <= 0.0:
            raise ValueError("dt_s must be > 0")

        delayed = self._delayed_command(command)
        effective = tuple(
            math.copysign(max(abs(value) - deadzone, 0.0), value)
            if value != 0.0 else 0.0
            for value, deadzone in zip(delayed, self.parameters.deadzone)
        )

        outputs = []
        matrix = self.parameters.mix_matrix
        for axis in range(BODY_AXIS_COUNT):
            total = self.parameters.body_bias[axis]
            row_start = axis * PWM_COUNT
            for wheel in range(PWM_COUNT):
                total += (
                    matrix[row_start + wheel]
                    * effective[wheel]
                    * self.parameters.wheel_gains[wheel]
                )
            outputs.append(total)
        return V1BodyVelocity(*outputs)

    def predict(
        self,
        commands: Iterable[Tuple[Sequence[object], float]],
        *,
        initial_pose: V1Pose,
    ) -> Tuple[V1Pose, ...]:
        """Integrate commands into a simulated metric pose trajectory.

        The returned poses are the state *after* each command interval.  This
        method resets command-delay state so repeated predictions are
        reproducible.
        """
        if not isinstance(initial_pose, V1Pose):
            raise TypeError("initial_pose must be a V1Pose")
        self.reset()
        x = float(initial_pose.x_mm)
        y = float(initial_pose.y_mm)
        yaw = float(initial_pose.yaw_rad)
        t_ns = int(initial_pose.t_pc_ns)
        poses = []
        for pwm, dt_s in commands:
            dt = _finite(dt_s, "dt_s")
            if dt <= 0.0:
                raise ValueError("dt_s must be > 0")
            velocity = self.step(pwm, dt)
            cos_yaw = math.cos(yaw)
            sin_yaw = math.sin(yaw)
            x += (velocity.vx_mm_s * cos_yaw - velocity.vy_mm_s * sin_yaw) * dt
            y += (velocity.vx_mm_s * sin_yaw + velocity.vy_mm_s * cos_yaw) * dt
            yaw += velocity.omega_rad_s * dt
            t_ns += int(round(dt * 1_000_000_000.0))
            poses.append(V1Pose(
                x_mm=x,
                y_mm=y,
                yaw_rad=yaw,
                confidence=initial_pose.confidence,
                t_pc_ns=t_ns,
                source="simulated",
                schema_version=initial_pose.schema_version,
            ))
        return tuple(poses)

    @classmethod
    def identify(cls, samples, **kwargs):
        """Fit samples or a synchronized-frame/dataset object without mutation."""
        from .v1_twin_identification import V1Identification

        if hasattr(samples, "sync_frames"):
            samples = samples.sync_frames
        samples = tuple(samples)
        if samples and hasattr(samples[0], "pose") and hasattr(samples[0], "telemetry"):
            return V1Identification.from_sync_frames(samples, **kwargs)
        return V1Identification.identify(samples, **kwargs)

    def _delayed_command(
        self,
        command: Tuple[float, float, float, float],
    ) -> Tuple[float, float, float, float]:
        delay = self.parameters.delay_steps
        if delay == 0:
            return command
        self._delay_buffer.append(command)
        if len(self._delay_buffer) <= delay:
            return (0.0, 0.0, 0.0, 0.0)
        return self._delay_buffer.pop(0)

    def _validate_pwm(self, pwm: Sequence[object]) -> Tuple[float, float, float, float]:
        try:
            length = len(pwm)
        except TypeError as exc:
            raise ValueError("pwm must contain exactly four channels") from exc
        if isinstance(pwm, (str, bytes)) or length != PWM_COUNT:
            raise ValueError("pwm must contain exactly four channels")
        values = tuple(_finite(value, "pwm[{}]".format(i)) for i, value in enumerate(pwm))
        if any(abs(value) > self.parameters.pwm_limit for value in values):
            raise ValueError("pwm values must be within +/-pwm_limit")
        return values  # type: ignore[return-value]
