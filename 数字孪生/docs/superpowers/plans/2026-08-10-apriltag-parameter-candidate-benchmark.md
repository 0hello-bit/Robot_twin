# AprilTag Parameter Candidate Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only offline benchmark for bounded OpenCV AprilTag parameter variants without changing the production tracker.

**Architecture:** A new `apriltag_parameter_matrix.py` adapter will reuse the existing Unicode-safe image loader, preprocessing conversion, OpenCV branch runner, result builder, and percentile summary from `apriltag_diagnostic_matrix.py`. Each parameter variant receives a fresh `cv2.aruco.DetectorParameters` instance; the report keeps parameter variant and preprocessing branch as separate dimensions and is marked screening-only.

**Tech Stack:** Python 3.11, OpenCV 5.0.0 ArUco AprilTag 36h11, pytest, existing JSON evidence format.

## Global Constraints

- Do not modify `PoseTracker`, firmware, PID, IMU control, camera mode, calibration, or hardware behavior.
- Reuse `apriltag_diagnostic_matrix.py`; do not create a second image loader or detector result schema.
- Use the fixed real observation contract: detection ratio `>=0.95`, maximum pose gap `<=2.0` frames, detector p95 `<=33.333333 ms`.
- Thumbnail-only results are `INSUFFICIENT_EVIDENCE` for B3 readiness.
- Refuse to overwrite existing output reports.
- Use TDD: each production behavior gets a failing test before implementation.

---

### Task 1: Add failing tests for parameter variants and report shape

**Files:**
- Create: `simulation/digital_twin/tests/test_apriltag_parameter_matrix.py`
- Read-only dependency: `tools/camera_toolchain/apriltag_diagnostic_matrix.py`

**Interfaces:**
- The tests import `PARAMETER_VARIANTS`, `DEFAULT_BRANCHES`, `build_detector_parameters`, and `run_parameter_matrix` from the new module.
- The tests use a small temporary JPEG and the real OpenCV ArUco API; they do not open a camera or socket.

- [ ] **Step 1: Write the failing test for stable variant names and exact default parameters**

```python
def test_parameter_variants_are_stable_and_default_matches_opencv():
    assert PARAMETER_VARIANTS == (
        "default", "subpix", "contour", "adaptive_wide", "perimeter_relaxed"
    )
    default = build_detector_parameters("default")
    assert default.adaptiveThreshWinSizeMax == 23
    assert default.minMarkerPerimeterRate == 0.03
```

- [ ] **Step 2: Write the failing test for independent parameter objects and bounded changes**

```python
def test_parameter_variants_create_independent_bounded_objects():
    first = build_detector_parameters("subpix")
    second = build_detector_parameters("subpix")
    assert first is not second
    assert first.cornerRefinementMethod == cv2.aruco.CORNER_REFINE_SUBPIX
    assert build_detector_parameters("contour").cornerRefinementMethod == cv2.aruco.CORNER_REFINE_CONTOUR
    assert build_detector_parameters("adaptive_wide").adaptiveThreshWinSizeMax == 53
    assert build_detector_parameters("perimeter_relaxed").minMarkerPerimeterRate == 0.015
```

- [ ] **Step 3: Write the failing test for invalid variant and branch rejection**

```python
def test_parameter_matrix_rejects_unknown_variant_and_branch(tmp_path):
    image_path = write_small_jpeg(tmp_path / "frame.jpg")
    with pytest.raises(ValueError, match="unsupported parameter variant"):
        run_parameter_matrix([image_path], variants=("unknown",))
    with pytest.raises(ValueError, match="unsupported branch"):
        run_parameter_matrix([image_path], branches=("unknown",))
```

- [ ] **Step 4: Write the failing test for screening-only report dimensions**

