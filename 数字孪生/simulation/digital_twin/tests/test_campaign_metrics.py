"""Tests for campaign metrics calculation and candidate acceptance rules.

Every test is written against the public interface before the implementation
exists.  Expected values are hand-derived to avoid reusing the implementation
under test.
"""

from __future__ import annotations

import json
import math
import os
import sys
import copy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# ============================================================
# Module-level helpers for constructing test data
# ============================================================


def _sensor_frame(s0, s1, s2, s3, error, tick_ms):
    """One raw telemetry frame dict matching the data_logger format."""
    return {
        "sensors": [s0, s1, s2, s3],
        "error": error,
        "tick_ms": tick_ms,
    }


def _all_white_frame(error, tick_ms):
    """Frame with all-sensors-white (normal tracking)."""
    return _sensor_frame(1, 1, 1, 1, error, tick_ms)


def _all_black_frame(error, tick_ms):
    """Frame with all-sensors-black (track lost)."""
    return _sensor_frame(0, 0, 0, 0, error, tick_ms)


def _mixed_frame(sensors, error, tick_ms):
    """Frame with explicit sensor values — sensors is a 4-element iterable."""
    s = list(sensors)
    return _sensor_frame(s[0], s[1], s[2], s[3], error, tick_ms)


def _make_run(telemetry_frames, completed=True, termination_reason="completed",
              safety_stop=False, valid=True):
    """Build a RunSummary from raw telemetry frames using compute_run_summary."""
    from analysis.campaign_metrics import compute_run_summary
    return compute_run_summary(
        frames=telemetry_frames,
        completed=completed,
        termination_reason=termination_reason,
        safety_stop=safety_stop,
        valid=valid,
    )


def _constant_error_runs(error_val, n=5, completed=True, duration_ms=40000,
                         safety_stop=False, termination_reason="completed",
                         valid=True):
    """Build n runs, each with constant error_val and given exact duration_ms."""
    tick_step = 1000
    frames_per_run = duration_ms // tick_step + 1  # +1 because 0-indexed
    runs = []
    for i in range(n):
        tick_start = 100 + i * (duration_ms + 10000)  # big gap between runs
        frames = []
        for j in range(frames_per_run):
            t = tick_start + j * tick_step
            frames.append(_all_white_frame(error_val, t))
        runs.append(_make_run(
            frames,
            completed=completed,
            termination_reason=termination_reason,
            safety_stop=safety_stop,
            valid=valid,
        ))
    return runs


# ============================================================
# Track-loss counting
# ============================================================

