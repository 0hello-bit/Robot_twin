# PC Causal Endpoint Uncertainty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admit only causal ClockSync samples whose PC application send/receive boundaries carry measured, sample-specific uncertainty intervals.

**Architecture:** Keep the existing TCP ClockExchangeCollector and causal fit contract. Wrap the existing PC `sendall()` and `recv()` observations with before/after `perf_counter_ns()` readings, serialize the midpoint and half-width plus interval provenance, and preserve fail-closed behavior for records without a complete interval.

**Tech Stack:** Python 3, `time.perf_counter_ns`, existing pytest suite, JSONL evidence.

## Global Constraints

- Do not modify firmware, transport protocol, or historical evidence.
- Do not invent a fixed PC uncertainty value.
- Keep `t_payload_generated` diagnostic-only.
- Preserve TCP-only causal-clock semantics.
- Run focused tests before the full regression.

---

### Task 1: Lock The Interval Contract With Tests

**Files:**
- Modify: `simulation/digital_twin/tests/test_clock_sync_protocol.py`
- Modify: `simulation/digital_twin/tests/test_causal_clock_capture_policy.py`
- Test subject: `tools/camera_toolchain/capture_sync_run.py`

**Interfaces:**
- The collector accepts a measured PC send interval at probe start and a measured PC receive interval at probe completion.
- A complete interval produces a midpoint timestamp, a positive or zero half-width uncertainty, and retained boundary fields.
- An absent or inverted interval remains excluded from formal fitting.

- [x] **Step 1: Write the failing test**

Add a test that completes a v3 formal exchange with send interval `(1_000,
1_100)` and receive interval `(2_000, 2_200)`, then asserts:

```python
assert record["pc_tx_ns"] == 1_050
assert record["pc_rx_ns"] == 2_100
assert record["pc_tx_event_uncertainty_ns"] == 50
assert record["pc_rx_event_uncertainty_ns"] == 100
assert record["pc_endpoint_uncertainty_model"] == (
    "application_call_interval_midpoint_v1"
)
assert record["included_in_fit"] is True
```

- [x] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
pytest -q simulation/digital_twin/tests/test_clock_sync_protocol.py -k "pc_endpoint_interval"
```

Expected: FAIL because the collector currently accepts only scalar PC times
and deliberately emits `None` PC uncertainty.

### Task 2: Implement Measured PC Boundaries

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Modify: `simulation/digital_twin/v1_twin/v1_twin_causal_sync.py` only if strict schema validation needs the new provenance fields.

**Interfaces:**
- Add one private interval normalizer returning `(midpoint_ns, half_width_ns)` and rejecting non-integer, negative, or inverted bounds.
- Extend `ClockExchangeCollector.begin_probe()` with an optional send interval.
- Extend `ClockExchangeCollector.complete_probe()` with an optional receive interval.
- Keep scalar timestamp compatibility only for non-formal/legacy evidence; formal samples without intervals remain excluded.

- [x] **Step 1: Implement the smallest interval normalizer**

The normalizer must require `start_ns <= end_ns`, return integer midpoint and
`(end_ns - start_ns + 1) // 2`, and raise `ValueError` for malformed bounds.

- [x] **Step 2: Wire the send interval around the existing `sendall()` call**

Capture the two host monotonic readings in the existing probe sender and pass
the interval into `begin_probe()`; do not add a second socket path.

- [x] **Step 3: Wire the receive interval around the existing `recv()` call**

Capture the two readings in the existing reader path and pass the interval
through the matched reply completion; retain the existing raw receive timestamp
as the underlying observation evidence.

- [x] **Step 4: Serialize provenance and admit only complete measured intervals**

Set the PC endpoint fields from the normalized intervals, set the model name,
and require both intervals before `included_in_fit=True`. Preserve
`uncertainty_unverified` for formal records that lack either interval.

### Task 3: Verify And Review

**Files:**
- No source files beyond Tasks 1-2.
- Evidence: focused test output, full Python regression output, compileall output, and `git diff --check`.

- [x] **Step 1: Run the focused ClockSync tests**

```powershell
pytest -q simulation/digital_twin/tests/test_clock_sync_protocol.py simulation/digital_twin/tests/test_causal_clock_capture_policy.py simulation/digital_twin/tests/test_v1_twin_causal_sync.py
```

- [x] **Step 2: Run the full Python regression and syntax checks**

```powershell
pytest -q
python -m compileall -q simulation tools
git diff --check
```

Result: the repository-root `pytest -q` is blocked during collection by the
existing `archive/legacy_workspace_20260805` dependency/test copies. The
canonical current-source suites passed with `1041 passed, 5 skipped` under
`simulation/digital_twin/tests` and `214 passed, 3 skipped` under the current
tooling test directories. `compileall` and `git diff --check` passed.

- [x] **Step 3: Inspect the diff and confirm hardware boundary**

Confirm that only offline Python/test/design files changed, no firmware or
historical evidence changed, and no hardware command was issued.
