# Ground Shakedown Task 1 Single-Owner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rejected threaded Ground Shakedown Task 1 lifecycle with a bounded, synchronous, single-owner control loop whose evidence is immutable at return.

**Architecture:** `run_ground_session()` delegates to one internal `_SessionLoop`; the calling thread exclusively sends, receives, parses, logs live raw I/O, schedules heartbeats, performs STOP, closes the transport, freezes evidence, publishes raw evidence, and builds one final result. The existing parser and public call signature remain compatible, but Task 1 creates no reader or heartbeat worker.

**Tech Stack:** Python 3.11, pytest, the existing runtime protocol module, and read-only primitives from `.embeddedskills/build/v1_task4b4/transport_soak.py`.

## Global Constraints

- The authoritative specification is `docs/superpowers/specs/2026-08-05-ground-shakedown-single-owner-design.md` with status `APPROVED_FOR_IMPLEMENTATION`.
- Preserve `run_ground_session(transport, campaign_id, run_id, duration_s, raw_logger=None) -> dict`, `ACK_TIMEOUT_S`, and `ControlAwareMixedStreamParser`.
- Keep Kp=35, Ki=0, Kd=10, speeds `580, 480, 380, 280, 260`, parameter versions 1 through 5, and heartbeat period 0.2 seconds.
- A supported transport declares `io_timeout_s` or `recv_timeout` as a finite positive number at or below 0.1 seconds. Measure each `send`, `recv`, and `close`; more than 0.15 seconds is `IO_CALL_BUDGET_EXCEEDED`.
- Task 1 creates no thread and no process. The calling thread is the only owner of transport and raw-logger calls.
- Task 1 emits `control_verdict` only and must never emit `shakedown_verdict`.
- Scope is exactly `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`, `simulation/digital_twin/tests/test_ground_shakedown.py`, the locked evidence directory, and the locked report file. Do not modify `transport_soak.py` or Task 2.
- Offline only: no TCP, camera, serial, debugger, Keil, flash, reset, firmware, hardware, or motion action.
- No Git writes: no branch, worktree, add, commit, reset, checkout, restore, clean, merge, rebase, push, or pull. Read-only `git status`, `git log`, and `git diff` are allowed.
- Preserve unrelated user changes. Stop and report `BLOCKED` if either pre-edit hash differs from the locked value.
- DS evidence directory: `.embeddedskills/build/v1_ground_shakedown_single_owner_ds_20260805_r1/`.
- Codex acceptance directory: `.embeddedskills/build/v1_ground_shakedown_single_owner_codex_acceptance_20260805_r1/`. The implementer must not create or write it.
- DS report: `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-1-single-owner-report.md`.
- Existing evidence is immutable. This plan uses new `r1` paths and never overwrites an older evidence directory.

---

### Task 1: Test-First Single-Owner Lifecycle Replacement

**Files:**
- Modify: `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`
- Modify: `simulation/digital_twin/tests/test_ground_shakedown.py`
- Create: `.embeddedskills/build/v1_ground_shakedown_single_owner_ds_20260805_r1/pre_edit_hashes.json`
- Create: `.embeddedskills/build/v1_ground_shakedown_single_owner_ds_20260805_r1/red_results.json`
- Create: `.embeddedskills/build/v1_ground_shakedown_single_owner_ds_20260805_r1/verification_results.json`
- Create: `.embeddedskills/build/v1_ground_shakedown_single_owner_ds_20260805_r1/implementation_manifest.json`
- Create: `.superpowers/sdd/2026-08-04-ground-shakedown-recorder/task-1-single-owner-report.md`

**Interfaces:**
- Consumes: a bounded transport with `send(bytes) -> None`, `recv(max_bytes) -> bytes | None`, `close() -> None`, and `io_timeout_s` or `recv_timeout` at or below 0.1 seconds.
- Consumes: a raw logger with `log_send(bytes)`, `log_recv(bytes, note=None)`, `events() -> list`, and `write()`.
- Produces: the unchanged public `run_ground_session(transport, campaign_id, run_id, duration_s, raw_logger=None) -> dict` call and a complete compatibility result plus the new failure, quiescence, STOP, heartbeat, and raw-publication evidence from the specification.
- Produces: no hardware action, no Task 2 verdict, and no Git state change.