class TestTrackLossCount:
    """Track loss counts contiguous all-zero sensor intervals, not individual frames."""

    def test_no_loss_no_count(self):
        from analysis.campaign_metrics import track_loss_count
        frames = [_all_white_frame(0, t) for t in range(10)]
        assert track_loss_count(frames) == 0

    def test_no_loss_mixed_sensors(self):
        from analysis.campaign_metrics import track_loss_count
        frames = [_mixed_frame((1, 0, 1, 0), 0, t) for t in range(10)]
        assert track_loss_count(frames) == 0

    def test_single_contiguous_block_counts_once(self):
        from analysis.campaign_metrics import track_loss_count
        frames = (
            [_all_white_frame(0, t) for t in range(0, 100)]
            + [_all_black_frame(10, t) for t in range(100, 200)]
            + [_all_white_frame(0, t) for t in range(200, 300)]
        )
        assert track_loss_count(frames) == 1

    def test_two_separate_blocks_count_two(self):
        from analysis.campaign_metrics import track_loss_count
        frames = (
            [_all_white_frame(0, t) for t in range(0, 50)]
            + [_all_black_frame(10, t) for t in range(50, 80)]
            + [_all_white_frame(0, t) for t in range(80, 120)]
            + [_all_black_frame(10, t) for t in range(120, 150)]
            + [_all_white_frame(0, t) for t in range(150, 200)]
        )
        assert track_loss_count(frames) == 2

    def test_single_frame_all_black(self):
        """A single all-black frame still counts as one loss event."""
        from analysis.campaign_metrics import track_loss_count
        frames = [_all_white_frame(0, 0), _all_black_frame(5, 50), _all_white_frame(0, 100)]
        assert track_loss_count(frames) == 1

    def test_sampling_rate_does_not_affect_count(self):
        """More frames within the same loss interval must not inflate the count."""
        from analysis.campaign_metrics import track_loss_count
        slow = (
            [_all_white_frame(0, t) for t in range(0, 100, 2)]
            + [_all_black_frame(10, t) for t in range(100, 200, 2)]
            + [_all_white_frame(0, t) for t in range(200, 300, 2)]
        )
        fast = (
            [_all_white_frame(0, t) for t in range(0, 100)]
            + [_all_black_frame(10, t) for t in range(100, 200)]
            + [_all_white_frame(0, t) for t in range(200, 300)]
        )
        assert track_loss_count(slow) == track_loss_count(fast)

    def test_empty_frames_returns_zero(self):
        from analysis.campaign_metrics import track_loss_count
        assert track_loss_count([]) == 0

    # ----- string sensor variants (I4) -----

    def test_string_zeros_detected_as_black(self):
        """String '0' sensors must be recognised as black (track loss)."""
        from analysis.campaign_metrics import track_loss_count
        frames = [
            {"sensors": ["1", "1", "1", "1"], "error": 0, "tick_ms": 100},
            {"sensors": ["0", "0", "0", "0"], "error": 5, "tick_ms": 200},
            {"sensors": ["1", "1", "1", "1"], "error": 0, "tick_ms": 300},
        ]
        assert track_loss_count(frames) == 1

    def test_mixed_int_and_string_sensors(self):
        """Mixed int 0 and str '0' sensors should be handled uniformly."""
        from analysis.campaign_metrics import track_loss_count
        frames = [
            {"sensors": [0, "0", 0, "0"], "error": 5, "tick_ms": 100},
            {"sensors": ["0", 0, "0", 0], "error": 8, "tick_ms": 200},
            {"sensors": [1, "1", 1, "1"], "error": 0, "tick_ms": 300},
        ]
        assert track_loss_count(frames) == 1


# ============================================================
# Single-run metrics
# ============================================================

