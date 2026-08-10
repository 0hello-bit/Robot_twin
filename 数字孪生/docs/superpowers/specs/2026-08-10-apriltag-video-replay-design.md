# AprilTag 1080p Video Replay Benchmark

## Problem

The latest real 1080p captures passed the synchronization gate but failed the
AprilTag observation gate. The retained evidence shows low detection ratios,
long detection gaps, and detector latency above the 30 FPS budget. A small
thumbnail matrix is useful for generating hypotheses, but it is not enough to
decide whether a change improves a moving sequence.

The next input will be one newly authorized raw 1080p motion video captured
with the current camera configuration. It must retain the complete frame
sequence and prove `1920x1080 / MJPG / 30 FPS`; a file that only has a
requested 1080p setting but decodes at another size is rejected.

The replay must therefore answer a narrow question:

> On exactly the same newly captured 1080p moving frames, does a bounded AprilTag
> candidate improve the existing stateful tracker without an unacceptable
> processing cost?

It must not answer the broader question “does B3 pass on the current 1080p
camera?” That question still requires a fresh matched real capture with the
unchanged synchronization and observation gates.

## Goal

Add a deterministic, read-only video replay benchmark that runs the unchanged
production tracker and bounded OpenCV parameter candidates on the exact same
decoded frames, records per-frame diagnostics, and produces a comparison
report that can authorize at most one later matched 1080p A/B test.

## Non-goals

- Do not open a camera, connect TCP, send START/STOP, flash firmware, reset the
  board, move the car, or change any hardware.
- Do not change the production observation profile or its default detector
  behavior.
- Do not use offline video replay to claim clock synchronization, calibration
  accuracy, or real-car improvement.
- Do not add a second TCP client, parser, heartbeat loop, session lifecycle,
  storage format, or hardware control path.
- Do not implement velocity prediction, EKF, Pupil/native AprilTag replacement,
  YOLO, encoder support, or stale-ROI prediction in this benchmark.
- Do not choose a candidate from a favorable sub-clip or from thumbnail-only
  evidence.

## Design

### 1. Reuse the existing tracker boundary

`PoseTracker` remains the single stateful detection and ROI implementation.
The only additive tracker change is an optional `detector_parameters` input
used to construct its existing `cv2.aruco.ArucoDetector`. When omitted, the
constructor must create the same OpenCV default parameter object as today.
The production `create_pose_tracker()` path and its default profile remain
byte-for-behavior equivalent.

The parameter object is created by the existing
`tools/camera_toolchain/apriltag_parameter_matrix.py` helper. The replay tool
must not duplicate the parameter variant definitions. The initial candidate
set is exactly:

- `default`: OpenCV defaults, the control;
- `subpix`: `CORNER_REFINE_SUBPIX`;
- `contour`: `CORNER_REFINE_CONTOUR`;
- `adaptive_wide`: adaptive threshold maximum 53;
- `perimeter_relaxed`: minimum marker perimeter rate 0.015.

The existing observation profiles remain available as a separate dimension:

- `production`: full-frame fallback scale `(2.0,)`;
- `r1_gray1x`: full-frame fallback scale `(1.0,)`.

The first benchmark runs `production/default` as the baseline. A candidate
may change only one of the two explicit dimensions in a run. Combining a
fallback-profile change and a detector-parameter change is deferred until
each component has an independent replay result.

### 2. New offline replay module

Create `tools/camera_toolchain/apriltag_video_replay.py` with these public
interfaces:

```python
def replay_video(
    video_path: str | Path,
    *,
    observation_profile: str = "production",
    parameter_variant: str = "default",
    target_id: int = 0,
    max_frames: int | None = None,
) -> dict[str, Any]:
    """Replay one local video through one fresh stateful tracker."""


def compare_video_candidates(
    video_path: str | Path,
    *,
    candidates: Sequence[Mapping[str, str]],
    target_id: int = 0,
    max_frames: int | None = None,
) -> dict[str, Any]:
    """Run every candidate on one video and return a JSON-safe report."""
```

The module is file-only: it accepts a video path and must reject camera-index
style input. It opens the newly retained file with `cv2.VideoCapture`, records
the reported width, height, FPS, FourCC, frame count, decoded frame count, and
SHA-256, and then closes the file before returning. A fresh tracker is created
for every candidate/video pair, so an earlier candidate cannot leave ROI state
in the next candidate.

The replay calls `track_with_diagnostics()` once per decoded frame. Detector
timing starts immediately before that call and ends immediately after it;
video decode time is recorded separately and is not presented as detector
latency. The frame stream is identical across candidates: a decode failure or
different decoded-frame count makes the comparison invalid instead of silently
aligning different samples.

Because the retained video does not contain the original camera capture timestamp,
the replay timebase is explicitly `DERIVED_FROM_VIDEO_FPS`. It is only used to
report frame-index gaps. No replay report may contain a synchronization verdict
or be passed to the real `ClockSync`/B3 synchronization gate.

### 3. Report and trace format

