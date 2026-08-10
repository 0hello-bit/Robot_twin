# AprilTag Fast Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add and offline-evaluate a bounded `fast_recovery` AprilTag candidate that reduces failure-frame processing cost without changing production behavior or requesting another real capture.

**Architecture:** Keep one `PoseTracker` implementation and add explicit recovery-policy inputs for ROI scales, preprocessing modes, preprocessing scales, fallback scales, and CLAHE caching. The replay tool selects `fast_recovery` through the existing candidate interface and compares it with a fresh production baseline on the same retained video. The candidate-selection gate will require both relative improvement and the absolute B3 thresholds.

**Tech Stack:** Python 3.11, OpenCV, pytest, existing `capture_sync_run.py`, `apriltag_video_replay.py`, and `PoseTracker` interfaces.

## Global Constraints

- Production/default tracker behavior remains unchanged: ROI scales `(1.0, 2.0, 3.0)`, all three existing preprocessing modes at scale `2.0`, production fallback `(2.0,)`, and uncached CLAHE construction.
- `fast_recovery` is offline-only and uses ROI scale `(1.0,)`, only `blue_clahe` at scale `(1.0,)`, full-frame fallback `(1.0,)`, and one cached CLAHE object.
- Replay must use the same input video hash, decoded frame count, calibration manifest, and target ID for baseline and candidate.
- AprilTag decodes are the only observations counted toward detection ratio; flow predictions remain separate.
- A candidate is not eligible for real A/B unless detection ratio >= `0.95`, maximum decoded-frame interval <= `2.0`, processing p95 <= `33.333333` ms, and no errors.
- If the candidate fails, preserve the evidence and continue offline algorithm work; do not request or perform another real capture.
- Do not modify firmware, TCP, camera configuration, calibration assets, or hardware state.
- Do not perform Git write operations or delete prior evidence in this task.

---

### Task 1: Add failing recovery-policy and selection-gate tests

**Files:**
- Modify: `simulation/digital_twin/tests/test_v1_twin_pose_tracker.py`
- Modify: `simulation/digital_twin/tests/test_apriltag_video_replay.py`
- Modify: `tools/camera_toolchain/apriltag_video_replay.py` only after RED

**Interfaces:**
- `PoseTracker(..., recovery_policy="fast_recovery")` exposes the policy in diagnostics.
- `replay_video(..., parameter_variant="fast_recovery")` is accepted and reports the candidate policy.
- `evaluate_candidate_selection(baseline, candidate)` rejects candidates that improve relatively but fail any absolute B3 threshold.

- [ ] **Step 1: Write a failing tracker-policy test.**

Add a test that creates a fast-policy tracker on the existing synthetic AprilTag frame helpers, performs an initial decode, then moves the tag within the retained ROI. Assert the second diagnostic record reports:

```python
assert diagnostics["recovery_policy"] == "fast_recovery"
assert diagnostics["attempted_scales"] == [1.0]
```

Also assert a production tracker retains the existing `[1.0, 2.0, 3.0]` bootstrap behavior already covered by the current tests.

- [ ] **Step 2: Write a failing replay candidate test.**

Extend the synthetic MJPG replay test with `parameter_variant="fast_recovery"` and assert:

```python
assert result["candidate"]["parameter_variant"] == "fast_recovery"
assert result["candidate"]["recovery_policy"] == "fast_recovery"
assert result["trace"][0]["recovery_policy"] == "fast_recovery"
```

- [ ] **Step 3: Write a failing absolute-threshold selection test.**

Add a candidate that improves the baseline but remains below the absolute B3 detection and gap thresholds:

```python
baseline = {
    "detection_ratio": 0.57,
    "max_detection_interval_frames": 13.0,
    "max_consecutive_missed_frames": 12,
    "processing_p95_ms": 111.0,
}
candidate = {
    "detection_ratio": 0.86,
    "max_detection_interval_frames": 5.0,
    "max_consecutive_missed_frames": 4,
    "processing_p95_ms": 31.0,
}
assert evaluate_candidate_selection(baseline, candidate)["verdict"] == "NOT_JUSTIFIED"
```

- [ ] **Step 4: Run the focused tests and confirm RED.**

