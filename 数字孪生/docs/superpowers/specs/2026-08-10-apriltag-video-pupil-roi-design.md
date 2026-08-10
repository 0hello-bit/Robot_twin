# AprilTag Video Retention and Pupil ROI Design

## Goal

Retain the exact 1080p frame stream used by the synchronized capture session,
and add a file-only Pupil AprilTag ROI candidate that can be replayed against
the same video without changing the production detector.

## Constraints

- The production `PoseTracker` and `production` observation profile remain
  unchanged.
- The capture path keeps one camera, one TCP client, and one START/STOP
  lifecycle. Video writing consumes the frames already returned by `cap.read()`.
- Video retention is evidence only. A valid video, a synchronization PASS, or
  a candidate replay cannot by itself make B3 pass.
- Pupil candidate output is labelled `INSUFFICIENT_EVIDENCE` until a complete
  matched motion video satisfies detection ratio >= 0.95, maximum pose gap <= 2
  frames, and detector p95 <= 33.333333 ms.
- Predicted or tracked poses are not counted as AprilTag decodes.
- Existing evidence files are never overwritten.

## Design

The synchronized capture session creates `camera.avi` in the unique run
directory using the actual validated camera dimensions, 30 FPS, and MJPG. Each
successful frame is written exactly once before detection. The writer is
released in the same cleanup path as the socket and camera. The session writes
`video_evidence.json` and includes the same evidence in `sync_report.json`,
including frame count, dimensions, FourCC, file size, and SHA-256 when the file
is complete.

The replay tool accepts the existing OpenCV candidates plus the special
`pupil_roi` candidate. Pupil uses `tag36h11`, target ID 0, `quad_decimate=1.5`,
four worker threads, the production ROI geometry, and a bounded full-frame
reacquisition fallback. It reports the ROI/fallback search mode and timing in
the existing trace shape. It does not import or modify firmware behavior and
does not call the production tracker detector; the production tracker is used
only for the already-defined calibration projection contract.

## Failure handling

- If the video writer cannot be opened, the session fails before START and
  closes the socket and camera without claiming a run.
- If a frame cannot be written, the session records `video_write_failed`, still
  performs STOP when START was sent, releases all resources, and publishes the
  failure report.
- If `pupil_apriltags` is unavailable, the offline candidate fails explicitly
  in its report; OpenCV baseline replay remains usable.

## Verification

- Unit tests cover video-writer lifecycle, frame write count, candidate
  validation, baseline preservation, and Pupil candidate report fields.
- Existing replay tests, full Python tests, `compileall`, and `git diff --check`
  must pass.
- The old retained 1080p video is used for an offline candidate screen only.
  No production change or hardware authorization follows from that screen.
