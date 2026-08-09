# 2026-08-09 1080p offline camera and ground-target audit

Status: `OFFLINE_READY_HARDWARE_COLLECTION_BLOCKED_UNTIL_AUTHORIZATION`

## Scope

This audit changed only offline camera tools, camera-contract validation, and
documentation. It did not open a camera, start a socket, send START/STOP,
flash firmware, or move the car.

## Verified changes

- Active camera defaults are `1920x1080`, `MJPG`, and `30 FPS` through the
  shared camera module. The interactive capture helpers no longer contain
  720p defaults.
- `ground_shakedown.py` now records and validates the active 1080p frame size;
  its tests use 1920x1080 metadata.
- The existing physical ground board is represented separately as
  `GROUND_CHECKERBOARD_SQUARE_MM=15.0` and `GROUND_CHECKERBOARD_ACTIVE_SIZE_MM`
  of `120x75 mm`.
- `tile_auto_align.py`, `tile_placement.py`, `mosaic_homography.py`,
  `homography_holdout_eval.py`, and `perpendicularity_preview.py` use the
  15 mm ground scale. The existing 25 mm A4 generator remains separate.

## Evidence boundary

- `VERIFIED`: offline source audit, targeted regression tests, and absence of
  active 720p defaults in the camera and shakedown tool directories.
- `INFERENCE`: the 15 mm board can supply a valid ground homography if it is
  rigid, flat, fully visible, and measured consistently.
- `INSUFFICIENT EVIDENCE`: any new 1080p physical capture, ground homography
  pass, AprilTag observation pass, synchronized B3 run, or robot motion.

## Next authorized interface

1. Fix the 15 mm checkerboard to a rigid backing and place it flat on the
   track plane, fully inside the C960 view.
2. Run the camera-only ground-homography collection tool and retain a new
   output directory; do not overwrite historical 720p or handheld evidence.
3. Promote a 1080p calibration manifest only after intrinsics and ground
   homography checks pass independently.
4. Only then request authorization for a bounded B3 synchronized car run.
