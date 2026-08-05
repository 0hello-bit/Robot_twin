# Claude Code Persistent Context Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every fresh Claude Code session a small automatic project context and a single-task handoff, then repair the false-passive transport soak behavior.

**Architecture:** Root `CLAUDE.md` is the stable entrypoint, `docs/agent-context/CURRENT_STATUS.md` is the mutable verified snapshot, and one handoff file defines the active task. Product debugging remains in the execution agent; Codex only checks the final diff and test evidence.

**Tech Stack:** Markdown, Python 3.11, pytest, existing `transport_soak.py` and `test_transport_soak_rework.py`.

## Global Constraints

- Do not scan the entire repository when the named entrypoint and handoff are sufficient.
- Do not connect hardware, open TCP, flash, reset, send START, or operate motors during the repair.
- Do not execute Git writes.
- Keep verified facts, inference, and unverified items separate.
- Passive mode must transmit exactly zero bytes.

---

### Task 1: Persistent context files

**Files:**
- Create: `CLAUDE.md`
- Create: `docs/agent-context/CURRENT_STATUS.md`
- Create: `docs/agent-context/handoffs/2026-08-03-transport-soak-passive-fix.md`

**Interfaces:**
- Consumes: `docs/Robot_Twin_AI_完整计划说明书_v2.0.md` as the long-form authority.
- Produces: a two-file startup contract: `CLAUDE.md` plus exactly one named handoff.

- [ ] **Step 1:** Write `CLAUDE.md` with project goal, authority order, safety rules, and the instruction to read only `CURRENT_STATUS.md` plus the named handoff.
- [ ] **Step 2:** Record the fresh MCU/ESP/camera facts and the false-passive incident in `CURRENT_STATUS.md`.
- [ ] **Step 3:** Write the task handoff with exact allowed files, forbidden hardware actions, red/green test requirements, and final report format.
- [ ] **Step 4:** Scan the three files for personal absolute paths, secrets, placeholders, contradictory status, and excessive duplicated history.

### Task 2: Claude Code repair handoff

**Files:**
- Modify: `.embeddedskills/build/v1_task4b4/transport_soak.py`
- Modify: `.embeddedskills/build/v1_task4b4/test_transport_soak_rework.py`

**Interfaces:**
- Consumes: CLI flag `--run` and `capture_session(..., run_mode, ...)`.
- Produces: passive execution with `n_send == 0`; run mode retains pre-STOP, START, heartbeat, and final STOP safety handshake.

- [ ] **Step 1:** Add a failing regression test that invokes the no-`--run` control path with a scripted transport and asserts no calls to `sendall` and `raw_io.n_send == 0`.
- [ ] **Step 2:** Run the targeted test and retain the RED output proving the current code sends control frames.
- [ ] **Step 3:** Replace ambiguous display strings as control values with one canonical internal mode value or boolean; format display labels only at report time.
- [ ] **Step 4:** Run the targeted test and retain GREEN output.
- [ ] **Step 5:** Run the full `test_transport_soak_rework.py` suite and relevant health parser tests; report exact counts and exit codes.
- [ ] **Step 6:** Confirm no hardware/network calls occurred and provide changed files, root cause, test results, remaining risks, and next interface.

### Task 3: Codex acceptance

**Files:**
- Read only: the two modified Python files and Claude Code report.

- [ ] **Step 1:** Inspect the focused diff for scope and mode consistency.
- [ ] **Step 2:** Independently run the new passive zero-TX test and full targeted suite.
- [ ] **Step 3:** Accept only if zero-TX is executable evidence and run-mode safety tests remain green.
