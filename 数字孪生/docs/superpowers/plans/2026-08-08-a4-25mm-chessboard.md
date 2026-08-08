# A4 25 mm Checkerboard Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a print-accurate A4 checkerboard target and make the new 1920x1080 calibration path use its 25 mm physical scale without changing historical calibration evidence.

**Architecture:** Keep the target geometry in the existing camera toolchain's shared configuration. Add a deterministic, hardware-free generator that emits a vector PDF, a raster preview, and machine-readable metadata. Pass the shared 25 mm value into the active homography and calibration helpers; keep lower-level APIs able to accept explicit legacy sizes.

**Tech Stack:** Python 3.11, OpenCV, NumPy, ReportLab, Pillow, pytest, Poppler (`pdfinfo`/`pdftoppm`).

## Global Constraints

- Paper is A4 landscape, 297 mm x 210 mm.
- The detector pattern is 9 x 6 inner corners, represented by a 10 x 7 square grid.
- Each printed square is 25 mm; the active grid is 250 mm x 175 mm.
- The target is a single continuous grid and must not be tiled from pages.
- The PDF is the print source and must be printed at 100 percent scale.
- Existing 15 mm and 1280x720 evidence and profiles are not rewritten.
- Generation and tests must not open a camera, socket, serial port, debugger, or robot control channel.

### Task 1: Centralize the new target constants

**Files:**
- Modify: `数字孪生/tools/camera_toolchain/camera_common.py`
- Test: `数字孪生/simulation/digital_twin/tests/test_camera_toolchain_common.py`

**Interfaces:**
- Produce `CHECKERBOARD_PATTERN = (9, 6)`.
- Produce `CHECKERBOARD_SQUARE_MM = 25.0`.
- Produce `CHECKERBOARD_GRID_SQUARES = (10, 7)` and `CHECKERBOARD_ACTIVE_SIZE_MM = (250.0, 175.0)`.

- [ ] **Step 1: Write the failing constant tests**

```python
def test_1080p_calibration_target_geometry_is_explicit():
    camera_common = _load_camera_common()
    assert camera_common.CHECKERBOARD_PATTERN == (9, 6)
    assert camera_common.CHECKERBOARD_SQUARE_MM == pytest.approx(25.0)
    assert camera_common.CHECKERBOARD_GRID_SQUARES == (10, 7)
    assert camera_common.CHECKERBOARD_ACTIVE_SIZE_MM == (250.0, 175.0)
```

- [ ] **Step 2: Run the focused test and observe the missing constants**

Run: `py -3.11 -m pytest -q 数字孪生\simulation\digital_twin\tests\test_camera_toolchain_common.py -k calibration_target`

Expected: FAIL with an `AttributeError` for the new constants.

- [ ] **Step 3: Add the constants beside the existing camera defaults**

Keep the values as plain numeric constants in `camera_common.py`; do not read the camera or filesystem when importing them.

- [ ] **Step 4: Run the focused test**

Run: `py -3.11 -m pytest -q 数字孪生\simulation\digital_twin\tests\test_camera_toolchain_common.py -k calibration_target`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- 数字孪生/tools/camera_toolchain/camera_common.py 数字孪生/simulation/digital_twin/tests/test_camera_toolchain_common.py
git commit -m "feat: define 25mm checkerboard target geometry"
```

### Task 2: Generate and validate the printable target

**Files:**
- Create: `数字孪生/tools/camera_toolchain/generate_a4_checkerboard.py`
- Create: `数字孪生/simulation/digital_twin/tests/test_a4_checkerboard_target.py`
- Create: `数字孪生/tools/camera_toolchain/calibration_targets/a4_checkerboard_9x6_25mm.pdf`
- Create: `数字孪生/tools/camera_toolchain/calibration_targets/a4_checkerboard_9x6_25mm.png`
- Create: `数字孪生/tools/camera_toolchain/calibration_targets/a4_checkerboard_9x6_25mm.json`

**Interfaces:**
- CLI: `py -3.11 generate_a4_checkerboard.py --out-dir <directory>`.
- The generator writes deterministic PDF, PNG, and JSON files and returns exit code 0.
- JSON records page size, pattern, square size, active grid size, border, and print scale.

- [ ] **Step 1: Write failing generator tests**

```python
def test_generator_emits_a4_metadata_and_outputs(tmp_path):
    result = generate_target(tmp_path)
    assert result.pdf_path.exists()
    assert result.png_path.exists()
    assert result.metadata_path.exists()
    metadata = json.loads(result.metadata_path.read_text("utf-8"))
    assert metadata["page_mm"] == [297.0, 210.0]
    assert metadata["square_size_mm"] == 25.0
    assert metadata["active_grid_mm"] == [250.0, 175.0]

def test_generated_preview_contains_9x6_checkerboard(tmp_path):
    result = generate_target(tmp_path)
    image = cv2.imread(str(result.png_path), cv2.IMREAD_GRAYSCALE)
    found, _ = cv2.findChessboardCorners(image, (9, 6), None)
    assert found

def test_generated_pdf_has_a4_landscape_media_box(tmp_path):
    result = generate_target(tmp_path)
    page = PdfReader(str(result.pdf_path)).pages[0]
    assert float(page.mediabox.width) == pytest.approx(297.0 * mm)
    assert float(page.mediabox.height) == pytest.approx(210.0 * mm)