class TestComputeRunSummary:
    """ComputeRunSummary extracts deterministic metrics from raw telemetry."""

    def test_basic_metrics_from_error_sequence(self):
        from analysis.campaign_metrics import compute_run_summary
        frames = [
            _all_white_frame(2, 100),
            _all_white_frame(4, 200),
            _all_white_frame(-4, 300),
            _all_white_frame(2, 400),
        ]
        summary = compute_run_summary(
            frames=frames, completed=True,
            termination_reason="completed", safety_stop=False,
        )
        # MAE = (2 + 4 + 4 + 2) / 4 = 3.0
        assert summary.mae == pytest.approx(3.0)
        # RMS = sqrt((4 + 16 + 16 + 4) / 4) = sqrt(10) ≈ 3.1623
        assert summary.rms_error == pytest.approx(math.sqrt(10.0))
        # Max error = 4
        assert summary.max_error == 4
        # Duration = 400 - 100 = 300 ms
        assert summary.duration_ms == 300
        assert summary.completed is True
        assert summary.termination_reason == "completed"
        assert summary.safety_stop is False

    def test_safety_stop_propagates(self):
        from analysis.campaign_metrics import compute_run_summary
        frames = [_all_white_frame(0, t) for t in range(10)]
        summary = compute_run_summary(
            frames=frames, completed=False,
            termination_reason="safety_stop", safety_stop=True,
        )
        assert summary.safety_stop is True
        assert summary.completed is False
        assert summary.termination_reason == "safety_stop"

    def test_invalid_run_still_computes_metrics(self):
        """Even a run marked valid=False should compute metrics (M1 fix)."""
        from analysis.campaign_metrics import compute_run_summary
        frames = [_all_white_frame(1, t) for t in range(5)]
        summary = compute_run_summary(
            frames=frames, completed=True,
            termination_reason="completed", safety_stop=False,
            valid=False,
        )
        assert summary.mae == 1.0
        assert summary.valid is False

    def test_nan_error_rejected(self):
        from analysis.campaign_metrics import compute_run_summary
        frames = [_all_white_frame(float("nan"), 100)]
        with pytest.raises(ValueError, match="NaN|Inf"):
            compute_run_summary(frames=frames, completed=True,
                                termination_reason="completed")

    def test_inf_error_rejected(self):
        from analysis.campaign_metrics import compute_run_summary
        frames = [_all_white_frame(float("inf"), 100)]
        with pytest.raises(ValueError, match="NaN|Inf"):
            compute_run_summary(frames=frames, completed=True,
                                termination_reason="completed")

    def test_empty_telemetry_rejected(self):
        from analysis.campaign_metrics import compute_run_summary
        with pytest.raises(ValueError, match="empty|no frames"):
            compute_run_summary(frames=[], completed=True,
                                termination_reason="completed")

    def test_negative_duration_raises(self):
        from analysis.campaign_metrics import compute_run_summary
        frames = [_all_white_frame(1, 200), _all_white_frame(2, 100)]
        with pytest.raises(ValueError, match="negative|duration"):
            compute_run_summary(frames=frames, completed=True,
                                termination_reason="completed")

    def test_track_loss_count_in_summary(self):
        from analysis.campaign_metrics import compute_run_summary
        frames = (
            [_all_white_frame(0, t) for t in range(0, 50)]
            + [_all_black_frame(10, t) for t in range(50, 80)]
            + [_all_white_frame(0, t) for t in range(80, 100)]
        )
        summary = compute_run_summary(
            frames=frames, completed=True, termination_reason="completed",
        )
        assert summary.track_loss_count == 1

    def test_unknown_termination_reason_raises(self):
        """Unknown termination reason must be rejected (not silently accepted)."""
        from analysis.campaign_metrics import compute_run_summary
        frames = [_all_white_frame(1, t) for t in range(5)]
        with pytest.raises(ValueError, match="unknown termination_reason"):
            compute_run_summary(
                frames=frames, completed=False,
                termination_reason="alien_invasion",
            )

    def test_empty_termination_reason_raises(self):
        from analysis.campaign_metrics import compute_run_summary
        frames = [_all_white_frame(1, t) for t in range(5)]
        with pytest.raises(ValueError, match="termination_reason"):
            compute_run_summary(
                frames=frames, completed=True, termination_reason="",
            )

    def test_non_numeric_error_rejected(self):
        """String error values must raise, not be silently converted."""
        from analysis.campaign_metrics import compute_run_summary
        frames = [{"error": "abc", "tick_ms": 100}]
        with pytest.raises(ValueError, match="non-numeric"):
            compute_run_summary(frames=frames, completed=True,
                                termination_reason="completed")

    def test_missing_fields_default_to_zero(self):
        """Dict missing 'error' — defaults to 0 which is finite."""
        from analysis.campaign_metrics import compute_run_summary
        frames = [{"sensors": [1, 1, 1, 1], "tick_ms": 100}]
        summary = compute_run_summary(frames=frames, completed=True,
                                      termination_reason="completed")
        assert summary.mae == 0.0


# ============================================================
# Task 2 JSON production entry (I5)
# ============================================================

