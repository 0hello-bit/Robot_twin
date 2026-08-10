# AprilTag Video Retention and Pupil ROI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve synchronized 1080p motion frames and benchmark a bounded Pupil AprilTag ROI candidate offline without changing production behavior.

**Architecture:** Extend the existing synchronized capture lifecycle with one injected MJPG video writer and auditable video metadata. Extend the existing file-only replay contract with a special `pupil_roi` candidate that reuses the production ROI geometry and existing trace/summary thresholds. Keep `production/default` as the mandatory baseline and mark all replay results screening-only.

**Tech Stack:** Python 3.11, OpenCV, `pupil_apriltags` when installed, pytest, existing capture/replay schemas.

## Global Constraints

- Do not change production `PoseTracker` defaults, calibration, firmware, TCP protocol, or camera mode.
- Do not open a second camera or create a second TCP lifecycle.
- Do not overwrite existing evidence reports or traces.
- Do not count Pupil predictions or temporal output as AprilTag decodes.
- B3 thresholds remain detection ratio >= 0.95, maximum pose gap <= 2 frames, detector p95 <= 33.333333 ms.

### Task 1: Test the capture video writer contract

**Files:**
- Modify: `simulation/digital_twin/tests/test_capture_sync_cleanup.py`
- Modify: `tools/camera_toolchain/capture_sync_run.py`

**Interfaces:**
- `run_sync_capture_session(..., video_writer=None, video_evidence=None)` accepts an optional injected writer.
- `video_evidence` records `enabled`, `frames_written`, `write_errors`, `released`, and `path`.

- [x] **Step 1: Write a failing test for injected writer lifecycle.**

  Add a fake writer with `write()` and `release()` methods, run the existing
  fake capture session through a successful short collection, and assert that
  every readable frame is written once and the writer is released.

- [x] **Step 2: Run the focused test and confirm RED.**

  Run `py -3.11 -m pytest -q simulation/digital_twin/tests/test_capture_sync_cleanup.py -k video_writer`.
  Expected failure: `run_sync_capture_session` does not accept `video_writer`.

- [x] **Step 3: Implement the minimal writer lifecycle.**

  Write each validated frame once before detector execution, release the writer
  in the collection `finally` block, and record a `video_write_failed` outcome
  on a writer exception while preserving the existing STOP/cleanup behavior.

- [x] **Step 4: Run the focused test and confirm GREEN.**

  Re-run the same command and require PASS.

### Task 2: Add auditable default `camera.avi` output

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Modify: `simulation/digital_twin/tests/test_capture_sync_cleanup.py`

**Interfaces:**
- Add `open_capture_video_writer(path, camera_mode)` for validated MJPG output.
- `sync_report.json` and `video_evidence.json` include the final video evidence.

- [x] **Step 1: Write failing tests for writer setup and report metadata.**

  Cover writer-open failure before START, `1920x1080/MJPG/30` metadata, frame
  count, and no false video PASS when the writer fails.

- [x] **Step 2: Run focused tests and confirm RED.**

  Run the two named tests and verify the missing helper/report fields fail.

- [x] **Step 3: Implement default per-run `camera.avi` creation.**

  Open the writer only after camera mode validation and TCP connection, pass it
  into the existing session, finalize size/hash/frame count after release, and
  publish metadata without changing the synchronization verdict logic.

- [x] **Step 4: Run focused tests and confirm GREEN.**

  Require all capture cleanup tests to pass.

### Task 3: Test and implement the offline Pupil ROI candidate

**Files:**
- Modify: `tools/camera_toolchain/apriltag_video_replay.py`
- Modify: `simulation/digital_twin/tests/test_apriltag_video_replay.py`

**Interfaces:**
- `replay_video(..., parameter_variant="pupil_roi")` runs the bounded Pupil candidate.
- Existing OpenCV variants and `production/default` behavior remain unchanged.
- Candidate reports include `detector_backend: "pupil_apriltags"`, ROI/fallback
  modes, and `evidence_status: "INSUFFICIENT_EVIDENCE"`.

- [x] **Step 1: Write failing validation and synthetic replay tests.**

  Assert `pupil_roi` is accepted, unknown variants still fail before opening a
  file, and a synthetic MJPG replay either records the Pupil backend or emits a
  structured unavailable-dependency error.

- [x] **Step 2: Run focused tests and confirm RED.**

  Run `py -3.11 -m pytest -q simulation/digital_twin/tests/test_apriltag_video_replay.py -k pupil`.
  Expected failure: `pupil_roi` is rejected as an unsupported parameter variant.

- [x] **Step 3: Implement the bounded backend.**

  Use one optional Pupil detector, run production-sized ROI first, use one
  bounded full-frame reacquisition fallback, translate corners into the
  existing projection helper, and report true decode status separately from
  all pose output fields.

- [x] **Step 4: Run focused replay tests and confirm GREEN.**

  Require the new tests and all existing replay tests to pass.

### Task 4: Offline verification and handoff

**Files:**
- Create: `docs/evidence/v1_b3_pupil_roi_replay_20260810/report.json`
- Create: `docs/agent-context/handoffs/2026-08-10-pupil-roi-video-retention.md`

- [x] **Step 1: Replay the retained old 1080p video with baseline and Pupil ROI.**

  Use the same video hash and calibration manifest; preserve separate traces.

- [x] **Step 2: Verify report thresholds and evidence labels.**

  Record detection ratio, max gap, p95, dependency status, and candidate
  decision. Do not authorize deployment from this result.

- [x] **Step 3: Run full verification.**

  Run `py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests`,
  `py -3.11 -m compileall -q simulation/digital_twin tools`, and `git diff --check`.

- [x] **Step 4: Hand off the next hardware boundary.**

  State that the next run must use the generated `camera.avi`, `production`
  baseline, the same calibration manifest, and a fresh explicit hardware
  authorization. No firmware flash is part of this step.