- [ ] **Step 1: Lock the rejected inputs and create fresh DS evidence**

Run these read-only checks before editing either source file:

```powershell
(Get-FileHash -Algorithm SHA256 '.embeddedskills\tools\shakedown_toolchain\ground_shakedown.py').Hash
(Get-FileHash -Algorithm SHA256 'simulation\digital_twin\tests\test_ground_shakedown.py').Hash
git status --short --branch
```

The hashes must be exactly:

```text
D330500F77DB1C0730396359A1D6CD0ABF72C52B6744372DA700AB9107B90BE7
23C72E5974A988663D648A810C19920BC4C0B1D1787DA8979DD1175879A24190
```

Create the DS evidence directory only if it does not exist. Record both full hashes, UTC/local timestamps, Python version, current branch, and the actual read-only `git status` output in `pre_edit_hashes.json`. Do not copy or normalize the source files, because that would invalidate the locked baseline.

- [ ] **Step 2: Make the test doubles declare bounded I/O and migrate old F2**

Add `io_timeout_s = 0.1` to `FirmwareScriptTransport`; all subclasses inherit it. Preserve its current 0.01-second queue timeout and synchronous ACK/status behavior.

Replace `test_collection_exception_stops_heartbeat_before_stop`, which monkeypatches the soon-to-be-removed `soak._collect`, with a fake transport that raises from the authorized running-window receive path:

```python
class RunningReceiveErrorTransport(FirmwareScriptTransport):
    def __init__(self, run_id):
        super().__init__(run_id)
        self._running_receive_armed = False

    def send(self, data):
        super().send(data)
        body = self.control_bodies[-1]
        if body.startswith("H,"):
            self._running_receive_armed = True

    def recv(self, max_bytes):
        if self._running_receive_armed and self._rx.empty():
            self._running_receive_armed = False
            raise OSError("injected running receive failure")
        return super().recv(max_bytes)


def test_running_receive_exception_deactivates_heartbeat_before_stop():
    transport = RunningReceiveErrorTransport("gnd00000012")
    result = run_ground_session(transport, "shake", "gnd00000012", 0.3)
    assert result["control_verdict"] == "FAIL"
    assert "OSError" in result["unexpected_exception"]
    assert result["heartbeat"]["started"] is True
    assert result["heartbeat"]["stopped_before_final_stop"] is True
    assert result["heartbeat"]["active_at_terminal_stop_reservation"] is False
    assert transport.control_bodies[-1] == "R,shake,gnd00000012,STOP"
    final_stop = len(transport.control_bodies) - 1
    heartbeats = [
        i for i, body in enumerate(transport.control_bodies)
        if body.startswith("H,")
    ]
    assert (not heartbeats) or max(heartbeats) < final_stop
```

This migration preserves F2 behavior and removes the obsolete internal monkeypatch. It is not permission to edit the historical soak module.

- [ ] **Step 3: Add all replacement regression tests before production edits**

Import `math` and `threading` in the test file. Add these five required tests with deterministic in-memory transports/loggers. Each test must invoke the real `run_ground_session()` and assert returned behavior, not source text.

```python
def test_all_public_status_records_include_host_receive_provenance():
    result = run_ground_session(
        SentinelIdentityTransport("gnd00000024"),
        "shake", "gnd00000024", 0.05,
    )
    public_statuses = [
        result["initial_status"],
        result["pre_stop"]["status"],
        result["start"]["status"],
        result["stop"]["status"],
    ] + result["statuses"]
    assert public_statuses
    for status in public_statuses:
        assert isinstance(status["receive_seq"], int)
        assert status["receive_seq"] > 0
        assert isinstance(status["receive_monotonic_s"], float)
        assert math.isfinite(status["receive_monotonic_s"])
    assert [s["receive_seq"] for s in result["statuses"]] == sorted(
        s["receive_seq"] for s in result["statuses"]
    )
```

