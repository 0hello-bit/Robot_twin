# DS Handoff: PWM Permille Scale Repair

## Role

You are the bounded implementer for one offline firmware task. Codex is the
controller and independent acceptor.

Read this requirements file first and follow it completely:

`C:\Users\24668\Desktop\stm32小车\.superpowers\sdd\2026-08-05-pwm-permille-scale-repair\task-1-brief.md`

## Binding Boundaries

- Offline only. Do not connect to `192.168.110.236` or any other device.
- Do not open or probe a camera, serial port, debugger, ST-Link, or ESP.
- Do not flash, reset, or issue any motion/runtime command.
- Do not use any Git write command: no add, commit, checkout, switch, branch,
  stash, reset, clean, push, or pull.
- Preserve every unrelated dirty or untracked file.
- Do not modify PID, directions, motor grouping, sensors, lost-line behavior,
  transport, heartbeat, STOP, rollback, or runtime bounds.
- You may edit only the production/test files listed in the brief and may write
  new evidence under the named `v1_pwm_permille_repair_20260805_r1` directory.
- If the evidence directory already exists before you start, stop and report
  `BLOCKED_EVIDENCE_EXISTS`; never overwrite it.

## Required Workflow

1. Create the test stub and real-`Motor.c` host test.
2. Snapshot and hash the untouched production `Motor.c`.
3. Compile and run RED. The acceptable RED is a runtime ARR assertion, not a
   compiler/path error.
4. Make the minimal production change.
5. Compile and run GREEN.
6. Run the named Python regressions.
7. Enumerate and rebuild Keil `Target 1`; never invoke flash.
8. Review the pre/post source diff with `git diff --no-index` and verify scope.

Use `apply_patch` for manual file edits. Build tools may write their normal
outputs. Do not overwrite historical evidence.

## Report Contract

Write the full report to:

`C:\Users\24668\Desktop\stm32小车\.superpowers\sdd\2026-08-05-pwm-permille-scale-repair\task-1-report.md`

The report must contain:

- status: `DONE`, `DONE_WITH_CONCERNS`, or `BLOCKED`;
- files created/modified;
- SHA-256 before and after for production `Motor.c`;
- exact RED compile/run commands, exit codes, and failing assertion;
- exact GREEN compile/run commands, exit codes, and output;
- pytest command/count/exit code;
- Keil target enumeration and rebuild command, errors/warnings, exit code,
  log path, HEX path, and AXF path;
- exact product diff summary;
- explicit statement that no hardware/network/camera/flash/Git write occurred;
- concerns and remaining hardware-only verification.

After writing the report, stop. Do not continue to another roadmap task.
