# AprilTag fast recovery wide replay handoff (r2)

## Boundary

This iteration is offline-only. It used the retained video below and did not
open a camera, connect TCP, flash firmware, move hardware, or change camera
configuration, calibration assets, or production defaults.

## Input evidence

- Video: `simulation/digital_twin/logs/c260810100004052/camera.avi`
- Video mode: 1920x1080 MJPG, 30 fps
- Decoded frames: 219
- SHA-256: `5C3A64340C0E94228192E66B852D377561BF65C9BA32E22C77603C825AFA5C08`
- Calibration manifest: `simulation/digital_twin/data/product/capture_manifests/c960_r3_1080p_exploratory_20260809/manifest.json`

## Candidate results

The production baseline was replayed fresh in the r2 report below. The earlier
reports remain preserved and were not overwritten.

| Candidate | Decode ratio | Max decoded gap | Max missed | p95 | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| production/default | 57.53% | 13 | 12 | 85.494 ms | baseline |
| fast_recovery | 86.30% | 5 | 4 | 30.40 ms | NOT_JUSTIFIED |
| fast_recovery_wide | 99.54% | 2 | 1 | 32.242 ms | QUALIFIED_FOR_ONE_REAL_AB |

The first candidate failure is preserved at
`docs/evidence/v1_b3_fast_recovery_replay_20260810/report.json`.

The wide candidate r2 report and traces are at
`docs/evidence/v1_b3_fast_recovery_wide_replay_20260810_r2/report.json`.

## Wide candidate configuration

- Initial full-frame bootstrap remains `(1.0, 2.0, 3.0)`.
- Recovery ROI scale is `(1.0,)`.
- Recovery preprocessing is blue-channel CLAHE at `(1.0,)`.
- Full-frame recovery scale is `(1.0,)`.
- CLAHE is cached.
- ROI padding is 96 px.
- Replay detector parameters use `adaptiveThreshWinSizeMax=53`,
  `adaptiveThreshWinSizeStep=5`, and `adaptiveThreshConstant=3.0`.

The production tracker remains the default configuration. The wide candidate
is selected only by the offline replay parameter variant
`fast_recovery_wide`.

## Process safeguards

- Real capture does not create `camera.avi` by default. Video retention is an
  explicit `--record-video` opt-in so an experiment cannot silently create a
  second evidence stream.
- Replay records `replay_complete=false` for a truncated prefix and the
  selection gate rejects that candidate, even if its prefix metrics look good.
- Per-frame detector errors are retained in the trace and summarized in
  `summary.errors`; any non-empty error list blocks candidate qualification.
- `fast_recovery` and `fast_recovery_wide` are rejected by the live tracker
  factory by default. A real run requires the explicit pair
  `--recovery-policy <candidate> --allow-experimental-recovery`; production
  remains the default.

## Evidence classification

- VERIFIED: both candidates used the same SHA-256
  `5c3a64340c0e94228192e66b852d377561bf65c9ba32e22c77603c825afa5c08`,
  219 decoded frames, and calibration manifest through the replay tool; the
  wide candidate met all fixed offline selection checks and produced no replay
  errors.
- VERIFIED: the first candidate did not meet the absolute detection and gap
  thresholds, so it was not eligible for hardware.
- INFERENCE: the major improvement comes from retaining a larger motion ROI
  while using a bounded threshold configuration; this is supported by the
  matched offline replay but is not a causal hardware conclusion.
- INSUFFICIENT EVIDENCE: real-time camera performance, real-car pose accuracy,
  physical line-following improvement, firmware compatibility, and any claim
  that the digital twin is calibrated for deployment.

## Next boundary

The wide candidate is eligible for one separately authorized, bounded real A/B
only. A real result must compare the retained baseline against this candidate
on the same track and safety conditions. If the real result fails, return to
offline algorithm analysis using the retained video and evidence; do not
recollect another video merely because the real A/B failed, and do not silently
change multiple variables.
