# Robot Twin AI Current Gate Ledger

Date: 2026-08-05

Status: TASK1_SOFTWARE_PASS; TASK2_SOFTWARE_PASS; HARDWARE_BLOCKED_PENDING_FRESH_AUTHORIZATION

This ledger separates verified facts, software-only results, exploratory
evidence, and unresolved hardware gates. It authorizes no device action.

## Current Position In The V1 Plan

| Area | Current status | What is actually proven | What is not proven / next gate |
|---|---|---|---|
| 4B-1 USB camera Gate 0 | `VERIFIED_COMPLETE` | EMEET C960 600 s at 1280x720/30 fps: 30.0 fps, 4.671% drop, monotonic timestamps, zero invalid frames | Camera identity/index is time-varying and must be renewed before hardware capture |
| 4B-2 C1 route extraction | `SOFTWARE_ONLY_PASS` | Complete C960 track image, `input_cropped=false`, route gates pass, 47 tests passed | A route mask is not a globally accurate physical-coordinate map |
| 4B-2 global metric mapping | `BLOCKED_FORMAL_2MM_GATE` | Raw-pixel exploratory profile was exported with provenance checks | Formal 2 mm gate is `REJECT`; model-class holdout p95 is about 10.6-11.0 mm; runtime chain is not connected |
| 4B-3 pose | `HARDWARE_VERIFIED_STATIC_HISTORICAL` | Historical static AprilTag detection/precision gate passed | Absolute vehicle x/y with tag-height parallax, yaw-to-nose alignment, and dynamic blur on the current setup remain unverified |
| 4B-4 synchronization | `SOFTWARE_ONLY_PASS; HARDWARE_GATE_PENDING` | Task 1 single-owner control, R4 telemetry batching, Task 2 recorder/CLI, and offline regressions are accepted by Codex | Camera-telemetry coverage >=95% and p95 <=33.3 ms have not passed; actual telemetry near 10 Hz is a known risk |
| 4B-5 | `SOFTWARE_ONLY_PASS` | Firmware-equivalent PID core and metric virtual four-sensor model implemented; 526 simulation tests pass | Physical sensor geometry and full motor/line-loss behavior remain unverified; 4B-6 still requires synchronized real excitation data |
| 4B-6 offline scaffold | `SOFTWARE_ONLY_SKELETON_PASS / REAL_DATA_INSUFFICIENT_EVIDENCE` | Four-channel plant, synthetic recovery, identifiability diagnostics, coverage report, and sync-frame velocity extraction; 546 simulation tests pass | No fresh authorized real excitation data; do not freeze parameters or claim 4B-7/4B-8 |
| 4B-7 offline scaffold | `SOFTWARE_ONLY_SKELETON_PASS / REAL_DATA_INSUFFICIENT_EVIDENCE` | Immutable calibration/holdout split and one-way model-freeze registry; 7 focused tests pass | No real calibration data or formal fitted model; 4B-8 remains blocked |
| 4B-8 | `PLANNED / BLOCKED_BY_UPSTREAM_GATES` | No formal completion | Do not claim READY or begin 4C until the dependency gates are met |
| 4C / 5A / 5B | `PLANNED` | No formal completion | 4B-8 READY is a hard prerequisite |

## Supporting Work Completed Offline

### PWM scale repair

Status: `SOFTWARE_ONLY_PASS`

- Accepted `Motor.c` SHA-256:
  `80DEB484B98C5B3D73D5E1CDC8431DFA830DDFA571B86964222CA84B83D07743`
- Accepted AXF SHA-256:
  `088EFD4E1492CC9FE6075BADD7962EEB7D193E9863CACD2BA53FBDA2457C2351`
- The repaired AXF has not been proven flashed to the car and has no physical
  timer/direction/motion validation.

### MPU6050 audit

Status: `STATIC_AUDIT_COMPLETE; HARDWARE_UNVERIFIED`

- Yaw telemetry is relative Z-gyro integration in degrees.
- MPU data is not used by the current PID or motor-control loop.
- Initialization failure is not latched, and telemetry has no validity bit;
  therefore MPU yaw is exploratory only and cannot enter control or acceptance.

### Bounded ground-shakedown tool

Status: `TASK1_SOFTWARE_PASS; TASK2_SOFTWARE_PASS`

- Task 1 single-owner replacement has DS implementation evidence, Codex
  `SPEC_COMPLIANCE: PASS`, `CODE_QUALITY: PASS`, and `17/17` independent fault
  probes on the current source after Task 2 changes.
- Task 2 camera/evidence/deny-by-default CLI implementation has 80 focused
  tests, 170 combined regressions, 554 full simulation tests, clean
  compilation, and CLI/dry-run boundary checks. Codex and DS independently
  accepted the locked hash set.
- Task 2 is software-only accepted. This does not authorize camera, TCP,
  flashing, reset, or motion.
- Neither software result authorizes camera, TCP, flashing, reset, or motion.

### 4B-5 firmware-equivalent twin components

Status: `SOFTWARE_ONLY_PASS`

- `v1_twin_controller.py` mirrors the firmware PID core with float32
  arithmetic, derivative/integral limits, turn gain, integer truncation, and
  turn output saturation.
