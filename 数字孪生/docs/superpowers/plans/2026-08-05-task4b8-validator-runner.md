# Task 4B-8 Validator and Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed, pure-Python 4B-8 readiness validator and an injected-predictor runner without claiming real-camera, synchronized-telemetry, or real-car evidence.

**Architecture:** `V1TwinValidator` computes G1-G8 from explicit evidence dictionaries and holdout summaries. `V1TwinRunner` validates PID parameters and a `V1TrackMap`, then delegates prediction to a required callable and validates the typed result. Neither module opens hardware or creates fabricated defaults.

**Tech Stack:** Python 3.11, dataclasses, typing, pytest, the existing `v1_twin_schema` types.

## Global Constraints

- Offline only: no camera, TCP, serial, flash, reset, debugger, or motor command.
- Do not modify firmware, camera/transport tools, existing calibration records, or model-registry semantics.
- Do not overwrite existing evidence directories; write only the new acceptance report under `.embeddedskills/build/v1_task4b8/`.
- No Git writes. Read-only `git status`/`git log` are allowed.
- Missing or malformed evidence is `INSUFFICIENT_EVIDENCE`; an explicit measured safety failure is `FAIL`.
- Aggregate verdict is `NOT_READY` if any gate fails, `INSUFFICIENT_EVIDENCE` if no gate fails but any gate lacks evidence, otherwise `READY`.

---

### Task 1: Define the runner contract with failing tests

**Files:**
- Create: `simulation/digital_twin/tests/test_v1_twin_runner.py`
- Create: `simulation/digital_twin/v1_twin/v1_twin_runner.py`

**Interfaces:**
- Consumes: `V1TrackMap` from `v1_twin_schema` and a callable
  `predictor(pid_params: Mapping[str, object], track_map: V1TrackMap) -> V1PredictedRun`.
- Produces: `V1TwinRunner`, `V1TwinRunnerError`, `V1PredictionMetrics`, and
  `V1PredictedRun` with deterministic `to_dict()` output.

- [ ] **Step 1: Write the failing runner tests**

  Add a small valid map fixture and tests for the exact public contract:

  ```python
  def test_runner_delegates_and_returns_validated_prediction():
      calls = []
      def predictor(params, track_map):
          calls.append((dict(params), track_map))
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
      result = V1TwinRunner(predictor, model_version="model-1").run(
          {"kp": 35.0, "ki": 0.0, "kd": 10.0}, valid_map()
      )
      assert result.pid_group_id == "pid-01"
      assert calls[0][0]["kp"] == 35.0
      assert result.to_dict()["model_version"] == "model-1"
  ```

  Also cover missing predictor, missing `kp`/`ki`/`kd`, non-finite PID values,
  wrong map type, wrong predictor result type, invalid terminal class, and
  NaN/negative metric values. These tests must import the not-yet-existing
  module so they fail because the contract is absent.

