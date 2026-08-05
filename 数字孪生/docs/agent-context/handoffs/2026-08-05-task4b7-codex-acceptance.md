# Task 4B-7 Codex Handoff

Date: 2026-08-05

## Status

`SOFTWARE_ONLY_SKELETON_PASS / REAL_DATA_INSUFFICIENT_EVIDENCE`

This handoff covers only the calibration/holdout isolation and model-freeze
mechanism.  It is not a formal behavior-model freeze and cannot advance
4B-8.

## Delivered Files

- `simulation/digital_twin/v1_twin/v1_twin_calibration_set.py`
- `simulation/digital_twin/v1_twin/v1_twin_model_registry.py`
- `simulation/digital_twin/tests/test_v1_twin_calibration_set.py`
- `simulation/digital_twin/tests/test_v1_twin_model_registry.py`
- `.embeddedskills/build/v1_task4b7/task4b7_offline_acceptance.md`

## Verified Behavior

- Calibration IDs are immutable, non-empty, and disjoint from the holdout set.
- Holdout registration fails before a model is frozen.
- Freeze is one-way and records canonical parameters, code hash, stopping
  conditions, calibration IDs, schema version, fit timestamp/metadata, and a
  SHA-256 model fingerprint.
- Reordering equivalent JSON mappings does not invalidate a model.
- Any changed parameter, code identity, or stopping condition invalidates the
  existing holdout qualification and blocks further registration.

## Verification

- Focused 4B-7 tests: `7 passed`.
- The previous 4B-6 suite remains green; no hardware action was performed.
- Full report: `.embeddedskills/build/v1_task4b7/task4b7_offline_acceptance.md`.

## Limits / Next Interface

No real calibration run IDs, fitted model, hyperparameters, or convergence
evidence are present.  The next formal owner must consume preserved real
4B-6 synchronized runs, choose and document the model, freeze it once, and
create a new empty holdout registry before any final holdout collection.