- `v1_twin_virtual_sensor.py` projects the schema sensor bar onto the metric
  track centerline and preserves firmware black-bit/error semantics.
- Fresh focused tests, full simulation tests, and related 4B-4 regressions are
  recorded in `.embeddedskills/build/v1_task4b5/task4b5_offline_acceptance.md`.
- This does not prove the physical sensor offsets, track width, motor smoothing,
  line-loss recovery, or any real-car behavior.

### 4B-6 four-wheel plant and identification scaffold

Status: `SOFTWARE_ONLY_SKELETON_PASS / REAL_DATA_INSUFFICIENT_EVIDENCE`

- `v1_twin_plant.py` implements the explicit exploratory M1..M4 signed-PWM
  mix, shared wheel gains, body bias, deadzone, delay, and pose integration.
- `v1_twin_identification.py` implements synthetic recovery, rank/condition/Fisher
  diagnostics, PWM coverage, pairwise combination counts, stop/straight/turn
  proportions, and timestamped sync-frame velocity extraction.
- Fresh focused tests: `13 passed`; full simulation suite: `546 passed`.
- Acceptance report:
  `.embeddedskills/build/v1_task4b6/task4b6_offline_acceptance.md`.
- Handoff:
  `docs/agent-context/handoffs/2026-08-05-task4b6-codex-acceptance.md`.
- The synthetic fixture is not physical evidence. Real synchronized data,
  calibration/holdout isolation, model freezing, and 4B-8 READY remain open.

### 4B-7 calibration/holdout and model-freeze scaffold

Status: `SOFTWARE_ONLY_SKELETON_PASS / REAL_DATA_INSUFFICIENT_EVIDENCE`

- `v1_twin_calibration_set.py` rejects empty calibration sets, invalid IDs,
  and calibration/holdout overlap through an immutable split.
- `v1_twin_model_registry.py` enforces freeze-before-holdout, canonical model
  fingerprints, fit timestamp/metadata retention, and invalidation when frozen
  inputs change.
- Focused tests: `7 passed`.
- Acceptance report:
  `.embeddedskills/build/v1_task4b7/task4b7_offline_acceptance.md`.
- Handoff:
  `docs/agent-context/handoffs/2026-08-05-task4b7-codex-acceptance.md`.
- Real calibration runs, formal model fitting, convergence evidence, and
  final holdout remain absent.

## Earliest Safe Path To Visible Car Motion

The car cannot be declared ready to run yet. The shortest valid sequence is:

1. User gives a fresh immediate hardware authorization with the car and camera
   powered on and remains beside the motor-power switch.
2. Verify and flash only the accepted AXF.
3. Run one 0.5-second elevated-wheel gate at speed 260 with no START retry.
4. Require five `APPLIED/APPLIED` ACKs, RUNNING, heartbeat, final
   `STOPPED/STOP`, readable C960 video, and telemetry.
5. Review evidence and physical observation. Only then request a separate
   authorization for one 0.5-second ground run.

The first ground run is data collection and a bounded shakedown. Even if it
passes, it does not complete 4B-4, the formal 2 mm mapping gate, 4B-8 READY, or
the Robot Twin AI V1 closed loop.

## Evidence Pointers

- PWM acceptance:
  `.embeddedskills/build/v1_pwm_permille_codex_acceptance_20260805_r1/software_acceptance.md`
- R3 exploratory verification:
  `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r2/verification_report.json`
- MPU audit:
  `docs/agent-context/handoffs/2026-08-05-mpu6050-observability-audit.md`
- Task 2 Codex and DS acceptance:
  `.embeddedskills/build/v1_ground_shakedown_task2_codex_acceptance_20260805_r3/acceptance_report.md`
- Task 2 handoff:
  `docs/agent-context/handoffs/2026-08-05-task2-codex-acceptance-r3.md`
- Task 1 Fix Round 1 rejection:
  `.embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_fix_r1_rejection.md`
- Task 1 Fix Round 3 final rejection and controller reproductions:
  `.embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_fix_r3_rejection.md`
- Task 1 lifecycle architecture analysis (DS, read-only):
  `.embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_architecture_analysis_ds.md`
- Task 2 blocked brief:
  `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-2-brief.md`
- Future hardware checklist:
  `docs/agent-context/handoffs/2026-08-05-next-hardware-gates.md`
- Task 4B-5 offline acceptance:
  `.embeddedskills/build/v1_task4b5/task4b5_offline_acceptance.md`
- Task 4B-5 handoff:
  `docs/agent-context/handoffs/2026-08-05-task4b5-codex-acceptance.md`
- Task 4B-6 offline acceptance:
  `.embeddedskills/build/v1_task4b6/task4b6_offline_acceptance.md`
- Task 4B-6 handoff:
  `docs/agent-context/handoffs/2026-08-05-task4b6-codex-acceptance.md`
- Task 4B-7 offline acceptance:
  `.embeddedskills/build/v1_task4b7/task4b7_offline_acceptance.md`
- Task 4B-7 handoff:
  `docs/agent-context/handoffs/2026-08-05-task4b7-codex-acceptance.md`
