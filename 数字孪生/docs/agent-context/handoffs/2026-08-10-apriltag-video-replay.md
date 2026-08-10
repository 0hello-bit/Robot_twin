# B3 Handoff: 1080p AprilTag Video Replay

Date: 2026-08-10
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_REPLAY_COMPLETE; HARDWARE_NOT_AUTHORIZED`

## Scope

This handoff covers one explicitly authorized 20 second ground capture and a
read-only offline replay of its retained raw video. No firmware was changed or
flashed during this task. The replay did not open a camera, connect TCP, send
START/STOP, or control the car.

## Capture evidence

Run directory:

`simulation/digital_twin/logs/v1_ground_shakedown_260810143237802`

Run ID: `g260810143237802`

The canonical ground shakedown returned `SHAKEDOWN_PASS`, with STOP confirmed
and cleanup completed. This is lifecycle/control evidence only; it is not a B3
observation or synchronization pass.

Video:

`simulation/digital_twin/logs/v1_ground_shakedown_260810143237802/camera.mkv`

- codec/FourCC: MJPG
- decoded format: 1920x1080 at 30 fps
- decoded frames: 655
- duration reported by ffprobe: 21.836 s, including capture lifecycle margins
- SHA-256: `A6D422D8DC8685673E0B6B490A14A05E544F2E9CEAF79F4E06D8AFFEDDAEC140`

## Replay evidence

Report:

`docs/evidence/v1_b3_1080p_video_replay_20260810/report.json`

The report uses the exploratory 1080p calibration manifest and records its
manifest, intrinsics, and relative-plane profile hashes. Its timebase is
explicitly `DERIVED_FROM_VIDEO_FPS`; it contains no synchronization verdict.

Each of the six candidate traces is beside the report and contains exactly
655 frame records. The comparison is valid because every candidate used the
same video hash and decoded the same number of frames.

| candidate | profile | parameter | detections | ratio | max gap | max missed | p95 ms |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| production | production | default | 451/655 | 68.85% | 61 | 60 | 95.62 |
| subpix | production | subpix | 453/655 | 69.16% | 59 | 58 | 96.36 |
| contour | production | contour | 457/655 | 69.77% | 56 | 55 | 95.86 |
| adaptive_wide | production | adaptive_wide | 557/655 | 85.04% | 55 | 54 | 139.24 |
| perimeter_relaxed | production | perimeter_relaxed | 451/655 | 68.85% | 61 | 60 | 206.43 |
| r1_gray1x | r1_gray1x | default | 458/655 | 69.92% | 57 | 56 | 71.13 |

## Decision

`selection.verdict = NOT_JUSTIFIED`.

`adaptive_wide` is a verified improvement on this one recorded sequence in
detection ratio and maximum gap, but its processing p95 is 139.24 ms. It fails
the fixed candidate rule and cannot be deployed or sent to a real A/B test.
All candidates fail the B3 observation thresholds of detection ratio >= 0.95,
maximum gap <= 2.0 frames, and processing p95 <= 33.333333 ms.

## Evidence boundary

### VERIFIED

- The new input is an actual 1920x1080/MJPG/30fps decoded video.
- All six candidates were run over the same 655-frame file and produced
  complete per-frame traces.
- The production tracker and the bounded detector parameter/profile candidates
  ran without replay errors.
- `adaptive_wide` improves this sequence's detection ratio from 68.85% to
  85.04%, but violates the processing budget and remains below 95%.

### INFERENCE

- The adaptive threshold widens recovery on this sequence, but the high p95
  indicates that this candidate is computationally unsuitable for the current
  tracker path.
- The long missed runs are consistent with a continuity/localization problem
  during the motion sequence, but this replay alone does not identify whether
  the cause is stale ROI, blur, lighting, tag geometry, or a combination.

### INSUFFICIENT EVIDENCE

- No candidate is qualified for a real A/B test.
- This replay cannot prove clock synchronization, absolute calibration accuracy,
  B3 readiness, real-car improvement, or generalization to another run.
- The exploratory calibration manifest remains relative-only and does not prove
  digital-twin absolute accuracy.

## Verification

- Focused replay and tracker tests: `22 passed`
- Full Python regression: `784 passed, 5 skipped`
- Python compileall for `simulation/digital_twin` and `tools`: exit 0
- `git diff --check`: exit 0; only existing line-ending warnings were emitted

## Next interface

Keep production, firmware, hardware, and communication unchanged. Because the
offline selection is `NOT_JUSTIFIED`, do not request a real A/B for these
candidates. The next step is a new offline candidate focused on recovery or
ROI continuity, evaluated against this full replay protocol or another newly
retained 1080p motion sequence. Any future real A/B requires a separate explicit
authorization after an offline candidate satisfies every fixed threshold.

## Follow-up root-cause separation

Date: 2026-08-10

The follow-up analysis is recorded in:

`docs/evidence/v1_b3_1080p_root_cause_analysis_20260810/report.json`

The new experiments were offline and in-memory only. They did not modify the
tracker or its default profile.

Verified findings:

- Production has 204 rejected frames, all in `roi_then_full` with an ROI.
- At frame 566, the retained production ROI is `[376, 178, 614, 416]`, while
  a stateless default 1x detector locates the target near `[268.25, 515.75]`.
  The default full-frame 2x detector produces a square-like rejected candidate
  near the same target (`rectangularity=0.962`, `side_ratio=1.076`) but does
  not decode it.
- Stateless full-frame default detection is only 368/655 at 1x and 269/655 at
  2x. A stateless adaptive 2x branch is 425/655. The 510-565 interval remains
  a 56-frame gap for these full-frame controls.
- Adding full-frame 1x before the existing 2x in memory gives 458/655 and a
  56-frame gap. A short-term predicted ROI gives 460/655 and the same 56-frame
  gap. Neither candidate is justified.
- On sampled frames 500, 510, 520, 530, 540, 550, 560, and 565, the best
  tested branch detects only 2/8 and has p95 above 164 ms; frames 520-565 are
  missed by all tested branches.

Evidence classification:

- `VERIFIED`: stale ROI contributes to reacquisition failure, and the 2x
  fallback is not a reliable recovery scale on this sequence.
- `VERIFIED`: the long second gap is not explained by ROI alone; the retained
  images contain a detector/scene failure across the tested branches.
- `INFERENCE`: motion blur, tag orientation/quiet-zone quality, exposure, and
  rolling-shutter effects may contribute, but this data does not isolate them.
- `INSUFFICIENT EVIDENCE`: no production change, real A/B, B3 pass, or camera
  hardware diagnosis is justified.

Next interface: perform a separate offline image-quality/temporal-tracking
experiment with retained per-frame diagnostics. Keep production unchanged and
do not request hardware authorization until a candidate satisfies the fixed
B3 gates.
