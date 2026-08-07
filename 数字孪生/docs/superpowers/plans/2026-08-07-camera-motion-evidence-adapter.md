# Camera Motion Evidence Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing synchronized capture output with auditable whole-car camera-motion evidence for the no-encoder car.

**Architecture:** Keep `estimate_camera_motion()` as the only finite-difference implementation. Add a pure evidence-summary module that labels camera derivatives, summarizes valid intervals, and carries the existing IMU evidence overlap without inferring IMU calibration. Integrate that module into `capture_sync_run.write_capture_artifacts()` so every artifact-producing capture path writes additive `camera_motion.jsonl` and `motion_evidence.json` files while the existing sync gate and TCP lifecycle remain authoritative.

**Tech Stack:** Python 3.11, existing `V1Pose`, `V1CameraMotion`, `V1PoseFusion`, `V1ImuEvidenceReport`, pytest, JSONL/JSON artifacts.

## Global Constraints

- Reuse `capture_sync_run.py`, the existing TCP/heartbeat/parser/session lifecycle, `V1Pose`, `V1CameraMotion`, and `summarize_imu_evidence()`; do not create a second transport or capture path.
- Camera derivatives are external whole-car observations labeled `CAMERA_POSE_DERIVATIVE`; they are not wheel speed, motor speed, RPM, or encoder feedback.
- `VERIFIED` is allowed for the new report only when the source is `REAL_SYNC`, the existing sync gate is `PASS`, and at least one valid camera-motion interval exists.
- Synthetic input, a missing sync verdict, a failed sync gate, malformed input, and invalid timestamp intervals remain `INSUFFICIENT_EVIDENCE` or fail closed.
- Do not infer or modify IMU sign, scale, bias, drift, firmware control, PID parameters, B3 thresholds, or hardware state.
- Do not connect a camera/socket/debugger, flash, reset, send START/STOP, or move the car during implementation and tests.
- Do not perform Git write operations in the already-dirty canonical workspace.

---

### Task 1: Define the pure camera-motion evidence report

**Files:**
- Create: `simulation/digital_twin/v1_twin/v1_twin_motion_evidence.py`
- Modify: `simulation/digital_twin/v1_twin/v1_twin_motion_observer.py:70-105`
- Test: `simulation/digital_twin/tests/test_v1_twin_motion_evidence.py`

**Interfaces:**
- Consumes: `Iterable[V1Pose]`, an evidence source (`"REAL_SYNC"` or `"SYNTHETIC"`), an optional sync-gate verdict, and an optional existing `V1ImuEvidenceReport`.
- Produces: `build_camera_motion_evidence(poses, *, source, sync_gate_verdict=None, imu_report=None, max_gap_ns=100_000_000) -> tuple[tuple[V1CameraMotion, ...], V1CameraMotionEvidence]`.
- The report contains `evidence_status`, `source`, `sync_gate_verdict`, `record_count`, `valid_count`, `insufficient_count`, `valid_ratio`, `time_span_ns`, `planar_speed_mean_mm_s`, `planar_speed_p95_mm_s`, `abs_yaw_rate_p95_rad_s`, `imu_overlap_count`, `camera_imu_delta_p95_rad`, and `reason`.