For `test_single_owner_calls_transport_and_live_raw_logger_only_on_calling_thread`, create subclasses that append `threading.get_ident()` in every `send`, `recv`, `close`, `log_send`, `log_recv`, `events`, and `write` call before delegating to the working base implementation. Run a 0.25-second successful session and assert every recorded ID equals the calling thread ID. Also assert `control_verdict == "PASS"` and `quiescence.proven is True`.

For `test_late_heartbeat_send_exceeds_io_budget_fails_and_no_heartbeat_follows_stop_reservation`, sleep 0.18 seconds during the first `H` send, while all other fake operations remain bounded. Assert:

```python
assert result["control_verdict"] == "FAIL"
assert result["primary_failure"]["code"] == "IO_CALL_BUDGET_EXCEEDED"
assert result["heartbeat"]["active_at_terminal_stop_reservation"] is False
assert transport.control_bodies[-1].endswith(",STOP")
stop_index = max(
    i for i, body in enumerate(transport.control_bodies)
    if body.endswith(",STOP")
)
assert not any(
    body.startswith("H,")
    for body in transport.control_bodies[stop_index + 1:]
)
```

For `test_primary_parameter_send_failure_survives_non_oserror_terminal_stop_failure`, make P2 `send()` raise `OSError("primary P2 failure")`. Make the second STOP invocation enqueue a correlated `STOPPED/STOP` and then raise `RuntimeError("secondary STOP failure")`, modeling a possibly partial transmission. Assert the function returns rather than raises, the P2 failure is the immutable primary, the STOP failure appears later in `secondary_errors`, and the complete STOP record says:

```python
assert result["stop"]["attempted"] is True
assert result["stop"]["rollback_requested"] is True
assert result["stop"]["cmd_sent"] is False
assert result["stop"]["send_outcome"] == "AMBIGUOUS_EXCEPTION"
assert result["stop"]["confirmed"] is True
assert result["cut_power_warning"] is True
```

For `test_late_receive_cannot_mutate_frozen_raw_evidence_or_pass`, use `monkeypatch` to set `STATUS_TIMEOUT_S` to 0.05 seconds and call `run_ground_session(transport, "shake", "gnd00000028", duration_s=0.30, raw_logger=logger)`. Return START/RUNNING normally; after at least one heartbeat has been recorded and the RX queue is empty, make one running-window `recv()` sleep 2.7 seconds and return one finite `b"LATE_RX\n"` chunk. The 2.7-second delay exceeds the rejected implementation's 0.30-second collection window, 0.05-second terminal-status wait, 2-second reader join, and 0.25-second margin, so it deterministically reproduces the old post-publication writer. Mark this fake explicitly as a fault injector that intentionally violates its declared 0.1-second contract; it is not a supported transport. Use a raw logger whose `write()` stores a frozen copy of its events. Assert `IO_CALL_BUDGET_EXCEEDED`, `control_verdict == "FAIL"`, `quiescence.proven is True` only if close completed, `quiescence.n_frozen_raw_events` equals both the returned event count and the publication snapshot, and all three remain unchanged after a 0.5-second wait. In the replacement architecture the slow receive returns before STOP/close/freeze because the caller owns it; in the rejected architecture the old reader can append after `write()`/return, so the mutation assertion is RED.

Add these five boundary tests before production edits as well:

```text
test_pre_stop_ambiguous_send_is_promoted_without_a_second_stop
test_rejects_missing_or_invalid_bounded_io_declaration_before_control_io
test_active_raw_log_failure_is_primary_and_still_attempts_terminal_stop
test_final_raw_write_failure_preserves_control_verdict_and_marks_unpublished
test_late_or_failing_close_forces_fail_and_unproven_quiescence
```

