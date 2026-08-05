# Task 4B-6 Codex Handoff

Date: 2026-08-05

## Status

`SOFTWARE_ONLY_SKELETON_PASS / REAL_DATA_INSUFFICIENT_EVIDENCE`

This is the next offline increment after the accepted 4B-5 controller and
virtual sensor.  It is intentionally below the formal 4B-7 model-freeze and
4B-8 READY gates.

## Delivered Files

- `simulation/digital_twin/v1_twin/v1_twin_plant.py`
- `simulation/digital_twin/v1_twin/v1_twin_identification.py`
- `simulation/digital_twin/tests/test_v1_twin_plant.py`
- `simulation/digital_twin/tests/test_v1_twin_identification.py`
- `.embeddedskills/build/v1_task4b6/task4b6_offline_acceptance.md`

## What Is Implemented

- Four signed M1..M4 PWM channels map through an explicit, auditable
  exploratory mecanum matrix to `vx_mm_s`, `vy_mm_s`, and `omega_rad_s`.
- The low-parameter model contains shared wheel gains, body velocity bias,
  signed per-wheel deadzones, and integer command delay.
- `predict()` integrates body velocity into metric simulated poses.
- `V1Identification` fits the seven linear coefficients, reports rank,
  column-normalized condition number, Fisher eigenvalues, and PWM coverage.
- Timestamped sync frames can be converted to body velocity; missing yaw is a
  hard error, not a fabricated value.
- Real-data fits remain `INSUFFICIENT_EVIDENCE`; no parameter-freeze API is
  provided by this task.

## Independent Verification

- Focused 4B-6 tests: `13 passed`.
- Full `simulation/digital_twin/tests`: `546 passed`.
- New-module `py_compile`: exit code `0`.
- No camera, TCP, serial, flash, reset, or motor action was performed.

Full report: `.embeddedskills/build/v1_task4b6/task4b6_offline_acceptance.md`.

## Important Limits

The wheel-order/sign matrix is an explicit exploratory assumption, not a
physical validation.  The synthetic recovery result proves only that the
implementation can recover its own known fixture.  There is no fresh
authorized synchronized car dataset in this handoff, and the existing project
ledger still blocks 4B-6 real acceptance on upstream 4B-4 and mapping gates.

## Next Owner / Interface

Once hardware is authorized under the existing safety runbook, preserve every
baseline/probe run and pass `SynchronizedRunDataset.sync_frames` to
`V1Identification.from_sync_frames()`.  A later 4B-7 task must perform the
calibration/holdout split and freeze evidence; do not use this handoff as a
formal model or as a 4B-8 READY declaration.
