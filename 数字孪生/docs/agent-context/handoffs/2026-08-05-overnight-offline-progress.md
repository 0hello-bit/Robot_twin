# Overnight Offline Progress Snapshot

Date: 2026-08-05

Status: OFFLINE_WORK_IN_PROGRESS; HARDWARE_OFF; NO_HARDWARE_AUTHORIZATION

## Accepted Offline Work

### PWM permille-scale repair

Status: `SOFTWARE_ONLY_PASS`

- `Motor.c` uses PSC=71 and ARR=999.
- Commands 0 through 999 map to 0 through 99.9 percent duty.
- Accepted source SHA-256:
  `80DEB484B98C5B3D73D5E1CDC8431DFA830DDFA571B86964222CA84B83D07743`
- Accepted AXF SHA-256:
  `088EFD4E1492CC9FE6075BADD7962EEB7D193E9863CACD2BA53FBDA2457C2351`
- Host contract, Python regressions, and Keil build passed in the recorded
  acceptance. This does not prove the artifact is flashed or that the physical
  timer, motor directions, wiring, wheels, or STOP behavior are correct.

Acceptance record:
`.embeddedskills/build/v1_pwm_permille_codex_acceptance_20260805_r1/software_acceptance.md`

### MPU6050 observability audit

Status: `STATIC_AUDIT_COMPLETE; HARDWARE_UNVERIFIED`

- MPU6050 is compiled, initialized, read, and included in yaw telemetry.
- It is not used by the line-following PID or motor-control loop.
- The current yaw is relative Z-gyro integration in degrees, not absolute
  heading.
- Initialization failure is not latched: a later successful raw read can set
  `ready=1` even when configuration, WHO_AM_I, or bias calibration failed.
- No current evidence proves wiring, pull-ups, address, WHO_AM_I, mounting
  direction, yaw sign, calibration quality, or drift on this physical car.

Audit handoff:
`docs/agent-context/handoffs/2026-08-05-mpu6050-observability-audit.md`

## Ground Shakedown Recorder

### Task 1 - ACK-aware fail-closed control core

Current status: `REJECT_PENDING_FIX_ROUND_3`

Fresh passing evidence on the Fix Round 1 hashes:

- 16 Task 1 tests passed.
- 41 historical transport-soak regressions passed.
- 34 runtime-protocol regressions passed.
- Python compile check passed.

Passing tests were not sufficient for acceptance. Codex and an independent
reviewer reproduced these safety defects:

- a P/START send exception can exit without a final STOP;
- collection failure can leave heartbeat traffic running after STOP/return;
- stale ACK or status evidence can cross a command boundary;
- heartbeat transmission failure can be swallowed while control reports PASS;
- Task 1 can claim overall SHAKEDOWN_PASS without camera or telemetry;
- structured ACK/rollback evidence is missing;
- raw-I/O and transport cleanup is racy on exceptions.

Fix Round 1 corrected the original seven findings, but independent probes then
returned `7/10` and exposed two remaining status-correlation defects:

- connection-time status is neither recorded nor consumed before pre-STOP, so
  an old status parsed late can falsely confirm the command;
- a same-run `STOPPED/TIMEOUT` after START is silently discarded, allowing a
  later `RUNNING/START` to produce control PASS.

Fix Round 2 corrected first-event-decisive status handling, but its connection
fixture incorrectly required the CONNECT snapshot to match the not-yet-sent new
campaign/run. Firmware sends `none/none` or prior-run identity at that point.
Fresh ordinary tests passed, while the firmware-realistic independent probe
rejected the result at `10/11`.

Fix Round 3 is delegated to visible DS session
`ds-ground-shakedown-task1-fix-r3` under the same offline-only two-file scope.
It must consume the first valid CONNECT snapshot without new-identity matching,
while retaining strict identity checks from pre-STOP onward. Acceptance now
requires `11/11` independent probes and a clean scoped review.

Fix handoff:
`docs/agent-context/handoffs/2026-08-05-ds-ground-shakedown-task1-fix-r3.md`

### Task 2 - camera, evidence, and deny-by-default CLI

Current status: `BLOCKED_ON_TASK1_ACCEPTANCE`

The design now includes bounded ffmpeg cleanup, injected offline process
tests, atomic final-report publication, finite-duration validation, fixed
verdict precedence, and explicit `--execute`. A further preflight freezes
unique campaign/run identifiers, MJPEG/1280x720/30fps ffprobe validation,
report schema, and the user-confirmation boundary.

The Task 2 plan is synchronized and a complete implementation brief has been
generated at
`.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-2-brief.md`, but its
status remains `BLOCKED_ON_TASK1_ACCEPTANCE` and it has not been dispatched.

Task 2 preflight:
`docs/agent-context/handoffs/2026-08-05-ground-shakedown-task2-preflight.md`

Offline environment facts:

- Python 3.11.7 is available.
- ffmpeg and ffprobe 7.1.1 are available.
- The camera was not opened or probed.
- No established TCP connection to remote port 8888 was observed.

## Hardware Gate Remains Blocked

The car and camera are powered off. Nothing in this overnight session flashes,
connects to, resets, observes, or moves hardware.

Before any motion:

1. Task 1 and Task 2 must both have clean offline acceptance.
2. The user must give a fresh immediate hardware authorization.
3. Flash only the accepted AXF after verifying its SHA-256.
4. Keep wheels elevated and the user beside the power switch.
5. Apply only the five bounded speed steps to 260, each requiring correlated
   `APPLIED/APPLIED`.
6. Run one 0.5-second elevated-wheel START with 200 ms heartbeat and no retry.
7. Require final correlated `STOPPED/STOP` and review all evidence.
8. A 0.5-second ground run needs a separate fresh authorization.

Hardware checklist:
`docs/agent-context/handoffs/2026-08-05-next-hardware-gates.md`

## Next Offline Sequence

1. Receive DS Fix Round 2 report.
2. Independently inspect the two scoped files and rerun focused plus historical
   regression tests.
3. Require all 10 independent fault-injection probes and an independent scoped
   review to pass.
4. Only after Task 1 passes, produce the final Task 2 brief and delegate its
   offline implementation.
5. Independently accept Task 2, compile the CLI, inspect the exact dry-run and
   future hardware command without executing it.