The pre-STOP test raises after enqueuing its first STOP confirmation and asserts exactly one STOP invocation, no P/START, `send_outcome == "AMBIGUOUS_EXCEPTION"`, a confirmed promoted `stop`, and control FAIL. The declaration test covers a missing declaration, string, `True`, `NaN`, infinity, zero, negative, and `0.100001`, plus separate transports missing each of `send`, `recv`, and `close`; duration validation covers `True`, negative, `NaN`, and infinity. Every fake transport/raw method present in these cases raises if called, and the returned result must show no dependency call, no STOP attempt, no close, `quiescence.proven == False`, and `cut_power_warning == True`. The active raw-log test lets the P transport send return, raises only from that P command's `log_send`, and proves the transport outcome was not reclassified as a send exception before terminal STOP. Extend the existing final-write test with `raw_io.published is False`, a non-empty `raw_io.write_error`, unchanged control PASS, and no primary failure. Parameterize the close test over a 0.18-second successful close and `RuntimeError("injected close failure")`; both paths close exactly once, force control FAIL, and set `quiescence.proven=false`. The late-close primary code is `IO_CALL_BUDGET_EXCEEDED`; the exception primary code is `TRANSPORT_CLOSE_EXCEPTION`.

- [ ] **Step 4: Run and record RED for every load-bearing replacement test**

Run each of the five required tests separately against the still-locked production hash:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py::test_all_public_status_records_include_host_receive_provenance
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py::test_single_owner_calls_transport_and_live_raw_logger_only_on_calling_thread
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py::test_late_heartbeat_send_exceeds_io_budget_fails_and_no_heartbeat_follows_stop_reservation
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py::test_primary_parameter_send_failure_survives_non_oserror_terminal_stop_failure
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py::test_late_receive_cannot_mutate_frozen_raw_evidence_or_pass
```

Every command must exit nonzero for its named behavioral defect, not for a syntax/import/setup error. Record command, output, exit code, expected defect, and observed assertion in `red_results.json`. Run the five boundary tests and record their RED outcomes too. Recompute the production hash after RED; it must still equal `D330500F77DB1C0730396359A1D6CD0ABF72C52B6744372DA700AB9107B90BE7`. Do not begin production edits until this complete RED gate is recorded.

Run the migrated F2 test and all five boundary tests explicitly:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py::test_running_receive_exception_deactivates_heartbeat_before_stop
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py::test_pre_stop_ambiguous_send_is_promoted_without_a_second_stop simulation/digital_twin/tests/test_ground_shakedown.py::test_rejects_missing_or_invalid_bounded_io_declaration_before_control_io simulation/digital_twin/tests/test_ground_shakedown.py::test_active_raw_log_failure_is_primary_and_still_attempts_terminal_stop simulation/digital_twin/tests/test_ground_shakedown.py::test_final_raw_write_failure_preserves_control_verdict_and_marks_unpublished simulation/digital_twin/tests/test_ground_shakedown.py::test_late_or_failing_close_forces_fail_and_unproven_quiescence
```

The migrated F2 test must be RED on the missing `active_at_terminal_stop_reservation` evidence or another named single-owner defect, not on setup timing. Every newly added boundary assertion must likewise be RED for the missing single-owner contract before production edits.

- [ ] **Step 5: Replace the threaded internals with `_SessionLoop`**

Remove Task 1's `threading.Thread`, `_HeartbeatSession`, `_heartbeat_worker`, reader-loop startup, `soak._collect()`, and every early return inside the owned session. Keep `ControlAwareMixedStreamParser`. `AckSessionContext` may remain as a passive compatibility/evidence accumulator, but it must not start or own I/O.

Use these exact constants:

```python
HEARTBEAT_PERIOD_S = 0.2
MAX_DECLARED_IO_TIMEOUT_S = 0.1
IO_CALL_BUDGET_S = 0.15
```

Implement `_failure(stage, code, detail, now) -> dict` with exactly the keys `stage`, `code`, `detail`, and rounded `monotonic_s`. Implement `_SessionLoop.__init__(transport, campaign_id, run_id, duration_s, raw_logger)` as state initialization only and `_SessionLoop.run() -> dict` as the single convergence path described below.

