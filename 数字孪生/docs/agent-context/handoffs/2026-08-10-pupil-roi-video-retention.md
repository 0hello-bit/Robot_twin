# B3 Handoff: Video Retention and Pupil ROI Screening

Date: 2026-08-10
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_SCREEN_COMPLETE; HARDWARE_NOT_AUTHORIZED`

## Implemented offline changes

- The canonical synchronized capture session can retain the exact readable
  frames already returned by `cap.read()` in `camera.avi`.
- The writer is opened only after camera-mode validation and TCP connection,
  before START is sent. It is released in the existing session cleanup path.
- `video_evidence.json` and `sync_report.json` expose writer status, frame
  count, dimensions, FourCC, file size, and SHA-256 when the file exists.
- Writer open, write, release, and finalization failures are fail-closed and
  still preserve the existing STOP/close/release behavior.
- Replay accepts a file-only `pupil_roi` candidate. It uses Pupil
  `tag36h11`, target ID 0, `quad_decimate=1.5`, four detector threads,
  production ROI geometry first, and at most one full-frame reacquisition.
- `production/default` and the production tracker defaults were not changed.

## Evidence

The matched replay report is:

`docs/evidence/v1_b3_pupil_roi_replay_20260810/report.json`

Source video:

`simulation/digital_twin/logs/v1_ground_shakedown_260810143237802/camera.mkv`

The two candidates decoded the same 655-frame 1920x1080/MJPG/30fps file.

| candidate | detections | ratio | max gap | max missed | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| production/default | 451/655 | 68.85% | 61 | 60 | 112.96 |
| pupil_roi | 462/655 | 70.53% | 58 | 57 | 53.37 |

## Evidence classification

### VERIFIED

- The video writer lifecycle is covered by offline tests and the writer
  failure path still closes the socket and releases the camera.
- Pupil ROI ran on the same retained video and produced complete per-frame
  traces.
- On this sequence Pupil ROI improves detection ratio by about 1.68 percentage
  points, reduces the longest gap from 61 to 58 frames, and is faster than the
  OpenCV production replay.
- The candidate selection verdict is `NOT_JUSTIFIED` because the fixed offline
  rules require at least a 5 percentage point ratio improvement and p95 no
  greater than 33.333333 ms.

### INFERENCE

- Pupil's lower p95 suggests its detector path is computationally cheaper on
  this machine, but the small ratio improvement means the dominant failure is
  not solved by changing detector backend alone.
- The remaining long gaps are consistent with scene/image-quality or
  continuity failures, but this experiment does not isolate blur, exposure,
  tag geometry, or stale localization as the sole cause.

### INSUFFICIENT EVIDENCE

- No candidate is qualified for a real A/B test or production deployment.
- This replay cannot prove camera clock synchronization, absolute calibration
  accuracy, B3 readiness, or real-car improvement.
- No firmware was changed or flashed, and no camera/TCP/hardware action was
  performed during this offline task.

## Next interface

When the user explicitly authorizes a new capture, use the updated canonical
capture entrypoint so the run retains `camera.avi`. Keep the production
baseline and the same calibration manifest in the run. This next capture is an
observation/data-retention run, not permission to deploy `pupil_roi`; any real
A/B requires a later explicit authorization after a candidate satisfies every
fixed offline threshold.
