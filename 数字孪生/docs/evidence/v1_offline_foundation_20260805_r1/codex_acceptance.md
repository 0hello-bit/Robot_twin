# Codex Independent Acceptance - Offline V1 Foundation

Date: 2026-08-05
Rechecked: 2026-08-05 after portable-workspace migration
Decision: ACCEPTED_OFFLINE_ONLY
Real-twin readiness: INSUFFICIENT_EVIDENCE

## Fresh Verification

All commands used Python 3.11 from the canonical portable workspace:

- V1 closed-loop, evaluator, calibration, and model-registry tests: 74 passed;
- complete simulation/digital_twin/tests: 603 passed, 5 skipped;
- cross-language protocol and C960 route-contract tests: 17 passed, 5 skipped;
- `compileall` for `simulation/digital_twin` and `tools`: exit 0.

The five skipped tests require the excluded real track image and homography
assets; they are intentionally outside this portable migration package.

## Verified

- v1_twin_closed_loop.py connects the controller, plant, virtual sensor,
  predictor, and candidate evaluator.
- Baseline plus at least two candidates are evaluated on the same frozen
  model inputs.
- Candidate-dependent prediction and deterministic ranking are covered.
- Completed candidates without line loss are the only eligible candidates.
- An evaluator with no eligible candidate cannot select one or report READY.
- Calibration and holdout evidence remain explicitly non-ready without real
  synchronized evidence.

## Review Fix

The initial implementation selected a timeout candidate when every candidate
failed to complete. A regression test reproduced this behavior. The evaluator
was corrected so it retains diagnostic ranking but sets
selected_candidate_id=None, adds an insufficient-evidence reason, and keeps
ready=False when no candidate completes without line loss.

## Not Verified

- No real synchronized calibration or independent holdout data.
- No physical PWM-to-velocity or turn calibration.
- No real-car run, B/C comparison, firmware flashing, or motor operation.
- No AI-generated core algorithm or PCB candidate.

This acceptance approves the software-only V1-A boundary only. It does not
authorize hardware activity and does not declare the real digital twin ready.