`_SessionLoop` owns these state groups:

```text
receive_seq and parsed event envelopes
telemetry frames, health frames, statuses, ACKs, parse errors, anomalies
phase deadline and derived overall deadline
heartbeat started/active/count/failure/next deadline
primary_failure and ordered secondary_errors/cleanup_errors
pre-STOP record and once-only terminal STOP state
transport close count/outcome
frozen raw events and raw publication outcome
one result dictionary built only after finalization
```

At loop entry, derive the overall deadline as the sum of the 2-second initial-status budget, 2-second pre-STOP budget, five 5-second ACK budgets, 2-second START-confirm budget, authorized `duration_s`, 2-second terminal-STOP budget, and 1-second scheduling margin. Each phase still uses its own deadline capped by the overall deadline; neither input draining nor the overall ceiling may extend a phase.

Validate `duration_s` and the timeout declaration before constructing `_SessionLoop`. Reject `bool`, non-numeric, non-finite, non-positive timeout declarations, declarations above 0.1, boolean/negative/non-finite duration, and missing or non-callable `send`/`recv`/`close`. The preflight-failure result must call no dependency method and use the exact result semantics from the specification.

The preflight-failure result has this complete public shape; `detail` contains the precise rejected field/value and `health` is computed locally as `soak.compute_health_summary([])`:

```python
{
    "run_mode": "run",
    "control_verdict": "FAIL",
    "cut_power_warning": True,
    "aborted_before_collect": True,
    "initial_status": None,
    "pre_stop": {"cmd_sent": False, "confirmed": False,
                 "status": None, "failure_reason": "PRESESSION_VALIDATION",
                 "cmd_hex": None},
    "speed_override": {"applied_speeds": [], "validated": False,
                       "failure_reason": "PRESESSION_VALIDATION"},
    "start": {"cmd_sent": False, "confirmed": False,
              "status": None, "failure_reason": "PRESESSION_VALIDATION",
              "cmd_hex": None},
    "stop": {"attempted": False, "rollback_requested": False,
             "cmd_sent": False, "send_outcome": "NOT_INVOKED",
             "send_error": None, "confirmed": False,
             "stop_confirmed": False, "status": None,
             "failure_reason": "PRESESSION_VALIDATION", "cmd_hex": None,
             "reservation_monotonic_s": None, "reserved_receive_seq": 0,
             "io_budget_exceeded": False},
    "parameter_acks": [],
    "protocol_anomalies": [],
    "statuses": [],
    "parse_errors": [],
    "telemetry": {"n": 0, "frames": []},
    "health_raw": [],
    "health": soak.compute_health_summary([]),
    "raw": {"n_rx_events": 0, "n_tx_events": 0,
            "n_rx_bytes": 0, "n_tx_bytes": 0},
    "rollback_requested": False,
    "stop_confirmed": False,
    "heartbeat": {"started": False, "ok": True, "n_sent": 0,
                  "failure": None, "stopped_before_final_stop": None,
                  "active_at_terminal_stop_reservation": None},
    "cleanup_errors": [],
    "unexpected_exception": None,
    "primary_failure": {"stage": "preflight",
                        "code": "PRESESSION_VALIDATION",
                        "detail": detail,
                        "monotonic_s": finite_monotonic_time},
    "secondary_errors": [],
    "quiescence": {"proven": False, "freeze_monotonic_s": None,
                   "n_frozen_raw_events": 0},
    "raw_io": {"published": False,
               "write_error": "NOT_ATTEMPTED_PRESESSION_VALIDATION"},
}
```

Wrap each transport operation with monotonic timing. A returned call over 0.15 seconds has completed, so preserve its actual return/`cmd_sent` outcome while recording `IO_CALL_BUDGET_EXCEEDED` and forcing control FAIL. A send exception is always `AMBIGUOUS_EXCEPTION`; it is never proof that zero bytes were sent. Catch `Exception` for dependency failures and handle `KeyboardInterrupt` through the same structured fail-closed convergence.