class TestRunSummaryFromTask2Json:
    """Verify the RealDataLogger output → RunSummary conversion."""

    def _make_task2_json(self, campaign_id="camp-001", run_id="run-007",
                         parameter_version=2, termination_reason="completed",
                         n_frames=10):
        """Build a dict matching RealDataLogger.save_campaign() output."""
        frames = [_all_white_frame(i % 5, 100 + i * 10) for i in range(n_frames)]
        return {
            "name": "camp-001/run-007",
            "source": "real_stm32",
            "params": {},
            "metrics": {},
            "data": frames,
            "_campaign_meta": {
                "campaign_id": campaign_id,
                "run_id": run_id,
                "parameter_version": parameter_version,
                "termination_reason": termination_reason,
                "saved_at": "2026-07-30T12:00:00Z",
            },
        }

    def test_from_task2_json_round_trip(self):
        from analysis.campaign_metrics import run_summary_from_task2_json
        data = self._make_task2_json()
        summary = run_summary_from_task2_json(data)
        assert isinstance(summary.rms_error, float)
        assert summary.completed is True
        assert summary.termination_reason == "completed"
        assert summary.valid is True

    def test_from_task2_json_safety_stop(self):
        from analysis.campaign_metrics import run_summary_from_task2_json
        data = self._make_task2_json(termination_reason="safety_stop")
        summary = run_summary_from_task2_json(data)
        assert summary.safety_stop is True
        assert summary.completed is False

    def test_from_task2_json_missing_meta_raises(self):
        from analysis.campaign_metrics import run_summary_from_task2_json
        with pytest.raises(ValueError, match="_campaign_meta"):
            run_summary_from_task2_json({"data": []})

    def test_from_task2_json_empty_data_raises(self):
        from analysis.campaign_metrics import run_summary_from_task2_json
        data = self._make_task2_json(n_frames=0)
        data["data"] = []
        with pytest.raises(ValueError, match="empty"):
            run_summary_from_task2_json(data)

    def test_from_task2_json_missing_campaign_id_raises(self):
        from analysis.campaign_metrics import run_summary_from_task2_json
        data = self._make_task2_json()
        data["_campaign_meta"]["campaign_id"] = ""
        with pytest.raises(ValueError, match="campaign_id"):
            run_summary_from_task2_json(data)

    def test_from_task2_json_missing_run_id_raises(self):
        from analysis.campaign_metrics import run_summary_from_task2_json
        data = self._make_task2_json()
        data["_campaign_meta"]["run_id"] = ""
        with pytest.raises(ValueError, match="run_id"):
            run_summary_from_task2_json(data)

    def test_from_frame_list_basic(self):
        """run_summary_from_frame_list accepts raw frames directly."""
        from analysis.campaign_metrics import run_summary_from_frame_list
        frames = [_all_white_frame(2, 100), _all_white_frame(4, 200)]
        summary = run_summary_from_frame_list(frames, termination_reason="completed")
        assert summary.mae == pytest.approx(3.0)
        assert summary.completed is True
        assert summary.valid is True


# ============================================================
# Aggregation
# ============================================================

class TestAggregation:
    """Aggregate metrics across multiple runs (I1/I2/I3 fix)."""

    def test_completion_rate_100_percent(self):
        from analysis.campaign_metrics import aggregate_run_summaries
        runs = [_make_run([_all_white_frame(1, t) for t in range(5)],
                           completed=True) for _ in range(5)]
        agg = aggregate_run_summaries(runs)
        assert agg["completion_rate"] == pytest.approx(1.0)

    def test_completion_rate_60_percent(self):
        from analysis.campaign_metrics import aggregate_run_summaries
        runs = []
        for i in range(5):
            completed = i < 3
            runs.append(_make_run(
                [_all_white_frame(1, t) for t in range(5)],
                completed=completed,
                termination_reason="completed" if completed else "line_lost",
            ))
        agg = aggregate_run_summaries(runs)
        assert agg["completion_rate"] == pytest.approx(0.6)

    def test_safety_stop_count(self):
        from analysis.campaign_metrics import aggregate_run_summaries
        runs = [_make_run([_all_white_frame(1, t) for t in range(5)],
                           completed=True) for _ in range(3)]
        runs.append(_make_run(
            [_all_white_frame(1, t) for t in range(5)],
            completed=False, safety_stop=True, termination_reason="safety_stop",
        ))
        agg = aggregate_run_summaries(runs)
        assert agg["safety_stop_count"] == 1

    def test_aggregate_empty_list(self):
        from analysis.campaign_metrics import aggregate_run_summaries
        with pytest.raises(ValueError, match="empty"):
            aggregate_run_summaries([])

    def test_all_invalid_returns_none_stats(self):
        """When all runs are valid=False, stats must be None (M2 fix)."""
        from analysis.campaign_metrics import aggregate_run_summaries
        runs = [_make_run([_all_white_frame(1, t) for t in range(5)],
                           completed=True, valid=False) for _ in range(3)]
        agg = aggregate_run_summaries(runs)
        assert agg["n_valid"] == 0
        assert agg["mean_rms"] is None
        assert agg["completion_rate"] is None
        assert agg["mean_duration_ms"] is None

    def test_invalid_runs_excluded_from_all_metrics(self):
        """valid=False runs must not contribute to any stat (I1 fix)."""
        from analysis.campaign_metrics import aggregate_run_summaries
        valid_runs = [_make_run([_all_white_frame(10, t) for t in range(5)],
                                 completed=True) for _ in range(3)]
        invalid = [_make_run([_all_white_frame(100, t) for t in range(5)],
                              completed=True, valid=False)]
        agg = aggregate_run_summaries(valid_runs + invalid)
        # Only 3 valid runs; completion from those 3
        assert agg["n_valid"] == 3
        assert agg["mean_rms"] == pytest.approx(10.0)  # invalid's 100 excluded

    def test_duration_from_completed_only(self):
        """Non-completed valid runs must not contribute to mean_duration (I3 fix)."""
        from analysis.campaign_metrics import aggregate_run_summaries
        completed = [_make_run([_all_white_frame(1, t) for t in range(0, 100, 10)],
                                completed=True) for _ in range(3)]
        early_abort = _make_run([_all_white_frame(1, t) for t in range(0, 20, 10)],
                                 completed=False, termination_reason="line_lost")
        agg = aggregate_run_summaries(completed + [early_abort])
        # 4 valid runs, 3 completed, 1 early abort
        assert agg["n_valid"] == 4
        assert agg["completion_rate"] == 0.75
        # Duration only from 3 completed runs
        assert agg["mean_duration_ms"] == pytest.approx(90.0)  # (90*3)/3 = 90ms


