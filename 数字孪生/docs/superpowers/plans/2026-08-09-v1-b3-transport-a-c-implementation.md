# V1-B3 transport A/C implementation plan

Status: completed
Date: 2026-08-09

## Objective

Repair the evidence boundary and delivery ownership in the existing ESP-01S
transport while preserving the existing AA55 protocol, P/R/A/S control
semantics, heartbeat, safety stop, session storage, and 30 ms telemetry
generation cadence.

The primary path is A (existing `AT+CIPSEND`). C (ESP transparent TCP) is an
offline alternative implementation only. nRF24L01 is a future fallback and is
out of scope for this round: no driver, PCB change, firmware variant, or real
hardware test is allowed here.

## Non-goals and safety boundary

- Do not change PID, line following, AprilTag, MPU6050 control, camera mode, or
  PCB design.
- Do not create a second TCP client, heartbeat, AA55 parser, ACK registry, or
  experiment/session storage format.
- Do not flash firmware, connect to ST-Link, enter transparent mode, send AT
  commands to the ESP, or move the car.
- Do not claim B3 hardware readiness from host tests, a build, or synthetic
  replay. The result must remain `VERIFIED`, `INFERENCE`, or
  `INSUFFICIENT_EVIDENCE` with the correct boundary.

## Work sequence

### 1. Baseline audit

Record the current dirty-worktree state and inspect the existing capture,
transport, telemetry batch, CIPSEND state machine, coordinator, and Keil source
list. Make no rollback or cleanup of unrelated agent changes.

### 2. Host capture evidence boundary

Update `capture_sync_run.py` and its supporting transport logging so that:

- each socket `recv()` gets one shared `arrival_pc_ns`;
- each decoded frame also retains a diagnostic `decode_pc_ns`;
- frames are tagged as outside-window, inside-window, or post-window;
- only frames after the matching `RUNNING/START` and before formal window close
  enter the B3 telemetry list used by ClockSync;
- data received during STOP confirmation/cleanup is retained as boundary
  evidence but excluded from the formal synchronized dataset;
- health/status/raw-I/O evidence remains available;
- reports expose formal telemetry count, outside-window count, generated count,
  and parsed count separately.

Add focused tests using fake socket/parser inputs. The tests must prove that a
single recv batch shares its arrival timestamp, that pre-window/post-window
frames are excluded, and that status ordering opens/closes the window.

### 3. Firmware transport A

Replace the current single consumable telemetry batch with explicit pending and
in-flight ownership. Keep one CIPSEND payload at or below the existing 248-byte
limit (8 x 31-byte frames) unless replay evidence proves another bound is
needed.

Required behavior:

- starting CIPSEND copies/transfers the selected batch into `inflight` but does
  not mark it delivered;
- `SEND OK` is the only event that consumes the in-flight batch;
- `ERROR`, `busy`, prompt timeout, send-OK timeout, or equivalent failure keeps
  the in-flight payload available for same-connection retry;
- CLOSED or a connection-generation change clears pending and in-flight data
  together with the existing connection-bound TX resources;
- a full pending queue drops only the oldest droppable telemetry and increments
  the existing overwrite evidence;
- ACK/STATUS/health priority and safety behavior are unchanged.

Use the real c260809102554685 health/raw logs to justify pending capacity. Do
not expand capacity to 16/32 only because it is convenient.

Add Host C tests for success, failure retention, retry without duplication,
new frames arriving while in-flight, queue overflow, and connection boundary
clearing. The production source path used by firmware must be exercised.

### 4. Firmware alternative C (offline only)

Add a small, allocation-free transparent TCP session state machine and include
it in the Keil project. It must record ESP AT capability inputs before selecting
transparent mode, represent configuration/TCP-connected/transparent/断线/failed
states, reuse the existing application protocol above the transport boundary,
and expose a testable safe exit rule.

`+++` is legal only when motors are stopped, the application stream is quiet,
and guard time is satisfied. A transparent-mode link loss must request local
safety stop. This implementation must not issue AT commands or enter
transparent mode during this round.

Add Host C tests for legal/illegal exit, capability rejection, connection loss,
and local stop request. C is not a hardware candidate until it is compared with
A under the same experiment conditions.

### 5. Verification

Run, in order:

1. focused Python tests;
2. Host C telemetry-batch and CIPSEND/coordinator/transparent-session tests;
3. relevant existing Python and Host C regression tests;
4. Keil Target 1 rebuild.

The offline gate requires zero test failures and a Keil build with zero errors
and zero warnings. Report changed files, commands/results, unverified claims,
and the exact next authorized interface.

## Acceptance gates

### A offline candidate

PASS only if pending/in-flight ownership is unambiguous, failure/retry does not
duplicate or lose frames in Host C replay, connection boundaries clear all old
data, formal capture windows exclude boundary frames, and the Keil build is
clean. This is still `INSUFFICIENT_EVIDENCE` for real-car delivery until the
user separately authorizes flashing and a bounded hardware run.

### C offline candidate

PASS only if the state machine and safe-exit invariants pass Host C tests and
Keil build. This is an offline alternative, not evidence that ESP transparent
TCP is supported by the installed module/firmware.

### Hardware handoff

Stop before any hardware action and ask the user for explicit authorization.
The handoff must state whether A is the recommended first flash candidate, what
is still unverified, and that nRF24L01 remains deferred.

## Completion Record

- The capture boundary fix and `SlowReaderSocket` regression fixture both pass.
- Scheme A now protects the in-flight prefix during pending-queue overflow;
  the regression covers retry retention, commit ordering, and overflow.
- Scheme C is included in the Keil project but remains an offline state-machine
  alternative; it is not connected to the runtime and emits no AT commands.
- Python regression: `755 passed, 5 skipped`; compileall and `git diff --check`
  pass.
- Host C regression: telemetry batch/delivery, transparent session,
  CIPSEND transaction/TX, queue, transport-generation, and coordinator tests
  all compile and pass with the production source files.
- Keil Target 1 rebuild: `0 Error(s), 0 Warning(s)`.
- Final offline artifact:
  `firmware/stm32_line_follower/Objects/Project.axf`
  SHA-256 `53B1CD3F13B56436855FCEA65D75BF6DEB3948EE779D64B7DEEBB17D6D3937C8`.
- This record does not establish real-car delivery, ESP transparent-mode
  support, synchronized B3 performance, or B3 pass. The next interface is
  explicit user authorization for flashing A, followed by a bounded hardware
  test. nRF24L01 remains deferred.
