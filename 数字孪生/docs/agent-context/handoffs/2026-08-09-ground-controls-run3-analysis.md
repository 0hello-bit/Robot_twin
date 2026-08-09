# 2026-08-09 Ground Controls Run3 Analysis

## Scope

Camera-only 1080p checkerboard collection and offline relative-plane analysis.
The car stayed out of the loop; no TCP, START/STOP, firmware, or hardware
action was used.

## Collection evidence

- Source: `tools/camera_toolchain/ground_controls_15mm_1080p_20260809_run3`
- `controls.json`: 90 controls, `view_00.png` through `view_89.png`
- Every view was independently re-read as `1920x1080`; all 90 checkerboards
  were detected again.
- `collector_stderr.log` is empty and the collector exited after saving 90/90.
- `run1` and partial `run2` remain unchanged and are not merged into this set.

## Rotation handling

The original collector wrote `angle_deg=0` for every view. That is not valid
when a human slides the board with small in-plane rotation. The collector now
uses the first accepted board as a relative plane reference and estimates a
per-view rigid angle. `correct_tile_controls.py` produced
`controls_angle_corrected.json` and `angle_report.json` without overwriting
the raw controls.

The joint fit is the preferred exploratory output:

- `joint_fit_controls_v2.json`
- `joint_fit_report_v2.json`

## Relative-plane results

`fit_tile_controls.py` reuses `mosaic_homography.fit_global_homography` and fits
one pixel-to-plane homography plus one rigid pose per view. The report uses raw
pixels and does not claim lens-distortion correction.

- Full-fit corner residual: mean `0.532 mm`, p95 `1.378 mm`, max `3.458 mm`.
- 45/45 checkerboard spatial holdout: p95 `1.493 mm`, max `2.983 mm`.
- Every-third-column holdout: p95 `1.995 mm`, max `3.728 mm`.
- Five column folds: mean p95 `1.583 mm`, worst p95 `2.528 mm`.

The existing 14-view 1080p intrinsics source was independently re-fit at RMS
`0.931 px` and p95 `1.987 px`. Applying that undistortion to this raw-plane
experiment worsened the full-fit p95 to `2.633 mm` and the worst five-fold
p95 to `4.836 mm`; it is not promoted as an improvement.

## Evidence boundary

`VERIFIED`: complete 1080p collection, repeated corner detection, relative
plane fit, and spatial holdout measurements above.

`INFERENCE`: the fixed camera, flat board, and 15 mm scale can support a useful
relative ground-plane model; typical internal consistency is around 1-2 mm.

`INSUFFICIENT EVIDENCE`: absolute physical ground accuracy, a formal 2 mm
holdout pass, and a runtime-ready 1080p calibration manifest.

The original pixel-grid x/y labels are not independent physical truth. The
joint-fit report records their translation discrepancy separately. Do not run
`homography_holdout_eval.py` with joint-fit poses and call that an independent
physical holdout; the poses were estimated from the same images.

## Next interface

To promote this from relative exploratory evidence to physical calibration,
add an independently known ground reference: a rigid full-plane target, taped
120x75 mm ground marks, or independently measured origin/translation/angle
for each control view. Then rerun the holdout using those measurements, not
pixel-grid labels or poses fitted from the same images.