```python
def test_parameter_matrix_report_separates_variant_and_branch(tmp_path):
    image_path = write_small_jpeg(tmp_path / "frame.jpg")
    report = run_parameter_matrix(
        [image_path],
        branches=("opencv_gray_1x",),
        variants=("default", "subpix"),
    )
    assert report["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["parameter_variants"] == ["default", "subpix"]
    assert report["branches"] == ["opencv_gray_1x"]
    assert set(report["summaries"]) == {"default", "subpix"}
    assert report["summaries"]["default"]["opencv_gray_1x"]["image_count"] == 1
```

- [ ] **Step 5: Run the focused tests and confirm the expected RED failure**

Run:

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_apriltag_parameter_matrix.py
```

Expected: collection or import failure because
`tools/camera_toolchain/apriltag_parameter_matrix.py` does not exist yet.

### Task 2: Implement the read-only parameter matrix

**Files:**
- Create: `tools/camera_toolchain/apriltag_parameter_matrix.py`
- Test: `simulation/digital_twin/tests/test_apriltag_parameter_matrix.py`

**Interfaces:**
- `build_detector_parameters(variant: str) -> cv2.aruco.DetectorParameters` returns a fresh object or raises `ValueError`.
- `run_parameter_matrix(image_paths, *, target_id=0, branches=DEFAULT_BRANCHES, variants=PARAMETER_VARIANTS) -> dict` returns a JSON-safe screening report.
- Each record contains `parameter_variant`, the reused preprocessing `branch`, image hash/path/shape, IDs, target detection, rejected count, elapsed nanoseconds, and error.

- [ ] **Step 1: Implement the parameter constants and validator**

```python
PARAMETER_VARIANTS = (
    "default", "subpix", "contour", "adaptive_wide", "perimeter_relaxed"
)
DEFAULT_BRANCHES = (
    "opencv_gray_1x", "opencv_gray_2x", "opencv_blue_2x", "opencv_blue_clahe_2x"
)
```

Validate both dimensions before loading any image, and reject an empty image list.

- [ ] **Step 2: Implement fresh parameter construction**

```python
def build_detector_parameters(variant):
    params = cv2.aruco.DetectorParameters()
    if variant == "subpix":
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    elif variant == "contour":
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_CONTOUR
    elif variant == "adaptive_wide":
        params.adaptiveThreshWinSizeMax = 53
    elif variant == "perimeter_relaxed":
        params.minMarkerPerimeterRate = 0.015
    elif variant != "default":
        raise ValueError("unsupported parameter variant: {}".format(variant))
    return params
```

- [ ] **Step 3: Implement one detector per parameter variant and reuse the existing branch runner**

For each variant, construct one `cv2.aruco.ArucoDetector(dictionary, params)`. For each image and branch, call the existing `_run_opencv(frame, branch, target_id, detector)` and then add `parameter_variant` to the reused `build_branch_result` output. Do not mutate or reuse a parameter object across variants.

- [ ] **Step 4: Implement nested summaries and screening evidence status**

Return:

```python
{
    "schema_version": 1,
    "type": "V1B3AprilTagParameterMatrix",
    "source": "RETAINED_PARAMETER_SCREENING",
    "evidence_status": "INSUFFICIENT_EVIDENCE",
    "parameter_variants": [...],
    "branches": [...],
    "images": [...],
    "summaries": {"default": {"opencv_gray_1x": {...}}},
    "records": [...],
}
```

Use the existing percentile function through `summarize_branch_results`; do not add a second percentile implementation. The report must preserve per-variant errors and never infer B3 readiness.

- [ ] **Step 5: Add CLI output with no-overwrite protection**

Support repeated `--image`, repeated `--branch`, repeated `--variant`, `--target-id`, and required `--output`. With no branch/variant flags, use the constants above. Refuse an existing output path, create the parent directory, and write UTF-8 JSON with a trailing newline.

- [ ] **Step 6: Run the focused tests and confirm GREEN**

Run:

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_apriltag_parameter_matrix.py simulation/digital_twin/tests/test_apriltag_diagnostic_matrix.py
```

Expected: all focused tests pass with no camera or network access.

