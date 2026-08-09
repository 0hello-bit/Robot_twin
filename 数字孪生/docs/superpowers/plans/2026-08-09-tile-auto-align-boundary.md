# Tile Auto Align Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 1080p checkerboard collector capture only physically visible target positions and render readable ASCII guidance.

**Architecture:** Keep `tile_auto_align.py` as the single collector. A pure
`safe_target_axes` helper computes safe pixel origins from the measured board
span; the existing detector and control-point writer consume those origins.

**Tech Stack:** Python 3.11, OpenCV, NumPy, pytest, PowerShell.

## Global Constraints

- Keep the existing 15 mm ground checkerboard and 1920x1080/MJPG/30 camera contract.
- Do not change detector thresholds, AprilTag code, firmware, TCP, or hardware control.
- Preserve `ground_controls_15mm_1080p_20260809_run1`; use a new output directory for the rerun.
- Hardware remains untouched; this is camera-only collection.

### Task 1: Safe target and readable collector

**Files:**
- Modify: `tools/camera_toolchain/tile_auto_align.py`
- Test: `simulation/digital_twin/tests/test_tile_auto_align.py`

**Interfaces:**
- `safe_target_axes(width, height, inner_span_w, inner_span_h) -> (list[int], list[int])`
- `WINDOW_TITLE`, `PLACE_PROMPT`, and `STATUS_PREFIX` are ASCII strings.

- [x] **Step 1: Write and run the failing tests**

  The retained tests require safe margins and ASCII display constants. Before
  the implementation they fail with missing production symbols.

- [x] **Step 2: Implement the smallest production change**

  Add one outer-square margin to both axes, preserve one-board-span stepping,
  use the resulting axes in the existing row-major loop, and replace visible
  Chinese text with ASCII.

- [ ] **Step 3: Run focused verification**

  Run `py -3.11 -m pytest -q simulation/digital_twin/tests/test_tile_auto_align.py`.

- [ ] **Step 4: Run repository verification**

  Run the complete digital-twin test suite, Python compileall for
  `simulation/digital_twin` and `tools`, and `git diff --check`.

- [ ] **Step 5: Start the separate camera-only run**

  Use `ground_controls_15mm_1080p_20260809_run2`; inspect `controls.json` and
  saved view dimensions before allowing homography evaluation.
