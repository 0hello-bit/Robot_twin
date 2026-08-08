# B3 Observation Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only offline replay gate that evaluates whether a real synchronized capture has enough continuous AprilTag observation quality for downstream B3 use.

**Architecture:** Reuse the existing `frame_index.jsonl` and `sync_report.json` artifacts. A small domain module will compute detection ratio, longest pose gap, and detector processing budget, classify evidence as `VERIFIED` or `INSUFFICIENT_EVIDENCE`, and report `PASS` or `FAIL` without changing the production detector or overwriting raw evidence. A CLI will write a new derived report only when the caller supplies a new output path.

**Tech Stack:** Python 3.10+, standard library JSON/hashlib/pathlib, pytest, existing `simulation/digital_twin` package layout.

## Global Constraints

- This task is offline-only: no camera, TCP, START, STOP, firmware build, flash, reset, or motor action.
- Reuse the existing capture artifacts and parser boundaries; do not add a second camera detector, TCP client, session store, or synchronization implementation.
- Require both the existing synchronization sub-gate and the overall capture verdict to be `PASS` before any real observation result can be verified.
- Preserve `VERIFIED`, `INFERENCE`, and `INSUFFICIENT_EVIDENCE` distinctions. A real run that fails the observation thresholds is a verified failed gate, not a successful B3 result.
- Do not modify AprilTag production parameters or calibration in this task.
- The first engineering profile is fixed at 30 fps, detection ratio >= 0.95, maximum detected-pose gap <= 2 frame periods, and detector p95 <= one frame period. These are declared screening thresholds, not claims of physical truth.
- Never overwrite raw session artifacts or an existing derived report.
- The CLI may declare `REAL_SYNC` only for the existing canonical capture roots; arbitrary temporary paths remain insufficient evidence.

---

### Task 1: Define the observation-gate contract with failing tests

**Files:**
- Create: `simulation/digital_twin/tests/test_v1_twin_observation_gate.py`
- Create: `simulation/digital_twin/v1_twin/v1_twin_observation_gate.py`

**Interfaces:**
- Consumes: ordered frame-index dictionaries with `frame_index`, `read_ok`, `pose_detected` or legacy `pose_present`, `t_pc_ns`, `failure_reason`, and optional `detect_elapsed_ns`, plus both sync and overall capture verdicts.
- Produces: `B3ObservationGateConfig`, `B3ObservationGateReport`, `evaluate_observation_gate()`, and `load_frame_index()`.

- [x] **Step 1: Write the failing tests**

  Cover these behaviors:

  ```python
  def test_real_sync_run_reports_verified_failed_observation_gate():
      records = make_records(
          [(0, True, 0), (1, False, 33_333_333), (2, True, 66_666_666)],
          elapsed_ns=40_000_000,
      )
      report = evaluate_observation_gate(
          records,
          source="REAL_SYNC",
          sync_gate_verdict="PASS",
          run_id="run-1",
      )
      assert report.evidence_status == "VERIFIED"
      assert report.verdict == "FAIL"
      assert "detection_ratio_below_threshold" in report.reasons
      assert "detector_processing_over_budget" in report.reasons

  def test_non_real_source_is_insufficient_evidence():
      report = evaluate_observation_gate(
          make_records([(0, True, 0), (1, True, 33_333_333)]),
          source="SYNTHETIC",
          sync_gate_verdict="PASS",
      )
      assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
      assert report.verdict == "INSUFFICIENT_EVIDENCE"
      assert report.reasons == ("source_not_real_sync",)

  def test_missing_or_non_monotonic_observation_data_fails_closed():
      with pytest.raises(ValueError):
          evaluate_observation_gate([{"read_ok": True}], source="REAL_SYNC", sync_gate_verdict="PASS")
  ```

  Also test threshold passing, the legacy `pose_present` field, read failures being excluded from the denominator, JSON serialization, and input file parsing errors.

- [x] **Step 2: Run the focused tests to verify RED**

  Run: `py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_observation_gate.py`

  Expected: collection or assertion failure because the new module and contract do not exist yet.

### Task 2: Implement the pure offline evaluator

**Files:**
- Modify: `simulation/digital_twin/v1_twin/v1_twin_observation_gate.py`
- Test: `simulation/digital_twin/tests/test_v1_twin_observation_gate.py`

**Interfaces:**
- `B3ObservationGateConfig(expected_fps=30.0, min_detection_ratio=0.95, max_pose_gap_frames=2.0)` validates finite positive values.
- `B3ObservationGateReport.to_dict()` emits units, fixed thresholds, raw counts, failure counts, metric values, evidence status, verdict, and reasons.
- `load_frame_index(path)` parses JSONL records without rewriting the source file.
- `evaluate_observation_gate(records, *, source, sync_gate_verdict, capture_verdict=None, run_id=None, config=None)` returns an immutable report.

- [x] **Step 1: Implement the minimal configuration and percentile helpers**

  Use only standard-library helpers. Calculate the frame-period budget as `1_000_000_000 / expected_fps` and use linear interpolation for p95.

