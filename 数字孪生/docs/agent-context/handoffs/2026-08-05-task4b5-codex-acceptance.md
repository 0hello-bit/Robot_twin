# Task 4B-5 Codex Handoff

Date: 2026-08-05
Status: `SOFTWARE_ONLY_PASS`

## Delivered files

- `simulation/digital_twin/v1_twin/v1_twin_controller.py`
- `simulation/digital_twin/v1_twin/v1_twin_virtual_sensor.py`
- `simulation/digital_twin/tests/test_v1_twin_controller.py`
- `simulation/digital_twin/tests/test_v1_twin_virtual_sensor.py`
- `.embeddedskills/build/v1_task4b5/task4b5_offline_acceptance.md`

The implementation is limited to the plan's 4B-5 allow-list. No firmware,
Keil project, existing v1 production module, camera, transport, or Git state
was changed by this Task.

## Verified behavior

`V1Controller` reproduces the firmware PID core with float32 arithmetic,
derivative/integral limits, turn gain, integer truncation, and output limit.
`validate_against_firmware()` compares a batch against externally supplied
firmware outputs and returns a structured mismatch report.

`V1VirtualSensor` transforms the four configured sensor offsets by `V1Pose`,
tests distance to the metric track centerline, emits firmware black-bit order,
and computes the firmware weighted error. It explicitly reports line loss and
preserves previous error for the all-black case.

## Commands and results

- Focused 4B-5 tests: `14 passed`, exit `0`.
- Full simulation suite: `526 passed`, exit `0`.
- Historical 4B-4 transport regression: `41 passed`, exit `0`.
- Capture/dataset/sync/pose regression: `41 passed`, exit `0`.
- New-module `py_compile`: exit `0`.

Full evidence: `.embeddedskills/build/v1_task4b5/task4b5_offline_acceptance.md`.

## Limits and next interface

This is a software gate only. Sensor offsets and metric line width remain model
inputs, not fresh physical measurements. The controller does not yet model
motor smoothing, curve overrides, or line-loss recovery. 4B-6 is the next
planned implementation, but its acceptance depends on fresh, authorized
real-car synchronized excitation data; until then only its offline skeleton
and synthetic fixtures may be developed, with no claim of model validity.
