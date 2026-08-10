# B3 fast-recovery holdout failure handoff

Date: 2026-08-10
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_CANDIDATE_REJECTED; HARDWARE_NOT_AUTHORIZED`

## Boundary

This iteration used only videos already retained in the workspace. It did not
open the camera, connect TCP, flash firmware, send START/STOP, or move the
vehicle. A candidate failure must return to offline analysis; it must not
trigger a replacement capture.

## Primary holdout

- Video: `simulation/digital_twin/logs/v1_ground_shakedown_260810143237802/camera.mkv`
- SHA-256: `a6d422d8dc8685673e0b6b490a14a05e544f2e9ceaf79f4e06d8affeddaec140`
- Format: 1920x1080, MJPG, 30 FPS, 655 decoded frames
- Replay report: `docs/evidence/v1_b3_fast_recovery_holdout_20260810/report.json`
- Calibration manifest: `c960_r3_1080p_exploratory_20260809`

| Candidate | Detection | Max gap | Max missed | p95 | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| production | 68.85% | 61 frames | 60 | 76.58 ms | baseline |
| fast_recovery_wide | 88.70% | 52 frames | 51 | 70.18 ms | NOT_JUSTIFIED |

The candidate improved the baseline but failed every absolute B3 observation
threshold. It is not eligible for a real A/B.

## Existing 1080p cross-checks

The same production/candidate pair was replayed on four already retained
1080p clips. Candidate detection ratios were 94.89%, 91.50%, 100.00%, and
100.00%, respectively. These mixed results show that the candidate is not a
general solution and that the long 655-frame clip is not safe to ignore.

## Evidence classification

- VERIFIED: the primary replay completed with no detector errors and the
  candidate improved detection ratio, but its 88.70% ratio and 52-frame gap
  fail the fixed B3 thresholds.
- VERIFIED: retained crops around frames 500, 520, 550, and 565 show a dark
  rigid vehicle component crossing the upper edge and code area of the roof
  AprilTag; full-frame brightness and sharpness did not collapse globally.
- INFERENCE: physical tag occlusion is a major contributor to the long miss
  interval. The replay does not isolate occlusion from print quality,
  perspective, exposure, or rolling shutter.
- INSUFFICIENT EVIDENCE: no claim of real-car pose accuracy, real-time
  performance, or B3 pass is justified.

## Required next behavior

1. Keep the retained videos and reports immutable.
2. If a real A/B later fails, diagnose and modify the algorithm offline, then
   replay the same video and existing 1080p holdouts before any new capture.
3. Never count optical-flow or IMU predictions as AprilTag decodes; report
   `pose_output_ratio` separately from `tag_decode_ratio`.
4. Do not relax the B3 thresholds merely to accommodate this candidate.
5. A new capture is justified only if offline evidence proves the input is
   insufficient to answer the question, or if the tag mount/camera/track
   conditions are deliberately changed. That would be a new matched
   experiment, not a response to an ordinary algorithm failure.

## Current conclusion

The current blocker is primarily an observation-visibility limitation, not a
proven detector-loop bug. Code-only recovery can improve continuity while a
tag is visible, but cannot reliably decode pixels physically covered by the
vehicle. Any future temporal bridge must therefore remain a separate state
estimation candidate and must not be presented as an AprilTag observation
pass.
