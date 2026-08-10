# AprilTag Fast Recovery Design

## Goal

Add one offline-only `fast_recovery` observation candidate that reduces the
failure-frame processing cost while preserving the production tracker as the
mandatory baseline. Evaluate it on the retained 1080p video before any real
hardware use.

## Fixed acceptance contract

The candidate is eligible for a later real A/B only when the same-video replay
shows all of the following:

- AprilTag decode ratio >= 0.95;
- maximum decoded-frame interval <= 2 frames;
- detector processing p95 <= 33.333333 ms;
- no replay errors.

Flow or other predicted poses are separate observations and never count as
AprilTag decodes.

## Non-goals and boundaries

- `production/default` behavior remains unchanged.
- No firmware, TCP protocol, camera configuration, calibration asset, or
  hardware action changes.
- The replay remains file-only and uses one fresh tracker per candidate.
- Existing reports and traces are never overwritten.
- A better result on one video is candidate evidence, not proof of B3 or a
  real-car improvement.

## Design

The existing `PoseTracker` receives an explicit recovery policy. The default
policy reproduces the current behavior exactly. The new `fast_recovery` policy
is selected only by the offline replay candidate and uses:

- the initial full-frame bootstrap scales `(1.0, 2.0, 3.0)`;
- one raw ROI detection scale `(1.0,)` after a prior successful decode;
- one blue-channel CLAHE ROI preprocessing branch at scale `(1.0,)` after a
  raw ROI miss;
- one full-frame reacquisition scale `(1.0,)` after the bounded ROI attempts;
- a cached CLAHE object so repeated failure frames do not recreate it.

The policy is represented by immutable configuration data passed to the
existing tracker factory. It does not create a second tracker implementation
or change the production defaults. Diagnostics expose the selected recovery
policy, attempted scales, search regions, and preprocessing mode so each
trace can be audited.

The replay candidate name is `fast_recovery`, with
`observation_profile="production"`, `parameter_variant="fast_recovery"`,
and the existing `temporal_observation="none"`. The candidate is included in
the existing comparison report and must be compared against a fresh
`production/default` run on the same video hash and decoded frame count.

## Failure handling

- Unknown recovery policies fail before a video is opened.
- Invalid scale or preprocessing configuration raises a configuration error.
- A detection miss returns the existing structured failure diagnostics; it
  never becomes a successful decode.
- If the optional CLAHE operation fails, the trace records the error and the
  candidate remains ineligible.

## Tests

Tests must prove:

1. The production policy retains its current full-frame and preprocessing
   behavior.
2. `fast_recovery` changes only the explicitly selected recovery branches.
3. The fast candidate is accepted by replay validation and keeps the
   production baseline requirement.
4. The cached preprocessing path is reused and still returns the expected
   diagnostics on a synthetic ROI miss.
5. Existing tracker, replay, and capture tests remain green.

## Verification sequence

1. Run the new focused tests and observe the expected RED result before the
   implementation.
2. Implement the smallest policy/configuration change.
3. Run focused tests, the full Python regression, compileall, and diff check.
4. Replay `simulation/digital_twin/logs/c260810100004052/camera.avi` with a
   fresh production baseline and `fast_recovery`, preserving separate traces.
5. Report detection ratio, maximum interval, maximum consecutive misses,
   processing p95, video hash, and the fixed candidate decision.