### Task 3: Run the candidate benchmark on retained evidence

**Files:**
- Create: `docs/evidence/v1_b3_parameter_candidate_screening_20260810/report.json`
- Read-only inputs: `docs/evidence/v1_b3_static_apriltag_20260810_s1/frames/*.jpg` and the six retained dynamic `failed_frames/*.jpg`

**Interfaces:**
- The CLI produces one immutable screening report; no existing evidence file is overwritten.

- [ ] **Step 1: Build the image argument list from the retained static and dynamic files**

Run from the workspace with PowerShell so the shell enumerates files without writing an intermediate list:

```powershell
$images = @(
  Get-ChildItem 'docs/evidence/v1_b3_static_apriltag_20260810_s1/frames' -Filter '*.jpg' |
    Sort-Object Name | Select-Object -ExpandProperty FullName
)
$images += @(
  Get-ChildItem 'simulation/digital_twin/data/product/sessions/v1_b/c260809101540981/failed_frames','simulation/digital_twin/data/product/sessions/v1_b/c260809102554685/failed_frames','simulation/digital_twin/data/product/sessions/v1_b/c260810033252119/failed_frames' -Filter '*.jpg' |
    Sort-Object FullName | Select-Object -ExpandProperty FullName
)
$args = @('tools/camera_toolchain/apriltag_parameter_matrix.py','--output','docs/evidence/v1_b3_parameter_candidate_screening_20260810/report.json')
foreach ($image in $images) { $args += '--image'; $args += $image }
& py -3.11 @args
```

Expected: the report contains 106 images (100 static plus 6 dynamic failure thumbnails), 5 parameter variants, and 4 preprocessing branches.

- [ ] **Step 2: Verify the report shape and input count**

Run:

```text
py -3.11 -c "import json; p='docs/evidence/v1_b3_parameter_candidate_screening_20260810/report.json'; r=json.load(open(p, encoding='utf-8')); assert r['evidence_status']=='INSUFFICIENT_EVIDENCE'; assert len(r['images'])==106; assert len(r['parameter_variants'])==5; assert len(r['branches'])==4; print('screening report shape: PASS')"
```

- [ ] **Step 3: Compare each variant against default**

Record dynamic-thumbnail detection ratio and p95 for every variant/branch. A candidate is only a hypothesis if it improves the dynamic thumbnail ratio over `default` without exceeding the default p95 by more than 10%; this is not the B3 acceptance gate.

- [ ] **Step 4: Keep production unchanged when no candidate meets the screen**

If no candidate clears the hypothesis screen, record `production_change: NOT_JUSTIFIED` and move to the separate ROI/recovery design. Do not change `PoseTracker` in this plan.

### Task 4: Regression verification and handoff

**Files:**
- Modify only if needed: `docs/agent-context/handoffs/2026-08-10-b3-offline-dynamic-static-analysis.md`
- Test: all existing `simulation/digital_twin/tests`

- [ ] **Step 1: Run the focused and full regression**

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_apriltag_parameter_matrix.py simulation/digital_twin/tests/test_apriltag_diagnostic_matrix.py
py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
py -3.11 -m compileall -q simulation/digital_twin tools
git diff --check
```

- [ ] **Step 2: Update the handoff with exact results**

Document changed files, commands, candidate metrics, `VERIFIED`/`INFERENCE`/`INSUFFICIENT EVIDENCE`, and whether a production or real-hardware change is justified. Explicitly state that the parameter benchmark is offline-only.

- [ ] **Step 3: Commit only the benchmark implementation, tests, report, and handoff**

```text
git add tools/camera_toolchain/apriltag_parameter_matrix.py simulation/digital_twin/tests/test_apriltag_parameter_matrix.py docs/evidence/v1_b3_parameter_candidate_screening_20260810/report.json docs/agent-context/handoffs/2026-08-10-b3-offline-dynamic-static-analysis.md
git commit -m "feat: benchmark apriltag detector parameter candidates"
```