The output report contains:

```json
{
  "schema_version": 1,
  "type": "V1B3AprilTagVideoReplay",
  "source": "1080P_VIDEO_REPLAY",
  "evidence_status": "INSUFFICIENT_EVIDENCE",
  "timebase": "DERIVED_FROM_VIDEO_FPS",
  "videos": [],
  "candidates": [],
  "summaries": [],
  "selection": {
    "verdict": "NOT_JUSTIFIED",
    "reason": "candidate did not meet the offline thresholds"
  }
}
```

Each summary records `video`, `candidate`, `observation_profile`,
`parameter_variant`, `decoded_frame_count`, `detected_count`,
`detection_ratio`, `max_detection_interval_frames`,
`max_consecutive_missed_frames`, `processing_p95_ms`,
`rejected_candidate_total`, `failure_reason_counts`, and `errors`.

Each video/candidate pair also writes an immutable JSONL trace beside the
report. One trace record contains `frame_index`, `detected`,
`detect_elapsed_ns`, `failure_reason`, `rejected_candidate_count`,
`attempted_scales`, `matched_scale`, `search_mode`, `roi_bounds`, and
`tag_side_px` when available. It does not write a second image or session
format. Existing input videos and existing evidence reports are never
modified.

`max_detection_interval_frames` is the largest frame-index difference between
two consecutive successful detections. A pair of detections on adjacent
frames has an interval of `1.0`; a completely missed frame between them has an
interval of `2.0`. `max_consecutive_missed_frames` is reported separately so
that “gap” and “number of missed frames” cannot be confused.

### 4. Offline candidate decision rule

The comparison must include the complete newly captured 1080p video and the
same candidate set. The production/default row is the control for that video.
A candidate is `QUALIFIED_FOR_ONE_REAL_AB` only when all conditions hold:

1. Every candidate run decoded the same number of frames as the baseline.
2. The detection ratio is at least 5 percentage points higher than
   production/default.
3. `max_detection_interval_frames` and
   `max_consecutive_missed_frames` are both no larger than production/default,
   with at least one strictly lower.
4. Processing p95 does not exceed production/default by more than 10% and is
   at or below `33.333333 ms`.

If any condition fails, the report must say `NOT_JUSTIFIED`; it must not choose
the “best-looking” sub-clip or silently relax a condition. Passing this offline
screen proves only a `VERIFIED` comparison on one 1080p recorded sequence and
authorizes preparation of one matched 1080p real A/B. It does not authorize
hardware access, deployment, a generalization claim, or a B3 pass. A single
video is a candidate screen, not a holdout set; the real A/B remains the
decisive test for this iteration.

The real observation contract remains unchanged for the later A/B:

- detection ratio at least `0.95`;
- maximum pose gap at most `2.0` frame periods;
- detector processing p95 at most `33.333333 ms`;
- synchronization gate evaluated independently.

### 5. CLI and evidence safety

The CLI accepts one `--video`, repeated candidate specifications, an
explicit `--output`, and optional `--max-frames`. Candidate specifications use
the form `name:observation_profile:parameter_variant`; for example,
`production:production:default` and `r1_gray1x:r1_gray1x:default`.

The default CLI candidate is only
`production:production:default`; no candidate is silently introduced. The
tool validates all video paths, profiles, variants, and output paths before
opening any video. It refuses an existing report, writes through a unique
temporary file, flushes it, and atomically installs the final report. Trace
paths use the candidate name plus the SHA-256-derived video stem and also
refuse overwrite.

## Verification

Tests are required before implementation is considered complete:

- invalid camera-index input and unknown profile/variant are rejected before
  opening a video;
- a generated small MJPG video is replayed through the real OpenCV detector;
- a fresh tracker is used for each candidate, and candidate state cannot leak
  between runs;
- frame counts, detection counts, missed-frame intervals, failure reasons, and
  p95 timing are calculated from trace records;
- a decode-count mismatch is classified as invalid comparison;
- the candidate rule returns `NOT_JUSTIFIED` for a regression and
  `QUALIFIED_FOR_ONE_REAL_AB` only when every threshold is met;
- existing production tracker and observation-profile tests remain green;
- no test opens a camera, creates a TCP socket, sends a command, or touches
  firmware.

The first evidence run will use the newly authorized 1080p video and write a
new report under `docs/evidence/v1_b3_1080p_video_replay_20260810/`. Its
report must include the exact input hash, verified decoded format, and exact
candidate list. The run is complete only when the evidence is reviewed under the
`VERIFIED`/`INFERENCE`/`INSUFFICIENT EVIDENCE` boundary.

## Explicit next boundary

After the offline report is reviewed, there are only two valid next steps:

- `NOT_JUSTIFIED`: design the next offline candidate, keeping production and
  hardware unchanged;
- `QUALIFIED_FOR_ONE_REAL_AB`: request explicit authorization for one matched
  1080p real A/B, production first and the single qualified candidate second.

No other step may flash, connect, or move the car based on offline replay
alone.
