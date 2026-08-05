"""Deterministic offline V1 closed-loop prediction and candidate ranking.

The module is intentionally hardware-free.  It connects the existing
firmware-equivalent controller, metric vehicle plant, and geometry-based
virtual sensor into one reproducible prediction path:

    initial pose + track + PID candidate -> controller -> plant -> sensor
    -> next pose

The default plant is exploratory.  A prediction is useful for software
regression and candidate comparison, but it is never a claim that the model
matches the physical car until real synchronized calibration and holdout
evidence is supplied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from .v1_twin_controller import DEFAULT_LOOP_DT_S, V1Controller
from .v1_twin_plant import V1BodyVelocity, V1Plant
from .v1_twin_schema import V1Pose, V1SensorModelConfig, V1TrackMap
from .v1_twin_virtual_sensor import V1VirtualSensor, VirtualSensorReading


PID_PARAMETER_VERSION = "runtime-pid-v1"
PID_PARAMETER_UNITS = {
    "kp": "turn_count_per_error",
    "ki": "turn_count_per_error_second",
    "kd": "turn_count_per_error",
    "speed_max": "pwm_count",
}

KP_MIN = 20.0
KP_MAX = 50.0
KI_MIN = 0.0
KI_MAX = 5.0
KD_MIN = 5.0
KD_MAX = 20.0
SPEED_MIN = 260.0
SPEED_MAX = 680.0
MOTOR_LIMIT = 650
SPEED_ERR_DECAY = 22.0
TURN_LIMIT = 600


class V1ClosedLoopError(ValueError):
    """Raised when a prediction input cannot be validated without guessing."""


class V1PredictionError(V1ClosedLoopError):
    """Raised when the offline predictor cannot produce a valid result."""


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise V1ClosedLoopError("{} must be numeric, not bool".format(name))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise V1ClosedLoopError("{} must be numeric".format(name)) from exc
    if not math.isfinite(number):
        raise V1ClosedLoopError("{} must be finite".format(name))
    return number


def _non_empty_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise V1ClosedLoopError("{} must be a non-empty string".format(name))
    return value.strip()


def _bounded(value: object, name: str, lower: float, upper: float) -> float:
    number = _finite(value, name)
    if number < lower or number > upper:
        raise V1ClosedLoopError(
            "{} must be within [{}, {}]".format(name, lower, upper)
        )
    return number


def _tuple_text(values: Iterable[object], name: str) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise V1ClosedLoopError("{} must be an iterable of run IDs".format(name))
    try:
        result = tuple(_non_empty_text(value, "{} item".format(name)) for value in values)
    except TypeError as exc:
        raise V1ClosedLoopError("{} must be an iterable of run IDs".format(name)) from exc
    if len(set(result)) != len(result):
        raise V1ClosedLoopError("{} must not contain duplicate run IDs".format(name))
    return tuple(sorted(result))


@dataclass(frozen=True)
class V1PidCandidate:
    """A bounded runtime PID candidate matching the firmware protocol.

    ``kp``, ``ki`` and ``kd`` use the controller's dimensionless line-error
    convention and produce bounded turn-count output.  ``speed_max`` is a
    signed-PWM magnitude in firmware counts.  Bounds mirror
    ``twin_control_protocol.h`` and ``parameter_version`` makes the contract
    explicit in every serialized prediction.
    """

    candidate_id: str
    kp: float
    ki: float
    kd: float
    speed_max: float
    parameter_version: str = PID_PARAMETER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _non_empty_text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "kp", _bounded(self.kp, "kp", KP_MIN, KP_MAX))
        object.__setattr__(self, "ki", _bounded(self.ki, "ki", KI_MIN, KI_MAX))
        object.__setattr__(self, "kd", _bounded(self.kd, "kd", KD_MIN, KD_MAX))
        object.__setattr__(self, "speed_max", _bounded(self.speed_max, "speed_max", SPEED_MIN, SPEED_MAX))
        object.__setattr__(self, "parameter_version", _non_empty_text(self.parameter_version, "parameter_version"))

    def controller(self) -> V1Controller:
        return V1Controller(kp=self.kp, ki=self.ki, kd=self.kd)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "kp": self.kp,
            "ki": self.ki,
            "kd": self.kd,
            "speed_max": self.speed_max,
            "parameter_version": self.parameter_version,
            "units": dict(PID_PARAMETER_UNITS),
            "bounds": {
                "kp": [KP_MIN, KP_MAX],
                "ki": [KI_MIN, KI_MAX],
                "kd": [KD_MIN, KD_MAX],
                "speed_max": [SPEED_MIN, SPEED_MAX],
            },
        }


@dataclass(frozen=True)
class V1CalibrationEvidence:
    """Evidence state consumed by the candidate evaluator.

    Only a verified real synchronized calibration with disjoint holdout runs
    can make ``ready`` true.  Synthetic fixtures and missing evidence remain
    explicitly non-ready.
    """

    status: str
    source: str
    calibration_run_ids: Tuple[str, ...] = ()
    holdout_run_ids: Tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        status = _non_empty_text(self.status, "status")
        source = _non_empty_text(self.source, "source")
        if status not in ("VERIFIED", "INSUFFICIENT_EVIDENCE"):
            raise V1ClosedLoopError("unsupported calibration evidence status")
        calibration = _tuple_text(self.calibration_run_ids, "calibration_run_ids")
        holdout = _tuple_text(self.holdout_run_ids, "holdout_run_ids")
        if set(calibration) & set(holdout):
            raise V1ClosedLoopError("calibration/holdout run_id overlap")
        if status == "VERIFIED" and source != "REAL_SYNC":
            raise V1ClosedLoopError("only REAL_SYNC evidence may be VERIFIED")
        if status == "VERIFIED" and (not calibration or not holdout):
            raise V1ClosedLoopError("VERIFIED evidence requires calibration and holdout run IDs")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "calibration_run_ids", calibration)
        object.__setattr__(self, "holdout_run_ids", holdout)
        object.__setattr__(self, "reason", str(self.reason))

    @classmethod
    def none(cls) -> "V1CalibrationEvidence":
        return cls(
            status="INSUFFICIENT_EVIDENCE",
            source="NONE",
            reason="real synchronized calibration and holdout evidence is missing",
        )

    @property
    def ready(self) -> bool:
        return (
            self.status == "VERIFIED"
            and self.source == "REAL_SYNC"
            and bool(self.calibration_run_ids)
            and bool(self.holdout_run_ids)
            and not set(self.calibration_run_ids) & set(self.holdout_run_ids)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "calibration_run_ids": list(self.calibration_run_ids),
            "holdout_run_ids": list(self.holdout_run_ids),
            "reason": self.reason,
            "ready": self.ready,
        }


@dataclass(frozen=True)
class V1ClosedLoopConfig:
    """Numerical and safety settings for one deterministic prediction."""

    plant: V1Plant
    sensor_config: V1SensorModelConfig
    dt_s: float = 0.005
    max_steps: int = 4000
    line_loss_patience_steps: int = 3
    completion_tolerance_mm: float = 8.0
    error_filter_old: float = 0.65
    error_filter_new: float = 0.35
    turn_filter_old: float = 0.55
    turn_filter_new: float = 0.45
    speed_filter_old: float = 0.75
    speed_filter_new: float = 0.25
    calibration_evidence: V1CalibrationEvidence = V1CalibrationEvidence.none()

    def __post_init__(self) -> None:
        if not isinstance(self.plant, V1Plant):
            raise V1ClosedLoopError("plant must be a V1Plant")
        if not isinstance(self.sensor_config, V1SensorModelConfig):
            raise V1ClosedLoopError("sensor_config must be a V1SensorModelConfig")
        dt = _finite(self.dt_s, "dt_s")
        if abs(dt - DEFAULT_LOOP_DT_S) > 1e-12:
            raise V1ClosedLoopError(
                "dt_s must equal the firmware 5 ms sampling period"
            )
        for name in ("max_steps", "line_loss_patience_steps"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise V1ClosedLoopError("{} must be a positive int".format(name))
        tolerance = _finite(self.completion_tolerance_mm, "completion_tolerance_mm")
        if tolerance < 0.0:
            raise V1ClosedLoopError("completion_tolerance_mm must be >= 0")
        for old_name, new_name in (
            ("error_filter_old", "error_filter_new"),
            ("turn_filter_old", "turn_filter_new"),
            ("speed_filter_old", "speed_filter_new"),
        ):
            old = _bounded(getattr(self, old_name), old_name, 0.0, 1.0)
            new = _bounded(getattr(self, new_name), new_name, 0.0, 1.0)
            if abs((old + new) - 1.0) > 1e-9:
                raise V1ClosedLoopError("{} + {} must equal 1".format(old_name, new_name))
        if not isinstance(self.calibration_evidence, V1CalibrationEvidence):
            raise V1ClosedLoopError("calibration_evidence must be V1CalibrationEvidence")
        object.__setattr__(self, "dt_s", dt)
        object.__setattr__(self, "completion_tolerance_mm", tolerance)


@dataclass(frozen=True)
class V1PredictionTrace:
    """One closed-loop sample after the command has advanced the plant."""

    step_index: int
    elapsed_s: float
    pose: V1Pose
    sensor_reading: VirtualSensorReading
    controller_error: float
    pid_output: int
    pwm_command: Tuple[int, int, int, int]
    predicted_velocity_mm_s: Tuple[float, float, float]
    progress_mm: float
    distance_to_centerline_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "elapsed_s": self.elapsed_s,
            "pose": self.pose.to_dict(),
            "sensor_reading": {
                "sensors": list(self.sensor_reading.sensors),
                "error": self.sensor_reading.error,
                "line_lost": self.sensor_reading.line_lost,
                "black_count": self.sensor_reading.black_count,
                "sensor_points_mm": [list(point) for point in self.sensor_reading.sensor_points_mm],
            },
            "controller_error": self.controller_error,
            "pid_output": self.pid_output,
            "pwm_command": list(self.pwm_command),
            "predicted_velocity_mm_s": list(self.predicted_velocity_mm_s),
            "progress_mm": self.progress_mm,
            "distance_to_centerline_mm": self.distance_to_centerline_mm,
        }


@dataclass(frozen=True)
class V1PredictionResult:
    candidate: V1PidCandidate
    status: str
    terminal_class: str
    line_lost: bool
    completed: bool
    completion_time_s: Optional[float]
    steps: int
    final_pose: Optional[V1Pose]
    trace: Tuple[V1PredictionTrace, ...]
    predicted_distance_mm: float
    predicted_speed_mean_mm_s: float
    max_abs_error: float
    model_version: str
    track_asset_version: str
    seed: int
    calibration_evidence: str
    failure_reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, V1PidCandidate):
            raise V1ClosedLoopError("candidate must be V1PidCandidate")
        if self.status not in ("PREDICTED", "FAILED"):
            raise V1ClosedLoopError("unsupported prediction status")
        if self.terminal_class not in ("completed", "line_loss", "timeout", "prediction_failed"):
            raise V1ClosedLoopError("unsupported terminal_class")
        if not isinstance(self.line_lost, bool) or not isinstance(self.completed, bool):
            raise V1ClosedLoopError("line_lost and completed must be bool")
        if self.status == "FAILED" and self.terminal_class != "prediction_failed":
            raise V1ClosedLoopError("failed predictions must use prediction_failed")
        if self.status == "PREDICTED" and self.terminal_class == "prediction_failed":
            raise V1ClosedLoopError("predicted results cannot use prediction_failed")
        if self.completion_time_s is not None and _finite(self.completion_time_s, "completion_time_s") < 0.0:
            raise V1ClosedLoopError("completion_time_s must be >= 0")
        if isinstance(self.steps, bool) or not isinstance(self.steps, int) or self.steps < 0:
            raise V1ClosedLoopError("steps must be a non-negative int")
        if self.final_pose is not None and not isinstance(self.final_pose, V1Pose):
            raise V1ClosedLoopError("final_pose must be V1Pose or None")
        if _finite(self.predicted_distance_mm, "predicted_distance_mm") < 0.0:
            raise V1ClosedLoopError("predicted_distance_mm must be >= 0")
        if _finite(self.predicted_speed_mean_mm_s, "predicted_speed_mean_mm_s") < 0.0:
            raise V1ClosedLoopError("predicted_speed_mean_mm_s must be >= 0")
        if _finite(self.max_abs_error, "max_abs_error") < 0.0:
            raise V1ClosedLoopError("max_abs_error must be >= 0")
        _non_empty_text(self.model_version, "model_version")
        _non_empty_text(self.track_asset_version, "track_asset_version")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise V1ClosedLoopError("seed must be an int")
        _non_empty_text(self.calibration_evidence, "calibration_evidence")

    @classmethod
    def failed(
        cls,
        candidate: V1PidCandidate,
        *,
        model_version: str,
        track_asset_version: str,
        seed: int,
        calibration_evidence: str,
        reason: str,
    ) -> "V1PredictionResult":
        return cls(
            candidate=candidate,
            status="FAILED",
            terminal_class="prediction_failed",
            line_lost=False,
            completed=False,
            completion_time_s=None,
            steps=0,
            final_pose=None,
            trace=(),
            predicted_distance_mm=0.0,
            predicted_speed_mean_mm_s=0.0,
            max_abs_error=0.0,
            model_version=model_version,
            track_asset_version=track_asset_version,
            seed=seed,
            calibration_evidence=calibration_evidence,
            failure_reason=_non_empty_text(reason, "reason"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "status": self.status,
            "terminal_class": self.terminal_class,
            "line_lost": self.line_lost,
            "completed": self.completed,
            "completion_time_s": self.completion_time_s,
            "steps": self.steps,
            "final_pose": None if self.final_pose is None else self.final_pose.to_dict(),
            "trace": [item.to_dict() for item in self.trace],
            "predicted_distance_mm": self.predicted_distance_mm,
            "predicted_speed_mean_mm_s": self.predicted_speed_mean_mm_s,
            "max_abs_error": self.max_abs_error,
            "model_version": self.model_version,
            "track_asset_version": self.track_asset_version,
            "seed": self.seed,
            "calibration_evidence": self.calibration_evidence,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class V1CandidateEvaluation:
    """Predictions and deterministic ranking for one baseline/candidate set."""

    status: str
    predictions: Tuple[V1PredictionResult, ...]
    ranking: Tuple[str, ...]
    selected_candidate_id: Optional[str]
    evidence_status: str
    evidence_reason: str
    ready: bool
    model_version: str
    track_asset_version: str
    seed: int
    calibration_run_ids: Tuple[str, ...]
    holdout_run_ids: Tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "predictions": [item.to_dict() for item in self.predictions],
            "ranking": list(self.ranking),
            "selected_candidate_id": self.selected_candidate_id,
            "evidence_status": self.evidence_status,
            "evidence_reason": self.evidence_reason,
            "ready": self.ready,
            "model_version": self.model_version,
            "track_asset_version": self.track_asset_version,
            "seed": self.seed,
            "calibration_run_ids": list(self.calibration_run_ids),
            "holdout_run_ids": list(self.holdout_run_ids),
        }


class V1ClosedLoopPredictor:
    """Run one candidate through controller -> plant -> virtual sensor."""

    def __init__(
        self,
        *,
        config: V1ClosedLoopConfig,
        model_version: str,
        track_asset_version: str,
        seed: int = 0,
    ) -> None:
        if not isinstance(config, V1ClosedLoopConfig):
            raise V1ClosedLoopError("config must be V1ClosedLoopConfig")
        self.config = config
        self.model_version = _non_empty_text(model_version, "model_version")
        self.track_asset_version = _non_empty_text(track_asset_version, "track_asset_version")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise V1ClosedLoopError("seed must be an int")
        self.seed = seed

    @property
    def calibration_evidence(self) -> V1CalibrationEvidence:
        return self.config.calibration_evidence

    def predict(
        self,
        candidate: V1PidCandidate,
        *,
        initial_pose: V1Pose,
        track_map: V1TrackMap,
    ) -> V1PredictionResult:
        if not isinstance(candidate, V1PidCandidate):
            raise V1PredictionError("candidate must be V1PidCandidate")
        if not isinstance(initial_pose, V1Pose):
            raise V1PredictionError("initial_pose must be V1Pose")
        if not isinstance(track_map, V1TrackMap):
            raise V1PredictionError("track_map must be V1TrackMap")
        if len(track_map.centerline_mm) < 2:
            raise V1PredictionError("track_map needs at least two centerline points")

        total_length = self._track_length(track_map)
        if total_length <= 0.0:
            raise V1PredictionError("track_map centerline length must be > 0")

        plant = self.config.plant
        plant.reset()
        controller = candidate.controller()
        sensor = V1VirtualSensor(self.config.sensor_config)
        pose = initial_pose
        previous_sensor_error = 0.0
        sm_error = 0.0
        sm_turn = 0.0
        sm_speed = min(400.0, candidate.speed_max)
        last_direction = 1
        loss_steps = 0
        line_lost_seen = False
        previous_pwm = (0, 0, 0, 0)
        trace = []
        travelled_mm = 0.0
        speed_integral = 0.0
        max_abs_error = 0.0
        terminal_class = "timeout"
        completed = False

        for step_index in range(self.config.max_steps):
            reading = sensor.read(pose, track_map, previous_sensor_error)
            if reading.line_lost:
                line_lost_seen = True
                loss_steps += 1
                if loss_steps <= 3:
                    pwm = previous_pwm
                    pid_output = 0
                    controller_error = sm_error
                else:
                    pwm = self._recovery_pwm(last_direction)
                    pid_output = 0
                    controller_error = sm_error
            else:
                loss_steps = 0
                sm_error = (
                    self.config.error_filter_old * sm_error
                    + self.config.error_filter_new * reading.error
                )
                # Firmware pattern 0x0F holds the filtered ``sm_err``.  Feed
                # that state back to the virtual sensor so the all-black
                # branch cannot regress to an unfiltered raw error.
                previous_sensor_error = sm_error
                max_abs_error = max(max_abs_error, abs(sm_error))
                controller_error = sm_error
                pid_output = controller.step(sm_error, self.config.dt_s)
                target_speed = int(
                    candidate.speed_max - abs(sm_error) * SPEED_ERR_DECAY
                )
                target_speed = max(int(SPEED_MIN), min(int(candidate.speed_max), target_speed))
                target_turn = max(-TURN_LIMIT, min(TURN_LIMIT, pid_output))
                sm_speed = (
                    self.config.speed_filter_old * sm_speed
                    + self.config.speed_filter_new * target_speed
                )
                sm_turn = (
                    self.config.turn_filter_old * sm_turn
                    + self.config.turn_filter_new * target_turn
                )
                speed = int(sm_speed)
                turn = int(sm_turn)
                if sm_error > 0.0:
                    last_direction = 1
                elif sm_error < 0.0:
                    last_direction = -1
                speed, turn = self._apply_curve_override(
                    reading.sensors, speed, turn, int(candidate.speed_max)
                )
                pwm = self._differential_to_wheels(speed, turn)

            velocity = plant.step(pwm, self.config.dt_s)
            pose = self._advance_pose(pose, velocity, self.config.dt_s)
            progress, distance = self._progress_and_distance(pose, track_map)
            elapsed_s = (step_index + 1) * self.config.dt_s
            speed_now = math.sqrt(
                velocity.vx_mm_s * velocity.vx_mm_s
                + velocity.vy_mm_s * velocity.vy_mm_s
            )
            travelled_mm += speed_now * self.config.dt_s
            speed_integral += speed_now * self.config.dt_s
            trace.append(
                V1PredictionTrace(
                    step_index=step_index,
                    elapsed_s=elapsed_s,
                    pose=pose,
                    sensor_reading=reading,
                    controller_error=controller_error,
                    pid_output=pid_output,
                    pwm_command=tuple(int(value) for value in pwm),
                    predicted_velocity_mm_s=velocity.as_tuple(),
                    progress_mm=progress,
                    distance_to_centerline_mm=distance,
                )
            )
            previous_pwm = tuple(int(value) for value in pwm)

            if progress >= total_length - self.config.completion_tolerance_mm:
                completed = True
                terminal_class = "completed"
                break
            if loss_steps >= self.config.line_loss_patience_steps:
                terminal_class = "line_loss"
                break

        completion_time = trace[-1].elapsed_s if completed and trace else None
        return V1PredictionResult(
            candidate=candidate,
            status="PREDICTED",
            terminal_class=terminal_class,
            line_lost=line_lost_seen,
            completed=completed,
            completion_time_s=completion_time,
            steps=len(trace),
            final_pose=pose,
            trace=tuple(trace),
            predicted_distance_mm=travelled_mm,
            predicted_speed_mean_mm_s=(speed_integral / trace[-1].elapsed_s if trace else 0.0),
            max_abs_error=max_abs_error,
            model_version=self.model_version,
            track_asset_version=self.track_asset_version,
            seed=self.seed,
            calibration_evidence=self.calibration_evidence.status,
        )

    @staticmethod
    def _track_length(track_map: V1TrackMap) -> float:
        return sum(
            math.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(track_map.centerline_mm, track_map.centerline_mm[1:])
        )

    @staticmethod
    def _progress_and_distance(pose: V1Pose, track_map: V1TrackMap) -> Tuple[float, float]:
        best_distance_sq = math.inf
        best_progress = 0.0
        cumulative = 0.0
        for (ax, ay), (bx, by) in zip(track_map.centerline_mm, track_map.centerline_mm[1:]):
            vx = bx - ax
            vy = by - ay
            length = math.hypot(vx, vy)
            if length == 0.0:
                cumulative += length
                continue
            t = ((pose.x_mm - ax) * vx + (pose.y_mm - ay) * vy) / (length * length)
            t = max(0.0, min(1.0, t))
            near_x = ax + t * vx
            near_y = ay + t * vy
            distance_sq = (pose.x_mm - near_x) ** 2 + (pose.y_mm - near_y) ** 2
            if distance_sq < best_distance_sq:
                best_distance_sq = distance_sq
                best_progress = cumulative + t * length
            cumulative += length
        return best_progress, math.sqrt(best_distance_sq)

    @staticmethod
    def _advance_pose(pose: V1Pose, velocity: V1BodyVelocity, dt_s: float) -> V1Pose:
        cos_yaw = math.cos(pose.yaw_rad)
        sin_yaw = math.sin(pose.yaw_rad)
        return V1Pose(
            x_mm=pose.x_mm + (velocity.vx_mm_s * cos_yaw - velocity.vy_mm_s * sin_yaw) * dt_s,
            y_mm=pose.y_mm + (velocity.vx_mm_s * sin_yaw + velocity.vy_mm_s * cos_yaw) * dt_s,
            yaw_rad=pose.yaw_rad + velocity.omega_rad_s * dt_s,
            confidence=pose.confidence,
            t_pc_ns=pose.t_pc_ns + int(round(dt_s * 1_000_000_000.0)),
            source="simulated",
            schema_version=pose.schema_version,
        )

    @staticmethod
    def _differential_to_wheels(speed: int, turn: int) -> Tuple[int, int, int, int]:
        left = max(-MOTOR_LIMIT, min(MOTOR_LIMIT, speed + turn))
        right = max(-MOTOR_LIMIT, min(MOTOR_LIMIT, speed - turn))
        # The firmware telemetry exposes the two differential outputs as
        # (left, right, right, left) for the four-wheel plant interface.
        return (left, right, right, left)

    @staticmethod
    def _recovery_pwm(direction: int) -> Tuple[int, int, int, int]:
        outer = MOTOR_LIMIT if direction >= 0 else -200
        inner = -200 if direction >= 0 else MOTOR_LIMIT
        return (outer, inner, inner, outer)

    @staticmethod
    def _apply_curve_override(
        sensors: Tuple[int, int, int, int], speed: int, turn: int, speed_max: int
    ) -> Tuple[int, int]:
        pattern = (sensors[0] << 3) | (sensors[1] << 2) | (sensors[2] << 1) | sensors[3]
        if pattern in (0x08, 0x0C):
            speed = max(int(SPEED_MIN), min(speed_max, int(SPEED_MIN)))
            turn = -(speed - (-260) + 60)
        elif pattern == 0x04:
            speed = max(int(SPEED_MIN), min(speed_max, int(SPEED_MIN)))
            turn = -(speed - (-120) + 20)
        elif pattern == 0x02:
            speed = max(int(SPEED_MIN), min(speed_max, int(SPEED_MIN)))
            turn = speed - (-120) + 20
        elif pattern in (0x03, 0x01):
            speed = max(int(SPEED_MIN), min(speed_max, int(SPEED_MIN)))
            turn = speed - (-260) + 60
        return speed, turn


class V1CandidateEvaluator:
    """Evaluate baseline plus at least two candidates on one frozen model."""

    def __init__(self, predictor: V1ClosedLoopPredictor) -> None:
        if not isinstance(predictor, V1ClosedLoopPredictor):
            raise V1ClosedLoopError("predictor must be V1ClosedLoopPredictor")
        self.predictor = predictor

    def evaluate(
        self,
        *,
        baseline: V1PidCandidate,
        candidates: Sequence[V1PidCandidate],
        initial_pose: V1Pose,
        track_map: V1TrackMap,
        calibration_run_ids: Iterable[object] = (),
        holdout_run_ids: Iterable[object] = (),
    ) -> V1CandidateEvaluation:
        if not isinstance(baseline, V1PidCandidate):
            raise V1ClosedLoopError("baseline must be V1PidCandidate")
        if isinstance(candidates, (str, bytes)):
            raise V1ClosedLoopError("candidates must be a sequence")
        try:
            candidate_items = tuple(candidates)
        except TypeError as exc:
            raise V1ClosedLoopError("candidates must be a sequence") from exc
        if len(candidate_items) < 2:
            raise V1ClosedLoopError("at least two PID candidates are required")
        if any(not isinstance(item, V1PidCandidate) for item in candidate_items):
            raise V1ClosedLoopError("candidates must contain V1PidCandidate values")
        all_candidates = (baseline,) + candidate_items
        ids = [item.candidate_id for item in all_candidates]
        if len(set(ids)) != len(ids):
            raise V1ClosedLoopError("candidate IDs must be unique")

        calibration, holdout, evidence_reason = self._run_id_evidence(
            calibration_run_ids, holdout_run_ids
        )
        predictions = []
        for item in all_candidates:
            try:
                predictions.append(
                    self.predictor.predict(
                        item,
                        initial_pose=initial_pose,
                        track_map=track_map,
                    )
                )
            except Exception as exc:
                predictions.append(
                    V1PredictionResult.failed(
                        item,
                        model_version=self.predictor.model_version,
                        track_asset_version=self.predictor.track_asset_version,
                        seed=self.predictor.seed,
                        calibration_evidence="INSUFFICIENT_EVIDENCE",
                        reason="{}: {}".format(type(exc).__name__, exc),
                    )
                )
                if not evidence_reason:
                    evidence_reason = "one or more candidate predictions failed"

        ordered = tuple(sorted(predictions, key=self._ranking_key))
        ranking = tuple(item.candidate.candidate_id for item in ordered)
        eligible = tuple(
            item
            for item in predictions
            if item.status == "PREDICTED" and item.completed and not item.line_lost
        )
        selected = min(
            eligible,
            key=lambda item: (
                item.completion_time_s
                if item.completion_time_s is not None
                else math.inf,
                item.candidate.candidate_id,
            ),
            default=None,
        )
        selected_id = selected.candidate.candidate_id if selected is not None else None
        failed = any(item.status == "FAILED" for item in predictions)
        if failed and not evidence_reason:
            evidence_reason = "one or more candidate predictions failed"
        if not eligible and not evidence_reason:
            evidence_reason = "no candidate completed without line loss"
        if not evidence_reason and not self.predictor.calibration_evidence.ready:
            evidence_reason = self.predictor.calibration_evidence.reason or (
                "real synchronized calibration and disjoint holdout evidence is required"
            )
        evidence_status = (
            "INSUFFICIENT_EVIDENCE"
            if evidence_reason or not self.predictor.calibration_evidence.ready
            else "VERIFIED"
        )
        ready = evidence_status == "VERIFIED" and not failed and bool(eligible)
        return V1CandidateEvaluation(
            status="PREDICTION_FAILED" if failed else "PREDICTION_COMPLETE",
            predictions=tuple(predictions),
            ranking=ranking,
            selected_candidate_id=selected_id,
            evidence_status=evidence_status,
            evidence_reason=evidence_reason,
            ready=ready,
            model_version=self.predictor.model_version,
            track_asset_version=self.predictor.track_asset_version,
            seed=self.predictor.seed,
            calibration_run_ids=calibration,
            holdout_run_ids=holdout,
        )

    @staticmethod
    def _ranking_key(result: V1PredictionResult) -> Tuple[int, float, str]:
        if result.status != "PREDICTED":
            return (2, math.inf, result.candidate.candidate_id)
        if result.completed and not result.line_lost:
            return (0, result.completion_time_s if result.completion_time_s is not None else math.inf, result.candidate.candidate_id)
        if not result.line_lost:
            return (1, result.completion_time_s if result.completion_time_s is not None else math.inf, result.candidate.candidate_id)
        return (2, result.completion_time_s if result.completion_time_s is not None else math.inf, result.candidate.candidate_id)

    @staticmethod
    def _run_id_evidence(
        calibration_run_ids: Iterable[object], holdout_run_ids: Iterable[object]
    ) -> Tuple[Tuple[str, ...], Tuple[str, ...], str]:
        try:
            calibration = _tuple_text(calibration_run_ids, "calibration_run_ids")
            holdout = _tuple_text(holdout_run_ids, "holdout_run_ids")
        except V1ClosedLoopError as exc:
            return (), (), str(exc)
        overlap = sorted(set(calibration) & set(holdout))
        if overlap:
            return calibration, holdout, "calibration/holdout run_id overlap: {}".format(", ".join(overlap))
        return calibration, holdout, ""
