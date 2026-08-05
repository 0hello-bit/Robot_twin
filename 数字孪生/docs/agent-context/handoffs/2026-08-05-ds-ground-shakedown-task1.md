# DS Handoff: Ground Shakedown Recorder Task 1

## Role

You are the bounded implementer for the offline ACK-aware control core only.
Codex is the controller and independent acceptor.

Read this file first; it is the complete Task 1 requirements source:

`C:\Users\24668\Desktop\stm32小车\.superpowers\sdd\2026-08-04-ground-shakedown-recorder\task-1-brief.md`

The brief includes a 2026-08-05 correction. In particular, the historical
`MixedStreamParser` does not forward `A,` lines, so merely overriding
`AckSessionContext._on_line()` is insufficient. Implement and test the local
`ControlAwareMixedStreamParser` exactly within the brief's boundary.

## Binding Boundaries

- Offline only. Do not connect to `192.168.110.236` or any other host/device.
- Do not open/probe a camera, serial port, debugger, ST-Link, ESP, or Keil.
- Do not flash, reset, or issue any real runtime/motion command.
- Do not use any Git write command: no add, commit, checkout, switch, branch,
  stash, reset, clean, push, pull, or worktree creation.
- Preserve every unrelated dirty or untracked file.
- Modify only these two Task 1 files:
  - `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`
  - `simulation/digital_twin/tests/test_ground_shakedown.py`
- Treat `.embeddedskills/build/v1_task4b4/transport_soak.py` and all historical
  evidence as read-only.
- You may create generated logs only under the new
  `.embeddedskills/build/v1_ground_shakedown_offline_20260805_r1/` directory.
  If it exists before you start, stop with `BLOCKED_EVIDENCE_EXISTS`.
- Do Task 1 only. Do not implement ffmpeg, camera lifecycle, final CLI, or any
  Task 2 behavior.

## Required TDD Workflow

1. Create tests first and run the named parser/success tests to obtain a real
   RED caused by the missing production module/API, not by a typo or bad path.
2. Implement the minimal A/S mixed-stream adapter and success sequence; run
   GREEN.
3. Add each rejected/malformed/mismatched ACK and final-STOP/heartbeat test
   before the production behavior that makes it pass. Preserve the individual
   RED outputs.
4. Run the complete Task 1 test file, then the directly affected historical
   transport-soak and runtime-protocol regressions.
5. Run `py -3.11 -m py_compile` on the new tool.
6. Review scope and verify no hardware-capable top-level call executes on
   import. Use `apply_patch` for manual file edits.

## Report Contract

Write the full report to:

`C:\Users\24668\Desktop\stm32小车\.superpowers\sdd\2026-08-04-ground-shakedown-recorder\task-1-report.md`

The report must contain:

- status: `DONE`, `DONE_WITH_CONCERNS`, or `BLOCKED`;
- files created/modified and SHA-256 hashes;
- every RED command, expected failure, exit code, and log path;
- every GREEN/full-regression command, pass count, exit code, and log path;
- parser evidence for fragmented A/S, binary-noise isolation, malformed ACK,
  and campaign/version mismatch;
- command-order and fail-closed evidence: pre-STOP, five P/ACK gates, START,
  heartbeat, final STOP;
- exact statement that no network, camera, serial, debugger, Keil, flash,
  hardware, motion, or Git write occurred;
- concerns and remaining Task 2/hardware-only work.

After writing the report, stop. Do not continue to Task 2.