```

- [ ] **Step 2: Run the new tests and confirm they fail because the generator is absent**

Run: `py -3.11 -m pytest -q 数字孪生\simulation\digital_twin\tests\test_a4_checkerboard_target.py`

Expected: FAIL during import because `generate_a4_checkerboard.py` does not exist.

- [ ] **Step 3: Implement the deterministic generator**

Use ReportLab points for the PDF so the grid is vector-accurate. Use 300 DPI for the PNG preview. Draw a 10 x 7 alternating square grid centered on A4 landscape with a 10 mm white border. Do not put text or logos inside the active grid. Write metadata with `ensure_ascii=False`, sorted keys, and a trailing newline.

- [ ] **Step 4: Run the new tests**

Run: `py -3.11 -m pytest -q 数字孪生\simulation\digital_twin\tests\test_a4_checkerboard_target.py`

Expected: PASS.

- [ ] **Step 5: Generate the repository print artifacts**

Run from `数字孪生\tools\camera_toolchain`:

```powershell
py -3.11 generate_a4_checkerboard.py --out-dir calibration_targets
```

Expected: the three named artifacts exist and the JSON reports `print_scale=1.0`.

- [ ] **Step 6: Commit**

```powershell
git add -- 数字孪生/tools/camera_toolchain/generate_a4_checkerboard.py 数字孪生/simulation/digital_twin/tests/test_a4_checkerboard_target.py 数字孪生/tools/camera_toolchain/calibration_targets
git commit -m "feat: add printable a4 25mm checkerboard target"
```

### Task 3: Bind active calibration helpers to the target size

**Files:**
- Modify: `数字孪生/simulation/digital_twin/v1_twin/v1_twin_calibration.py`
- Modify: `数字孪生/tools/camera_toolchain/homography_holdout_eval.py`
- Modify: `数字孪生/tools/camera_toolchain/mosaic_homography.py`
- Modify: `数字孪生/tools/camera_toolchain/perpendicularity_preview.py`
- Modify: `数字孪生/tools/camera_toolchain/capture_intrinsics_coverage.py`
- Modify: `数字孪生/tools/camera_toolchain/capture_homography_positions.py`
- Modify: `数字孪生/tools/camera_toolchain/extract_calibration_frames.py`
- Modify: `数字孪生/tools/camera_toolchain/guided_capture.py`
- Test: `数字孪生/simulation/digital_twin/tests/test_v1_twin_calibration.py`

**Interfaces:**
- Active tools import `camera_common.CHECKERBOARD_PATTERN` instead of duplicating `(9, 6)`.
- Active geometry tools use `camera_common.CHECKERBOARD_SQUARE_MM` for physical coordinates.
- Homography replay tools expose `--square-size-mm`, defaulting to 25.0 while allowing an explicit 15.0 for legacy evidence.
- `detect_checkerboard` keeps accepting an explicit `square_size_mm` so historical 15 mm data can still be tested or replayed intentionally.

- [ ] **Step 1: Add a regression test proving the explicit 25 mm path**

```python
def test_pattern_object_points_support_the_new_25mm_target():
    obj = pattern_object_points((9, 6), square_size_mm=25.0)
    assert np.linalg.norm(obj[0, :2] - obj[1, :2]) == pytest.approx(25.0)
    assert np.linalg.norm(obj[0, :2] - obj[9, :2]) == pytest.approx(25.0)
```

- [ ] **Step 2: Run the focused calibration test**

Run: `py -3.11 -m pytest -q 数字孪生\simulation\digital_twin\tests\test_v1_twin_calibration.py -k 25mm`

Expected: FAIL because the new regression test is not present yet.

- [ ] **Step 3: Replace duplicated active-tool constants with the shared constants**

Keep the lower-level calibration function parameterized; callers for the new target pass `camera_common.CHECKERBOARD_SQUARE_MM`. Do not modify any archived JSON or old profile.

- [ ] **Step 4: Run the focused tests**

Run: `py -3.11 -m pytest -q 数字孪生\simulation\digital_twin\tests\test_v1_twin_calibration.py 数字孪生\simulation\digital_twin\tests\test_camera_toolchain_common.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- 数字孪生/simulation/digital_twin/v1_twin/v1_twin_calibration.py 数字孪生/tools/camera_toolchain 数字孪生/simulation/digital_twin/tests/test_v1_twin_calibration.py
git commit -m "feat: use shared checkerboard geometry in calibration tools"
```

### Task 4: Update documentation and perform visual/regression verification

**Files:**
- Modify: `数字孪生/tools/camera_toolchain/README.md`

- [ ] **Step 1: Document the generator command and the 25 mm target**

State that the PDF must be printed at 100 percent, the active grid is 250 mm x 175 mm, and the 15 mm legacy target must not be mixed with the new 1080p campaign.

- [ ] **Step 2: Render the PDF and inspect the PNG**

Run: `pdftoppm -png -r 150 数字孪生\tools\camera_toolchain\calibration_targets\a4_checkerboard_9x6_25mm.pdf tmp\a4_checkerboard_qa`

Expected: one A4 PNG with the entire grid visible and no clipping. Inspect it with `view_image`.

- [ ] **Step 3: Run complete verification**

```powershell
py -3.11 -m pytest -q 数字孪生\simulation\digital_twin\tests
py -3.11 -m compileall -q 数字孪生\simulation\digital_twin 数字孪生\tools
git diff --check
```

Expected: all tests pass, compileall exits 0, and diff check is clean.

- [ ] **Step 4: Verify repository state and final commit**

Confirm the generated metadata, PDF page dimensions, and PNG detector result from the raw artifacts. Confirm no camera, socket, serial, debugger, START, STOP, flash, or car motion occurred.

```powershell
git status --short
git log -5 --oneline
```

- [ ] **Step 5: Commit**

```powershell
git add -- 数字孪生/tools/camera_toolchain/README.md
git commit -m "docs: document a4 25mm checkerboard workflow"
```
