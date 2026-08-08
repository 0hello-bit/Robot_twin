# B3 local preprocess candidate handoff

Date: 2026-08-08 Asia/Shanghai  
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`  
Status: `OFFLINE_CANDIDATE_HARDWARE_RERUN_REQUIRED`

## Why this change exists

The real synchronized run `c260808052942717` is still below the B3
observation screen:

- `154 / 370` detected poses (`41.62%`);
- `216` `candidates_rejected` frames;
- detector p95 `77.447895 ms` against a `33.333333 ms` frame budget;
- maximum pose gap `58.74531` frame periods.

The raw run and its observation-gate report remain immutable. This change does
not rewrite that result.

## Offline candidate

After a raw grayscale ROI miss, `PoseTracker` now tries three bounded local
inputs before the existing full-frame reacquisition:

1. blue-channel CLAHE;
2. blue-channel unsharp mask;
3. grayscale CLAHE.

Each input uses a 32 px white diagnostic border by default and one `2x`
detector scale. The branch runs only when a previous valid ID=0 observation
already provides an ROI. The full-frame fallback remains in place for
reacquisition. Unknown IDs and rejected quadrilaterals are never accepted.

The capture path also retains failure frames at source width up to `1280` px
with JPEG quality `95`. The previous run's `640x360`, quality-70 images are
not retroactively upgraded.

## Offline evidence

The eight retained failure images are diagnostic thumbnails from the real run,
not original full-resolution frames. With an independently seeded approximate
ROI for replay, the candidate recovered ID=0 in `7/8` images; the remaining
image still failed after all three local inputs and full-frame `2x` fallback.
This is candidate evidence only, not a new real detection ratio.

Existing successful recordings replayed through the current tracker without
regression:

- `91/91`, p95 approximately `6.82 ms`;
- `90/91`, p95 approximately `7.87 ms`;
- `76/76`, p95 approximately `11.19 ms`;
- `76/76`, p95 approximately `6.17 ms`.

These are local video replays. They do not prove the candidate on the moving
run that produced `c260808052942717`.

## Verification

- Focused pose tests: `15 passed`.
- Full digital-twin Python regression: `734 passed, 5 skipped`.
- Python `compileall`: exit `0`.
- `git diff --check`: no whitespace errors.
- No camera, TCP, ST-Link, firmware flash, START, STOP, reset, or motor action
  was performed in this offline task.

## Evidence boundary

### VERIFIED

- The bounded local preprocessing branch is covered by regression tests.
- Existing synthetic and retained successful recordings remain detectable.
- The next failure-frame artifacts will preserve source-resolution detail.

### INFERENCE

- The failed thumbnails are compatible with a local color/contrast and motion
  interaction. The blue-channel branch is a practical hypothesis because it
  recovered most retained thumbnails, not a general camera theorem.
- Local ROI search should cost less than repeated full-frame multi-scale search
  when the previous ID=0 observation remains near the vehicle.

### INSUFFICIENT EVIDENCE

- No post-change real detection ratio, pose-gap result, or detector p95 exists.
- B3 observation continuity is not accepted.
- No conclusion about camera resolution, calibration accuracy, or vehicle
  behavior follows from this candidate.

## Next authorized interface

Keep hardware idle until explicit authorization. Then run one bounded capture
with the marker visible from the first frame using the current source. Compare
against `c260808052942717`:

- timestamp monotonicity;
- detection ratio;
- maximum pose gap;
- detector p95;
- sync-gate verdict.

Inspect the new source-resolution `failed_frames/` before changing any other
detector parameter, camera resolution, calibration, or firmware behavior.
