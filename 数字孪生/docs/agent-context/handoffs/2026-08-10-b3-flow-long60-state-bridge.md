# B3 offline long temporal state bridge handoff

Date: 2026-08-10
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_STATE_CANDIDATE_VERIFIED; B3_OBSERVATION_NOT_PASSED`

## Boundary

This iteration was file-only. It did not open the camera, connect TCP, flash
firmware, send START/STOP, reset the STM32, or move the vehicle. No new video
was collected. The retained videos and raw evidence remain unchanged.

## Implementation

`tools/camera_toolchain/apriltag_video_replay.py` now exposes the explicit
offline-only temporal profile `flow_long60`:

- `none` remains the default;
- `flow_short2` remains bounded at two prediction frames;
- `flow_long60` allows at most 60 consecutive optical-flow prediction frames;
- predicted poses remain labelled `flow_prediction` and are never counted as
  AprilTag decodes;
- the replay report keeps `tag_decode_ratio` and `pose_output_ratio` separate.

Focused tests: `17 passed` for the replay and temporal-observation modules.

## Primary replay

- Video: `simulation/digital_twin/logs/v1_ground_shakedown_260810143237802/camera.mkv`
- SHA-256: `a6d422d8dc8685673e0b6b490a14a05e544f2e9ceaf79f4e06d8affeddaec140`
- Format: 1920x1080, MJPG, 30 FPS, 655 frames
- Report: `docs/evidence/v1_b3_flow_long60_replay_20260810/report.json`

| Candidate | Tag decode | Pose output | Tag gap | Pose gap | Predictions | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| production | 68.85% | 68.85% | 61 | 61 | 0 | 80.34 ms |
| fast_recovery_wide | 88.70% | 88.70% | 52 | 52 | 0 | 82.15 ms |
| flow_long60 | 88.70% | 100.00% | 52 | 1 | 74 | 92.79 ms |

`flow_long60` is therefore a useful state-output candidate but is
`NOT_JUSTIFIED` for the fixed B3 AprilTag observation gate. It does not
increase true tag decoding and its current detector-every-frame implementation
does not meet the 33.333333 ms p95 budget.

## Existing 1080p holdout

On the retained 137-frame video
`simulation/digital_twin/logs/v1_ground_shakedown_260809202759215/camera.mkv`,
`flow_long60` raised pose output from 94.89% to 100.00%, reduced the pose gap
from 3 to 1 frame, and produced 7 predictions with 6 re-acquisitions. Its tag
decode ratio remained 94.89%; the candidate remains outside the B3 gate.

## Other offline alternatives screened

On the primary 655-frame video, the best non-temporal OpenCV branch was
`fast_recovery_wide` at 88.70% with a 52-frame gap. `adaptive_wide` reached
85.04% with 106.45 ms p95; `subpix`, `contour`, and `perimeter_relaxed` were
lower or slower. The independent `pupil_roi` branch reached 70.53% with
53.37 ms p95. None qualifies for hardware.

## Evidence classification

- `VERIFIED`: long temporal prediction improves pose-output continuity on the
  primary video and an existing 1080p holdout.
- `VERIFIED`: predictions are not tag decodes; the fixed B3 observation gate
  remains failed.
- `VERIFIED`: the primary missed interval coincides with retained crops where
  a dark vehicle component crosses the roof tag's upper/code area.
- `INFERENCE`: the visibility/occlusion condition is the dominant blocker;
  exact contributions from print quality, perspective, exposure, and rolling
  shutter remain unisolated.
- `INSUFFICIENT_EVIDENCE`: real-time performance, physical pose accuracy,
  IMU/flow fusion accuracy, and any real-car improvement.

## Required next behavior

After any future candidate failure, replay the same input and existing 1080p
holdouts before considering new data. Do not count predictions as decodes and
do not relax the B3 thresholds. A genuinely new capture is justified only
after an intentional external change makes the tag visible; that is a new
matched experiment, not a replacement for an ordinary failed algorithm run.
