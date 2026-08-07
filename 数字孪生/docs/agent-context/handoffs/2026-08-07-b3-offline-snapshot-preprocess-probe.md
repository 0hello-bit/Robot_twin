# B3 offline snapshot detector probe

Date: 2026-08-07
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_CANDIDATE_ONLY`

## Purpose

Use the retained local camera snapshots to separate a possible contrast issue
from a detector-family or calibration issue. This is a replay probe only. It
does not change the production `PoseTracker`, camera settings, calibration,
sync thresholds, firmware, or hardware lifecycle.

## Inputs

The inputs are local probe artifacts, not a new synchronized run:

- `tools/camera_toolchain/live_1280.png` (`1280x720`)
- `tools/camera_toolchain/live_1920.png` (`1920x1080`)
- `tools/camera_toolchain/live_1280_tag_crop.png`
- `tools/camera_toolchain/live_1920_tag_crop.png`

These files remain local and ignored by Git. They are not substitutes for
failed-frame artifacts from `c260807144501519`.

## Offline observations

- The current `APRILTAG_36h11` detector returned no ID on the raw 1280 and
  1920 snapshots. The diagnostic reason was `candidates_rejected`.
- The same detector also failed on the saved tag crops at their original
  contrast. Testing all available OpenCV AprilTag and common ArUco dictionaries
  did not produce an ID on those raw crops.
- A targeted ROI around the visible tag decoded ID `0` with
  `APRILTAG_36h11` after global histogram equalization. On the full 1280 and
  1920 snapshots, global equalization followed by the existing 2x probe also
  decoded ID `0`.
- The current three-scale production probe costs roughly 62 ms on the 1280
  snapshot and 115 ms on the 1920 snapshot in this machine-local replay. A
  preprocessing candidate that decodes a frame is not automatically suitable
  for a 30 fps moving capture.
- CLAHE did not decode the full snapshots in the same probe. This is a reason
  to keep the next production change as a single explicit alternative, not to
  stack preprocessing methods.

## Evidence classification

### VERIFIED

- The current offline detector can decode the visible tag in these local
  snapshots after one bounded preprocessing candidate: global histogram
  equalization plus the existing 2x detector attempt.
- The production tracker remains unchanged and the Python regression remains
  `708 passed, 5 skipped`; compileall and `git diff --check` pass.

### INFERENCE

- Low local contrast or illumination may contribute to the observed
  `candidates_rejected` result. This is a hypothesis about the snapshots, not a
  root-cause attribution for the moving run.

### INSUFFICIENT EVIDENCE

- No conclusion about the 172 failed frames in
  `c260807144501519` is possible because that run has no retained image for
  those failures.
- This probe does not establish continuous detection, synchronization quality,
  vehicle motion, digital-twin calibration, or a real-car improvement.
- It does not justify changing the production detector or accepting a 30 fps
  processing budget.

## Next constrained experiment

After explicit authorization, run the existing synchronized capture once so
that `failed_frames/`, `frame_index.jsonl`, and
`failure_frame_summary.json` are populated. Replay the same retained images
through exactly two branches:

1. current production detector;
2. global equalization plus 2x detection as one candidate change.

Compare decoded-frame ratio, failure reasons, longest pose gap, and per-frame
processing time on the identical images. Promote the candidate only if the
real run also improves detection continuity without violating the existing
sync and safety gates.

