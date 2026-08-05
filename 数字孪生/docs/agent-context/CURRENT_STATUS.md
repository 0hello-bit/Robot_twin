# Robot Twin AI - Current Status

Snapshot: 2026-08-05
Canonical workspace: stm32小车/数字孪生

This file is the current authoritative status for the active workspace.
Historical status is preserved in CURRENT_STATUS_LEGACY_20260803.md and must
not override this file.

## V1-A Offline Foundation

Status: ACCEPTED_OFFLINE_ONLY

The following software path is verified:

initial pose + track map + PID candidate -> controller -> plant -> virtual sensor -> next pose

The candidate evaluator runs a baseline plus at least two candidates on one
frozen model and ranks candidates with these rules:

1. completed and no line loss is the only eligible tier;
2. eligible candidates are ordered by predicted completion time;
3. candidate ID is the deterministic tie-breaker;
4. no eligible candidate may be selected or reported READY.

Fresh verification from the canonical portable workspace after the final gate fix:

- V1 closed-loop, evaluator, calibration, and model-registry tests: 74 passed;
- complete simulation/digital_twin/tests: 603 passed, 5 skipped;
- cross-language protocol and C960 route-contract tests: 17 passed, 5 skipped;
- Python 3.11 compileall for simulation/digital_twin and tools: exit 0.

The skipped tests require the excluded real track image and homography assets;
they are not test failures.

## Evidence Boundary

### VERIFIED

- Controller, plant, virtual sensor, predictor, and evaluator are connected in
  one deterministic offline path.
- Different PID candidates can produce different predicted outcomes.
- A line-loss candidate is ranked below completed/no-loss candidates.
- Repeating identical inputs produces identical serialized output.
- Missing or overlapping calibration/holdout IDs cannot report real readiness.
- The evaluator cannot select a candidate when none completes without line
  loss. This was added after independent review found the missing gate.

### INFERENCE

- The exploratory plant wiring is numerically coherent enough for software
  regression and candidate comparison.
- The current controller/plant/sensor combination may be useful as the first
  calibration target.

### INSUFFICIENT EVIDENCE

- No real synchronized calibration fit has been supplied.
- No independent real holdout validation has been supplied.
- PWM-to-velocity, turn response, camera-to-ground mapping, and encoder-like
  speed are not verified by this V1-A task.
- No real-car B/C comparison has occurred.
- No AI-generated core algorithm patch or PCB has been validated.

## Current Next Interface

The next task is V1-B. Its detailed plan is
`docs/superpowers/plans/2026-08-05-v1-b-real-calibration-holdout.md`.
The first agent task is offline-only: define the data contract, acceptance
profile, validator and preflight. Only after Codex independently accepts B1 and
the user gives a fresh authorization may the project collect disjoint real
synchronized calibration and holdout runs. Feed verified evidence through the
existing V1Identification and V1ModelRegistry interfaces. Do not declare the
real twin READY from synthetic data.
