# R3 Raw-Pixel Exploratory Calibration Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not spawn another implementation agent.

**Goal:** Export the corrected R3 raw-pixel ground mapping as a strict, versioned `EXPLORATORY_RELATIVE_ONLY` calibration profile with reproducible evidence, while making it impossible to treat that profile as the verified 2 mm gate.

**Architecture:** A new pure-Python profile module owns the calibration ID, pixel domain, quality level, ground homography and provenance. A separate camera-toolchain exporter reads the corrected immutable joint-fit report, validates its schema and SHA-256, and writes a new evidence directory without overwriting anything. This package deliberately does not wire the profile into `PoseTracker`, route conversion, 4B-4 capture or formal model gates; those are separately reviewed packages.

**Tech Stack:** Python 3.11, dataclasses, enum, pathlib, hashlib, json, NumPy, existing `HomographyTransform`, pytest.

## Global Constraints

- Workspace root: `C:\Users\24668\Desktop\stm32小车`.
- Read `CLAUDE.md`, `docs/agent-context/CURRENT_STATUS.md`, the approved design, this plan, and the current handoff before editing.
- The worktree is heavily dirty. Preserve every pre-existing modification and untracked file; do not revert, rename, delete or reformat unrelated files.
- Do not execute any Git write operation, including `git add`, `commit`, `checkout`, `reset`, `stash`, `clean`, `push` or branch creation. The coordinator owns Git.
- Do not connect to hardware, open the camera, use ESP/TCP, flash, reset, send `START`, or run motors.
- Do not modify old evidence. New generated evidence goes only to `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/`, and the exporter must refuse a non-empty output directory.
- The immutable source is `.embeddedskills/build/codex_r3_acceptance_20260804/joint_fit_v1/verification_corrected/joint_raw_linear.json` with SHA-256 `D02DBB33D9258F63575A67036228C52E27AD589D1BA60070B7C9167E9938037D`.
- The source result is ground-control-point evidence only: holdout p95 `10.62712398475308 mm`, LOO p95 `11.01137209510592 mm`. It does not validate car pose because AprilTag height parallax is unresolved.
- The package status must remain `EXPLORATORY_RELATIVE_ONLY`; it must not claim 2 mm, 4B-2 completion, 4B-3 completion, 4B-4 completion, READY, G1-G8 or final PID ranking.
- Existing baselines before implementation: `test_v1_twin_calibration.py` = 12 passed; `test_v1_twin_pose_tracker.py` = 8 passed.
- This package contains no dependency changes and no PDF/ChArUco implementation.

---

## File Map

**Create**

- `simulation/digital_twin/v1_twin/v1_twin_calibration_profile.py`: immutable profile types, validation, JSON round-trip and formal-ground-gate guard.
- `simulation/digital_twin/tests/test_v1_twin_calibration_profile.py`: unit tests for profile validation, round-trip and gate rejection.
- `.embeddedskills/tools/camera_toolchain/export_exploratory_profile.py`: strict exporter from corrected R3 JSON to a new evidence directory.
- `simulation/digital_twin/tests/test_export_exploratory_profile.py`: exporter tests using temporary source/output directories.
- `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/calibration_profile.json`: generated artifact, never hand-edited.
- `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/verification_report.json`: generated provenance and gate report, never hand-edited.
- `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/ds_execution_report.md`: DS handback with commands, outputs, exit codes and limitations.

**Modify**

- `docs/agent-context/CURRENT_STATUS.md`: append a dated correction that supersedes the stale global-accuracy interpretation without deleting history.

**Must Not Modify In This Package**

- `simulation/digital_twin/v1_twin/v1_twin_pose_tracker.py`
- `simulation/digital_twin/v1_twin/v1_twin_track_map.py`
- `.embeddedskills/build/v1_task4b4/capture_sync_run.py`
- firmware under `程序/`
- any existing file under `.embeddedskills/build/**/verification_corrected/`
- `docs/Robot_Twin_AI_完整计划说明书_v2.0.md`

---

### Task 1: Immutable Calibration Profile Contract

**Files:**

- Create: `simulation/digital_twin/v1_twin/v1_twin_calibration_profile.py`
- Create: `simulation/digital_twin/tests/test_v1_twin_calibration_profile.py`
- Read: `simulation/digital_twin/v1_twin/v1_twin_calibration.py`

**Interfaces:**

- Consumes: `HomographyTransform.from_dict(data)` and `HomographyTransform.to_dict()`.
- Produces: `PixelDomain`, `CalibrationQuality`, `GroundAccuracyEvidence`, `CalibrationProfile`, `CalibrationProfileError`.
- Produces: `CalibrationProfile.from_dict(data)`, `to_dict()`, and `require_ground_holdout_verified_2mm()`.

