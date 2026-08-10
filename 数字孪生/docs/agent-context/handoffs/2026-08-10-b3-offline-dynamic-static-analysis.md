# B3 Handoff: Offline Dynamic/Static AprilTag Analysis

Date: 2026-08-10
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_ANALYSIS_COMPLETE; HARDWARE_NOT_AUTHORIZED`

## Scope

The encoder motor is deferred. This handoff covers only the existing 1080p
camera observation path and retained B3 evidence. No camera, TCP socket,
START/STOP command, motor, firmware flash, reset, or hardware resource was
used in this work.

## Evidence

Primary report:

`docs/evidence/v1_b3_offline_dynamic_static_analysis_20260810/report.json`

The report combines the retained observation replay, the four available
dynamic failure thumbnails, and the 100-frame static 1080p detector matrix.

Verified dynamic observation results:

| run_id | camera/pose | detection ratio | max gap (frames) | p95 (ms) | sync | observation |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `c260809100608075` | 166/90 | 54.22% | 34.946622 | 75.54185 | PASS | FAIL |
| `c260809101540981` | 140/68 | 48.57% | 14.522472 | 91.17974 | PASS | FAIL |
| `c260809102554685` | 223/205 | 91.93% | 7.537272 | 67.96016 | FAIL | INSUFFICIENT_EVIDENCE |

All 166 rejected frames were readable frames classified as
`candidates_rejected` and entered the ROI/preprocessing/full-frame fallback
path. The first session saved no failure thumbnails because three encoding
attempts failed. The current offline diagnostic change reports the actual
`cv2.imencode` failure with shape, dtype, and contiguity instead of the old
incorrect `cv2.imwrite` label.

The four retained failure thumbnails do not justify a detector replacement:
OpenCV branches detected at most 1/4, Pupil 1x detected 2/4 but had a
140.93708 ms p95, and Pupil 2x had a 421.752975 ms p95. Static results do not
transfer to this dynamic sample, but the sample is too small to identify the
cause as a threshold defect, blur, occlusion, or ROI error.

## Decision

- Keep the production detector, thresholds, calibration, firmware, and
  control logic unchanged.
- Treat detector algorithm change as `NOT_JUSTIFIED`.
- Treat the failure-frame instrumentation as offline verified and ready for a
  matched real rerun.
- Do not claim B3 pass, calibrated twin accuracy, or real algorithmic
  improvement.

## Verification

- `py -3.11 -m pytest -q simulation/digital_twin/tests/test_capture_sync_cleanup.py simulation/digital_twin/tests/test_apriltag_diagnostic_matrix.py simulation/digital_twin/tests/test_static_apriltag_capture.py`
  -> `47 passed`
- `py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests`
  -> `765 passed, 5 skipped`
- `py -3.11 -m compileall -q simulation/digital_twin tools` -> exit 0
- `git diff --check` -> no whitespace errors

## Next interface

The next step is one matched 1080p real capture with the diagnostic build,
the car and AprilTag fully in view, and retained failure thumbnails. It must
be separately authorized by the user before opening the camera or TCP path.
After that capture, replay the same offline comparison before changing any
detector branch or threshold.

## ROI parameter candidate update

Date: 2026-08-10

The offline ROI candidate benchmark is complete. It did not access the
camera, TCP, firmware, or vehicle.

Changed files for this update:

- `tools/camera_toolchain/apriltag_parameter_matrix.py`
- `simulation/digital_twin/tests/test_apriltag_parameter_matrix.py`
- `docs/evidence/v1_b3_roi_parameter_candidate_screening_20260810/report.json`
- `docs/evidence/v1_b3_roi_parameter_candidate_decision_20260810/report.json`

The new `run_roi_parameter_matrix` function requires an explicit retained ROI
for every image. It reuses the existing OpenCV detector parameter builder,
preprocessing branches, result schema, and percentile summary. It does not
infer an ROI from the candidate result and does not modify `PoseTracker`.

Verified screening results on 100 static frames plus six retained dynamic
failure thumbnails:

| variant | branch | dynamic | dynamic p95 | static | static p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `default` | `opencv_gray_1x` | 0/6 | 6.528 ms | 99/100 | 6.457 ms |
| `default` | `opencv_blue_2x` | 1/6 | 6.816 ms | 92/100 | 8.005 ms |
| `adaptive_wide` | `opencv_gray_1x` | 0/6 | 10.502 ms | 99/100 | 10.169 ms |
| `adaptive_wide` | `opencv_blue_2x` | 4/6 | 12.686 ms | 100/100 | 15.063 ms |

Evidence classification:

- `VERIFIED`: the bounded offline candidate is substantially better than the
  gray ROI control on the six retained thumbnails and remains below the
  33.333333 ms processing budget in this offline sample.
- `INFERENCE`: ROI restriction is likely responsible for the lower cost, but
  the recovery mechanism is a composite of blue-channel preprocessing and
  adaptive-wide parameters.
- `INSUFFICIENT EVIDENCE`: the sample is too small and non-contiguous to prove
  B3 detection continuity, pose-gap limits, or a real-car improvement.

Decision: `production_change=NOT_JUSTIFIED`, `b3_status=FAIL`.

Focused verification:

- `py -3.11 -m pytest -q simulation/digital_twin/tests/test_apriltag_parameter_matrix.py` -> `6 passed`
- `py -3.11 -m pytest -q simulation/digital_twin/tests/test_apriltag_parameter_matrix.py simulation/digital_twin/tests/test_apriltag_diagnostic_matrix.py` -> `12 passed`
- `py -3.11 -m compileall -q tools/camera_toolchain/apriltag_parameter_matrix.py` -> exit 0
- `git diff --check` -> no whitespace errors

Next interface: after explicit hardware authorization, perform one matched
1080p real capture comparing the unchanged production path with the bounded
ROI candidate. Retain the full frame index and failure frames, then apply the
unchanged B3 gates: detection ratio >= 0.95, maximum pose gap <= 2.0 frames,
and detector p95 <= 33.333333 ms. Do not deploy the candidate before that
comparison.

## R1 fallback profile implementation

Date: 2026-08-10

The offline R1 candidate is now exposed through the existing capture entrypoint
without adding a second detector, TCP client, or capture lifecycle:

- `production` keeps `full_frame_fallback_scales=(2.0,)` and remains the CLI
  default.
- `r1_gray1x` changes only the full-frame fallback to `(1.0,)`.
- `--observation-profile` rejects unknown names before camera or TCP setup.
- `sync_report.json` and early session failure reports record the selected
  profile and fallback scales, so production/R1 evidence cannot be silently
  mixed.

Offline candidate evidence remains unchanged: on the four retained failure
thumbnails, gray `1x` detected `2/4` and gray `2x` detected `0/4`. This is
`VERIFIED` as a bounded screening result only; it is not evidence of continuous
real-car detection or B3 readiness.

Fresh verification after implementation:

- `py -3.11 -m pytest -q simulation/digital_twin/tests/test_capture_observation_profile.py simulation/digital_twin/tests/test_capture_sync_cleanup.py`
  -> `44 passed`
- `py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests`
  -> `777 passed, 5 skipped`
- `py -3.11 -m compileall -q simulation/digital_twin tools` -> exit 0
- `git diff --check` -> no whitespace errors

No camera, TCP socket, START/STOP command, firmware flash, motor, or debugger
was used. The next interface is an explicitly authorized matched 1080p A/B
capture under the same calibration, start pose, direction, lighting, and run
duration: production first, then `r1_gray1x`. Analyze each run independently
against detection ratio >= 0.95, maximum pose gap <= 2.0 frames, detector p95
<= 33.333333 ms, and the separate synchronization gate. Do not call R1 an
improvement or B3 pass from the offline screening alone.

## Authorized production vs R1 real A/B

Date: 2026-08-10

The matched 1080p A/B capture was completed with the same calibration manifest,
camera source, 8 second duration, and existing TCP/session lifecycle. No
firmware or hardware was changed.

| profile | run_id | camera frames | poses | detection ratio | max gap (frames) | detector p95 | sync | observation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `production` | `c260810053628761` | 117 | 23 | 19.66% | 158.26 | 84.98 ms | PASS | FAIL |
| `r1_gray1x` | `c260810053724527` | 145 | 42 | 28.97% | 43.83 | 122.65 ms | PASS | FAIL |

Reports:

- `docs/evidence/v1_b3_observation_gate_20260810_1080p_c260810053628761/replay_report.json`
- `docs/evidence/v1_b3_observation_gate_20260810_1080p_c260810053724527/replay_report.json`
- `docs/evidence/v1_b3_ab_failure_detector_matrix_20260810/report.json`
- `docs/evidence/v1_b3_ab_failure_parameter_matrix_20260810/report.json`

Evidence classification:

- `VERIFIED`: both runs used actual `1920x1080/MJPG/30`, matched synchronization
  passed, and cleanup recorded matching STOP plus socket/camera release.
- `VERIFIED`: R1 improved the observed detection ratio and maximum pose gap in
  this matched run, but made detector p95 worse. It is not a deployable B3
  improvement because both profiles fail every observation threshold.
- `VERIFIED`: all 197 failed frames were classified as `candidates_rejected`,
  with no camera read failures. The 8 retained thumbnails contain rejected
  quadrilaterals around 60 px at 1x, but median rectangularity is only about
  0.70-0.79 and median side ratio is about 2, not a stable square tag.
- `VERIFIED`: offline branch screening over the 8 thumbnails found Pupil gray
  1x at 4/8 with about 180 ms p95, OpenCV adaptive-wide blue 2x at 3/8 with
  about 76 ms p95, and OpenCV gray 1x at 1/8 with about 21.5 ms p95. No tested
  branch met both useful recovery and the 33.333333 ms budget.
- `INFERENCE`: the current ROI is stale during fast motion. Among the 4 frames
  that full-frame Pupil could decode, only 1 tag center was inside the retained
  production ROI. The other 3 were outside it, so ROI retries add latency while
  missing the target.
- `INSUFFICIENT EVIDENCE`: the exact contribution of illumination, motion blur,
  tag print quality, and detector geometry cannot be separated from these
  eight retained failure thumbnails.

Decision: keep both production and R1 out of deployment. The next offline
candidate must address stale ROI work before any threshold change; it needs a
focused test and a replayable comparison. A new real run is required only
after that candidate passes offline screening, with explicit authorization.
