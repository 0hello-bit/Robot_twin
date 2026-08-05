# DS Task 1 Fix Round 3 - Firmware-Realistic Initial Identity

Status: AUTHORIZED_OFFLINE_FIX_ONLY

Read completely:

1. `docs/agent-context/handoffs/2026-08-05-ds-ground-shakedown-task1-fix-r2.md`
2. `.embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_fix_r2_rejection.md`
3. `.embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/probe_manifest.md`
4. This handoff.

## Scope

Modify only:

- `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`
- `simulation/digital_twin/tests/test_ground_shakedown.py`
- append Fix Round 3 evidence to
  `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-1-report.md`

The independent acceptance probe is read-only. Do not implement Task 2. No
Git writes, network/camera/serial/debugger access, Keil, flash, reset, hardware,
or motion commands.

## Confirmed Root Cause

Fix Round 2 incorrectly requires the connection-time authoritative status to
match the new campaign/run. Its tests make the same incorrect assumption.

Firmware source is authoritative:

- `twin_control_protocol.c` initializes identity to `none/none` before any R
  command.
- `twin_control_queue_authoritative_status()` re-emits cached state using the
  current identity, which can be sentinel or a prior run.
- only parsing the new pre-STOP R command changes identity to the new
  campaign/run.

Therefore the first valid CONNECT snapshot must be consumed and recorded
without comparing it to the not-yet-sent new identity. It is evidence only and
cannot confirm any command. From pre-STOP onward, existing strict identity and
first-event-decisive checks remain mandatory.

## Required RED/GREEN Test

Add a transport that queues `S,none,none,INIT,MOTION_INHIBITED,...` or a prior
identity before the reader starts, then emits a new-identity `STOPPED/STOP`
only in response to pre-STOP.

Assert:

- top-level `initial_status` retains the sentinel/prior identity;
- `pre_stop.status` uses the new campaign/run and is a distinct event;
- the normal bounded sequence can reach control PASS;
- the connection snapshot never confirms pre-STOP/START/final STOP;
- all post-command identity checks remain strict.

Run this test against the Fix Round 2 baseline first. It must fail because
`wait_for_initial_status()` skips the snapshot and times out. Then make the
minimal production change and verify GREEN. Do not weaken the post-command
status waiter.

## Verification

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py
py -3.11 -m pytest -q .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py
py -3.11 -m pytest -q simulation/digital_twin/tests/test_runtime_protocol.py
py -3.11 -m py_compile .embeddedskills/tools/shakedown_toolchain/ground_shakedown.py
py -3.11 -B .embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_fault_probes.py
```

Expected: Task 1 `19 passed`, historical `41 passed`, runtime `34 passed`,
compile exit 0, independent probes `11/11` exit 0.

Append RED/GREEN evidence, exact exit codes, final two hashes, implementation
explanation, and concerns to the existing report. Then stop. Task 2 remains
blocked until controller tests and a fresh independent review both pass.
