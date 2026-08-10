# B3 Handoff: Bounded Temporal Observation Replay

Date: 2026-08-10
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_CANDIDATE_SCREENED; HARDWARE_NOT_AUTHORIZED`

## Scope

This task stayed offline. It did not open a camera, connect TCP, send
START/STOP, flash firmware, reset the STM32, or control the vehicle.

## Implementation

The existing `PoseTracker` remains the production default. It now exposes raw
decoded corners through a separate geometry method so an offline observer can
reuse the detector result without running a second detector.

`tools/camera_toolchain/temporal_observation.py` adds the bounded candidate
`flow_short2`:

- a successful AprilTag decode is the only anchor;
- optical flow can predict at most two consecutive frames;
- all four corners, flow error, displacement, convex geometry, and scale
  change must pass checks;
- predicted poses are labelled `flow_prediction` and are not counted as tag
  decodes;
- a later decode records position and yaw correction against the last
  prediction.

The replay summary now separates `tag_decode_ratio` from
`pose_output_ratio`, and records flow quality and reacquisition correction.

## 1080p replay result

Report:

`docs/evidence/v1_b3_temporal_flow_screening_20260810_r3/report.json`

| candidate | tag decode | pose output | max decode gap | max pose gap | p95 | predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| production | 68.85% | 68.85% | 61 frames | 61 frames | 112.44 ms | 0 |
| flow_short2 | 68.85% | 83.97% | 61 frames | 59 frames | 122.11 ms | 99 |

For `flow_short2`, flow error p95 was 7.65 px, position correction p95 was
4.76 mm, and yaw correction p95 was 0.067 rad on re-acquisition. These are
offline replay quantities, not calibrated real-world accuracy claims.

Decision: `NOT_JUSTIFIED`. The candidate improves short-term continuity but
does not improve true AprilTag decoding, does not satisfy the B3 thresholds,
and is not eligible for a real A/B test.

## Root-cause boundary

The retained crop evidence is recorded in:

`docs/evidence/v1_b3_temporal_flow_screening_20260810_r3/occlusion_analysis.json`

Frames 500, 520, 550, and 565 show a dark rigid vehicle component crossing the
upper edge and code area of the roof tag, most strongly during the 510-565
missed interval. Full-frame brightness and Laplacian variance do not show a
global camera failure. This is a verified visual observation; its causal role
is still an inference until a matched run changes tag visibility or mounting.

## Verification

- Focused temporal, replay, and pose-tracker tests: `25 passed`
- Full Python regression and compile checks remain required before handoff.
- No hardware evidence was created by this task.

## Next interface

Stop code-only B3 iteration at this boundary. The next meaningful experiment
requires correcting tag visibility or mounting and retaining a matched 1080p
motion sequence. Only after that offline replay shows all fixed thresholds may
the user authorize a real A/B. Do not flash or deploy `flow_short2`.