# ============================================================
# Acceptance / rejection
# ============================================================

class TestEvaluateCandidate:
    """Accept/Reject decision logic.

    Both baseline and candidate have 5 valid runs unless otherwise noted.
    """

    def test_accept_when_all_thresholds_pass(self):
        """Golden path: candidate meets all criteria."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, duration_ms=40000)
        candidate = _constant_error_runs(7.5, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "accepted"

    def test_reject_when_error_does_not_improve_15_percent(self):
        """RMS from 10 to 9 is only 10% reduction — under the 15% threshold."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, duration_ms=40000)
        candidate = _constant_error_runs(9, duration_ms=35000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "rejected"
        assert decision.reason == "rms_error_threshold"

    def test_reject_insufficient_valid_candidate_runs(self):
        """Only 3 valid candidate runs out of required 5."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=3, duration_ms=35000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"

    def test_reject_insufficient_valid_baseline_runs(self):
        """Baseline has only 3 valid runs — must be rejected too."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=3, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=5, duration_ms=35000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"

    def test_reject_completion_rate_lower(self):
        """Candidate completion rate (3/5 = 60%) below baseline (5/5 = 100%)."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        completed_runs = _constant_error_runs(7.5, n=3, duration_ms=35000)
        incomplete_runs = _constant_error_runs(
            7.5, n=2, completed=False, duration_ms=35000,
            termination_reason="line_lost",
        )
        candidate = completed_runs + incomplete_runs
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "rejected"
        assert decision.reason == "completion_rate"

    def test_reject_max_error_increases(self):
        """Candidate max error > baseline max error (RMS threshold passes first)."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, duration_ms=40000)
        candidate = _constant_error_runs(6, duration_ms=35000)
        candidate[2] = _make_run(
            [_all_white_frame(22, 100), _all_white_frame(8, 500),
             _all_white_frame(9, 900), _all_white_frame(8, 1300)],
            completed=True,
        )
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "rejected"
        assert decision.reason == "max_error"

    def test_reject_track_loss_increases(self):
        """Candidate track loss > baseline track loss."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, duration_ms=40000)
        # 4 clean runs + 1 run with track loss = exactly 5
        candidate = _constant_error_runs(7.5, n=4, duration_ms=36000)
        frames_with_loss = (
            [_all_white_frame(5, t) for t in range(0, 50)]
            + [_all_black_frame(10, t) for t in range(50, 80)]
            + [_all_white_frame(5, t) for t in range(80, 100)]
        )
        candidate.append(_make_run(frames_with_loss, completed=True))
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "rejected"
        assert decision.reason == "track_loss"

    def test_reject_duration_not_improved_5_percent(self):
        """Candidate RMS is good, but duration only improved by 2.5%."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, duration_ms=40000)
        candidate = _constant_error_runs(7.5, duration_ms=39000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "rejected"
        assert decision.reason == "duration"

    def test_reject_safety_stop(self):
        """Candidate with a safety stop must be rejected (RMS threshold passes first)."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, duration_ms=40000)
        candidate = _constant_error_runs(6, duration_ms=36000)
        candidate[3] = _make_run(
            [_all_white_frame(5, t) for t in range(10)],
            completed=True, safety_stop=True, termination_reason="safety_stop",
        )
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "rejected"
        assert decision.reason == "safety_stop"

    def test_rejection_priority_insufficient_valid_runs_first(self):
        """Even if RMS would pass, insufficient runs takes priority."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=3, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=2, duration_ms=35000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"

    def test_rejection_priority_completion_rate_before_rms(self):
        """Completion rate checked before rms."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate = _constant_error_runs(7, duration_ms=35000)
        candidate[0] = _make_run(
            [_all_white_frame(5, t) for t in range(10)],
            completed=False, termination_reason="line_lost",
        )
        candidate[1] = _make_run(
            [_all_white_frame(5, t) for t in range(10)],
            completed=False, termination_reason="line_lost",
        )
        # 3/5 = 60% vs 5/5 = 100%
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "completion_rate"

    def test_rejection_priority_duration_before_safety_stop(self):
        """Duration (#6) must be checked before safety_stop (#7) (M4)."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, duration_ms=40000)
        # All 5 candidate runs meet RMS threshold (6 < 8.5).
        # Make the safety_stop run have the same 39000ms duration so it
        # does NOT artificially lower the mean — the mean stays at 39000.
        # 39000 > 38000 → fails at duration BEFORE safety stop.
        candidate = _constant_error_runs(6, duration_ms=39000)
        safety_run = _make_run(
            [_all_white_frame(5, 100 + t * 1000) for t in range(40)],
            completed=True, safety_stop=True, termination_reason="safety_stop",
        )
        candidate[3] = safety_run  # duration ≈ 39000 ms, safety_stop=True
        decision = evaluate_candidate(baseline, candidate)
        # Should fail at duration (priority #6) not safety_stop (#7)
        assert decision.reason == "duration"

    def test_no_candidate_raises(self):
        """No candidate runs at all raises ValueError."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        with pytest.raises(ValueError, match="candidate"):
            evaluate_candidate(baseline, [])

    def test_no_baseline_raises(self):
        """No baseline runs at all raises ValueError."""
        from analysis.campaign_metrics import evaluate_candidate
        candidate = _constant_error_runs(7.5, n=5, duration_ms=35000)
        with pytest.raises(ValueError, match="baseline"):
            evaluate_candidate([], candidate)

    # ----- Killer tests for valid semantics (I1/I2/I3) -----

    def test_4_valid_1_invalid_high_error_insufficient(self):
        """4 valid + 1 invalid(high-error): only 4 valid → insufficient_valid_runs."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate_good = _constant_error_runs(7.5, n=4, duration_ms=36000)
        candidate_bad = _make_run(
            [_all_white_frame(999, t) for t in range(10)],
            completed=True, valid=False,
        )
        candidate = candidate_good + [candidate_bad]
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"
        # The 999-error run must NOT be in baseline_agg stats
        assert decision.candidate_stats["n_valid"] == 4

    def test_invalid_completed_does_not_boost_completion_rate(self):
        """valid=False, completed=True must not increase completion_rate."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate_good = _constant_error_runs(7.5, n=4, duration_ms=36000)
        # This run is valid=False but completed=True — it should NOT
        # help completion_rate.  Only 4 valid → insufficient_valid_runs.
        candidate_invalid_completed = _make_run(
            [_all_white_frame(5, t) for t in range(10)],
            completed=True, valid=False,
        )
        candidate = candidate_good + [candidate_invalid_completed]
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"
        assert decision.candidate_stats["n_valid"] == 4

    def test_early_abort_does_not_shorten_duration(self):
        """A non-completed run with short duration must not lower mean_duration."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        # 5 valid candidate runs: 4 completed at 36000ms, 1 early abort at 100ms
        completed = _constant_error_runs(7.5, n=4, duration_ms=36000)
        early_abort = _make_run(
            [_all_white_frame(5, t) for t in range(0, 200, 10)],
            completed=False, termination_reason="line_lost",
        )
        candidate = completed + [early_abort]  # 5 valid, 4 completed
        # completion_rate = 4/5 = 0.8 vs baseline 1.0 → fails at completion_rate
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "completion_rate"
        # Verify duration is from 4 completed, NOT including the 190ms abort
        assert decision.candidate_stats["mean_duration_ms"] == pytest.approx(36000.0)

    # ----- Exact-5 gate killer tests (N1/N3) -----

    def test_5_good_plus_1_invalid_is_insufficient(self):
        """5 valid + 1 invalid = 6 total but 1 invalid → insufficient_valid_runs."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=5, duration_ms=36000)
        candidate.append(_make_run(
            [_all_white_frame(0, t) for t in range(5)],
            completed=True, valid=False,
        ))
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"
        assert decision.candidate_stats["n_runs"] == 6

    def test_5_good_plus_1_valid_is_insufficient(self):
        """5 valid + 1 valid (total 6) → insufficient_valid_runs (exact-5 gate)."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=6, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"

    def test_4_valid_1_invalid_exact_five_is_insufficient(self):
        """4 valid + 1 invalid = 5 total but 1 invalid → insufficient_valid_runs."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=4, duration_ms=36000)
        candidate.append(_make_run(
            [_all_white_frame(0, t) for t in range(5)],
            completed=True, valid=False,
        ))
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"
        assert decision.candidate_stats["n_invalid"] == 1

    def test_5_valid_1_not_completed_goes_to_completion_rate(self):
        """Exactly 5 valid, 1 completed=False → completion_rate, not insufficient."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=4, duration_ms=36000)
        candidate.append(_make_run(
            [_all_white_frame(5, t) for t in range(10)],
            completed=False, termination_reason="line_lost",
        ))
        decision = evaluate_candidate(baseline, candidate)
        # 4/5 completed = 80% vs baseline 100% → completion_rate
        assert decision.reason == "completion_rate"

    def test_5_valid_1_safety_stop_all_other_gates_pass(self):
        """Exactly 5 valid, 1 safety_stop but gates pass → safety_stop."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate = _constant_error_runs(6, n=4, duration_ms=36000)
        candidate.append(_make_run(
            [_all_white_frame(5, 100 + t * 1000) for t in range(40)],
            completed=True, safety_stop=True, termination_reason="safety_stop",
        ))
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "safety_stop"

    def test_baseline_less_than_5(self):
        """Baseline with 4 → insufficient_valid_runs."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=4, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=5, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"

    def test_baseline_more_than_5(self):
        """Baseline with 6 → insufficient_valid_runs."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=6, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=5, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"

    def test_baseline_has_invalid(self):
        """Baseline with a valid=False run → insufficient_valid_runs."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=4, duration_ms=40000)
        baseline.append(_make_run(
            [_all_white_frame(0, t) for t in range(5)],
            completed=True, valid=False,
        ))
        candidate = _constant_error_runs(7.5, n=5, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"

    def test_stats_include_n_total_n_valid_n_invalid(self):
        """Stats must expose n_total/n_valid/n_invalid for evidence tracking."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        # 4 valid + 1 invalid → 1 invalid
        candidate = _constant_error_runs(7.5, n=4, duration_ms=36000)
        candidate.append(_make_run(
            [_all_white_frame(0, t) for t in range(5)],
            completed=True, valid=False,
        ))
        decision = evaluate_candidate(baseline, candidate)
        assert "n_runs" in decision.baseline_stats
        assert "n_valid" in decision.baseline_stats
        assert "n_invalid" in decision.baseline_stats
        assert decision.candidate_stats["n_invalid"] == 1
        assert decision.candidate_stats["n_valid"] == 4

    def test_baseline_insufficient_valid(self):
        """Baseline with < 5 valid runs must fail insufficient_valid_runs."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=4, duration_ms=40000, valid=True)
        candidate = _constant_error_runs(7.5, n=5, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "insufficient_valid_runs"
        # baseline stats show n_valid=4
        assert decision.baseline_stats["n_valid"] == 4

    def test_extra_bad_run_does_not_hide_candidate_weakness(self):
        """A valid-but-bad run within the 5 must be counted in error metrics."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10, n=5, duration_ms=40000)
        candidate = _constant_error_runs(6, n=4, duration_ms=36000)
        # Add a 5th valid run with max_error=50 — exactly 5 runs total.
        candidate.append(_make_run(
            [_all_white_frame(50, t) for t in range(10)],
            completed=True,
        ))
        # 5 valid runs, one with error=50.
        # mean_rms = (6*4 + 50)/5 = 14.8 > 10*0.85 = 8.5 → rejected.
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "rejected"


# ============================================================
# Boundary tests
# ============================================================

class TestThresholdBoundaries:
    """Exact boundary tests to avoid floating-point random failures at 15%/5% edges."""

    def test_rms_exactly_15_percent_below_baseline_passes(self):
        """15% reduction = factor of 0.85 exactly on the boundary passes."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10.0, duration_ms=40000)
        candidate = _constant_error_runs(8.5, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "accepted" or (
            decision.status == "rejected" and decision.reason != "rms_error_threshold"
        )

    def test_rms_14_point_9_percent_below_baseline_fails(self):
        """14.9% reduction — just under the threshold."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10.0, duration_ms=40000)
        candidate = _constant_error_runs(8.51, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "rms_error_threshold"

    def test_exactly_5_percent_faster_duration_passes(self):
        """5% reduction = factor of 0.95 exactly on the boundary passes."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10.0, duration_ms=40000)
        candidate = _constant_error_runs(7.5, duration_ms=38000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.status == "accepted"

    def test_4_point_9_percent_faster_duration_fails(self):
        """4.9% reduction — just under the threshold."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10.0, duration_ms=40000)
        candidate = _constant_error_runs(7.5, duration_ms=39000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason == "duration"

    def test_equal_max_error_passes(self):
        """Max error equal to baseline does not trigger rejection."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10.0, duration_ms=40000)
        candidate = _constant_error_runs(6.0, duration_ms=36000)
        candidate[2] = _make_run(
            [_all_white_frame(10, 100), _all_white_frame(-5, 500),
             _all_white_frame(8, 900), _all_white_frame(9, 1300)],
        )
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason != "max_error"

    def test_equal_track_loss_passes(self):
        """Track loss equal to baseline does not trigger rejection."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10.0, duration_ms=40000)
        candidate = _constant_error_runs(7.5, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason not in ("track_loss",)

    def test_completion_rate_exactly_equal_passes(self):
        """Same completion rate as baseline does not trigger rejection."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(10.0, n=5, duration_ms=40000)
        candidate = _constant_error_runs(7.5, n=5, duration_ms=36000)
        decision = evaluate_candidate(baseline, candidate)
        assert decision.reason not in (
            "insufficient_valid_runs", "completion_rate",
        )

    def test_rms_0_exactly_equal_when_baseline_also_0(self):
        """If baseline RMS is 0, 15% improvement check must reject (no improvement)."""
        from analysis.campaign_metrics import evaluate_candidate
        baseline = _constant_error_runs(0.0, duration_ms=40000)
        candidate = _constant_error_runs(0.0, duration_ms=38000)
        decision = evaluate_candidate(baseline, candidate)
        # 0 >= 0 → True → rms_error_threshold
        assert decision.reason in ("rms_error_threshold",)


# ============================================================
# Invalid input tests
# ============================================================

class TestInvalidInputs:
    """Deterministic rejection of malformed or edge-case inputs."""

    def test_nan_error_values_rejected(self):
        from analysis.campaign_metrics import compute_run_summary
        frames = [_all_white_frame(float("nan"), 100)]
        with pytest.raises(ValueError, match="NaN|Inf"):
            compute_run_summary(frames=frames, completed=True,
                                termination_reason="completed")

    def test_inf_error_values_rejected(self):
        from analysis.campaign_metrics import compute_run_summary
        frames = [_all_white_frame(float("inf"), 100)]
        with pytest.raises(ValueError, match="NaN|Inf"):
            compute_run_summary(frames=frames, completed=True,
                                termination_reason="completed")

    def test_non_numeric_error_rejected(self):
        """String error values must raise."""
        from analysis.campaign_metrics import compute_run_summary
        frames = [{"error": "abc", "tick_ms": 100}]
        with pytest.raises(ValueError, match="non-numeric"):
            compute_run_summary(frames=frames, completed=True,
                                termination_reason="completed")

    def test_run_with_zero_frames_is_invalid(self):
        from analysis.campaign_metrics import compute_run_summary
        with pytest.raises(ValueError, match="empty|no frames"):
            compute_run_summary(frames=[], completed=True,
                                termination_reason="completed")