- [ ] **Step 1: Write failing profile tests**

Create tests with this fixture shape and assertions:

```python
def _profile_dict():
    return {
        "schema_version": 1,
        "calibration_id": "c960_r3_raw_global_exploratory_v1",
        "camera": {"model": "EMEET SmartCam C960", "image_size": [1280, 720]},
        "input_domain": "RAW_PIXEL",
        "quality": "EXPLORATORY_RELATIVE_ONLY",
        "ground_transform": {
            "type": "HomographyTransform",
            "matrix": [[0.9471, -0.0043, -757.8874],
                       [-0.0096, 0.9564, -440.9269],
                       [0.0000459, 0.0000058, 1.0]],
        },
        "accuracy_evidence": {
            "scope": "GROUND_CONTROL_POINTS_ONLY",
            "stratified_holdout_p95_mm": 10.62712398475308,
            "stratified_holdout_max_mm": 10.758592939623588,
            "loo_p95_mm": 11.01137209510592,
            "loo_max_mm": 11.577187539478283,
            "evidence_class": "MODEL_ESTIMATED_NOT_PHYSICALLY_INDEPENDENT_ANGLE",
        },
        "pose_absolute_accuracy": "UNVERIFIED_TAG_HEIGHT_PARALLAX",
        "provenance": {
            "source": ".embeddedskills/build/source.json",
            "sha256": "d" * 64,
        },
    }


def test_profile_round_trip_preserves_domain_quality_matrix_and_evidence():
    profile = CalibrationProfile.from_dict(_profile_dict())
    assert profile.pixel_domain is PixelDomain.RAW_PIXEL
    assert profile.quality is CalibrationQuality.EXPLORATORY_RELATIVE_ONLY
    assert profile.image_size == (1280, 720)
    assert profile.accuracy.stratified_holdout_p95_mm == pytest.approx(10.62712398475308)
    assert CalibrationProfile.from_dict(profile.to_dict()).to_dict() == profile.to_dict()


def test_formal_ground_gate_rejects_exploratory_profile():
    profile = CalibrationProfile.from_dict(_profile_dict())
    with pytest.raises(CalibrationProfileError, match="HOLDOUT_VERIFIED_2MM"):
        profile.require_ground_holdout_verified_2mm()
```

Also test rejection of: absolute provenance paths, `..` path traversal, non-64-hex SHA-256, non-positive image dimensions, non-finite/singular homography, unknown enum values, negative accuracy metrics, and a forged `HOLDOUT_VERIFIED_2MM` profile whose p95 exceeds 2.0 mm.

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_calibration_profile.py
```

Expected: collection/import failure because `v1_twin_calibration_profile` does not exist. Record the exact failure and exit code in the DS report.

- [ ] **Step 3: Implement the minimal strict profile module**

Use string enums and frozen dataclasses. The formal guard must require both the formal quality enum and p95 at most 2.0 mm:

```python
class PixelDomain(str, Enum):
    RAW_PIXEL = "RAW_PIXEL"
    UNDISTORTED_PIXEL = "UNDISTORTED_PIXEL"


class CalibrationQuality(str, Enum):
    EXPLORATORY_RELATIVE_ONLY = "EXPLORATORY_RELATIVE_ONLY"
    HOLDOUT_VERIFIED_2MM = "HOLDOUT_VERIFIED_2MM"


def require_ground_holdout_verified_2mm(self) -> None:
    if self.quality is not CalibrationQuality.HOLDOUT_VERIFIED_2MM:
        raise CalibrationProfileError("formal ground use requires HOLDOUT_VERIFIED_2MM")
    if self.accuracy.stratified_holdout_p95_mm > 2.0:
        raise CalibrationProfileError("formal ground p95 exceeds 2.0 mm")
```

Validate the homography with `np.isfinite(matrix).all()` and `abs(np.linalg.det(matrix)) > 1e-12`. Keep the source path workspace-relative and serialize paths with `/` separators. Do not add runtime mapping behavior or import `PoseTracker`.

- [ ] **Step 4: Run the profile tests and existing calibration regression**

Run:

```powershell
py -3.11 -m pytest -q `
  simulation/digital_twin/tests/test_v1_twin_calibration_profile.py `
  simulation/digital_twin/tests/test_v1_twin_calibration.py