For a command send, keep transport and raw logging as two ordered, independent outcomes:

```text
capture receive boundary
invoke and time transport.send(command)
record completed return or ambiguous exception
invoke raw_logger.log_send(command), even after an ambiguous send exception
record raw-log success or active evidence failure independently
```

An active raw-log exception forces FAIL and terminal STOP but does not change `cmd_sent` or `send_outcome`. `unexpected_exception` mirrors only the first exception-backed primary failure; `primary_failure` remains authoritative.

- [ ] **Step 6: Implement receive envelopes, gates, and synchronous scheduling**

When the parser completes an ACK/status line, increment one shared sequence and capture `time.monotonic()` once. Store exactly one JSON-serializable envelope:

```python
{
    "kind": "ack" or "status" or "parse_error",
    "receive_seq": sequence,
    "receive_monotonic_s": round(received_at, 6),
    "raw_line": line,
    "parsed": parsed_dict_or_none,
    "error": error_or_none,
}
```

The public ACK record and every public status record copy the envelope provenance. `initial_status`, `pre_stop.status`, `start.status`, `stop.status`, and every item in `statuses` must carry `receive_seq` and `receive_monotonic_s`. MCU `tick_ms` remains separate.

Before each command boundary, synchronously drain already-buffered input until one bounded `b""` timeout so pre-existing events receive pre-boundary sequence numbers. Draining remains capped by the active phase and overall deadlines; continuous input that prevents a bounded boundary fails closed. For each P gate, the first ACK or ACK parse error is decisive. For each R gate, the first status or status parse error is decisive. A stale required-kind event, parse error, identity mismatch, wrong state/reason, rejection, EOF, receive exception, or deadline expiry fails the gate; unrelated event kinds remain evidence and cannot satisfy it.

The control sequence is exactly:

```text
first valid connection status, with any identity
pre-STOP and correlated STOPPED/STOP
P1 through P5 with one APPLIED/APPLIED ACK each
START and correlated RUNNING/START
immediate heartbeat
bounded running receive/heartbeat loop
deactivate heartbeat scheduling
terminal STOP and correlated STOPPED/STOP
```

After RUNNING confirmation, invoke the first heartbeat immediately on the calling thread. Set the next deadline to successful/returned completion time plus 0.2 seconds. Before every running-window receive, check the heartbeat deadline. Never burst missed heartbeats. If the current time is at least one full heartbeat period past a deadline, record a scheduling failure. Any heartbeat send/raw/I/O-budget failure deactivates scheduling before terminal STOP reservation.

Replace the old F2 collection behavior with the running loop itself: a running `recv()` exception becomes the immutable primary failure, heartbeat scheduling becomes inactive, and all paths converge on terminal STOP.

- [ ] **Step 7: Implement once-only STOP, close, freeze, publication, and result build**

Allocate the terminal STOP dictionary at reservation, before encoding or sending. It must always include:

```text
attempted
rollback_requested
cmd_sent
send_outcome
send_error
confirmed
stop_confirmed
status
failure_reason
cmd_hex
reservation_monotonic_s
reserved_receive_seq
io_budget_exceeded
```

Set `rollback_requested=true` when STOP send invocation begins. Set `cmd_sent=true` only after transport send returns. On any send exception, use `send_outcome="AMBIGUOUS_EXCEPTION"`, keep the exception as evidence, and still service the bounded confirmation window. Set `cut_power_warning=true` unless send returned successfully, stayed inside budget, live raw logging succeeded, and a correlated STOP confirmation arrived.

Pre-STOP is a separate transaction. If its send, raw log, or confirmation fails, promote that exact record to `stop`, send no second STOP, send no P/START, and converge on close/freeze/publication. After a successful pre-STOP, terminal STOP may be reserved exactly once. Once reserved, reject any later non-STOP command attempt as an internal control failure.

Finalize in this exact order, with no return before the end:

```text
1. finish/fail terminal STOP confirmation
2. call and time transport.close exactly once
3. copy raw_logger.events into a stable frozen list
4. set quiescence freeze timestamp and frozen count
5. call raw_logger.write exactly once
6. build one result from frozen control/raw evidence
7. return with no possible later mutation
```

