"""End-to-end offline V1 twin tests.

These tests intentionally exercise the real controller, plant, and virtual
sensor objects together.  They do not use camera, serial, TCP, or hardware
fixtures.
"""

from __future__ import annotations

import pytest

from v1_twin.v1_twin_closed_loop import (
    V1CalibrationEvidence,
    V1CandidateEvaluator,
    V1ClosedLoopConfig,
    V1ClosedLoopError,
    V1ClosedLoopPredictor,
    V1PidCandidate,
)
from v1_twin.v1_twin_plant import V1Plant, V1PlantParameters
from v1_twin.v1_twin_schema import V1Pose, V1SensorModelConfig, V1TrackMap


def _track() -> V1TrackMap:
    return V1TrackMap(
        mask=((1,),),
        centerline_mm=((0.0, 0.0), (400.0, 0.0)),
        width_mm=12.0,
    )


def _predictor() -> V1ClosedLoopPredictor:
    # The scale is an explicit exploratory fixture, not a claim about the
    # physical car.  It makes the synthetic turn response numerically stable.
    mix = (
        0.25, 0.25, 0.25, 0.25,
        0.0, 0.0, 0.0, 0.0,
        0.003, -0.003, -0.003, 0.003,
    )
    plant = V1Plant(V1PlantParameters(mix_matrix=mix))
    sensor = V1SensorModelConfig(
        lateral_offsets_mm=(-15.0, -5.0, 5.0, 15.0),
        sensor_bar_fore_aft_mm=0.0,
    )
    return V1ClosedLoopPredictor(
        config=V1ClosedLoopConfig(
            plant=plant,
            sensor_config=sensor,
            dt_s=0.005,
            max_steps=2000,
            line_loss_patience_steps=3,
            completion_tolerance_mm=8.0,
            calibration_evidence=V1CalibrationEvidence.none(),
        ),
        model_version="offline-v1-synthetic-plant-1",
        track_asset_version="fixture-track-1",
        seed=7,
    )


def _candidates():
    return (
        V1PidCandidate("baseline-A", 35.0, 0.0, 10.0, 420.0),
        V1PidCandidate("candidate-B", 45.0, 0.0, 15.0, 520.0),
        V1PidCandidate("candidate-C", 25.0, 0.0, 7.0, 320.0),
    )


def test_closed_loop_prediction_connects_all_components_and_records_provenance():
    predictor = _predictor()
    result = predictor.predict(
        _candidates()[1],
        initial_pose=V1Pose(0.0, 8.0, 0.0, 1.0, 0, source="simulated"),
        track_map=_track(),
    )

    assert result.status == "PREDICTED"
    assert result.model_version == "offline-v1-synthetic-plant-1"
    assert result.track_asset_version == "fixture-track-1"
    assert result.seed == 7
    assert result.steps > 0
    assert result.trace
    assert result.trace[0].sensor_reading.sensors
    assert result.trace[0].pwm_command
    assert result.trace[0].predicted_velocity_mm_s
    assert result.predicted_speed_mean_mm_s >= 0.0
    assert result.calibration_evidence == "INSUFFICIENT_EVIDENCE"


def test_candidate_evaluation_uses_no_line_loss_then_completion_time_and_is_repeatable():
    predictor = _predictor()
    evaluator = V1CandidateEvaluator(predictor)
    initial = V1Pose(0.0, 8.0, 0.0, 1.0, 0, source="simulated")

    first = evaluator.evaluate(
        baseline=_candidates()[0],
        candidates=_candidates()[1:],
        initial_pose=initial,
        track_map=_track(),
    )
    second = evaluator.evaluate(
        baseline=_candidates()[0],
        candidates=_candidates()[1:],
        initial_pose=initial,
        track_map=_track(),
    )

    assert first.to_dict() == second.to_dict()
    assert len(first.predictions) == 3
    assert len(set(first.ranking)) == 3
    assert first.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert first.ready is False
    assert len({p.line_lost for p in first.predictions}) > 1

    eligible = [
        p for p in first.predictions if p.completed and not p.line_lost
    ]
    if eligible:
        assert first.ranking[0] == min(
            eligible, key=lambda p: (p.completion_time_s, p.candidate.candidate_id)
        ).candidate.candidate_id


