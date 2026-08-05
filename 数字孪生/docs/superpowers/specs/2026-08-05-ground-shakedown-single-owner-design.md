# Ground Shakedown Task 1 Single-Owner Lifecycle Design

Date: 2026-08-05
Status: APPROVED_FOR_IMPLEMENTATION

## Decision

Replace the rejected Task 1 threaded lifecycle with a single-owner synchronous
event loop. The calling thread is the only actor allowed to call transport
send/receive/close, parse incoming bytes, mutate control evidence, or write raw
I/O evidence.

This is an architecture replacement, not Fix Round 4. The user approved this
written specification on 2026-08-05.

## Evidence Behind The Decision

The rejected implementation is locked at:

- production SHA-256:
  `D330500F77DB1C0730396359A1D6CD0ABF72C52B6744372DA700AB9107B90BE7`
- tests SHA-256:
  `23C72E5974A988663D648A810C19920BC4C0B1D1787DA8979DD1175879A24190`

It passed 19 Task 1 tests, 41 transport regressions, 34 runtime-protocol
regressions, Python compilation, and 11/11 independent probes. Final review
still rejected it because those suites did not cover four load-bearing
lifecycle defects:

1. public status evidence lost host receive sequence and monotonic time;
2. a heartbeat worker could remain alive after being reported stopped;
3. a secondary STOP exception could hide the primary failure;
4. a blocked reader could mutate raw evidence after publication.

Controller probes reproduced findings 2 through 4. The complete record is in
`.embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_fix_r3_rejection.md`.

## Scope

### In scope

- Replace the internal lifecycle of `run_ground_session()`.
- Preserve the bounded command sequence and fail-closed behavior.
- Add complete receive provenance to ACK and status evidence.
- Make STOP and result finalization explicit state transitions.
- Add deterministic RED tests for the rejected architecture.
- Preserve the public call shape used by Task 2.

### Out of scope

- Task 2 camera, CLI, evidence-directory, and overall-verdict implementation.
- Changes to firmware, PID gains, speed steps, or protocol framing.
- TCP, camera, serial, debugger, Keil, flash, reset, or hardware execution.
- Git writes.
- General refactoring of the historical `transport_soak.py` evidence module.

## Required External Behavior

The public interface remains:

```python
run_ground_session(
    transport,
    campaign_id,
    run_id,
    duration_s,
    raw_logger=None,
) -> dict
```

The command sequence remains:

```text
connection status
pre-STOP
P1=580 -> P2=480 -> P3=380 -> P4=280 -> P5=260
START
RUNNING confirmation
immediate heartbeat, then one heartbeat every 200 ms
authorized running window
terminal STOP
STOPPED/STOP confirmation
```

Kp=35, Ki=0, and Kd=10 remain unchanged. Parameter versions remain 1 through
5. There is no P retry, START retry, or automatic second motion window.

Task 1 emits `control_verdict` only. It must never emit `shakedown_verdict`.

## Transport Contract

The single-owner design depends on bounded synchronous I/O. A supported
transport must provide `send(bytes)`, `recv(max_bytes)`, and `close()` with
these guarantees:

- every call returns or raises within 0.15 seconds;
- `recv()` returns bytes, `b""` for a bounded timeout, or `None` for EOF;
- a successful `send()` return is the only proof that the call completed;
- an exception from `send()` is treated as an ambiguous transmission outcome;
- `close()` is idempotent from the caller's perspective.

The production `SocketTransport` uses a 0.1-second socket timeout for the
underlying socket, covering both `sendall()` and `recv()`, and satisfies the
intended bound. Test transports expose a finite positive `io_timeout_s` or
`recv_timeout` declaration at or below 0.1 seconds and honor it for send,
receive, and close. A missing or invalid declaration is rejected before
session ownership transfers and before any control I/O; that pre-session
validation error does not attempt STOP through an unsupported transport.
Every actual I/O call is timed. A call that returns after 0.15 seconds records
`IO_CALL_BUDGET_EXCEEDED` and forces control FAIL.

