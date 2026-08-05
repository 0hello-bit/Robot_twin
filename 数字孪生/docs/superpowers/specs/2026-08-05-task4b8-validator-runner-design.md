# Task 4B-8 Validator and Runner Design

**Status:** IMPLEMENTED - SOFTWARE-ONLY SKELETON

## Goal

Provide a reusable, fail-closed software boundary for the V1 model readiness
gate. The implementation must distinguish `READY`, `NOT_READY`, and
`INSUFFICIENT_EVIDENCE` without fabricating camera, synchronized telemetry, or
real-car results.

## Scope

This increment adds only two pure-Python modules and their tests:

- `simulation/digital_twin/v1_twin/v1_twin_validator.py`
- `simulation/digital_twin/v1_twin/v1_twin_runner.py`
- `simulation/digital_twin/tests/test_v1_twin_validator.py`
- `simulation/digital_twin/tests/test_v1_twin_runner.py`

It does not alter firmware, camera tools, transport code, existing calibration
records, model registry behavior, or any real evidence directory.

## Gate Contract

`V1TwinValidator.evaluate(gates, holdout)` returns a serializable report with
G1 through G8, each having `status` in `PASS`, `FAIL`, or
`INSUFFICIENT_EVIDENCE`, plus measured values, thresholds, and a reason.

The aggregate status is computed as follows:

1. Any explicit `FAIL` produces `NOT_READY`.
2. With no failures, any missing or insufficient gate produces
   `INSUFFICIENT_EVIDENCE`.
3. Only eight `PASS` gates produce `READY`.

Missing fields, empty input, non-finite numbers, and insufficient sample counts
are evidence failures, not passes. An explicit observed failure remains a
`FAIL`, so safety evidence cannot be hidden by a small sample.

The thresholds are fixed to the project plan:

- G1: fps >= 20, drop <= 0.05, monotonic timestamps, invalid frames == 0.
- G2: reprojection p95 <= max(2 px, 5% of black-line width in px).
- G3: detection rate >= 0.95, x/y p95 <= 5% of black-line width, yaw p95 <= 2 deg.
- G4: match coverage >= 0.95 and p95 time difference <= the supplied period bound.
- G5: holdout macro-F1 >= 0.90 and no semantic inversion.
- G6: holdout lateral-error p95 <= 0.5 black-line width and terminal class agrees.
- G7: RMS relative error <= 0.15, maximum relative error <= 0.15, and
  completion-time relative error <= 0.10.
- G8: at least five unseen PID groups, Spearman rank >= 0.70, and danger
  recall == 1.0.

G1-G4 consume already-produced gate evidence. G5-G8 consume independent
holdout evaluation records. No gate runs hardware itself.

## Runner Contract

`V1TwinRunner` is a thin deterministic adapter around an injected predictor:

```python
runner = V1TwinRunner(predictor)
predicted = runner.run(pid_params, track_map)
```

The predictor must be callable and return a `V1PredictedRun` containing finite
metric values and a terminal class. The runner validates parameters, track-map
type, returned shape, and numeric finiteness. It raises `V1TwinRunnerError`
for missing predictors, malformed results, or implicit fabricated defaults. A
runner therefore supplies a stable interface for a later model-backed runner
without claiming that the current exploratory plant is physically calibrated.

## Error and Evidence Rules

- The validator never catches an explicit safety failure and converts it to
  insufficient evidence.
- NaN, infinity, negative rates, percentages outside [0, 1], and impossible
  sample counts are rejected as malformed evidence.
- Holdout group IDs must be disjoint from calibration IDs and unique.
- The report is JSON-serializable and contains no raw camera frames or socket
  handles.

## Verification

Tests will cover all threshold boundaries, missing evidence, malformed values,
semantic inversion, danger-recall failure, holdout isolation, runner input
validation, deterministic predictor output, and report serialization. The
full offline digital-twin suite must remain green. No camera, TCP, serial,
flash, reset, or motor command is part of this task.