- [ ] **Step 2: Run the runner tests and verify the expected RED result**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_runner.py
  ```

  Expected: collection/import failure naming `v1_twin_runner` or its missing
  public symbols, not a test typo.

### Task 2: Implement the minimal typed runner

**Files:**
- Modify: `simulation/digital_twin/v1_twin/v1_twin_runner.py`
- Test: `simulation/digital_twin/tests/test_v1_twin_runner.py`

**Interfaces:**
- `V1PredictionMetrics(sensor_macro_f1, lateral_error_p95_mm, predicted_score, completion_time_s)`.
- `V1PredictedRun(pid_group_id, terminal_class, metrics, danger_predicted)`.
- `V1TwinRunner(predictor, model_version).run(pid_params, track_map) -> V1PredictedRun`.

- [ ] **Step 1: Add dataclasses and validation helpers**

  Require finite numeric metrics, `sensor_macro_f1` in [0, 1], non-negative
  lateral error and completion time, a non-empty group ID, a terminal class in
  `completed`, `line_loss`, `safety_stop`, or `timeout`, and a real bool for
  `danger_predicted`. Require a mapping containing finite numeric `kp`, `ki`,
  and `kd`; allow additional finite numeric PID fields.

- [ ] **Step 2: Implement `V1TwinRunner.run`**

  Reject a non-callable predictor, wrong map type, or malformed predictor
  output with `V1TwinRunnerError`. Call the predictor exactly once, attach the
  runner's model version in `to_dict()`, and return no default prediction when
  the predictor is absent.

- [ ] **Step 3: Run the runner tests and refactor only after GREEN**

  Run the focused test file again. Expected: all tests pass with no warnings.

### Task 3: Define G1-G8 and isolation behavior with failing tests

**Files:**
- Create: `simulation/digital_twin/tests/test_v1_twin_validator.py`
- Create: `simulation/digital_twin/v1_twin/v1_twin_validator.py`

**Interfaces:**
- Consumes: `gate_evidence: Mapping[str, Mapping[str, object]] | None` for G1-G4 and
  `holdout_evidence: Mapping[str, object] | None` for G5-G8.
- Produces: `V1GateResult`, `V1ValidationReport`, and
  `V1TwinValidator.evaluate(gate_evidence, holdout_evidence, *, calibration_run_ids=(), holdout_run_ids=(), model_version=None)`.

- [ ] **Step 1: Write boundary tests before implementation**

  Add tests for:

  ```python
  def test_empty_evidence_is_insufficient_not_ready():
      report = V1TwinValidator.evaluate(None, None)
      assert report.verdict == "INSUFFICIENT_EVIDENCE"
      assert all(g.status == "INSUFFICIENT_EVIDENCE" for g in report.gates.values())

  def test_all_thresholds_at_boundary_produce_ready():
      report = V1TwinValidator.evaluate(valid_g1_to_g4(), valid_holdout(),
                                         calibration_run_ids=("cal-1",),
                                         holdout_run_ids=("hold-1", "hold-2", "hold-3", "hold-4", "hold-5"),
                                         model_version="model-1")
      assert report.verdict == "READY"
      assert all(g.status == "PASS" for g in report.gates.values())

  def test_explicit_monotonicity_failure_is_not_insufficient_evidence():
      evidence = valid_g1_to_g4()
      evidence["G1"]["timestamps_monotonic"] = False
      report = V1TwinValidator.evaluate(evidence, valid_holdout())
      assert report.verdict == "NOT_READY"
      assert report.gates["G1"].status == "FAIL"

  def test_holdout_overlap_fails_isolation():
      report = V1TwinValidator.evaluate(valid_g1_to_g4(), valid_holdout(),
                                         calibration_run_ids=("same",),
                                         holdout_run_ids=("same",))
      assert report.verdict == "NOT_READY"
      assert report.data_isolation["status"] == "FAIL"
  ```

  Add threshold tests for G1 fps/drop/invalid frames, G2 reprojection, G3
  detection and pose errors, G4 coverage/time, G5 inversion, G6 terminal
  agreement, G7 three relative-error limits, G8 fewer than five groups,
  Spearman below 0.70, and danger recall below 1.0. Add malformed/NaN and
  missing-field tests that expect `INSUFFICIENT_EVIDENCE`, plus JSON
  serialization coverage.

- [ ] **Step 2: Run validator tests and verify the expected RED result**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_validator.py
  ```

  Expected: import/collection failure for the absent validator module.

### Task 4: Implement the fail-closed validator

**Files:**
- Modify: `simulation/digital_twin/v1_twin/v1_twin_validator.py`
- Test: `simulation/digital_twin/tests/test_v1_twin_validator.py`

