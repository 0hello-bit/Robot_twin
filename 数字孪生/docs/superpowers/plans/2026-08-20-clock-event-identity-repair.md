# Clock Event Identity Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent delayed or weakly-proven timestamps from being treated as exact causal-clock observations.

**Architecture:** Keep the existing TCP-only v2 wire format. Model each exchange boundary with a distinct event identity, enforce exact exchange scope and validity in the low-level event object, represent unproven uncertainty as unknown in production capture records, and keep legacy v1 RTT data in a separately named replay summary.

**Tech Stack:** Python 3.11, pytest, Keil MDK/uVision Target 1, existing STM32 C protocol implementation.

## Global Constraints

- Do not change the existing v2 `Q`/`T` wire format in this repair.
- Do not add UDP to the firmware or use UDP as causal-clock evidence.
- Preserve legacy records as immutable replay evidence, but never use them for causal fitting or formal transport metrics.
- Use `None` plus an explicit insufficient-evidence classification when an uncertainty bound is not physically established.
- Do not connect, flash, reset, or control the real car during this task.

---

### Task 1: Event Identity and Validity Contract

**Files:**
- Modify: `simulation/digital_twin/v1_twin/clock_event_identity.py`
- Test: `simulation/digital_twin/tests/test_clock_event_identity.py`

**Interfaces:**
- `ClockEvent` retains its current constructor and `build_clock_event()` API.
- `ClockEvent` validates the exact `ClockExchangeIdentity` scope, causal-parent scope, and observed-boundary semantics.

- [ ] **Step 1: Write failing tests**

Add tests that a mismatched capture scope or causal parent is rejected, and that an `observed_boundary` cannot omit its observation time or claim a nonzero age.

- [ ] **Step 2: Run the focused tests and confirm the expected failures**

Run: `python -m pytest simulation/digital_twin/tests/test_clock_event_identity.py -q`

- [ ] **Step 3: Implement the smallest validation change**

Store the transport and capture scope on `ClockEvent`, derive the exact expected event ID from `ClockExchangeIdentity`, require a same-exchange causal parent, and enforce `observed_time == event_time` with `data_age == 0` for `observed_boundary`.

- [ ] **Step 4: Re-run the focused tests**

Run: `python -m pytest simulation/digital_twin/tests/test_clock_event_identity.py -q`

### Task 2: Production Uncertainty and Legacy Evidence Boundaries

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Modify: `tools/shakedown_toolchain/clock_sync_transport_ab.py`
- Test: `simulation/digital_twin/tests/test_clock_sync_protocol.py`
- Test: `simulation/digital_twin/tests/test_clock_sync_transport_ab.py`

**Interfaces:**
- v2 records keep independent `event_id`, event time, validity, and delay-diagnostic fields.
- Production records use `None` for unverified event uncertainty and are fail-closed by `build_causal_sync_report()`.
- Top-level transport summary excludes matched v1 records; `legacy_replay` contains their replay-only metrics.

- [ ] **Step 1: Write failing tests**

Assert v2 production ledger records do not expose a hardcoded uncertainty as measured evidence, causal reporting fails closed for those records, legacy ticks are retained by the capture collector, and legacy RTT appears only under `legacy_replay`.

- [ ] **Step 2: Run the focused tests and confirm the expected failures**

Run: `python -m pytest simulation/digital_twin/tests/test_clock_sync_protocol.py simulation/digital_twin/tests/test_clock_sync_transport_ab.py -q`

- [ ] **Step 3: Implement the smallest production changes**

Replace the production ledger's unproven uncertainty values with `None`, preserve raw v1 ticks in capture records, and split formal transport summary metrics from replay-only v1 metrics without deleting raw observations.

- [ ] **Step 4: Re-run the focused tests**

Run: `python -m pytest simulation/digital_twin/tests/test_clock_sync_protocol.py simulation/digital_twin/tests/test_clock_sync_transport_ab.py -q`

### Task 3: Regression and Firmware Build

**Files:**
- No additional source files unless a focused regression exposes a contract mismatch.

- [ ] **Step 1: Run the project test directory**

Run: `python -m pytest simulation/digital_twin/tests -q`

- [ ] **Step 2: Run static checks**

Run: `python -m compileall -q simulation/digital_twin/v1_twin simulation/digital_twin/real_world tools/camera_toolchain tools/shakedown_toolchain` and `git diff --check`.

- [ ] **Step 3: Rebuild Keil Target 1**

Run the existing Keil rebuild entry point with `F:\keil\UV4\UV4.exe`, `firmware/stm32_line_follower/project.uvprojx`, and `Target 1`; record errors, warnings, AXF path, and SHA-256.

- [ ] **Step 4: Run a final read-only review**

Review the changed files for event identity, delayed-boundary semantics, uncertainty status, legacy isolation, and evidence claims. Do not flash or run hardware.