- [x] **Step 2: Implement ordered record validation and metric calculation**

  Count only `read_ok == True` frames in the denominator. Accept `pose_detected` first and `pose_present` only for legacy records. Require non-negative integer frame indexes and timestamps, strictly increasing frame indexes, and strictly increasing timestamps for detected poses.

  Compute detection ratio, failure-reason counts, maximum detected-pose timestamp gap, gap in frame periods, and p95 detector time. Do not infer a pose for missing records.

- [x] **Step 3: Implement fail-closed evidence classification**

  Return `INSUFFICIENT_EVIDENCE` when the source is not `REAL_SYNC`, the sync gate is not `PASS`, there are no readable frames, fewer than two detected poses exist, or timestamps/order are invalid. For a valid real synchronized run, return `VERIFIED` with `PASS` only when all declared thresholds pass; otherwise return `VERIFIED` with `FAIL` and explicit reasons.

- [x] **Step 4: Run focused tests to verify GREEN**

  Run: `py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_observation_gate.py`

  Expected: all focused tests pass.

### Task 3: Add a non-destructive CLI and evidence report

**Files:**
- Create: `tools/camera_toolchain/analyze_b3_observation.py`
- Modify: `simulation/digital_twin/tests/test_v1_twin_observation_gate.py`

**Interfaces:**
- CLI: `py -3.11 tools/camera_toolchain/analyze_b3_observation.py --session-dir <dir> --output <new-json> --source REAL_SYNC`
- Consumes: `<session-dir>/frame_index.jsonl` and `<session-dir>/sync_report.json`, including both `sync_gate_verdict` and overall `verdict`.
- Produces: a derived JSON report containing input SHA-256 hashes and the pure evaluator result.

- [x] **Step 1: Add a failing CLI test**

  Verify that the CLI writes a report for a temporary session, includes `run_id`, `input_artifacts`, and the evaluator result, and refuses to overwrite an existing output file.

- [x] **Step 2: Run the CLI test to verify RED**

  Run: `py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_observation_gate.py -k cli`

  Expected: failure because the CLI does not exist yet.

- [x] **Step 3: Implement the CLI**

  Require an explicit output path, create only its parent directory, require a canonical session root for `REAL_SYNC`, load both the existing sync and overall capture verdicts/run ID, hash the two input files, and write atomically to a previously nonexistent output path. Exit `0` for a report and `1` for input/configuration errors; do not treat a reported observation `FAIL` as a process error.

- [x] **Step 4: Run focused tests and compile check**

  Run: `py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_observation_gate.py` and `py -3.11 -m compileall -q simulation/digital_twin tools`.

  Expected: focused tests pass and compileall exits `0`.

### Task 4: Replay the latest real B3 run without changing raw evidence

**Files:**
- Create: `docs/evidence/v1_b3_observation_gate_20260808/report.json`
- Create: `docs/agent-context/handoffs/2026-08-08-b3-observation-gate-offline.md`
- Modify: `docs/agent-context/CURRENT_STATUS.md`

**Interfaces:**
- Input: `simulation/digital_twin/logs/c260807144501519/frame_index.jsonl` and its `sync_report.json`.
- Output: a tracked derived report and a handoff that labels the result as offline replay, not a new hardware run.

- [x] **Step 1: Run the analyzer against the immutable 2026-08-07 run**

  Run:

  ```text
  py -3.11 tools/camera_toolchain/analyze_b3_observation.py --session-dir simulation/digital_twin/logs/c260807144501519 --output docs/evidence/v1_b3_observation_gate_20260808/report.json --source REAL_SYNC
  ```

- [x] **Step 2: Independently inspect the derived report**

  Confirm the report preserves the observed 193 camera frames, 21 detected poses, approximately 10.9% detection ratio, `sync_gate_verdict=PASS`, and a failed observation gate. Confirm raw session files have not changed.

- [x] **Step 3: Write the handoff and update current status**

  State that the offline gate is verified, the latest real run remains a verified failed observation gate, the detector/calibration/firmware were not changed, and the next interface is one authorized capture with retained failed-frame thumbnails.

### Task 5: Full verification and review checkpoint

**Files:**
- No additional source files.

- [x] **Step 1: Run the focused and full regression suites**

  Run: `py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests`, `py -3.11 -m compileall -q simulation/digital_twin tools`, and `git diff --check`.

- [x] **Step 2: Review the diff and evidence boundaries**

  Verify that no firmware, hardware, camera settings, detector parameters, raw logs, or existing reports were overwritten; verify that the derived report is reproducible from the two input hashes.

- [ ] **Step 3: Commit the checkpoint**

  ```text
  git add docs/superpowers/plans/2026-08-08-b3-observation-gate.md simulation/digital_twin/v1_twin/v1_twin_observation_gate.py simulation/digital_twin/tests/test_v1_twin_observation_gate.py tools/camera_toolchain/analyze_b3_observation.py docs/evidence/v1_b3_observation_gate_20260808/report.json docs/agent-context/handoffs/2026-08-08-b3-observation-gate-offline.md docs/agent-context/CURRENT_STATUS.md
  git commit -m "feat: add offline B3 observation gate"
  ```
