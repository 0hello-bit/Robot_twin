# Tile Auto Align Boundary Design

## Problem

The 1080p ground checkerboard collector detects a checkerboard, but its first
target puts the first inner corner at pixel `(0, 0)`. That target cannot keep
the physical checkerboard fully inside the camera frame. OpenCV's default text
renderer also cannot render the collector's Chinese overlay strings.

## Design

Keep the existing 15 mm checkerboard, detector, tolerance, row-major capture
order, and physical control-point coordinates. Compute target origins with one
outer-square margin at every frame edge, then advance by one measured
checkerboard span so adjacent control points retain the existing coordinate
meaning. Use ASCII-only constants for the OpenCV window title and all visible
overlay/status text.

## Acceptance

- `safe_target_axes(1920, 1080, 177, 111)` returns targets whose full board and
  one outer square remain inside the frame.
- The overlay constants are ASCII-only and the collector uses them for its
  window and visible text.
- The focused regression, full Python regression, `compileall`, and
  `git diff --check` pass before a new camera-only run.
- The failed `ground_controls_15mm_1080p_20260809_run1` directory remains
  unchanged; a new run uses a separate `run2` directory.