def test_missing_real_calibration_and_overlapping_split_never_report_ready():
    predictor = _predictor()
    evaluator = V1CandidateEvaluator(predictor)
    result = evaluator.evaluate(
        baseline=_candidates()[0],
        candidates=_candidates()[1:],
        initial_pose=V1Pose(0.0, 8.0, 0.0, 1.0, 0, source="simulated"),
        track_map=_track(),
        calibration_run_ids=("run-1",),
        holdout_run_ids=("run-2",),
    )

    assert result.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert result.ready is False
    assert result.calibration_run_ids == ("run-1",)
    assert result.holdout_run_ids == ("run-2",)

    overlapping = evaluator.evaluate(
        baseline=_candidates()[0],
        candidates=_candidates()[1:],
        initial_pose=V1Pose(0.0, 8.0, 0.0, 1.0, 0, source="simulated"),
        track_map=_track(),
        calibration_run_ids=("same",),
        holdout_run_ids=("same",),
    )
    assert overlapping.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert overlapping.ready is False
    assert "overlap" in overlapping.evidence_reason


def test_prediction_failure_is_explicit_and_does_not_guess_a_result():
    predictor = _predictor()
    result = V1CandidateEvaluator(predictor).evaluate(
        baseline=_candidates()[0],
        candidates=_candidates()[1:],
        initial_pose=V1Pose(0.0, 0.0, 0.0, 1.0, 0, source="simulated"),
        track_map=V1TrackMap(mask=((1,),), centerline_mm=(), width_mm=12.0),
    )

    assert result.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert result.ready is False
    assert all(item.status == "FAILED" for item in result.predictions)
    assert all(item.failure_reason for item in result.predictions)


def test_evaluator_does_not_select_or_ready_when_no_candidate_completes():
    predictor = V1ClosedLoopPredictor(
        config=V1ClosedLoopConfig(
            plant=V1Plant(V1PlantParameters()),
            sensor_config=V1SensorModelConfig((-15.0, -5.0, 5.0, 15.0)),
            max_steps=1,
            calibration_evidence=V1CalibrationEvidence(
                status="VERIFIED",
                source="REAL_SYNC",
                calibration_run_ids=("cal-1",),
                holdout_run_ids=("hold-1",),
            ),
        ),
        model_version="offline-v1-timeout-fixture",
        track_asset_version="timeout-track",
        seed=9,
    )
    candidates = (
        V1PidCandidate("baseline-timeout", 35.0, 0.0, 10.0, 420.0),
        V1PidCandidate("candidate-timeout-b", 36.0, 0.0, 10.0, 420.0),
        V1PidCandidate("candidate-timeout-c", 37.0, 0.0, 10.0, 420.0),
    )

    result = V1CandidateEvaluator(predictor).evaluate(
        baseline=candidates[0],
        candidates=candidates[1:],
        initial_pose=V1Pose(0.0, 0.0, 0.0, 1.0, 0, source="simulated"),
        track_map=V1TrackMap(
            mask=((1,),),
            centerline_mm=((0.0, 0.0), (1000.0, 0.0)),
            width_mm=12.0,
        ),
    )

    assert all(item.terminal_class == "timeout" for item in result.predictions)
    assert result.selected_candidate_id is None
    assert result.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert result.ready is False


def test_closed_loop_rejects_a_non_firmware_sampling_period():
    with pytest.raises(V1ClosedLoopError, match="5 ms"):
        V1ClosedLoopConfig(
            plant=V1Plant(V1PlantParameters()),
            sensor_config=V1SensorModelConfig((-15.0, -5.0, 5.0, 15.0)),
            dt_s=0.02,
        )