The 0.15-second call budget applies specifically to transport `send()`,
`recv()`, and `close()`. Raw-logger methods are local synchronous dependency
calls: active `log_send()` / `log_recv()` exceptions are control failures, and
final `write()` exceptions are publication failures as described below. This
task does not claim that an arbitrary custom raw logger which violates its
synchronous local-call contract can be preempted without a worker or process.

`duration_s` must be a finite non-boolean number at or above zero. The timeout declaration
must be a finite positive number at or below 0.1 seconds. Invalid duration or
transport declarations are rejected before session ownership transfers. On
that pre-session path, Task 1 calls none of `send()`, `recv()`, `close()`,
`log_send()`, `log_recv()`, or `write()`: the caller retains ownership. The
returned result is a structured control FAIL with `stop.attempted=false`,
`rollback_requested=false`, `stop.send_outcome="NOT_INVOKED"`,
`quiescence.proven=false`, and `cut_power_warning=true` because STOP was not
proved.

A transport that can block indefinitely is unsupported by this design. It
would require the separately rejected worker-supervisor alternative or process
isolation. This limitation must remain explicit in the code, tests, and
handoff.

## Single-Owner Event Loop

`run_ground_session()` creates one internal `_SessionLoop`. No Task 1 reader or
heartbeat thread is created. The calling thread owns:

- transport send, receive, and close;
- raw TX/RX logging;
- byte parsing;
- ACK/status queues;
- heartbeat deadlines;
- STOP transactions;
- error ordering;
- evidence freeze and return.

The loop services input with bounded `recv()` calls. During the running window
it checks the heartbeat deadline before every receive. The first heartbeat is
sent immediately after `RUNNING/START`; later heartbeats use monotonic
deadlines spaced by 0.2 seconds. Missed deadlines are never caught up by
bursting multiple heartbeats. A deadline missed by one full heartbeat period,
or an I/O call exceeding its budget, forces FAIL and terminal STOP.

The overall deadline is derived, not independently configurable:

```text
initial-status budget
+ pre-STOP budget
+ five ACK budgets
+ START-confirm budget
+ authorized duration
+ terminal-STOP budget
+ one-second scheduling margin
```

Each phase retains its own deadline. The overall deadline is a final safety
ceiling and cannot extend a phase.

## Receive Evidence Model

Every complete control line is converted exactly once into an event envelope
before entering any queue:

```python
{
    "kind": "ack" | "status" | "parse_error",
    "receive_seq": int,
    "receive_monotonic_s": float,
    "raw_line": str,
    "parsed": dict | None,
    "error": str | None,
}
```

`receive_seq` is one session-wide monotonically increasing sequence shared by
ACK and status events. The timestamp is captured on the host when the complete
line is received. MCU `tick_ms` remains separate and never substitutes for
host receive time.

All public ACK/status fields, including `initial_status`, `pre_stop.status`,
`start.status`, `stop.status`, and every item in `statuses`, include
`receive_seq` and `receive_monotonic_s`.

Command gates capture the current sequence before sending. Only events with a
strictly greater sequence can confirm that command. The first post-boundary
event of the required kind is decisive: ACK for a P gate and status for an R
gate. Other event kinds remain evidence but cannot satisfy that gate. A
decisive event is never skipped in search of a later matching event.

The first valid connection status is consumed as `initial_status` without
requiring the not-yet-sent campaign/run identity. It is evidence only and
cannot confirm pre-STOP, START, or terminal STOP.

## Send And Raw-Log Separation

The historical `_send()` combines transport send and raw logging. The new loop
must record them as separate outcomes:

1. call `transport.send(command)` and record its completion or exception;
2. call `raw_logger.log_send(command)` and record its independent outcome;
3. never reinterpret a raw-logger failure as proof that the transport send
   failed.

If a control command may have reached the MCU but raw logging fails, the gate
fails closed and proceeds to terminal STOP. The primary failure remains the
first causal failure; later STOP, close, and raw-publication failures are
appended to `secondary_errors`.