```

Expected: all tests PASS, exit code 0.

---

### Task 2: Strict Corrected-R3 Exporter

**Files:**

- Create: `.embeddedskills/tools/camera_toolchain/export_exploratory_profile.py`
- Create: `simulation/digital_twin/tests/test_export_exploratory_profile.py`

**Interfaces:**

- Consumes: corrected joint-fit JSON and `CalibrationProfile.to_dict()`.
- Produces: `build_profile(source: Path, workspace_root: Path) -> CalibrationProfile`.
- Produces: `export_profile(source: Path, out_dir: Path, workspace_root: Path, expected_sha256: str) -> dict`.
- CLI: `source`, `out_dir`, required `--workspace-root`, required `--expected-sha256`.

- [ ] **Step 1: Write failing exporter tests**

The tests must construct a minimal corrected source JSON containing:

```python
{
    "method": "joint pixel-to-mm homography plus one in-plane angle per training view",
    "evidence_class": "MODEL_ESTIMATED_NOT_PHYSICALLY_INDEPENDENT_ANGLE",
    "coordinate_convention": {
        "anchor_correction": "corner0=outer+R(angle)*[15,15]"
    },
    "inputs": {"image_size": [1280, 720]},
    "full_16_view_fit_in_sample": {"homography_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
    "stratified_9_7": {"holdout": {"independent_anchor_position_mm": {"p95": 10.6, "max": 10.8}}},
    "leave_one_view_out": {"independent_anchor_position_mm": {"p95": 11.0, "max": 11.6}},
}
```

Assert that the exporter:

- writes exactly `calibration_profile.json` and `verification_report.json`;
- records `input_domain=RAW_PIXEL` and `quality=EXPLORATORY_RELATIVE_ONLY`;
- records `formal_2mm_gate=REJECT` and `pose_absolute_accuracy=UNVERIFIED_TAG_HEIGHT_PARALLAX`;
- preserves the source matrix and all four accuracy metrics;
- rejects a SHA mismatch before creating output;
- rejects missing/wrong `anchor_correction` so the obsolete inner-vs-outer reporting bug cannot return;
- rejects an existing non-empty output directory;
- produces byte-identical JSON for the same input in two different empty output directories, excluding no timestamps because generated artifacts must be deterministic.

- [ ] **Step 2: Run the exporter tests and confirm RED**

Run:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_export_exploratory_profile.py
```

Expected: import/file failure because the exporter does not exist. Record exit code.

- [ ] **Step 3: Implement deterministic export**

Use sorted, indented JSON with a final newline:

```python
payload = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
path.write_text(payload, encoding="utf-8", newline="\n")
```

The verification report must include:

```python
{
    "status": "EXPLORATORY_PROFILE_EXPORTED",
    "formal_2mm_gate": "REJECT",
    "reason": "independent ground holdout p95 exceeds 2.0 mm",
    "source_sha256": actual_sha256,
    "profile_sha256": profile_sha256,
    "old_runtime_chain_accuracy": "NOT_ESTABLISHED_BY_THIS_PROFILE",
    "hardware_used": False,
}
```

Do not call the export `PASS`. The command may exit 0 because the requested exploratory artifact was generated correctly; the report must still say the formal 2 mm gate is rejected.

- [ ] **Step 4: Run exporter tests and compile checks**

Run:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_export_exploratory_profile.py
py -3.11 -m py_compile `
  simulation/digital_twin/v1_twin/v1_twin_calibration_profile.py `
  .embeddedskills/tools/camera_toolchain/export_exploratory_profile.py
```

Expected: both commands exit 0.

---

### Task 3: Export New Immutable Evidence

**Files:**

- Read: `.embeddedskills/build/codex_r3_acceptance_20260804/joint_fit_v1/verification_corrected/joint_raw_linear.json`
- Create through the exporter only: `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/calibration_profile.json`
- Create through the exporter only: `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/verification_report.json`

**Interfaces:**

- Produces the frozen artifact consumed by the next package. It is not yet a runtime-selected profile.

- [ ] **Step 1: Confirm the output directory does not exist**

Run:

```powershell
Test-Path '.embeddedskills\build\v1_task4b2_r3_exploratory_profile_20260804_r1'
```

Expected: `False`. If it is `True`, stop with `BLOCKED_EVIDENCE_DIR_EXISTS`; do not delete or reuse it.

- [ ] **Step 2: Run the real export**

Run:

```powershell
py -3.11 .embeddedskills/tools/camera_toolchain/export_exploratory_profile.py `
  .embeddedskills/build/codex_r3_acceptance_20260804/joint_fit_v1/verification_corrected/joint_raw_linear.json `
  .embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1 `
  --workspace-root . `
  --expected-sha256 D02DBB33D9258F63575A67036228C52E27AD589D1BA60070B7C9167E9938037D
```

Expected: exit 0, `status=EXPLORATORY_PROFILE_EXPORTED`, `formal_2mm_gate=REJECT`.

- [ ] **Step 3: Independently reload and verify the generated profile**

Run:

```powershell
py -3.11 -c "import json,sys; sys.path.insert(0,'simulation/digital_twin'); from v1_twin.v1_twin_calibration_profile import CalibrationProfile,CalibrationProfileError; p=CalibrationProfile.from_dict(json.load(open('.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/calibration_profile.json',encoding='utf-8'))); print(p.calibration_id,p.pixel_domain.value,p.quality.value,p.accuracy.stratified_holdout_p95_mm); assert p.pixel_domain.value=='RAW_PIXEL'; assert p.quality.value=='EXPLORATORY_RELATIVE_ONLY'; assert abs(p.accuracy.stratified_holdout_p95_mm-10.62712398475308)<1e-12; exec('try:\n p.require_ground_holdout_verified_2mm()\n raise AssertionError(\"formal gate unexpectedly accepted\")\nexcept CalibrationProfileError:\n pass')"
```

Expected: exit 0 and printed exploratory identity/metric.

---

### Task 4: Correct Current Status Without Rewriting History

**Files:**

- Modify: `docs/agent-context/CURRENT_STATUS.md`
- Create: `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/ds_execution_report.md`

**Interfaces:**

- Produces a truthful entry for subsequent Claude Code sessions.
- The report is the Codex acceptance input.

- [ ] **Step 1: Append a dated correction block to current status**

Add a `2026-08-04 R3 独立复核更正` section near the top. It must state all of the following explicitly:

```text
- 旧“板附近 0.3 mm / 全图约 5%”不证明全赛道绝对毫米精度。
- 修正后的 raw-pixel ground holdout p95=10.627 mm，LOO p95=11.011 mm。
- 当前去畸变路径的同类 holdout=19.386 mm；运行链不能自动称为 10 mm。
- 新 profile 只是 EXPLORATORY_RELATIVE_ONLY，尚未接入 PoseTracker/route/4B-4 capture。
- AprilTag 高度视差未修正，车体绝对 x/y 精度未验证。
- R3/2 mm gate 仍 BLOCKED；下一步必须由独立 package 接线和复验。
```

Do not delete the old bullets. Mark them as historical/local evidence and point to the new evidence directory.

- [ ] **Step 2: Write the DS execution report**

The report must list:

1. exact files created/modified;
2. baseline RED and final GREEN commands, outputs and exit codes;
3. real source/profile/report SHA-256 values;
4. extracted matrix and four error metrics;
5. `formal_2mm_gate=REJECT` and why;
6. explicit statement that no consumer was wired, no camera/hardware/network was opened, and no Git write occurred;
7. unverified items and the exact next interface: `CalibrationProfile` plus generated `calibration_profile.json`.

- [ ] **Step 3: Run final scoped verification**

Run:

```powershell
py -3.11 -m pytest -q `
  simulation/digital_twin/tests/test_v1_twin_calibration_profile.py `
  simulation/digital_twin/tests/test_export_exploratory_profile.py `
  simulation/digital_twin/tests/test_v1_twin_calibration.py `
  simulation/digital_twin/tests/test_v1_twin_pose_tracker.py
py -3.11 -m py_compile `
  simulation/digital_twin/v1_twin/v1_twin_calibration_profile.py `
  .embeddedskills/tools/camera_toolchain/export_exploratory_profile.py
```

Expected: all tests PASS and both commands exit 0.

- [ ] **Step 4: Stop for Codex acceptance**

Do not continue into profile wiring, A4 PDF generation, C960 capture, telemetry batching or 4B-5. Return the DS report path and wait for the coordinator to issue either `PASS` or a bounded rework handoff.

---

## Codex Acceptance Gate

Codex will independently:

1. inspect `git diff`/`git status` and reject unrelated edits;
2. recompute source/profile/report hashes;
3. compare the exported matrix and metrics byte-for-value with corrected source JSON;
4. run all four pytest modules and both compile checks;
5. test SHA mismatch, non-empty output, path traversal, forged formal quality and singular matrix failures;
6. verify `CURRENT_STATUS.md` preserves history and labels the runtime chain as not yet wired;
7. issue `PASS`, `REJECT` or `INSUFFICIENT_EVIDENCE`.

Only a Codex `PASS` unlocks the next handoff. This package can pass while the 2 mm gate remains rejected; those are deliberately different verdicts.
