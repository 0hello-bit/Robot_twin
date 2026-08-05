# Robot Twin AI - Canonical Workspace

This directory is the only active workspace for the Robot Twin AI project:

C:\Users\24668\Desktop\stm32小车\数字孪生

The parent directory is an outer container containing legacy code, unrelated
files, old build outputs, and historical evidence. Do not search it by default,
do not create new work there, and do not treat old copies as current sources.

## Read First

1. docs/agent-context/CURRENT_STATUS.md
2. docs/Robot_Twin_AI_完整计划说明书_v2.7.md
3. The handoff explicitly named by the current task
4. Only the source files and tests required by that handoff

The v2.6 plan and CURRENT_STATUS_LEGACY_20260803.md are historical records.
They must not override the v2.7 plan or the current status file.

## Project Proposition

The long-term goal is an AI-led robot R&D loop:

real behavior -> problem/hypothesis -> algorithm, firmware, or hardware candidate -> digital-twin screening -> real deployment -> real validation -> feedback

The current V1 is only the offline digital-twin foundation and the first
bounded PID candidate payload. It is not proof that AI can already modify core
algorithms or design usable hardware.

## Current Accepted Boundary

- V1-A offline foundation is accepted as software-only.
- The closed loop connects the controller, plant, virtual sensor, prediction,
  and deterministic candidate ranking.
- The plant parameters are synthetic/exploratory.
- Real synchronized calibration, independent holdout evidence, and real-car
  improvement are still unverified.
- Current V1 does not connect hardware, flash firmware, start motors, or run a
  camera/serial/TCP session without explicit authorization.

## Evidence Rules

- Separate VERIFIED, INFERENCE, and INSUFFICIENT EVIDENCE.
- A passing unit test is not real-hardware evidence.
- A synthetic plant is not a calibrated digital twin.
- The model may be a black box, but the experiment protocol may not be one.
- A candidate is eligible only when it completes the scenario without line
  loss; otherwise the evaluator must not select it or report READY.

## Workspace Rules

- All new source, tests, plans, handoffs, and evidence belong under this
  directory.
- Do not write new files to the parent workspace.
- Do not connect, flash, reset, or control the real car unless the user gives
  authorization for that specific hardware task.
- Do not modify or delete historical evidence to make a new result look clean.
- Do not perform Git write operations unless separately authorized.
- Each agent handles one bounded task, reports changed files and fresh test
  output, lists unverified items, and stops at its handoff boundary.
