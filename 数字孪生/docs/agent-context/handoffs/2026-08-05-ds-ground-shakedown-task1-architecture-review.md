# DS Task 1 Lifecycle Architecture Review

Status: `AUTHORIZED_READ_ONLY_ANALYSIS_ONLY`

Date: 2026-08-05

This is not Fix Round 4. Do not edit production code, tests, plans, existing
evidence, or Git state. Do not open a camera or TCP connection and do not use
serial, debugger, Keil, flash, reset, hardware, or motion commands.

## Purpose

Three bounded patch rounds passed their then-current tests but each exposed a
new shared-state or resource-lifecycle defect. Determine the root architectural
cause and recommend a replacement design before any further implementation.

## Read Completely

1. `.embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_fix_r3_rejection.md`
2. `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`
3. `simulation/digital_twin/tests/test_ground_shakedown.py`
4. `.embeddedskills/build/v1_task4b4/transport_soak.py`
5. `simulation/digital_twin/real_world/runtime_protocol.py`
6. `docs/superpowers/specs/2026-08-04-ground-shakedown-recorder-design.md`
7. `docs/superpowers/plans/2026-08-04-ground-shakedown-recorder.md`

Firmware source may be consulted read-only only to confirm protocol facts:
`程序/3. 麦轮巡线小车/User/twin_control_protocol.c`.

## Required Analysis

Trace all resource/data ownership from transport construction through reader,
ACK/status parsing, heartbeat, STOP, reader termination, transport close, raw
snapshot, and result publication. Explain why the current design permits:

1. loss of host receive time on status evidence;
2. a heartbeat worker to remain alive after the owner claims it stopped;
3. a secondary STOP exception to hide the primary failure;
4. a blocked reader to race raw evidence publication.

Compare at least these approaches, adding another only if materially distinct:

- one single-owner event loop schedules reads, heartbeat deadlines, commands,
  and evidence without background heartbeat ownership;
- a structured worker supervisor retains explicit ownership until every worker
  reaches a terminal state, using close-to-unblock then bounded re-join before
  evidence freeze;
- process isolation for the complete control session, with the parent treating
  child termination and an atomic result envelope as the lifecycle boundary.

For each approach, assess safety behavior, testability with deterministic fake
transports, compatibility with the current synchronous transport API, change
size, and residual risk. Recommend one design. Do not write code.

## Non-Negotiable Design Contracts

- one authoritative owner publishes exactly one terminal result;
- preserve the primary failure and append cleanup failures separately;
- STOP attempt reservation, send outcome, status confirmation, and evidence
  publication are distinct states; no exception can leave the STOP record
  absent;
- every parsed ACK/status has host receive sequence and monotonic time before
  entering any queue or public result;
- no worker may be reported stopped while still alive;
- raw evidence is frozen only after reader/heartbeat quiescence is proven;
- failure to prove quiescence is a structured FAIL and forbids evidence PASS;
- no automatic START retry and no command after terminal STOP reservation;
- Task 1 emits only `control_verdict`; Task 2 owns the overall verdict;
- tests must use real `run_ground_session()` behavior and deterministic
  blocking/fault transports, with RED evidence before replacement code.

## Output

Write only:

`.embeddedskills/build/v1_ground_shakedown_codex_acceptance_20260805_r1/task1_architecture_analysis_ds.md`

The report must contain:

1. root-cause statement;
2. current ownership/data-flow map;
3. approach comparison;
4. recommended architecture and exact lifecycle sequence;
5. proposed public/internal interfaces;
6. mandatory RED test matrix for all four rejection findings plus nominal and
   existing F1-F9 regressions;
7. open assumptions or issues requiring user choice.

End with exactly one line:

`ARCHITECTURE_RECOMMENDATION: READY_FOR_CONTROLLER_REVIEW`

