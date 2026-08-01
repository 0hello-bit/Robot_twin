"""Campaign metrics calculation and strict candidate acceptance rules.

This module provides:
- RunSummary: computed metrics from raw telemetry for a single run
- CandidateDecision: acceptance/rejection result for a candidate parameter set
- track_loss_count(): count contiguous all-zero sensor intervals
- compute_run_summary(): extract deterministic metrics from raw telemetry frames
- aggregate_run_summaries(): pool metrics across multiple runs
- evaluate_candidate(): strict multi-threshold acceptance/rejection decision
- run_summary_from_task2_json(): production entry for RealDataLogger output
- run_summary_from_frame_list(): production entry from raw frame sequence
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ============================================================
# Known termination reasons (from firmware / Task 2 schema)
# ============================================================

_KNOWN_TERMINATION_REASONS = frozenset({
    "completed",
    "line_lost",
    "safety_stop",
    "timeout",
    "manual_stop",
    "operator_stop",
})


def _is_termination_reason_known(reason: str) -> bool:
    """Check whether *reason* is a known termination reason string."""
    return reason in _KNOWN_TERMINATION_REASONS


# ============================================================
# Data models
# ============================================================


@dataclass(frozen=True)
class RunSummary:
    """Immutable computed metrics for a single run."""
    mae: float                     # mean absolute error
    rms_error: float               # root-mean-square error
    max_error: float               # maximum absolute error
    track_loss_count: int          # number of track-loss events
    duration_ms: int               # completion time in milliseconds
    completed: bool                # run completed the full track
    termination_reason: str        # how the run ended
    safety_stop: bool              # was a safety stop triggered
    valid: bool = True             # meets test protocol; only valid runs
                                   # count toward acceptance evidence


@dataclass(frozen=True)
class CandidateDecision:
    """Result of evaluating a candidate parameter set against baseline."""
    status: str                    # "accepted" or "rejected"
    reason: str                    # rejection reason (empty if accepted)
    baseline_stats: Dict[str, Any] = field(default_factory=dict)
    candidate_stats: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# Sensor helpers
# ============================================================


def _sensor_is_black(value: Any) -> bool:
    """Return True if a sensor reading represents 'on black line'.

    Accepts int 0, bool False, and the string ``"0"``.  This is
    resilient to JSON serialisation that may convert 0 → ``"0"``.
    Rejects any other type or value as non-black (white / unknown).
    """
    if isinstance(value, bool):
        return not value  # False  → black (0)
    if isinstance(value, int):
        return value == 0
    if isinstance(value, str):
        return value == "0"
    return False


# ============================================================
# Track loss counting
# ============================================================

def track_loss_count(frames: Sequence[Dict[str, Any]]) -> int:
    """Count contiguous all-zero sensor intervals (track-loss events).

    A track-loss event is a contiguous sequence of frames where all four
    line sensors read 0 (black). Adjacent all-zero frames are part of the
    same event; separated all-zero intervals count as separate events.

    This counting method is invariant to sampling rate — doubling the
    frame rate within the same loss interval does not change the count.
    """
    count = 0
    in_loss = False
    for frame in frames:
        sensors = frame.get("sensors", [1, 1, 1, 1])
        all_zero = all(_sensor_is_black(s) for s in sensors)
        if all_zero and not in_loss:
            count += 1
            in_loss = True
        elif not all_zero:
            in_loss = False
    return count


# ============================================================
# Single-run metrics computation
# ============================================================

def compute_run_summary(
    frames: Sequence[Dict[str, Any]],
    completed: bool = True,
    termination_reason: str = "completed",
    safety_stop: bool = False,
    valid: bool = True,
) -> RunSummary:
    """Compute deterministic metrics from a telemetry frame sequence.

    Args:
        frames: List of raw telemetry frame dicts, each with ``'error'``,
                ``'sensors'``, and ``'tick_ms'`` keys.
        completed: Whether the run completed the full track.
        termination_reason: Machine-readable reason the run ended.
        safety_stop: Whether a safety stop was triggered.
        valid: Whether this run meets the test protocol and may be
               counted toward acceptance decisions.

    Returns:
        A frozen RunSummary with all computed metrics.

    Raises:
        ValueError: If *frames* is empty, contains NaN/Inf error values,
                    has negative duration, or *termination_reason* is
                    not a known value.
    """
    if not frames:
        raise ValueError("no frames: cannot compute metrics from empty telemetry")

    if not termination_reason:
        raise ValueError("termination_reason is required")
    if not _is_termination_reason_known(termination_reason):
        raise ValueError(
            "unknown termination_reason: {0!r}".format(termination_reason)
        )

    errors = []
    for f in frames:
        err = f.get("error", 0)
        if isinstance(err, (int, float)):
            if not math.isfinite(err):
                raise ValueError(
                    "NaN or Inf error value detected in telemetry"
                )
            errors.append(float(err))
        else:
            # Non-numeric error (e.g. string) — reject rather than guess
            raise ValueError(
                "non-numeric error value: {0!r}".format(err)
            )

    if not errors:
        raise ValueError("no valid error values in frames")

    # MAE
    abs_errors = [abs(e) for e in errors]
    mae = sum(abs_errors) / len(abs_errors)

    # RMS
    rms_error = math.sqrt(sum(e * e for e in errors) / len(errors))

    # Max absolute error
    max_error = max(abs_errors)

    # Track loss count
    loss_count = track_loss_count(frames)

    # Duration — use first and last frame tick to detect non-monotonic sequences
    tick_ms_values = [f.get("tick_ms", 0) or 0 for f in frames]
    if tick_ms_values:
        first_tick = tick_ms_values[0]
        last_tick = tick_ms_values[-1]
        if last_tick < first_tick:
            raise ValueError("negative duration: tick_ms not monotonic")
        duration_ms = last_tick - first_tick
    else:
        duration_ms = 0

    return RunSummary(
        mae=mae,
        rms_error=rms_error,
        max_error=max_error,
        track_loss_count=loss_count,
        duration_ms=duration_ms,
        completed=completed,
        termination_reason=termination_reason,
        safety_stop=safety_stop,
        valid=valid,
    )


# ============================================================
# Task 2 JSON / raw frame production entries
# ============================================================

def run_summary_from_task2_json(task2_data: Dict[str, Any]) -> RunSummary:
    """Convert a ``RealDataLogger.save_campaign()`` JSON dict to RunSummary.

    Expected structure (produced by ``data_logger.py``)::

        {
            "_campaign_meta": {
                "campaign_id": "camp-001",
                "run_id": "run-007",
                "parameter_version": 2,
                "termination_reason": "completed"
            },
            "data": [
                {"tick_ms": 100, "error": 0, "sensors": [1,1,1,1], ...},
                ...
            ]
        }

    Raises:
        ValueError: If the dict is not a recognised Task 2 campaign JSON,
                    *data* is empty, or termination_reason is unknown.
    """
    meta = task2_data.get("_campaign_meta")
    if not meta or not isinstance(meta, dict):
        raise ValueError("missing _campaign_meta — not a Task 2 campaign JSON")

    campaign_id = meta.get("campaign_id", "")
    run_id = meta.get("run_id", "")
    parameter_version = meta.get("parameter_version", 0)
    termination_reason = meta.get("termination_reason", "")

    if not campaign_id:
        raise ValueError("missing campaign_id in _campaign_meta")
    if not run_id:
        raise ValueError("missing run_id in _campaign_meta")

    frames = task2_data.get("data", [])
    if not frames or not isinstance(frames, list):
        raise ValueError("empty or missing data array in Task 2 JSON")

    completed = termination_reason == "completed"
    safety_stop = termination_reason == "safety_stop"

    return compute_run_summary(
        frames=frames,
        completed=completed,
        termination_reason=termination_reason,
        safety_stop=safety_stop,
        valid=True,
    )


def run_summary_from_frame_list(
    frames: Sequence[Dict[str, Any]],
    termination_reason: str,
    campaign_id: str = "",
    run_id: str = "",
) -> RunSummary:
    """Build a RunSummary directly from a raw frame list.

    This is the lower-level entry point for callers that already have
    parsed telemetry frames (e.g. from a replay file or live stream)
    without the enclosing ``_campaign_meta`` wrapper.

    Args:
        frames: List of dicts with at least ``'error'`` and ``'tick_ms'``.
        termination_reason: How the run ended.
        campaign_id: Optional — for informational / logging use.
        run_id: Optional — for informational / logging use.

    Raises:
        ValueError: If *termination_reason* is unknown or *frames* is empty.
    """
    completed = termination_reason == "completed"
    safety_stop = termination_reason == "safety_stop"

    return compute_run_summary(
        frames=frames,
        completed=completed,
        termination_reason=termination_reason,
        safety_stop=safety_stop,
        valid=True,
    )


# ============================================================
# Aggregation
# ============================================================

def aggregate_run_summaries(
    runs: Sequence[RunSummary],
) -> Dict[str, Any]:
    """Aggregate metrics across multiple runs.

    **Only** runs where ``valid is True`` are used for every metric.
    Runs with ``valid is False`` are excluded from completion_rate,
    safety_stop, error, track-loss *and* duration metrics —
    they cannot provide any positive benefit.

    The ``mean_duration_ms`` field is computed **only** from runs that
    are both ``valid is True`` **and** ``completed is True`` (early-abort
    or failed runs do not contribute a short duration that would lower
    the mean).

    When there are zero valid runs, *or* zero completed+valid runs for
    duration, the corresponding stats are set to ``None`` (serialised as
    JSON ``null``) so downstream callers cannot mistake them for perfect
    metrics.

    Returns a dict with:
        - n_runs: total number of runs (including invalid)
        - n_valid: number of valid runs
        - n_invalid: number of invalid runs
        - n_baseline_valid: aliased to n_valid for caller convenience
        - completion_rate: completed_valid / total_valid (0.0 … 1.0, or None)
        - safety_stop_count: count of valid runs with safety_stop
        - mean_mae: mean of MAE across valid runs (or None)
        - mean_rms: mean of RMS across valid runs (or None)
        - max_max_error: maximum of max_error across valid runs (or None)
        - mean_duration_ms: mean of duration_ms across completed+valid
          runs (or None)
        - max_track_loss: maximum of track_loss_count across valid runs
          (or None)

    Raises:
        ValueError: If *runs* sequence is empty.
    """
    if not runs:
        raise ValueError("empty run sequence")

    valid_runs = [r for r in runs if r.valid]
    completed_runs = [r for r in valid_runs if r.completed]
    n_runs = len(runs)
    n_valid = len(valid_runs)
    n_invalid = n_runs - n_valid

    if n_valid == 0:
        return {
            "n_runs": n_runs,
            "n_valid": 0,
            "n_invalid": n_invalid,
            "n_baseline_valid": 0,
            "completion_rate": None,
            "safety_stop_count": None,
            "mean_mae": None,
            "mean_rms": None,
            "max_max_error": None,
            "mean_duration_ms": None,
            "max_track_loss": None,
        }

    completion_rate = len(completed_runs) / n_valid if n_valid > 0 else None
    safety_stop_count = sum(1 for r in valid_runs if r.safety_stop)

    mean_mae = sum(r.mae for r in valid_runs) / n_valid
    mean_rms = sum(r.rms_error for r in valid_runs) / n_valid
    max_max_error = max(r.max_error for r in valid_runs)
    max_track_loss = max(r.track_loss_count for r in valid_runs)

    if completed_runs:
        mean_duration_ms = sum(r.duration_ms for r in completed_runs) / len(completed_runs)
    else:
        mean_duration_ms = None

    return {
        "n_runs": n_runs,
        "n_valid": n_valid,
        "n_invalid": n_invalid,
        "n_baseline_valid": n_valid,
        "completion_rate": completion_rate,
        "safety_stop_count": safety_stop_count,
        "mean_mae": mean_mae,
        "mean_rms": mean_rms,
        "max_max_error": max_max_error,
        "mean_duration_ms": mean_duration_ms,
        "max_track_loss": max_track_loss,
    }


# ============================================================
# Acceptance / rejection decision
# ============================================================

REJECTION_PRIORITY = [
    "insufficient_valid_runs",
    "completion_rate",
    "rms_error_threshold",
    "max_error",
    "track_loss",
    "duration",
    "safety_stop",
]

RMS_IMPROVEMENT_FACTOR = 0.85   # candidate RMS <= baseline RMS * 0.85
DURATION_IMPROVEMENT_FACTOR = 0.95  # candidate duration <= baseline * 0.95
MIN_VALID_RUNS = 5


def evaluate_candidate(
    baseline_runs: Sequence[RunSummary],
    candidate_runs: Sequence[RunSummary],
) -> CandidateDecision:
    """Evaluate candidate parameter set against baseline using strict rules.

    **Exact-5 gate (N1/N3):**

    Both *baseline_runs* and *candidate_runs* must contain **exactly** 5
    runs, each with ``valid is True``.  Any deviation — fewer than 5,
    more than 5, or any ``valid is False`` — is immediately rejected
    with ``insufficient_valid_runs``.

    Failed runs (``completed=False``, ``safety_stop=True``) remain
    ``valid=True`` provided the telemetry data is complete and finite.
    They are not automatically marked invalid; instead they progress
    through the normal priority chain (``completion_rate``,
    ``safety_stop``, etc.).

    **Metrics computation:**

    - ``aggregate_run_summaries`` receives the full run lists (not
      filtered), guaranteeing that the stats dicts reflect the true
      ``n_total`` / ``n_valid`` / ``n_invalid`` counts.
    - ``mean_duration_ms`` is computed from runs that are **both**
      ``valid is True`` **and** ``completed is True``.

    Args:
        baseline_runs: RunSummary sequence from baseline parameter set.
        candidate_runs: RunSummary sequence from candidate parameter set.

    Returns:
        CandidateDecision with status ``"accepted"`` or ``"rejected"``.
        On rejection, ``reason`` contains the first failing criterion
        from the fixed priority order.

    Raises:
        ValueError: If either sequence is empty.
    """
    if not baseline_runs:
        raise ValueError("no baseline runs provided")
    if not candidate_runs:
        raise ValueError("no candidate runs provided")

    # Aggregate the full (unfiltered) lists so stats reflect true counts.
    baseline_agg = aggregate_run_summaries(baseline_runs)
    candidate_agg = aggregate_run_summaries(candidate_runs)

    # --- Exact-5 gate (N1/N3) ---
    # Both baseline and candidate must have exactly 5 runs, all valid=True.
    def _exact_five(runs, agg):
        if len(runs) != MIN_VALID_RUNS:
            return agg
        for r in runs:
            if not r.valid:
                return agg
        return None

    baseline_bad = _exact_five(baseline_runs, baseline_agg)
    if baseline_bad is not None:
        return CandidateDecision(
            status="rejected",
            reason="insufficient_valid_runs",
            baseline_stats=baseline_bad,
            candidate_stats=candidate_agg,
        )
    candidate_bad = _exact_five(candidate_runs, candidate_agg)
    if candidate_bad is not None:
        return CandidateDecision(
            status="rejected",
            reason="insufficient_valid_runs",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_bad,
        )

    # 1. insufficient_valid_runs — aggregate already verifies n_valid.
    #    (Also caught by exact-5 gate above, but kept for defence in depth.)
    if baseline_agg["n_valid"] < MIN_VALID_RUNS:
        return CandidateDecision(
            status="rejected",
            reason="insufficient_valid_runs",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_agg,
        )
    if candidate_agg["n_valid"] < MIN_VALID_RUNS:
        return CandidateDecision(
            status="rejected",
            reason="insufficient_valid_runs",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_agg,
        )

    # 2. completion_rate
    if candidate_agg["completion_rate"] < baseline_agg["completion_rate"]:
        return CandidateDecision(
            status="rejected",
            reason="completion_rate",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_agg,
        )

    # 3. rms_error_threshold
    # Must show improvement: RMS must be strictly less than baseline RMS,
    # and at least 15% lower.
    if candidate_agg["mean_rms"] >= baseline_agg["mean_rms"]:
        return CandidateDecision(
            status="rejected",
            reason="rms_error_threshold",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_agg,
        )
    if candidate_agg["mean_rms"] > baseline_agg["mean_rms"] * RMS_IMPROVEMENT_FACTOR:
        return CandidateDecision(
            status="rejected",
            reason="rms_error_threshold",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_agg,
        )

    # 4. max_error
    if candidate_agg["max_max_error"] > baseline_agg["max_max_error"]:
        return CandidateDecision(
            status="rejected",
            reason="max_error",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_agg,
        )

    # 5. track_loss
    if candidate_agg["max_track_loss"] > baseline_agg["max_track_loss"]:
        return CandidateDecision(
            status="rejected",
            reason="track_loss",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_agg,
        )

    # 6. duration — only checked if all previous pass
    # Use completed+valid runs only (via aggregate_run_summaries).
    if candidate_agg["mean_duration_ms"] is None:
        # No completed candidate runs — duration cannot improve
        return CandidateDecision(
            status="rejected",
            reason="duration",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_agg,
        )
    if baseline_agg["mean_duration_ms"] is not None:
        if candidate_agg["mean_duration_ms"] > baseline_agg["mean_duration_ms"] * DURATION_IMPROVEMENT_FACTOR:
            return CandidateDecision(
                status="rejected",
                reason="duration",
                baseline_stats=baseline_agg,
                candidate_stats=candidate_agg,
            )

    # 7. safety_stop — all candidate runs must be free of safety stops
    if candidate_agg["safety_stop_count"] > 0:
        return CandidateDecision(
            status="rejected",
            reason="safety_stop",
            baseline_stats=baseline_agg,
            candidate_stats=candidate_agg,
        )

    return CandidateDecision(
        status="accepted",
        reason="",
        baseline_stats=baseline_agg,
        candidate_stats=candidate_agg,
    )