**Interfaces:**
- G1 evidence keys: `fps`, `drop_rate`, `timestamps_monotonic`, `invalid_frames`.
- G2 keys: `reprojection_p95_px`, `black_line_width_px`.
- G3 keys: `detection_rate`, `x_p95_mm`, `y_p95_mm`, `yaw_p95_deg`, `black_line_width_mm`.
- G4 keys: `coverage`, `p95_time_diff_ms`, `period_bound_ms`.
- Holdout `g5`: `macro_f1`, `semantic_inversion`, `sample_count`.
- Holdout `g6`: `lateral_error_p95_mm`, `black_line_width_mm`, `terminal_class_accuracy`, `sample_count`.
- Holdout `g7`: `rms_relative_error`, `max_relative_error`, `completion_time_relative_error`, `sample_count`.
- Holdout `g8`: `group_count`, `spearman`, `danger_recall`, `danger_count`, `sample_count`.

- [ ] **Step 1: Implement shared evidence parsing**

  Use finite-number and bounded-fraction helpers. Missing keys, wrong types,
  non-finite values, negative counts, and empty sections return an
  `INSUFFICIENT_EVIDENCE` result with a precise reason. Do not silently coerce
  bools to numbers.

- [ ] **Step 2: Implement G1-G4 threshold evaluators**

  Use the exact thresholds in the design: G1 fps >= 20/drop <= 0.05/
  monotonic/invalid == 0; G2 threshold `max(2.0, 0.05 * width_px)`; G3
  position threshold `0.05 * width_mm` and yaw <= 2 degrees; G4 coverage >=
  0.95 and p95 time <= the supplied period bound. Any measured threshold
  violation is `FAIL`.

- [ ] **Step 3: Implement G5-G8 holdout evaluators**

  Require each section and positive `sample_count`. G5 rejects semantic
  inversion and requires macro-F1 >= 0.90. G6 requires lateral p95 <= half
  the line width and terminal class accuracy == 1.0. G7 applies 0.15/0.15/
  0.10 limits. G8 requires group_count >= 5, Spearman >= 0.70, and danger
  recall == 1.0; a nonzero danger count with a lower recall is an explicit
  failure.

- [ ] **Step 4: Implement isolation and aggregate report**

  Normalize run IDs to unique non-empty strings. Missing IDs are insufficient;
  overlap is an explicit `FAIL`. Build an immutable-style report object whose
  `to_dict()` contains only JSON-compatible values. Aggregate statuses in the
  order `FAIL` > `INSUFFICIENT_EVIDENCE` > `PASS`.

- [ ] **Step 5: Run focused validator tests and refactor after GREEN**

  Run both new test files. Expected: all tests pass with no warnings.

### Task 5: Offline regression, evidence report, and independent review

**Files:**
- Create: `.embeddedskills/build/v1_task4b8/task4b8_offline_acceptance.md`
- Do not modify existing evidence directories.

- [ ] **Step 1: Run focused verification**

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_runner.py simulation/digital_twin/tests/test_v1_twin_validator.py
  py -3.11 -m py_compile simulation/digital_twin/v1_twin/v1_twin_runner.py simulation/digital_twin/v1_twin/v1_twin_validator.py
  ```

- [ ] **Step 2: Run the full digital-twin regression**

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests
  ```

  Record exact counts and exit codes; do not call the work hardware-complete.

- [ ] **Step 3: Invoke DS for an independent read-only review**

  Give DS the two new modules, tests, plan, and focused/full test output. DS
  must not edit files, access hardware, or run camera/TCP/serial/flash actions.
  Save its verdict and any findings in a new review log. Evaluate every finding
  against the source and tests before changing anything.

- [ ] **Step 4: Write the acceptance handoff**

  Record changed files, hashes, exact commands/results, DS verdict, and the
  hard boundary: 4B-8 remains `SOFTWARE_ONLY_SKELETON_PASS /
  REAL_DATA_INSUFFICIENT_EVIDENCE` until 4B-4 synchronized data, a frozen
  model, and the required independent holdout runs exist. State clearly that
  no user presence was needed for this offline task.
