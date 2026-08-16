# Camera Capture and Analysis Decoupling

**Date:** 2026-08-17
**Status:** Design approved in conversation; awaiting written-spec review
**Scope:** `tools/camera_toolchain/capture_sync_run.py`

## Problem

The 20-second TCP-only synchronized run wrote 280 video frames. The
`frame_index.jsonl` timestamps span 19.96 seconds, so the run did not stop
early. The capture loop processed about 14 frames per second because it reads
a frame, writes it, and then runs AprilTag detection synchronously before it
can read the next frame. AprilTag detection averaged 53.3 ms and reached
93.5 ms at p95, while a 30 fps camera has only 33.3 ms per frame.

The AVI writer is configured for 30 fps, so 280 frames play back as 9.33
seconds. That playback duration is not a valid substitute for the per-frame
PC timestamps used by synchronization.

## Goals

1. Keep the control session and the 20-second STOP deadline in the existing
   owner thread.
2. Write every successfully read camera frame before any AprilTag analysis.
3. Move AprilTag detection to a bounded worker queue so slow analysis cannot
   block camera reads, video writes, heartbeat handling, or STOP timing.
4. Preserve per-frame PC timestamps and make analysis drops explicit in
   `frame_index.jsonl`.
5. Preserve the existing raw evidence files, cleanup behavior, and TCP-only
   protocol boundary.
6. Keep the change testable without connecting to the real car or camera.

## Non-goals

- Do not change firmware, transport, START/STOP wire messages, or heartbeat
  policy.
- Do not interpolate or duplicate frames to manufacture a 30 fps evidence
  stream.
- Do not claim that the camera hardware delivered every physical sensor frame;
  the software can only prove frames read and written by the capture path.
- Do not change calibration quality or improve AprilTag accuracy in this
  change.
- Do not run a new hardware experiment as part of implementation.

## Chosen Design

Keep `run_sync_capture_session()` as the control and camera-capture owner, and
add one bounded analysis worker inside the session:

```text
control/session thread
  heartbeat + deadline + STOP
  cap.read -> timestamp -> video_writer.write
          \-> bounded analysis queue -> analysis worker -> result queue
                                      AprilTag tracker
```

The control/session thread will:

1. Read a frame and record the PC timestamp immediately at the camera-read
   boundary.
2. Validate its dimensions.
3. Write the frame to the AVI before enqueueing analysis work.
4. Enqueue an immutable analysis item containing the frame, frame index, and
   capture timestamp when capacity is available.
5. Mark the frame as `analysis_dropped` when the queue is full. The frame is
   still retained in the video and frame index.
6. Drain completed analysis results without blocking.
7. Continue its existing heartbeat and deadline handling. At the deadline it
   sends STOP through the existing cleanup path without waiting for the
   analysis worker to finish.

The analysis worker will:

1. Consume queued frames in capture order.
2. Run `track_with_diagnostics()` or `track()` using the original capture
   timestamp.
3. Return the pose, detector diagnostics, frame index, and analysis status in
   a result queue.
4. Never send network commands or mutate session cleanup state.

After STOP, the session will signal the worker, wait only the existing bounded
join interval, mark unresolved queued items as `analysis_incomplete`, and
release the camera and writer exactly once. Pose records will be ordered by
capture timestamp before synchronization fitting.

## Evidence Contract

Existing fields remain intact. `frame_index.jsonl` gains only explicit
analysis-state fields:

- `analysis_status`: `queued`, `processed`, `dropped`, or `incomplete`.
- `analysis_dropped`: boolean, true only when the bounded queue was full.
- `analysis_error`: serialized worker error when analysis fails for that frame.

`video_evidence.frames_written` counts frames successfully handed to the AVI
writer. It must not be derived from pose count or analysis count. A new
diagnostic summary may report total captured, processed, dropped, and
incomplete frames, but it must not upgrade synchronization or physical-motion
evidence.

## Failure and Cleanup Rules

- A camera read or video write failure follows the existing fail-closed session
  outcome and still attempts STOP only when START was sent.
- A full analysis queue is not a capture failure; it is recorded as an
  analysis-data limitation.
- An analysis worker exception is recorded and does not prevent STOP, socket
  close, camera release, or video release.
- The worker is joined with a bounded timeout. The session never waits
  indefinitely for slow detection after STOP.
- No retry starts a second motion session.

## Alternatives Considered

### Inline analysis throttling

Skip analysis on selected frames in the current loop. This is the smallest
change but leaves camera reads and video writes exposed to detector latency,
so it cannot guarantee a stable recording rate.

### Separate FFmpeg recorder process

Use FFmpeg to own the camera and keep the Python process as an analysis client.
This could provide stronger capture throughput, but introduces camera-device
sharing, process lifecycle, and timestamp coordination risks for this narrow
fix.

The bounded analysis worker keeps the existing camera, evidence format, and
control lifecycle while removing the identified blocking edge.

## Verification Plan

Add deterministic tests using a fake camera, fake writer, and deliberately
slow fake tracker:

1. A 30 fps, 20-second fake capture writes approximately 600 frames even when
   analysis is slower than 30 fps.
2. Queue overflow marks analysis drops but does not reduce
   `frames_written`.
3. Completed poses retain their original capture timestamps.
4. Worker exceptions still produce STOP/close/release cleanup state in the
   session harness.
5. Existing capture cleanup, report, causal-clock, and protocol tests remain
   green.

Acceptance is limited to offline behavior and artifact accounting. A new
real-car run requires separate user authorization after the code and tests
are reviewed.
