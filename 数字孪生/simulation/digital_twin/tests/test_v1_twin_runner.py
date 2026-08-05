import math

import pytest

from v1_twin.v1_twin_runner import (
    V1PredictionMetrics,
    V1PredictedRun,
    V1TwinRunner,
    V1TwinRunnerError,
)
from v1_twin.v1_twin_schema import V1TrackMap


def valid_map():
    return V1TrackMap(
        mask=((1, 1), (1, 1)),
        centerline_mm=((0.0, 0.0), (100.0, 0.0)),
        width_mm=20.0,
    )


def valid_prediction():
    return V1PredictedRun(
        pid_group_id="pid-01",
        terminal_class="completed",
        metrics=V1PredictionMetrics(
            sensor_macro_f1=0.96,
            lateral_error_p95_mm=2.0,
            predicted_score=0.8,
            completion_time_s=4.0,
        ),
        danger_predicted=False,
    )


def test_runner_delegates_and_returns_validated_prediction():
    calls = []

    def predictor(params, track_map):
        calls.append((dict(params), track_map))
        return valid_prediction()

    result = V1TwinRunner(predictor, model_version="model-1").run(
        {"kp": 35.0, "ki": 0.0, "kd": 10.0}, valid_map()
    )

    assert result.pid_group_id == "pid-01"
    assert len(calls) == 1
    assert calls[0][0] == {"kp": 35.0, "ki": 0.0, "kd": 10.0}
    assert calls[0][1] == valid_map()
    assert result.to_dict()["model_version"] == "model-1"


def test_runner_rejects_missing_predictor_and_invalid_model_version():
    with pytest.raises(V1TwinRunnerError, match="callable"):
        V1TwinRunner(None, model_version="model-1")
    with pytest.raises(V1TwinRunnerError, match="model_version"):
        V1TwinRunner(lambda *_: valid_prediction(), model_version="")


@pytest.mark.parametrize(
    "params, message",
    [
        ({"ki": 0.0, "kd": 10.0}, "kp"),
        ({"kp": 35.0, "kd": 10.0}, "ki"),
        ({"kp": 35.0, "ki": 0.0}, "kd"),
        ({"kp": math.nan, "ki": 0.0, "kd": 10.0}, "finite"),
        ({"kp": True, "ki": 0.0, "kd": 10.0}, "numeric"),
        ({"kp": "35", "ki": 0.0, "kd": 10.0}, "numeric"),
    ],
)
def test_runner_rejects_malformed_pid_parameters(params, message):
    runner = V1TwinRunner(lambda *_: valid_prediction(), model_version="model-1")
    with pytest.raises(V1TwinRunnerError, match=message):
        runner.run(params, valid_map())


def test_runner_rejects_wrong_track_map_type():
    runner = V1TwinRunner(lambda *_: valid_prediction(), model_version="model-1")
    with pytest.raises(V1TwinRunnerError, match="V1TrackMap"):
        runner.run({"kp": 35.0, "ki": 0.0, "kd": 10.0}, object())


@pytest.mark.parametrize(
    "prediction_factory, message",
    [
        (lambda: None, "V1PredictedRun"),
        (lambda: {}, "V1PredictedRun"),
        (lambda: V1PredictedRun(
            pid_group_id="pid-01",
            terminal_class="unknown",
            metrics=V1PredictionMetrics(0.9, 1.0, 0.5, 1.0),
            danger_predicted=False,
        ), "terminal_class"),
    ],
)
def test_runner_rejects_malformed_predictor_output(prediction_factory, message):
    runner = V1TwinRunner(lambda *_: prediction_factory(), model_version="model-1")
    with pytest.raises(V1TwinRunnerError, match=message):
        runner.run({"kp": 35.0, "ki": 0.0, "kd": 10.0}, valid_map())


def test_prediction_metrics_reject_non_finite_or_out_of_range_values():
    with pytest.raises(ValueError, match="macro_f1"):
        V1PredictionMetrics(math.nan, 1.0, 0.5, 1.0)
    with pytest.raises(ValueError, match="macro_f1"):
        V1PredictionMetrics(1.1, 1.0, 0.5, 1.0)
    with pytest.raises(ValueError, match="lateral"):
        V1PredictionMetrics(0.9, -1.0, 0.5, 1.0)
    with pytest.raises(ValueError, match="completion"):
        V1PredictionMetrics(0.9, 1.0, 0.5, -1.0)


def test_prediction_serialization_is_json_compatible():
    result = V1PredictedRun(
        pid_group_id="pid-01",
        terminal_class="safety_stop",
        metrics=V1PredictionMetrics(0.91, 3.0, 0.2, 5.0),
        danger_predicted=True,
    ).to_dict()
    assert result["terminal_class"] == "safety_stop"
    assert result["danger_predicted"] is True
    assert result["metrics"]["sensor_macro_f1"] == 0.91
