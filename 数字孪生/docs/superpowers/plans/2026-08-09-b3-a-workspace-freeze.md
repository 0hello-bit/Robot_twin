# B3-A Workspace Freeze and Hardware Handoff Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the current B3-A offline transport and camera-observation work in a reversible Git checkpoint, while keeping large local capture media outside the repository and stopping before hardware action.

**Architecture:** The canonical `数字孪生` directory remains the only active project root. Reproducible source, tests, reports, and handoffs are versioned; generated build objects and large raw camera captures remain local or in the existing archive. The resulting checkpoint is an offline handoff only: the next interface is separately authorized A firmware flashing followed by a bounded hardware run.

**Tech Stack:** Git, PowerShell, Python 3.11, existing digital-twin Python/Host C tests, and the existing Keil project. Python 3.13 and nRF24L01 are out of scope for this checkpoint.

## Global Constraints

- Do not delete source code, formal experiment data, camera evidence, firmware artifacts, or other agent changes.
- Do not flash firmware, connect to ST-Link, send ESP commands, start/stop the car, or invoke the camera hardware in this checkpoint.
- Do not implement or flash transport scheme C; do not add nRF24L01, encoder logic, PID changes, AprilTag threshold changes, or control-algorithm changes.
- Preserve the existing AA55 protocol, P/R/A/S control path, heartbeat, STOP safety behavior, and campaign/session storage.
- Keep the freshly rebuilt offline A artifact identified in the handoff by
  its verified SHA-256 as the intended hardware candidate; do not reuse an
  older AXF solely because its hash appears in a historical handoff.
- Raw camera media larger than the repository checkpoint remains available on disk and is recorded as local-only evidence.

---

### Task 1: Classify and archive generated root artifacts

**Files:**
- Move: `数字孪生/twin_control_protocol.obj`
- Move: `数字孪生/twin_control_trace_runner.obj`
- Archive destination: `数字孪生/archive/generated_workspace_20260809/project_root_objects/`

**Interfaces:**
- Consumes: the two generated Host C object files currently at the project root.
- Produces: a root directory without generated `.obj` files; the original files remain recoverable under the generated archive.

- [ ] **Step 1: Verify the two exact source files and archive destination.**

  Run PowerShell checks for both literal source paths and the destination staying under the canonical workspace.

- [ ] **Step 2: Move only those two generated files.**

  Use `Move-Item -LiteralPath` for the two explicit files. Do not use a recursive delete or wildcard move.

- [ ] **Step 3: Verify the root is clean of `.obj` files and both archived files exist.**

### Task 2: Record local-only media policy and freeze handoff

**Files:**
- Modify: `数字孪生/.gitignore`
- Create: `数字孪生/docs/agent-context/handoffs/2026-08-09-workspace-freeze-b3-a.md`
- Modify: `数字孪生/docs/agent-context/CURRENT_STATUS.md`

**Interfaces:**
- Consumes: current B3-A handoff, current 1080p observation report, current Git status, and local capture directories.
- Produces: explicit ownership of reproducible files versus local raw media, current evidence boundary, and the exact hardware handoff.

- [ ] **Step 1: Add narrow ignore rules for dated raw camera media.**

  Ignore only `calibration_15mm_1080p_20260809.mp4`, the dated calibration frame/view directories, and dated `ground_controls_15mm_1080p_20260809_run2/run3` image files. Do not ignore their JSON controls, reports, or general source files.

- [ ] **Step 2: Write the handoff with VERIFIED, INFERENCE, and INSUFFICIENT EVIDENCE sections.**

  Record that real 1080p synchronization passed, AprilTag observation failed at about 54.2% with detector p95 about 75.5 ms, the A transport implementation is offline-only until hardware verification, and no physical improvement has been established.

- [ ] **Step 3: Update the authoritative status with the freeze commit boundary.**

  State that B3-A is an offline candidate and the next interface is explicit authorization for flashing A; do not mark B3 complete.

### Task 3: Build the Git rollback checkpoint

**Files:**
- Stage: all current non-ignored project source, tests, JSON reports, plans, specs, and handoffs under `数字孪生/`.
- Exclude: dated raw video/frame PNGs, generated object/build outputs, and
  untracked per-user Keil `uvguix.*` UI state. Keep the two already-tracked
  `uvoptx` files in the checkpoint because their current source-entry changes
  are part of the observed project state.

**Interfaces:**
- Consumes: the cleaned workspace and the new handoff.
- Produces: one commit on the current branch containing the current project state without large local-only media.

- [ ] **Step 1: Review staged paths before committing.**

  Confirm that no file outside `数字孪生/` is staged and that no raw video or PNG capture is staged.

- [ ] **Step 2: Create the checkpoint commit.**

  Use commit message `chore: freeze b3-a offline handoff`.

- [ ] **Step 3: Verify the commit contains the intended source and handoff files.**

  Inspect `git show --stat --oneline HEAD` and the commit path list.

### Task 4: Run the offline release gate

**Files:**
- Test: `数字孪生/simulation/digital_twin/tests/`
- Build evidence: existing Keil Target 1 project and current offline AXF.

**Interfaces:**
- Consumes: the committed checkpoint.
- Produces: fresh regression evidence and a clean handoff boundary; no hardware claim.

- [ ] **Step 1: Run the full Python digital-twin regression with Python 3.11.**

  Run `python -m pytest simulation/digital_twin/tests -q` from `数字孪生` and record the exit code and skipped-test reason.

- [ ] **Step 2: Run Python compileall and `git diff --check`.**

- [ ] **Step 3: Confirm the current Keil build evidence is still the exact offline A artifact.**

  Do not flash it during this task.

### Task 5: Hardware handoff boundary

**Files:**
- Read: `数字孪生/docs/agent-context/handoffs/2026-08-09-workspace-freeze-b3-a.md`
- Use next: existing `tools/shakedown_toolchain/ground_shakedown.py --execute`

**Interfaces:**
- Consumes: the verified checkpoint and offline gate results.
- Produces: a user-facing request for explicit ST-Link flash authorization; no hardware action in this plan.

- [ ] **Step 1: Report exact commit, AXF hash, test results, and remaining evidence gaps.**

- [ ] **Step 2: Stop before flashing and request a separate authorization.**