Run:

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_pose_tracker.py simulation/digital_twin/tests/test_apriltag_video_replay.py
```

Expected: the new policy/variant assertions fail because the policy and candidate are not implemented; the new selection assertion fails because the current selector checks only relative improvement and timing.

### Task 2: Implement explicit tracker recovery policies

**Files:**
- Modify: `simulation/digital_twin/v1_twin/v1_twin_pose_tracker.py`
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Test: `simulation/digital_twin/tests/test_v1_twin_pose_tracker.py`

**Interfaces:**
- `PoseTracker` adds optional keyword arguments `roi_detect_scales`, `recovery_preprocess_modes`, `cache_preprocessors`, and `recovery_policy`; existing callers remain valid.
- `capture_sync_run.resolve_recovery_policy(name)` returns immutable policy data for `production` and `fast_recovery`.
- `capture_sync_run.create_pose_tracker(..., recovery_policy="production")` passes the selected policy into the existing tracker.

- [ ] **Step 1: Add immutable policy definitions and validation.**

Define in `capture_sync_run.py`:

```python
RECOVERY_POLICIES = {
    "production": {
        "roi_detect_scales": (1.0, 2.0, 3.0),
        "recovery_preprocess_modes": ("blue_clahe", "blue_unsharp", "gray_clahe"),
        "roi_preprocess_scales": (2.0,),
        "cache_preprocessors": False,
        "full_frame_fallback_scales": None,
    },
    "fast_recovery": {
        "roi_detect_scales": (1.0,),
        "recovery_preprocess_modes": ("blue_clahe",),
        "roi_preprocess_scales": (1.0,),
        "cache_preprocessors": True,
        "full_frame_fallback_scales": (1.0,),
    },
}
```

Use the repository's `MappingProxyType` pattern and raise `ValueError("unsupported recovery policy")` for unknown names. Keep the production observation profile's fallback `(2.0,)` when the selected policy does not override it.

- [ ] **Step 2: Add tracker configuration inputs without changing defaults.**

In `PoseTracker.__init__`, normalize the optional ROI scale tuple, validate preprocessing modes against the three existing names, store `recovery_policy`, and create one CLAHE object only when `cache_preprocessors=True`. With default arguments, all current fields and branch order must remain unchanged.

- [ ] **Step 3: Apply the policy to the existing detection loop.**

Pass the configured ROI scale tuple into the ROI `_detect_region` call. Make `_roi_preprocessed_inputs` generate only the configured modes and only compute channel conversions, blur, and CLAHE results required by those modes. Reuse the cached CLAHE object for `fast_recovery`. Keep full-frame bootstrap on `self._scales` and use the existing fallback tuple for reacquisition.

- [ ] **Step 4: Publish policy diagnostics.**

Add `recovery_policy` to every success and failure diagnostics dictionary. Preserve all existing diagnostic keys and meanings, especially `tag_decoded`, `failure_reason`, `attempted_scales`, and `preprocess_modes_attempted`.

- [ ] **Step 5: Run the focused tracker tests and confirm GREEN.**

Run:

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_pose_tracker.py
```

Expected: all tracker tests pass, including the new fast-policy test.

### Task 3: Wire the replay candidate and harden selection

**Files:**
- Modify: `tools/camera_toolchain/apriltag_video_replay.py`
- Modify: `simulation/digital_twin/tests/test_apriltag_video_replay.py`

**Interfaces:**
- `REPLAY_PARAMETER_VARIANTS` includes `fast_recovery`.
- `replay_video(..., parameter_variant="fast_recovery")` uses default OpenCV detector parameters plus `recovery_policy="fast_recovery"`.
- `_trace_record` and candidate metadata include `recovery_policy`.
- `evaluate_candidate_selection` requires absolute candidate thresholds in addition to relative improvement checks.

- [ ] **Step 1: Accept and construct `fast_recovery`.**

Add `fast_recovery` to the replay variant set. For this variant, construct the existing OpenCV `default` detector parameters and call `create_pose_tracker` with `recovery_policy="fast_recovery"`; all other variants use `recovery_policy="production"`.

- [ ] **Step 2: Preserve auditable trace and candidate metadata.**

Copy `recovery_policy` from diagnostics into each trace record and add it to the fast candidate metadata. Do not treat the policy name as a detector backend or as a decode result.

- [ ] **Step 3: Enforce absolute B3 thresholds.**

Add selection checks:

```python
"detection_ratio_meets_b3": candidate_ratio >= 0.95,
"max_detection_interval_meets_b3": candidate_gap <= 2.0,
```

Include both checks in `qualified = all(checks.values())`; retain all existing relative and p95 checks.

- [ ] **Step 4: Run replay-focused tests and confirm GREEN.**

Run:

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_apriltag_video_replay.py simulation/digital_twin/tests/test_v1_twin_pose_tracker.py
```

### Task 4: Replay the retained video and preserve evidence

**Files:**
- Create: `docs/evidence/v1_b3_fast_recovery_replay_20260810/report.json`
- Create: `docs/agent-context/handoffs/2026-08-10-fast-recovery-replay.md`

**Interfaces:**
- The CLI runs only on `camera.avi` and writes a new report/traces without overwriting prior evidence.
- The report records the same video hash, frame count, calibration manifest hash, baseline summary, candidate summary, and selection checks.

- [ ] **Step 1: Run production and fast candidate replay on the exact retained video.**

Run:

```text
py -3.11 tools/camera_toolchain/apriltag_video_replay.py `
  --video simulation/digital_twin/logs/c260810100004052/camera.avi `
  --calibration-manifest simulation/digital_twin/data/product/capture_manifests/c960_r3_1080p_exploratory_20260809/manifest.json `
  --candidate production:production:default `
  --candidate fast_recovery:production:fast_recovery `
  --output docs/evidence/v1_b3_fast_recovery_replay_20260810/report.json
```

Expected: one report with two candidates, identical video hashes and decoded frame counts, and separate trace files beside the report.

- [ ] **Step 2: Verify the fixed gates from the report.**

Read the report and independently confirm the candidate's detection ratio, maximum interval, maximum consecutive misses, processing p95, and selection checks. If any gate fails, label the result `NOT_JUSTIFIED` and do not request another capture.

- [ ] **Step 3: Run full offline verification.**

Run:

```text
py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
py -3.11 -m compileall -q simulation/digital_twin tools
git diff --check
```

Expected: no test failures, compileall exit 0, and no new whitespace errors. Existing dirty files and prior evidence remain untouched.

- [ ] **Step 4: Write the handoff.**

Record the exact commands, changed files, video hash, metrics, evidence classification, and next boundary. State explicitly that a failed candidate leads to another offline candidate iteration and not to a new physical capture.

## Completion rule

This plan is complete only when the code and tests are verified and the replay evidence is preserved. It is not a B3 pass unless the candidate satisfies every fixed threshold. A failed replay is still a valid offline iteration and becomes the input to the next offline design; no hardware authorization is implied.