## STOP Transactions

Pre-STOP and terminal STOP are separate transactions.

### Pre-STOP

Pre-STOP uses the normal command-boundary and confirmation rules. It passes
only when transport send completed without exception, raw TX logging
completed, and a correlated `STOPPED/STOP` was confirmed. If any condition
fails, that same attempt is promoted to the terminal `stop` record; no
duplicate STOP is sent and no P or START command follows. A confirmation after
an ambiguous send exception remains valuable evidence but cannot make the
transaction PASS.

If the pre-STOP send raises, its bounded confirmation window is still serviced.
That same attempt is promoted to the terminal `stop` record; a second STOP must
not be sent.

### Terminal STOP

For every path after a successful pre-STOP, terminal STOP uses a once-only
state machine:

```text
NOT_RESERVED
-> RESERVED
-> SEND_INVOKED
-> SEND_COMPLETED | SEND_AMBIGUOUS_EXCEPTION
-> CONFIRMED | UNCONFIRMED
-> RECORDED
```

The `stop` result dictionary is allocated at reservation, before encoding,
sending, logging, or waiting. Therefore no exception can leave it absent.
After terminal STOP reservation, no further control command may be sent.

Compatibility and explicit semantics:

- `attempted=true` once reserved;
- `rollback_requested=true` once STOP send invocation begins;
- `cmd_sent=true` only when `transport.send()` returns successfully;
- `send_outcome="AMBIGUOUS_EXCEPTION"` when send raises, because partial
  transmission cannot be excluded;
- `stop_confirmed` is derived only from a correlated post-boundary
  `STOPPED/STOP`;
- `cut_power_warning=true` unless send completed and confirmation succeeded.

A STOP send exception does not skip the bounded confirmation window. A
correlated status may still prove that a partially transmitted command reached
the MCU. The exception remains evidence even when confirmation arrives.

## Error Ordering

The first control or quiescence failure is immutable and stored as
`primary_failure`. A STOP or transport-close failure becomes the primary only
when no earlier control failure exists. Subsequent STOP, close, and control-I/O
failures are appended in occurrence order to `secondary_errors`; none may
overwrite the primary.

A final `raw_logger.write()` failure is publication evidence, not a control
failure. It is recorded in `cleanup_errors`, `secondary_errors`, and
`raw_io.write_error`, while `primary_failure` remains unchanged. A
`raw_logger.log_send()` or `log_recv()` failure during the active control
sequence is different: it compromises live evidence, becomes a control
failure, and triggers terminal STOP.

For compatibility, `unexpected_exception` is retained only as a mirror of the
first exception-backed primary failure. `primary_failure` is authoritative and
is never replaced by that compatibility field or by a later exception.

`KeyboardInterrupt` follows the same fail-closed control path: record it as the
primary failure, perform terminal STOP if required, close resources, and return
a structured FAIL result.

There are no successful or failed early returns from inside the control
sequence. Every path converges on terminal STOP handling, resource close, raw
publication, and one final result build.

## Close, Freeze, And Final Result

Finalization order is fixed:

1. finish or fail terminal STOP confirmation;
2. call `transport.close()` exactly once and record its outcome;
3. copy the stable raw event list;
4. call `raw_logger.write()` exactly once and record its independent outcome;
5. build the final result from the frozen control and raw evidence;
6. return the result without any later mutation.

Because Task 1 creates no workers, all Task 1 I/O activity has ended before
step 2. `quiescence.proven` is true only when single-owner execution remained
intact and transport close completed. A close failure, late I/O call, raw
mutation, or other inability to prove quiescence forces `control_verdict=FAIL`.
A `raw_logger.write()` failure is different: it is recorded in
`cleanup_errors` and `raw_io.published=false`, but it does not rewrite an
otherwise completed control verdict. Task 2 must fail the overall shakedown
verdict when required raw evidence is absent.

The result retains existing keys and adds:

