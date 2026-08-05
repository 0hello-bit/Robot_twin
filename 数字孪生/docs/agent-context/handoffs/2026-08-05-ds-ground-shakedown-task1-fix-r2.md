# DS Task 1 Fix Round 2 - Status Correlation

Status: AUTHORIZED_OFFLINE_FIX_ONLY

Read these files completely before editing:

1. `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-1-report.md`
2. `docs/agent-context/handoffs/2026-08-05-ds-ground-shakedown-task1-fix-r1.md`
3. This Fix Round 2 handoff.
4. `.embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/probe_manifest.md`

## Scope

You may modify only:

- `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`
- `simulation/digital_twin/tests/test_ground_shakedown.py`
- append Fix Round 2 evidence to
  `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-1-report.md`

The independent probe and acceptance directory are read-only inputs. Do not
implement Task 2. Do not edit historical `transport_soak.py`, firmware, plans,
specs, or evidence. Do not perform Git writes, network/camera/serial/debugger
access, Keil, flash, reset, hardware access, or motion commands.

## Stable Fix Round 1 Baseline

- Production SHA-256:
  `580E08F4BD07EF49166E861994A250D218C35C7E780029CE50DEA129981A95DE`
- Test SHA-256:
  `295D28E689C8D8C3660C9E2FEE664553C015A2D7D5759B307C085EA5B182DD59`
- Fresh controller tests: Task 1 `16 passed`, transport `41 passed`, runtime
  protocol `34 passed`, and `py_compile` exit 0.
- Independent fault probes: `7/10`, exit 1. The three RED probes identify the
  two production defects below.

## F8 - Connection Status Is Neither Recorded Nor Isolated

Confirmed source facts:

- `initial_status_s` is defined but unused.
- `run_ground_session()` starts the reader and immediately captures the
  pre-STOP boundary and sends STOP.
- No code writes `initial_status` into the result.
- If the connection-time `STOPPED/STOP` is queued before pre-STOP but parsed
  after the boundary is captured, it receives a sequence above the boundary
  and can falsely confirm pre-STOP.

Independent reproduction:

```powershell
py -3.11 -B .embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_fault_probes.py
```

Both `F3_F4_nominal_ack_rollback` and
`F6_initial_and_stale_final_status` fail with
`initial_status was not recorded`.

Required behavior:

1. After the reader starts and before any control command, wait for and
   consume exactly one connection-time authoritative status within the
   bounded `initial_status_s` window.
2. Serialize it as top-level `initial_status` using the normal status schema.
3. Its campaign/run identity may legitimately be the firmware sentinel or a
   prior session because the new production identity has not yet been sent.
   Record it without requiring identity equality to the new campaign/run. It
   may never confirm pre-STOP, START, or final STOP.
4. A missing, malformed, or reader-failed initial-status gate is fail-closed:
   never send P or START; attempt one correlated STOP and return control FAIL
   with structured failure evidence.
5. After consuming the initial status, capture a fresh boundary, send
   pre-STOP, and require a distinct post-command `STOPPED/STOP` status.

Add a deterministic RED test that queues an exact matching connection status
before the reader starts, emits a different-tick status only in response to
pre-STOP, and asserts that `initial_status` and `pre_stop.status` are both
present and have different ticks. The old code must fail this test for the
confirmed reason before production is changed.

## F9 - Post-Command Safety Status Is Silently Discarded

Confirmed source fact: `wait_for_status_boundary()` deletes every nonmatching
post-boundary status and keeps waiting. Therefore an active-identity
`STOPPED/TIMEOUT` or `STOPPED/LINE_LOST` can be discarded and a later
`RUNNING/START` can incorrectly make the START gate pass.

Independent reproduction `F6_post_start_safety_status_first_event_decisive`
injects active-identity `STOPPED/TIMEOUT` before `RUNNING/START`. Fix Round 1
returns `control_verdict=PASS`; the probe requires FAIL.

Required behavior:

1. Continue draining and recording pre-boundary statuses; none may confirm a
   later command.
2. After a command boundary, the first parsed status event is decisive.
3. A matching expected state/reason succeeds the gate.
4. Any other same-identity status, especially `TIMEOUT` or `LINE_LOST`, fails
   the gate immediately, remains in structured evidence, and triggers the
   single fail-closed exit STOP.
5. Identity-mismatched or otherwise unexpected post-boundary status also
   fails closed; do not silently skip it in search of a later matching status.
6. A later `RUNNING/START` must never override an earlier post-START safety
   status.

Add a deterministic RED test using the exact TIMEOUT-then-RUNNING sequence.
Assert control FAIL, START not confirmed, TIMEOUT retained in evidence, final
command STOP, and no automatic START retry.

## Verification

After GREEN, run all commands and append outputs/counts/exit codes to the Task
1 report:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py
py -3.11 -m pytest -q .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py
py -3.11 -m pytest -q simulation/digital_twin/tests/test_runtime_protocol.py
py -3.11 -m py_compile .embeddedskills/tools/shakedown_toolchain/ground_shakedown.py
py -3.11 -B .embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_fault_probes.py
```

Expected independent-probe result after the fix: `10/10`, exit 0. Do not
modify the probe to obtain GREEN.

Append:

- both RED tests and their expected pre-fix failures;
- all final GREEN commands and exact counts;
- final SHA-256 hashes of both scoped files;
- F8/F9 implementation explanation;
- remaining concerns.

Then stop and return only `DONE`, hashes, one-line test summary, and concerns.
Task 2 remains blocked until controller reacceptance and an independent review
both pass.
