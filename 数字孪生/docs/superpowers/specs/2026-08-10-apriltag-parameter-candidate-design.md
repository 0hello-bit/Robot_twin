# AprilTag Parameter Candidate Benchmark

## Problem

The latest real 1080p capture passed synchronization but failed the
observation gate: detection ratio 75.38%, maximum pose gap 7.31 frames, and
detector p95 74.58 ms. Pupil gray 1x recovered 4/6 retained dynamic failure
thumbnails but had a 142.12 ms p95. No currently tested detector satisfies
both continuity and the 33.33 ms frame budget.

The next change must therefore distinguish detector-parameter effects from
ROI/recovery-architecture effects without changing the production tracker or
hardware behavior.

## Goal

Add a reproducible, read-only offline benchmark for a small set of OpenCV
AprilTag `DetectorParameters` variants. It will reuse the existing Unicode-
safe image loading, preprocessing branches, result schema, timing summaries,
and retained evidence. It will rank hypotheses; it will not select or deploy
a production detector.

## Non-goals

- No change to `PoseTracker` construction or runtime behavior.
- No change to camera resolution, calibration, thresholds in the production
  tracker, firmware, PID, IMU control, or hardware.
- No Pupil detector integration into the production path.
- No B3 pass claim from thumbnail-only evidence.

## Design

Create `tools/camera_toolchain/apriltag_parameter_matrix.py` as a thin offline
adapter around `apriltag_diagnostic_matrix.py`. It will reuse
`load_image`, `_opencv_input`, `build_branch_result`, and
`summarize_branch_results` rather than create a second image or report
format.

The public interfaces are:

```python
PARAMETER_VARIANTS = (
    "default",
    "subpix",
    "contour",
    "adaptive_wide",
    "perimeter_relaxed",
)

def build_detector_parameters(variant: str) -> cv2.aruco.DetectorParameters:
    ...

def run_parameter_matrix(
    image_paths: Sequence[str | Path],
    *,
    target_id: int = 0,
    branches: Sequence[str] = (
        "opencv_gray_1x",
        "opencv_gray_2x",
        "opencv_blue_2x",
        "opencv_blue_clahe_2x",
    ),
    variants: Sequence[str] = PARAMETER_VARIANTS,
) -> dict[str, Any]:
    ...
```

Every variant creates a fresh OpenCV parameter object. The variants change
one bounded parameter family at a time:

- `default`: current OpenCV defaults, as the control branch;
- `subpix`: enable `CORNER_REFINE_SUBPIX` with the existing refinement
  defaults;
- `contour`: enable `CORNER_REFINE_CONTOUR` with the existing refinement
  defaults;
- `adaptive_wide`: widen adaptive-threshold window maximum from 23 to 53;
- `perimeter_relaxed`: lower `minMarkerPerimeterRate` from 0.03 to 0.015.

The report will contain one record and one summary for every
`variant x preprocessing branch x image` combination, with image hashes,
target detection, rejected-candidate count, errors, p95 timing, and an
explicit `screening_only` evidence status.

## Dataset and acceptance

The first run uses the existing 100 static 1080p frames plus the six retained
dynamic failure thumbnails. Static results are a regression reference;
thumbnail results are a hypothesis screen and cannot establish B3 readiness.

A candidate may be proposed for a later matched real rerun only if it shows a
clear improvement over `default` on the dynamic thumbnail screen without a
material timing regression. It still must pass the real observation contract
on a fresh matched run:

- detection ratio >= 0.95;
- maximum pose gap <= 2.0 frames;
- detector processing p95 <= 33.333333 ms.

If no candidate meets those conditions, the next design target is the
stateful ROI/recovery architecture, not another unbounded detector fallback.

## Failure handling

- Unknown variants or branches fail before processing images.
- Existing image decoding and per-branch exception retention remain in force.
- Existing output files are never overwritten.
- A missing detector parameter API is recorded as a branch error rather than
  silently changing the control branch.

## Verification

Tests will prove variant names, fresh independent parameter objects, exact
control defaults, invalid-input rejection, and report shape. The benchmark
will then be run on the retained images and its JSON will be reviewed against
the unchanged B3 thresholds before any production edit is considered.
