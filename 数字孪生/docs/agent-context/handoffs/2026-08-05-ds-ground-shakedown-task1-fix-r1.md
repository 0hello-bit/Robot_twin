# DS Task 1 Fix Round 1 - Ground Shakedown Safety Core

Status: AUTHORIZED_OFFLINE_FIX_ONLY

Read these files completely before editing:

1. `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-1-brief.md`
2. `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-1-report.md`
3. `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-1-review-package.diff`
4. This fix handoff.

## Scope

You may modify only:

- `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`
- `simulation/digital_twin/tests/test_ground_shakedown.py`
- append Fix Round 1 evidence to
  `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-1-report.md`

Do not implement Task 2. Do not edit the historical `transport_soak.py`,
runtime protocol, firmware, plans, specs, or existing evidence directories.
Do not perform Git writes, network access, camera access, serial/debugger
access, Keil, flash, reset, hardware access, or motion commands.

## Confirmed Findings

### F1 - STOP is skipped on an exception before START

Current reproduction: inject `OSError` while sending P version 2. The function
returns `control_verdict=FAIL`, but the last command is P2 and `result["stop"]`
is absent. Root cause: the exception path attempts STOP only when
`started_send` is true. This violates the global requirement to attempt a
correlated STOP on every exit path.

Fix the ownership/state model so an exception during any P send, ACK wait,
START send (including a send that may have partially succeeded), RUNNING wait,
collection, or finalization attempts the correlated exit STOP exactly once.
Do not use successful return from `_send()` as proof that START was not
partially transmitted.

### F2 - Heartbeat can continue after STOP and after function return

Current reproduction: make `soak._collect()` raise after the heartbeat thread
starts. `run_ground_session()` sends final STOP and returns, then a later
`H,shake,...` is still emitted. Root cause: `heartbeat_stop` and `hb_thread`
are cleaned only on the normal collection path.

Make heartbeat lifecycle single-owner and idempotent. On every path, stop and
join the heartbeat before attempting the exit STOP and before closing the
transport. Treat a heartbeat thread that cannot be stopped within a bounded
join as a failure and record it. No H command may be attempted after the final
STOP or after function return.

### F3 - Control-only success falsely claims overall SHAKEDOWN_PASS

Current reproduction returns `shakedown_verdict=SHAKEDOWN_PASS` with
`telemetry.n=0` and no camera evidence. Task 2 defines overall PASS as requiring
control PASS, finalized video, and at least one telemetry frame.

Task 1 may report `control_verdict=PASS` or `FAIL`, but it must not emit the
overall `shakedown_verdict` field. Task 2 is the single owner of all
`SHAKEDOWN_PASS`, `SHAKEDOWN_FAIL`, and `INSUFFICIENT_EVIDENCE` decisions.

### F4 - Required ACK and rollback evidence is not returned

`AckSessionContext.parameter_acks` is local and lost at return. The result also
omits the required top-level separation of rollback request and STOP
confirmation.

Return JSON-serializable parameter ACK records (campaign, version, outcome,
reason, raw line, receive sequence, and receive monotonic time), including the
rejecting ACK when present. Return explicit
`rollback_requested` and `stop_confirmed` booleans derived from command-send
and correlated status evidence; do not claim numeric speed 680 was measured.
Keep malformed ACK evidence in `parse_errors` and the raw trace.

### F5 - Cleanup and raw-I/O publication are not exception-safe

The current `finally` writes raw I/O before stopping the reader, so the event
list can still mutate while it is serialized. If `raw_logger.write()` raises,
reader shutdown and `transport.close()` are skipped.

Make cleanup bounded and exception-safe: stop heartbeat, request the exit STOP
when still required, stop/unblock and join the reader, close the transport
exactly once, then write the final raw-I/O snapshot exactly once. A cleanup
failure must be recorded without suppressing the primary control failure or
skipping later cleanup actions.

### F6 - Queued ACK/status evidence can satisfy the wrong send boundary

`wait_for_parameter_ack()` consumes the first queued event but does not prove
that the event arrived after the current P send. A pre-existing matching
campaign/version ACK can therefore pass a gate. The inherited status waiter
has the same flaw: a stale `STOPPED/STOP` can confirm a later final STOP that
received no response.

Add explicit monotonically ordered receive events and a per-command boundary
captured before each P/R send. ACK and status waiters must accept only evidence
strictly newer than that command boundary. A queued ACK before its P command is
unexpected and fails closed as stale evidence. Status handling is different:
the firmware is expected to emit one authoritative status on connection, so
record and consume that as `initial_status` before pre-STOP; it may never
confirm pre-STOP or final STOP. Later pre-boundary statuses are recorded and
consumed but cannot confirm the next R command; a safety status for the active
identity (for example TIMEOUT or LINE_LOST) must fail the control session while
the exit STOP is still attempted. Preserve the first-event-decisive rule after
each send boundary. Do not weaken campaign/version, run identity,
`APPLIED/APPLIED`, or state/reason checks.

### F7 - Heartbeat transmission failure is silently treated as success

The inherited heartbeat helper catches `OSError` and exits without reporting
the failure. A session can therefore remain in its authorized window without
the required 200 ms lease renewal and still return `control_verdict=PASS`.

Make heartbeat outcome observable. Any heartbeat send failure, premature
heartbeat-thread exit, or failure to join before STOP sets control FAIL and is
recorded in structured evidence. Do not modify the historical helper file;
adapt or wrap behavior locally in the new tool.

## Required TDD Regressions

Write and run focused RED tests against the current code before changing
production behavior. At minimum cover these independent breaks:

1. P-send exception before START: no START, correlated STOP is last, FAIL,
   close exactly once.
2. START-send exception that may have partially transmitted: exit STOP is
   attempted and PASS is impossible.
3. Collection exception: heartbeat is stopped before STOP and no heartbeat is
   attempted after return.
4. Task 1 success and failure results do not contain `shakedown_verdict`;
   they contain only the bounded `control_verdict`.
5. Success and rejected-ACK results contain serializable ACK evidence plus
   explicit `rollback_requested` and `stop_confirmed` fields.
6. A stale matching ACK queued before P1 cannot authorize P1/START.
7. A stale matching `STOPPED/STOP` cannot confirm a later final STOP whose
   response is absent.
   Also cover the expected connection-time authoritative status: it is
   recorded as `initial_status`, does not fail preflight by itself, and cannot
   satisfy the later pre-STOP confirmation.
8. A heartbeat send failure or premature heartbeat exit forces control FAIL
   and is present in structured evidence.
9. A raw logger whose `write()` raises cannot prevent reader/heartbeat cleanup
   or the single transport close; no cleanup operation runs twice.

Tests must exercise real `run_ground_session()` behavior. Use deterministic
in-process transports and injected/monkeypatched offline functions only; do
not assert merely that a mock was called.

## Verification

After GREEN, run all of these:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py
py -3.11 -m pytest -q .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py
py -3.11 -m pytest -q simulation/digital_twin/tests/test_runtime_protocol.py
py -3.11 -m py_compile .embeddedskills/tools/shakedown_toolchain/ground_shakedown.py
```

Append to the existing Task 1 report:

- each RED command, expected failure, actual key output, and exit code;
- final GREEN commands, counts, and exit codes;
- final SHA-256 hashes of both scoped files;
- a finding-by-finding explanation of the fix;
- any remaining concern.

Then stop. Return only `DONE`, the new hashes, one-line test summary, and
concerns. Do not start Task 2.
