# Task 4B-D / 4B-1 / 4B-2 Reacceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use systematic-debugging, test-driven-development, and verification-before-completion. Execute tasks sequentially and keep evidence in the new output directory.

**Goal:** Repair the three independent-acceptance gaps without changing firmware, hardware state, Task 4B-3, or later digital-twin work.

**Architecture:** Treat documentation consistency, camera-stream validity, and track-centerline geometry as three separate gates. Diagnose and test each gate before changing production code. Old evidence remains immutable; all new reports go to `.embeddedskills/build/v1_task4b_reacceptance/`.

**Tech Stack:** Python 3.11, pytest, OpenCV, NumPy, existing Robot Twin AI V1 modules and Markdown/JSON evidence.

## Global Constraints

- Python: `C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe`.
- Do not run `git init`; this workspace is not currently a Git repository.
- No MCU/ST-Link/ESP/serial/TCP/Keil/flash/reset/motor operation.
- Do not overwrite `.embeddedskills/build/v1_task4bd`, `v1_task4b1*`, or `v1_task4b2`.
- Do not change Task 4B-3 or any later model/controller work.
- A report is not proof: preserve commands, exit codes, metrics, images, and machine-readable JSON.
- Read the approved design first: `docs/superpowers/specs/2026-08-01-task4bd-4b1-4b2-reacceptance-design.md`.

---

### Task 1: Reaccept Task 4B-D documentation consistency

**Files:**
- Read: `.embeddedskills/build/v1_task4bd/handoff.md`
- Read: `docs/superpowers/plans/2026-07-30-robot-twin-ai-v1-remaining-execution-charter.md`
- Read/verify: the two 2026-07-28 PID spec/plan files named by the 4B-D charter
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4bd/gate_report.json`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4bd/handoff.md`

- [ ] Extract every 4B-D requirement and its claimed evidence into a machine-readable checklist.
- [ ] Verify each item against actual file content and exact line numbers.
- [ ] Record unresolved contradictions, including the historical `NOT MET` state and later task execution.
- [ ] Modify documentation only where the current facts genuinely require synchronization; never rewrite historical evidence as if it had passed earlier.
- [ ] Re-run the checklist and produce PASS only when zero required items remain unresolved.

### Task 2: Add camera content-validity regression tests

**Files:**
- Modify: `simulation/digital_twin/tests/test_v1_twin_camera.py`
- Modify only if required: `simulation/digital_twin/v1_twin/v1_twin_camera.py`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b1/red_green.md`

- [ ] Write tests that fail on an all-black/startup frame, stale repeated frames, and a device that reports a resolution different from the requested one.
- [ ] Run only the new tests and record the expected RED output.
- [ ] Implement the minimum warm-up/content-validity/resolution reporting behavior.
- [ ] Re-run the new tests and the complete camera test module; record GREEN output and exit codes.

### Task 3: Run a fresh 4B-1 hardware Gate 0

**Files:**
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b1/gate0_report.json`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b1/frame_start.png`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b1/frame_mid.png`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b1/frame_end.png`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b1/montage.png`

- [ ] Open DroidCam index 1 and request 1280×720; record the actual negotiated resolution.
- [ ] Warm up until consecutive content-valid frames are present; do not count warm-up time.
- [ ] Record a fresh uninterrupted 600-second gate and all required raw counters.
- [ ] Fail if actual resolution is not 1280×720, fps is below 20, drop exceeds 5%, timestamps are non-monotonic, or invalid-content frames enter the official interval.
- [ ] Save representative images and report status as `PENDING_INDEPENDENT_VISUAL_REVIEW`, never self-approve the manual gate.

### Task 4: Diagnose and test the 4B-2 centerline defect

**Files:**
- Modify: `simulation/digital_twin/tests/test_v1_twin_track_map.py`
- Modify only after RED evidence: `simulation/digital_twin/v1_twin/v1_twin_track_map.py`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b2/diagnosis.md`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b2/red_green.md`

- [ ] Reproduce the current `centerline_final.png` defect from the existing input and identify whether the red geometry is a contour, skeleton, unordered point set, or graph traversal error.
- [ ] Write failing tests for center-to-boundary distance, continuity/no blank-space jumps, and short-spur rejection.
- [ ] If the source course has branches, test that topology is represented explicitly; if a single fixed route is required but not documented, stop route selection with `NEEDS_USER_ROUTE_CHOICE` rather than guessing.
- [ ] Run the tests and record expected RED output before production changes.
- [ ] Implement the smallest root-cause fix and run the new tests plus all four V1 camera/calibration/track/pose test modules.

### Task 5: Regenerate 4B-2 evidence and self-review

**Files:**
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b2/track_map.json`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b2/trackmap_report.json`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/4b2/centerline_overlay.png`
- Create: `.embeddedskills/build/v1_task4b_reacceptance/final_report.md`

- [ ] Regenerate the map from the existing calibrated source without overwriting old evidence.
- [ ] Report centerline point count, component count, endpoints, branch nodes, maximum consecutive jump, rejected spur lengths, and center-to-boundary distance statistics.
- [ ] Render the mask, centerline and topology nodes with distinct colors over the original image.
- [ ] Confirm the calibration p95 gate remains satisfied and all existing tests remain green.
- [ ] Scan changed files for out-of-scope firmware/4B-3/later-task modifications and fail scope review if found.
- [ ] Finish with one of: `READY_FOR_INDEPENDENT_REVIEW`, `NEEDS_USER_ROUTE_CHOICE`, or `BLOCKED`, with exact remaining reasons.

## Required final response

Return only a concise status, actual files changed, commands/tests and exit codes, the 4B-1 live metrics, the 4B-2 topology metrics, and remaining blockers. Do not claim final acceptance; Codex performs that independently.