A close exception or close budget overrun forces control FAIL and `quiescence.proven=false`. A final `events()` freeze failure also prevents quiescence proof and PASS. A final `write()` failure adds ordered secondary and cleanup evidence, sets `raw_io.published=false` and `raw_io.write_error`, but does not change the already-determined control verdict or primary failure.

Preserve these compatibility keys and meanings:

```text
control_verdict, cut_power_warning, aborted_before_collect
initial_status, pre_stop, speed_override, start, stop
parameter_acks, protocol_anomalies, statuses, parse_errors
telemetry, health_raw, health, raw
rollback_requested, stop_confirmed, heartbeat
cleanup_errors, unexpected_exception
```

Add the specification keys:

```text
primary_failure, secondary_errors
quiescence.proven, quiescence.freeze_monotonic_s
quiescence.n_frozen_raw_events
heartbeat.active_at_terminal_stop_reservation
stop.send_outcome, stop.reservation_monotonic_s
stop.reserved_receive_seq
raw_io.published, raw_io.write_error
```

Set `heartbeat.stopped_before_final_stop` to `None` when scheduling never started. When it did start, it is true only if scheduling was inactive before terminal STOP reservation. Set control PASS only after all five ACK gates, START/RUNNING, heartbeat timing, terminal STOP send/confirmation, close, and quiescence proof succeed with no primary failure; every other control or quiescence path is FAIL.

- [ ] **Step 8: Run focused GREEN tests, then the full offline regression gate**

First rerun every test named in Steps 2 and 3. All must pass. Then run:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py
py -3.11 -m pytest -q .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py
py -3.11 -m pytest -q simulation/digital_twin/tests/test_runtime_protocol.py
py -3.11 -m py_compile .embeddedskills/tools/shakedown_toolchain/ground_shakedown.py
```

Required outcomes are at least 24 Task 1 tests passed, exactly 41 historical transport tests passed, exactly 34 runtime-protocol tests passed, compilation exit 0, and no warning/error output. If a test exposes a new defect, add the smallest failing regression first, observe RED for that defect, then repair production and rerun all four commands.

- [ ] **Step 9: Write immutable DS evidence and self-review report**

Write `verification_results.json` with every command, complete summary output, exit code, duration, and test count. Write `implementation_manifest.json` with final SHA-256 for both modified files, the approved spec hash, exact modified paths, exact created evidence/report paths, and explicit statements that no hardware-capable action or Git write occurred.

Write the DS report at the locked report path with these headings:

```text
Status: DONE | DONE_WITH_CONCERNS | BLOCKED
Scope and safety boundary
Locked pre-edit hashes
RED evidence for each required test
Implementation summary
Changed and created files
GREEN and regression commands/results/exit codes
Final hashes
Self-review against every specification section
Unverified items and concerns
Codex acceptance handoff
```

Self-review must explicitly search production code for `threading.Thread`, `_HeartbeatSession`, `_heartbeat_worker`, `soak._collect`, early `return` statements inside the owned lifecycle, duplicate STOP sends after reservation, and result mutation after raw publication. Explain every remaining match. Do not claim acceptance: DS may report implementation complete, but Task 1 remains blocked until Codex independently verifies and a fresh reviewer returns both PASS verdicts.

## Controller Acceptance Gate

After DS reports completion, Codex, not the implementer, creates `.embeddedskills/build/v1_ground_shakedown_single_owner_codex_acceptance_20260805_r1/`, re-runs all four verification commands, independently probes every five load-bearing defect plus F1-F9, locks final source/test hashes, and creates a review package from explicit pre-edit snapshots or hashes without Git writes. A fresh independent reviewer must return both `SPEC_COMPLIANCE: PASS` and `CODE_QUALITY: PASS` on those stable hashes. Any REJECT or hash drift keeps Task 2 `BLOCKED_PENDING_TASK1_FINAL_REVIEW`.
