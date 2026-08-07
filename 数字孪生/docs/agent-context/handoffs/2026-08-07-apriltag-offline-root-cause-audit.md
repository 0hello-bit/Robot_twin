# AprilTag Offline Root-Cause Audit Handoff

Date: 2026-08-07 Asia/Shanghai
Status: `CAUSE_NOT_YET_ISOLATED_NO_DETECTOR_FIX_APPLIED`

## Findings

- The retained recording
  `simulation/digital_twin/logs/v1_ground_shakedown_260806154311594/camera.mkv`
  has no visible car or AprilTag in sampled frames. The `0/76` result is not
  a valid target-detection benchmark.
- The current tracker decoded the same target in four other retained 720p
  recordings at `91/91`, `90/91`, `76/76`, and `76/76` frames.
- The C960 was directly probed at `1280x720` and `1920x1080`; both modes
  returned MJPG at 30 fps.
- On separate live static samples, default detection was `19/20` at 720p and
  `18/20` at 1080p. This is not a matched moving comparison.
- A single `wide_adaptive` detector parameter variant reached `20/20` on the
  current static sample and `91/91` on one good retained video, but remained
  `0/76` on the no-car recording. It was not applied to production.

## Interpretation

`candidates_rejected` means OpenCV produced rejected quadrilateral candidates
without decoding a marker ID. It does not prove that the application decoded
the target and then discarded it. The latest moving run remains unresolved:
only 21 of 193 camera frames produced poses, with longest gaps of 2.75 s and
2.547 s, but no images were retained for the failed frames.

## Boundary

No detector threshold, camera resolution, calibration, firmware, or control
change was made in this audit. The existing 1280 calibration remains the only
valid pose projection profile.

## Next interface

Add bounded failed-frame thumbnail retention to the existing synchronized
capture path, then run one authorized session to classify the actual failure
as out-of-view, blur/occlusion, low contrast, or detector rejection. Keep the
current sync gate and TCP/session lifecycle unchanged. Only after that
classification should one constrained detector, camera setup, or 1920x1080
calibration change be proposed.