- [ ] **Step 1: Write the failing report tests**

  Add tests that use real `V1Pose` objects and the existing `V1ImuEvidenceReport` contract:

  ```python
  def test_real_sync_report_summarizes_valid_camera_motion_without_calibrating_imu():
      motions, report = build_camera_motion_evidence(
          (_pose(0), _pose(100_000_000, x=100.0, yaw=0.2)),
          source="REAL_SYNC",
          sync_gate_verdict="PASS",
          imu_report=_imu_report(used_imu_count=2,
                                 camera_imu_delta_p95_rad=0.03),
      )
      assert motions[1].source == "CAMERA_POSE_DERIVATIVE"
      assert report.evidence_status == "VERIFIED"
      assert report.valid_count == 1
      assert report.planar_speed_mean_mm_s == pytest.approx(1000.0)
      assert report.camera_imu_delta_p95_rad == pytest.approx(0.03)

  def test_failed_sync_gate_cannot_promote_camera_motion_to_verified():
      _, report = build_camera_motion_evidence(
          (_pose(0), _pose(100_000_000, x=100.0)),
          source="REAL_SYNC",
          sync_gate_verdict="FAIL",
      )
      assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
      assert report.reason == "sync_gate_not_pass"

  def test_synthetic_and_invalid_intervals_fail_closed():
      motions, report = build_camera_motion_evidence(
          (_pose(0), _pose(0, x=100.0)),
          source="SYNTHETIC",
          sync_gate_verdict="PASS",
      )
      assert motions[1].quality is MotionObservationQuality.INSUFFICIENT_EVIDENCE
      assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
      assert report.reason == "source_not_real_sync"
  ```

  Include validation tests for unsupported source values, invalid report types, empty input, percentile behavior, and a non-positive `max_gap_ns`.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_motion_evidence.py
  ```

  Expected: collection or test failure because the report module and API do not exist yet. A failure caused by a test typo is not acceptable.

- [ ] **Step 3: Add immutable unit metadata to camera-motion serialization**

  Extend `V1CameraMotion.to_dict()` with an explicit `units` mapping without changing the numeric fields or computation:

  ```python
  "units": {
      "timestamp": "ns",
      "dt": "s",
      "delta_position": "mm",
      "velocity": "mm/s",
      "yaw_rate": "rad/s",
  },
  ```

  Keep `source == "CAMERA_POSE_DERIVATIVE"` mandatory.

- [ ] **Step 4: Implement the minimal report builder**

  Implement a frozen `V1CameraMotionEvidence` dataclass and `build_camera_motion_evidence()` by:

  1. calling `estimate_camera_motion()` exactly once;
  2. counting `VALID` versus `INSUFFICIENT_EVIDENCE` records;
  3. calculating the time span from the first and last motion timestamps;
  4. calculating mean planar speed, p95 planar speed, and p95 absolute yaw rate only from valid records;
  5. copying `used_imu_count` and `camera_imu_delta_p95_rad` from the existing IMU report when present;
  6. returning `VERIFIED` only for `source == "REAL_SYNC"`, `sync_gate_verdict == "PASS"`, and `valid_count > 0`.

  Use these reason priorities: `source_not_real_sync`, `sync_gate_not_pass`, `no_camera_motion_records`, `no_valid_camera_motion_records`, then `real_sync_motion_summary_only`.

- [ ] **Step 5: Run the focused tests and verify GREEN**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_motion_evidence.py simulation/digital_twin/tests/test_v1_twin_motion_observer.py
  ```

  Expected: all new evidence and existing observer tests pass with no hardware resource access.

---

### Task 2: Integrate additive artifacts into the canonical capture writer

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py:55-100,185-230,930-1105`
- Test: `simulation/digital_twin/tests/test_capture_sync_cleanup.py:576-680`

**Interfaces:**
- Consumes: `poses`, existing `fusion_records`, `fusion_evidence_source`, and the existing sync-gate verdict.
- Produces: `camera_motion.jsonl` and `motion_evidence.json` beside the existing `fusion.jsonl` and `imu_evidence.json`.

- [ ] **Step 1: Write integration tests that fail before the adapter is wired**

  Extend the existing artifact tests to call `write_capture_artifacts()` with the current fake pose/fusion data and assert:

  ```python
  assert (out_dir / "camera_motion.jsonl").exists()
  assert (out_dir / "motion_evidence.json").exists()
  camera_records = [
      json.loads(line)
      for line in (out_dir / "camera_motion.jsonl").read_text(
          encoding="utf-8").splitlines()
  ]
  assert camera_records[1]["source"] == "CAMERA_POSE_DERIVATIVE"
  assert camera_records[1]["units"]["velocity"] == "mm/s"
  motion_report = json.loads(
      (out_dir / "motion_evidence.json").read_text(encoding="utf-8"))
  assert motion_report["evidence_status"] == "INSUFFICIENT_EVIDENCE"
  assert motion_report["reason"] == "source_not_real_sync"
  ```

  Add a second integration assertion that `fusion_evidence_source="REAL_SYNC"` with `sync_gate_verdict="FAIL"` keeps `motion_evidence.json` at `INSUFFICIENT_EVIDENCE`.

- [ ] **Step 2: Run the integration tests and verify RED**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_capture_sync_cleanup.py -k "artifact or motion"
  ```

  Expected: the new file-existence or report assertions fail because the writer does not yet publish the new artifacts.