```text
primary_failure
secondary_errors
quiescence.proven
quiescence.freeze_monotonic_s
quiescence.n_frozen_raw_events
heartbeat.active_at_terminal_stop_reservation
stop.send_outcome
stop.reservation_monotonic_s
stop.reserved_receive_seq
raw_io.published
raw_io.write_error
```

`heartbeat.stopped_before_final_stop` remains for compatibility. It is true
only when heartbeat scheduling started and was deactivated before terminal
STOP reservation; it is `None` when heartbeat never started.

## Verdict Rules

`control_verdict=PASS` requires all of the following:

- valid connection status evidence;
- confirmed pre-STOP;
- five correlated `APPLIED/APPLIED` ACKs;
- confirmed `RUNNING/START`;
- no heartbeat or I/O-budget failure;
- heartbeat scheduling inactive at terminal STOP reservation;
- terminal STOP send completed;
- correlated terminal `STOPPED/STOP`;
- transport close completed;
- `quiescence.proven=true`;
- no primary failure.

Any failed control/quiescence condition produces `control_verdict=FAIL`.
Raw-publication failure remains structured evidence without overwriting that
control result. Task 2 remains solely responsible for required-artifact checks
and `SHAKEDOWN_PASS`, `SHAKEDOWN_FAIL`, or `INSUFFICIENT_EVIDENCE`.

## Test-First Replacement Gate

Before production edits, DS must add and run these RED tests against the locked
rejected hash:

1. every public status record contains host receive sequence and monotonic
   receive time;
2. every transport/raw-log call occurs on the calling thread only;
3. a bounded-late heartbeat send exceeds the I/O budget, forces FAIL, and
   cannot be followed by another heartbeat after STOP reservation;
4. a primary P-send failure followed by non-`OSError` STOP failure returns a
   structured result with the primary preserved and a complete STOP record;
5. a bounded-late receive cannot mutate raw evidence after freeze and prevents
   PASS when the I/O budget is exceeded.

The expanded suite must also cover the following specification boundaries:

- a pre-STOP ambiguous send is promoted without sending a second STOP;
- a missing, non-numeric, non-finite, zero, negative, or greater-than-0.1
  transport timeout declaration is rejected before any transport/raw call;
- an active `log_send()` or `log_recv()` failure becomes the primary control
  failure and still converges on terminal STOP;
- final raw publication failure preserves the already-determined control
  verdict and sets `raw_io.published=false`.

Timing tests use a delay of at least 0.18 seconds against the 0.15-second
budget, rather than testing at the exact boundary, to leave scheduler margin.

The historical F2 harness monkeypatches `ground_shakedown.soak._collect()`.
Architecture A removes `_collect()`, so that harness must be migrated rather
than preserved literally. Its replacement uses a bounded fake transport that
raises while `run_ground_session()` services receive during the authorized
running window. The migrated test must retain these behavioral assertions:

- `control_verdict == "FAIL"`;
- heartbeat scheduling is deactivated before terminal STOP reservation;
- terminal STOP is the last command;
- no heartbeat is sent after terminal STOP reservation.

Each new test must fail for the named reason before implementation. The RED
logs and pre-edit hashes are written to a new evidence directory.

After implementation:

- all five new tests pass;
- all 19 existing Task 1 behavioral assertions pass; test transports may gain
  only the required bounded-I/O declaration;
- all 41 historical transport regressions pass;
- all 34 runtime-protocol regressions pass;
- Python compilation passes;
- independent probes cover the five new cases and existing F1-F9 contracts;
- production and test hashes remain stable throughout independent review;
- a fresh reviewer returns both `SPEC_COMPLIANCE: PASS` and
  `CODE_QUALITY: PASS`.

Task 2 remains `BLOCKED_PENDING_TASK1_FINAL_REVIEW` until every condition is
met. Software PASS still does not authorize TCP, camera, firmware, or motion.

## Implementation Ownership

One fresh DS implementation session owns the test-first replacement and writes
one report. Codex owns RED-evidence verification, fresh regression reruns,
fault probes, hash lock, and final independent review. No fourth patch loop is
created around the rejected threaded design.
