"""Pure offline adapter for running a frozen V1 twin prediction.

The runner deliberately requires an injected predictor.  It never invents a
trajectory or opens a hardware interface when a model is unavailable.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from numbers import Real
from typing import Any, Dict

from .v1_twin_schema import V1TrackMap


TERMINAL_CLASSES = frozenset(("completed", "line_loss", "safety_stop", "timeout"))
_REQUIRED_PID_KEYS = ("kp", "ki", "kd")


class V1TwinRunnerError(ValueError):
    """Raised when a prediction cannot be validated without guessing."""


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise V1TwinRunnerError("{} must be numeric".format(name))
    number = float(value)
    if not math.isfinite(number):
        raise V1TwinRunnerError("{} must be finite".format(name))
    return number


@dataclass(frozen=True)
class V1PredictionMetrics:
    """Metrics emitted by an injected model predictor."""

    sensor_macro_f1: float
    lateral_error_p95_mm: float
    predicted_score: float
    completion_time_s: float

    def __post_init__(self) -> None:
        f1 = _finite_number(self.sensor_macro_f1, "sensor_macro_f1")
        if not 0.0 <= f1 <= 1.0:
            raise ValueError("sensor_macro_f1 must be in [0, 1]")
        lateral = _finite_number(self.lateral_error_p95_mm, "lateral_error_p95_mm")
        if lateral < 0.0:
            raise ValueError("lateral_error_p95_mm must be >= 0")
        score = _finite_number(self.predicted_score, "predicted_score")
        completion = _finite_number(self.completion_time_s, "completion_time_s")
        if completion < 0.0:
            raise ValueError("completion_time_s must be >= 0")
        object.__setattr__(self, "sensor_macro_f1", f1)
        object.__setattr__(self, "lateral_error_p95_mm", lateral)
        object.__setattr__(self, "predicted_score", score)
        object.__setattr__(self, "completion_time_s", completion)

    def to_dict(self) -> Dict[str, float]:
        return {
            "sensor_macro_f1": self.sensor_macro_f1,
            "lateral_error_p95_mm": self.lateral_error_p95_mm,
            "predicted_score": self.predicted_score,
            "completion_time_s": self.completion_time_s,
        }


@dataclass(frozen=True)
class V1PredictedRun:
    """Validated result for one model-side PID group prediction."""

    pid_group_id: str
    terminal_class: str
    metrics: V1PredictionMetrics
    danger_predicted: bool
    model_version: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.pid_group_id, str) or not self.pid_group_id.strip():
            raise ValueError("pid_group_id must be a non-empty string")
        if self.terminal_class not in TERMINAL_CLASSES:
            raise ValueError("terminal_class is not supported")
        if not isinstance(self.metrics, V1PredictionMetrics):
            raise ValueError("metrics must be a V1PredictionMetrics")
        if not isinstance(self.danger_predicted, bool):
            raise ValueError("danger_predicted must be a bool")
        if not isinstance(self.model_version, str):
            raise ValueError("model_version must be a string")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid_group_id": self.pid_group_id,
            "terminal_class": self.terminal_class,
            "metrics": self.metrics.to_dict(),
            "danger_predicted": self.danger_predicted,
            "model_version": self.model_version,
        }


class V1TwinRunner:
    """Call and validate an injected model predictor exactly once per run."""

    def __init__(
        self,
        predictor: Callable[[Mapping[str, object], V1TrackMap], V1PredictedRun],
        *,
        model_version: str,
    ) -> None:
        if not callable(predictor):
            raise V1TwinRunnerError("predictor must be callable")
        if not isinstance(model_version, str) or not model_version.strip():
            raise V1TwinRunnerError("model_version must be a non-empty string")
        self._predictor = predictor
        self.model_version = model_version

    def run(
        self,
        pid_params: Mapping[str, object],
        track_map: V1TrackMap,
    ) -> V1PredictedRun:
        self._validate_pid_params(pid_params)
        if not isinstance(track_map, V1TrackMap):
            raise V1TwinRunnerError("track_map must be a V1TrackMap")
        try:
            result = self._predictor(dict(pid_params), track_map)
        except V1TwinRunnerError:
            raise
        except Exception as exc:
            raise V1TwinRunnerError("predictor returned invalid result: {}".format(exc)) from exc
        if not isinstance(result, V1PredictedRun):
            raise V1TwinRunnerError("predictor must return V1PredictedRun")
        try:
            # Re-run the dataclass invariants for subclasses or unusual objects.
            V1PredictedRun(
                pid_group_id=result.pid_group_id,
                terminal_class=result.terminal_class,
                metrics=result.metrics,
                danger_predicted=result.danger_predicted,
                model_version=result.model_version,
            )
        except Exception as exc:
            raise V1TwinRunnerError("predictor returned invalid result: {}".format(exc)) from exc
        if result.model_version and result.model_version != self.model_version:
            raise V1TwinRunnerError("predictor model_version does not match runner")
        return replace(result, model_version=self.model_version)

    @staticmethod
    def _validate_pid_params(pid_params: Mapping[str, object]) -> None:
        if not isinstance(pid_params, Mapping):
            raise V1TwinRunnerError("pid_params must be a mapping")
        for key in _REQUIRED_PID_KEYS:
            if key not in pid_params:
                raise V1TwinRunnerError("pid_params is missing {}".format(key))
        for key, value in pid_params.items():
            _finite_number(value, "pid_params[{}]".format(key))
