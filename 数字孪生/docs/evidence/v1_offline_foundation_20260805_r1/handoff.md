# Offline V1 Digital-Twin Foundation Handoff

Date: 2026-08-05
Status: `OFFLINE_V1_FOUNDATION_COMPLETE`
Real-twin readiness: `INSUFFICIENT_EVIDENCE`

## Scope completed

This task stops at the offline prediction and ranking boundary.  It does not
connect a camera, serial port, TCP, or the car; it does not flash, reset, or
start motors; and it does not modify firmware, UI, MCP, PCB, or later tasks.

The new closed-loop path is:

`initial_pose + track_map + PID candidate -> V1Controller -> V1Plant -> V1VirtualSensor -> next_pose`

The predictor rejects any sampling period other than the firmware's fixed
5 ms loop period.

`V1CandidateEvaluator` runs one baseline plus at least two candidates on the
same initial state, track asset, model version, and seed.  Ranking uses a hard
eligibility tier (`completed` and no line loss) before predicted completion
time, with candidate ID as the deterministic tie-breaker.

## Actual changes

- `simulation/digital_twin/v1_twin/v1_twin_closed_loop.py`
  - `V1PidCandidate`: firmware protocol bounds, units, and parameter version.
  - `V1ClosedLoopPredictor`: controller/plant/virtual-sensor integration,
    line-loss and timeout termination, completion time, predicted speed,
    trace diagnostics, model/asset/seed provenance.
  - `V1CandidateEvaluator`: baseline + two-or-more candidate interface,
    deterministic hard-constraint ranking, explicit prediction failures.
  - `V1CalibrationEvidence`: real synchronized calibration/holdout readiness
    boundary; missing or synthetic evidence never becomes READY.
- `simulation/digital_twin/tests/test_v1_twin_closed_loop.py`
  - end-to-end fixture with baseline A and candidates B/C;
  - candidate-dependent outcomes and ranking repeatability;
  - missing/overlapping calibration evidence remains non-ready;
  - failed prediction is returned explicitly, without guessed metrics.

No existing firmware or historical evidence file was overwritten.

## Verification commands and results

All commands ran from the workspace root with Python 3.11.

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_closed_loop.py
5 passed in 0.30s

py -3.11 -m py_compile simulation/digital_twin/v1_twin/v1_twin_closed_loop.py simulation/digital_twin/tests/test_v1_twin_closed_loop.py
exit 0

py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_closed_loop.py simulation/digital_twin/tests/test_v1_twin_controller.py simulation/digital_twin/tests/test_v1_twin_plant.py simulation/digital_twin/tests/test_v1_twin_virtual_sensor.py simulation/digital_twin/tests/test_v1_twin_runner.py simulation/digital_twin/tests/test_v1_twin_calibration_set.py simulation/digital_twin/tests/test_v1_twin_model_registry.py simulation/digital_twin/tests/test_v1_twin_validator.py
65 passed in 0.77s

py -3.11 -m pytest -q simulation/digital_twin/tests
607 passed in 41.65s
```

The first RED run of the new test was also observed before implementation:
module collection failed with `ModuleNotFoundError` and exit code 1.  The
focused test then turned GREEN at 4/4.

## Evidence boundary

### VERIFIED

- The controller is tested against an independent float32 firmware oracle,
  including derivative/integral/output limits and reset behavior.
- The virtual sensor uses four binary black-line bits, metric sensor offsets,
  the firmware weighted error values, all-black error hold, and explicit line
  loss.
- The plant accepts signed four-channel PWM and emits **predicted** body
  velocity and pose; no encoder value is fabricated.
- The new test drives all three components in one loop and compares three
  candidates on the same model.  The high-speed candidate records a line-loss
  event and is ranked below the two no-loss candidates; the latter are then
  ordered by predicted completion time.  This demonstrates that the twin
  affects ranking and that the hard no-loss constraint is active.
- Repeating the same input produces byte-for-byte equal `to_dict()` output.
- Empty or invalid track input produces `status=FAILED` with a reason rather
  than guessed completion metrics.
- Calibration/holdout run IDs are normalized and overlap is rejected; absent
  real evidence returns `INSUFFICIENT_EVIDENCE`, never `READY`.

### INFERENCE

- The injected plant and its turn scale are an explicit software fixture.  The
  path demonstrates numerical wiring and ranking behavior, not physical
  fidelity.
- Completion time and speed fields are model predictions only.

### INSUFFICIENT_EVIDENCE

- No real synchronized calibration fit or independent holdout measurement was
  supplied for this task.
- Physical PWM-to-velocity/turn parameters, camera-to-ground accuracy,
  encoder-equivalent speed, and real-car completion behavior remain unverified.
- Therefore this handoff does not declare the real digital twin READY and does
  not authorize a hardware run.

## Current interface

```python
evaluation = V1CandidateEvaluator(predictor).evaluate(
    baseline=baseline_a,
    candidates=(candidate_b, candidate_c),
    initial_pose=initial_pose,
    track_map=track_map,
)
```

Use `evaluation.predictions` for diagnostics and `evaluation.ranking` for the
deterministic model-side order.  Treat `evaluation.ready` as false until real
calibration and disjoint holdout evidence is injected.

## Next and only interface

Provide real synchronized calibration and holdout run IDs/measurements through
the existing `V1Identification` and `V1ModelRegistry` interfaces, then feed a
verified `V1CalibrationEvidence(status="VERIFIED", source="REAL_SYNC", ...)`
into a new predictor instance.  That is a later evidence task; this offline
foundation is complete and stops here.