- [ ] **Step 3: Register the additive output names**

  Add exactly `camera_motion.jsonl` and `motion_evidence.json` to `OUTPUT_FILENAMES`. Do not add them to `B3_RAW_FILENAMES`; raw capture validity remains governed by the existing pose/telemetry/frame-index contract.

- [ ] **Step 4: Wire the existing writer without changing session ownership**

  Import `build_camera_motion_evidence`. Extend the writer signature with `sync_gate_verdict=None`. After computing the existing `imu_evidence` object, call:

  ```python
  camera_motion, motion_evidence = build_camera_motion_evidence(
      poses,
      source=fusion_evidence_source,
      sync_gate_verdict=sync_gate_verdict,
      imu_report=imu_evidence,
  )
  ```

  Write every `camera_motion` record as sorted JSONL and write `motion_evidence.to_dict()` as indented JSON. Preserve all existing artifacts and do not open any resource in this function.

- [ ] **Step 5: Pass the actual sync verdict from the successful main path**

  In the final successful/failed-after-dataset path, pass `sync_gate_verdict=gate.verdict` to `write_capture_artifacts()`. Leave earlier collection, clock-fit, and dataset-failure paths without a real-sync source so their motion report remains insufficient evidence.

- [ ] **Step 6: Run the integration tests and verify GREEN**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_capture_sync_cleanup.py -k "artifact or motion"
  ```

  Expected: existing cleanup/session tests and the new additive artifact tests pass.

---

### Task 3: Record the new offline boundary and perform full verification

**Files:**
- Modify: `docs/agent-context/PROJECT_MEMORY.md`
- Modify: `docs/agent-context/CURRENT_STATUS.md`
- Create: `docs/agent-context/handoffs/2026-08-07-camera-motion-evidence-adapter.md`

**Interfaces:**
- Consumes: exact test and static-check output from Tasks 1 and 2.
- Produces: a handoff that names the artifact paths, evidence status rules, and the next explicit hardware authorization boundary.

- [ ] **Step 1: Update project memory and status**

  Record that camera motion artifacts are external body-level evidence, `m1..m4` remain PWM commands, and a failed sync gate cannot be promoted by the motion summary. State that no firmware control or Kalman filter was added.

- [ ] **Step 2: Write the handoff with evidence classes**

  Include the exact changed files, commands/results, `VERIFIED` offline facts, `INFERENCE` about future body-level calibration, `INSUFFICIENT EVIDENCE` for wheel RPM/IMU calibration/control benefit, and the next interface: one user-authorized synchronized camera + TCP + MPU6050 run.

- [ ] **Step 3: Run focused regression and static checks**

  Run:

  ```powershell
  py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_motion_observer.py simulation/digital_twin/tests/test_v1_twin_motion_evidence.py simulation/digital_twin/tests/test_capture_sync_cleanup.py
  py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
  py -3.11 -m compileall -q simulation/digital_twin tools
  git diff --check
  ```

  Expected: focused tests pass, the full Python suite passes with only its pre-existing skips, compileall exits `0`, and diff-check reports no whitespace errors. Do not claim real synchronization or hardware improvement from these commands.

- [ ] **Step 4: Stop at the hardware boundary**

  Do not run `capture_sync_run.py` or any other camera/TCP command. Report the artifact contract and ask for explicit authorization only after the offline checks are complete.
