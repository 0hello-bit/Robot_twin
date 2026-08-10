# B3 R1 Full-Frame Recovery Profile

## Problem

The 2026-08-10 real 1080p run detected AprilTag in only 25/128 frames. The
retained failure thumbnails show that the current full-frame grayscale `2x`
fallback detected 0/4, while a bounded offline grayscale `1x` screen detected
2/4 with a lower p95. This is a candidate signal, not proof of a B3 fix.

## Goal

Expose a versioned observation profile so the unchanged production profile and
the R1 grayscale `1x` full-frame fallback can be run and compared without
duplicating the tracker or silently changing the default behavior.

## Non-goals

- Do not change the default production fallback, ROI geometry, detector
  thresholds, camera mode, calibration, firmware, control logic, or hardware.
- Do not infer continuous detection or B3 readiness from the four thumbnails.
- Do not add a second AprilTag detector, TCP client, or capture lifecycle.
- Do not open a camera or socket during offline tests.

## Design

`capture_sync_run.py` will define two explicit profiles:

- `production`: existing `PoseTracker` behavior with full-frame fallback scale
  `(2.0,)`.
- `r1_gray1x`: identical tracker settings except full-frame fallback scale
  `(1.0,)`.

The CLI accepts `--observation-profile` with `production` as the default. A
small factory creates the tracker from the selected profile. The selected
profile is included in the session's derived synchronization report and the
capture status metadata, so later comparisons can prove which path ran.

The profile is a candidate experiment switch only. It does not select a
candidate based on live results, change ROI state, or make an autonomous
deployment decision.

## Acceptance

- Existing production invocation resolves to `production` and `(2.0,)`.
- `r1_gray1x` resolves to `(1.0,)` and changes no other tracker argument.
- Unknown profiles fail before camera/TCP access.
- Offline tests cover both profile mappings and report metadata.
- Existing test suite remains green.
- No real-run claim is made until a matched A/B capture is explicitly
  authorized and independently analyzed with detection ratio >= `0.95`,
  maximum pose gap <= `2.0` frames, and detector p95 <= `33.333333 ms`.
