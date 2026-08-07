# B3 failure-frame diagnostic offline handoff

Date: 2026-08-07
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED`

## Objective

Make the existing synchronized capture path retain enough representative
failed camera frames to explain the latest sparse AprilTag pose stream. This
task is diagnostic only; it does not select a detector fix.

## Changed files

- `tools/camera_toolchain/capture_sync_run.py`
  - Added optional `failure_frame_dir` and bounded sampling.
  - Production entrypoint uses `failed_frames/` under each new run directory.
  - Saves at most 12 JPEG thumbnails.
  - Records `failure_frame_path` in `frame_index.jsonl`.
  - Writes `failure_frame_summary.json`.
- `simulation/digital_twin/tests/test_capture_sync_cleanup.py`
  - Added coverage for thumbnail saving, cap, relative path, and summary
    serialization.
- `.gitignore`
  - Keeps local run logs, Keil `Objects/Listings`, and camera probe captures
    out of Git while retaining them on disk.
- `docs/agent-context/CURRENT_STATUS.md`
- `docs/agent-context/PROJECT_MEMORY.md`

## Sampling contract

- First observed frame for each failure reason is saved.
- Every 30th subsequent occurrence is saved until 12 total images are saved.
- Failure reasons remain those emitted by the existing tracker, including
  `no_markers`, `candidates_rejected`, and `target_tag_not_found`.
- Images are diagnostic thumbnails only. The complete raw camera video is not
  created by this change.

## Verification

- Focused capture and pose-tracker tests: `42 passed`.
- Full Python regression excluding archive: `708 passed, 5 skipped`.
- `py -3.11 -m compileall -q simulation/digital_twin tools`: exit `0`.
- `git diff --check`: no whitespace errors; existing LF/CRLF conversion
  warnings remain.
- No camera, TCP, ST-Link, firmware flash, START, STOP, reset, or motor action
  was performed by this task.
- Keil UV4 was not found in the current environment's known installation
  paths; no fresh firmware build is claimed here.

## Evidence classification

### VERIFIED

- The offline capture path can bind a failed frame to its detector metadata
  and retain it under a deterministic bounded policy.
- Existing capture lifecycle and all current offline regressions remain green.

### INFERENCE

- The next real run should distinguish visibility, blur, occlusion, low
  contrast, and detector rejection more reliably than the previous run because
  the failed frames will be available for inspection.

### INSUFFICIENT EVIDENCE

- No new evidence proves that AprilTag detection, synchronization, calibration,
  or vehicle behavior improved.
- Do not change detector parameters or calibration until the retained images
  are inspected.

## Next interface

After explicit user authorization, run one bounded synchronized capture with
the tag fully visible from the first frame. Inspect:

1. `frame_index.jsonl`
2. `failure_frame_summary.json`
3. `failed_frames/`

Then choose exactly one constrained next experiment: detector parameter,
camera/marker setup, or an independently calibrated 1920x1080 profile.
