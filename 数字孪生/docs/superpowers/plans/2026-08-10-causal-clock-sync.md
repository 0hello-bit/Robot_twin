# Causal Clock Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unverified PC-receive-time assumption with an evidence-traceable PC-to-MCU clock mapping that can independently gate physical-event synchronization.

**Architecture:** Keep the existing `ClockSync` and `build_synchronized_dataset()` as the coarse alignment path. Add a separate causal-sync layer based on bounded PC-to-MCU-to-PC clock exchanges: PC send time `t1`, MCU receive tick `t2`, MCU reply tick `t3`, and PC receive time `t4`. Fit `pc_ns = a * mcu_tick_ms + b` from exchange midpoints, report RTT and uncertainty, and expose a separate `causal_sync` verdict. The current telemetry payload, ESP-01S TCP client, heartbeat, ACK, status, and safety lifecycle remain unchanged until this contract is independently reviewed.

**Tech Stack:** Python 3.11, dataclasses, NumPy, pytest, existing ASCII XOR framing, existing Keil/STM32 C path in a later hardware-contract task.

## Global Constraints

- Do not connect to, flash, reset, or command the physical car in this plan.
- Preserve the frozen evidence commit `21c0c1f` as the baseline; never rewrite old run evidence.
- Keep `alignment` and `causal_sync` as separate claims. A passing coarse alignment gate cannot promote causal synchronization.
- Old runs without four timestamp exchange samples must remain `INSUFFICIENT EVIDENCE`.
- Preserve raw fields: `sample_tick_ms`, `pc_recv_ns`, packet/batch evidence, and any future exchange timestamps.
- Reuse the existing ESP-01S TCP and ASCII control path. Do not add a second TCP client, heartbeat sender, ACK registry, parser, or telemetry protocol.
- The first implementation must be offline-testable and must not claim a hardware result from synthetic samples.

---

### Task 1: Define the exchange evidence contract

**Files:**
- Create: `simulation/digital_twin/v1_twin/v1_twin_causal_sync.py`
- Test: `simulation/digital_twin/tests/test_v1_twin_causal_sync.py`

**Interfaces:**
- `ClockExchangeSample.from_dict(record: Mapping[str, Any]) -> ClockExchangeSample`
- `ClockExchangeSample.to_dict() -> dict[str, int]`
- Required fields are `sequence`, `pc_tx_ns`, `mcu_rx_tick_ms`, `mcu_tx_tick_ms`, and `pc_rx_ns`.
- Reject missing fields, non-integers, negative PC timestamps, duplicate/non-increasing sequence values within a fit, and malformed tick values.

- [ ] **Step 1: Write the failing tests**

```python
def test_exchange_sample_round_trips_all_four_timestamps():
    sample = ClockExchangeSample.from_dict({
        "sequence": 7,
        "pc_tx_ns": 10_000_000_000,
        "mcu_rx_tick_ms": 1234,
        "mcu_tx_tick_ms": 1235,
        "pc_rx_ns": 10_012_000_000,
    })
    assert sample.to_dict() == {
        "sequence": 7,
        "pc_tx_ns": 10_000_000_000,
        "mcu_rx_tick_ms": 1234,
        "mcu_tx_tick_ms": 1235,
        "pc_rx_ns": 10_012_000_000,
    }


def test_exchange_sample_rejects_missing_receive_timestamp():
    with pytest.raises(ValueError, match="pc_rx_ns"):
        ClockExchangeSample.from_dict({
            "sequence": 1,
            "pc_tx_ns": 100,
            "mcu_rx_tick_ms": 1,
            "mcu_tx_tick_ms": 1,
        })
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest simulation/digital_twin/tests/test_v1_twin_causal_sync.py -q`

Expected: FAIL because `v1_twin_causal_sync.py` and `ClockExchangeSample` do not exist yet.

- [ ] **Step 3: Implement the minimal immutable sample type**

Use a frozen dataclass. Normalize values with `int()` only after rejecting booleans; validate `pc_tx_ns >= 0`, `pc_rx_ns >= pc_tx_ns`, and `mcu_tx_tick_ms >= mcu_rx_tick_ms` in the same non-wrapping exchange. Do not silently repair invalid records.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -m pytest simulation/digital_twin/tests/test_v1_twin_causal_sync.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the contract**

```text
git add simulation/digital_twin/v1_twin/v1_twin_causal_sync.py simulation/digital_twin/tests/test_v1_twin_causal_sync.py
git commit -m "feat: define causal clock exchange evidence"
```

### Task 2: Fit the causal clock and expose uncertainty

**Files:**
- Modify: `simulation/digital_twin/v1_twin/v1_twin_causal_sync.py`
- Test: `simulation/digital_twin/tests/test_v1_twin_causal_sync.py`

**Interfaces:**
- `CausalSyncPolicy(min_exchanges=8, max_rtt_p95_ns=20_000_000, max_residual_p95_ns=5_000_000, max_uncertainty_p95_ns=10_000_000)`
- `CausalClockFit.fit(samples: Sequence[ClockExchangeSample]) -> CausalClockFit`
- `CausalClockFit.tick_to_pc_ns(tick_ms: float) -> float`
- `CausalClockFit.metrics() -> dict[str, float | int]`
- `evaluate_causal_sync(fit: CausalClockFit, policy: CausalSyncPolicy) -> CausalSyncGateResult`

The exchange midpoint is the only mapping observation:

```text
pc_mid_ns  = (pc_tx_ns + pc_rx_ns) / 2
mcu_mid_ms = (mcu_rx_tick_ms + mcu_tx_tick_ms) / 2
```

The measured transport component is:

```text
rtt_ns = (pc_rx_ns - pc_tx_ns) - (mcu_tx_tick_ms - mcu_rx_tick_ms) * 1_000_000
```

Use linear least squares over midpoint samples and report `rtt_min/median/p95/max`, residual `rms/p95/max`, slope, and drift in ppm. The fit slope `a` is already in `ns/ms`, so report `uncertainty_ns = rtt_ns / 2 + 0.5 * abs(a)` to expose the 1 ms MCU clock resolution instead of hiding it. This is an uncertainty proxy, not proof that Wi-Fi path asymmetry is bounded.

- [ ] **Step 1: Add failing synthetic exchange tests**

```python
def test_causal_fit_recovers_mapping_and_reports_rtt():
    samples = [
        ClockExchangeSample(i, 1_000_000_000 + i * 100_000_000,
                            10_000 + i * 100,
                            10_000 + i * 100 + 1,
                            1_000_000_000 + i * 100_000_000 + 12_000_000)
        for i in range(12)
    ]
    fit = CausalClockFit.fit(samples)
    assert fit.tick_to_pc_ns(10_500) == pytest.approx(1_500_000_000, abs=1_000_000)
    assert fit.metrics()["rtt_p95_ns"] == pytest.approx(11_000_000, abs=1)


def test_causal_gate_does_not_pass_without_enough_exchanges():
    samples = [
        ClockExchangeSample(i, i * 100_000_000,
                            i * 100, i * 100 + 1,
                            i * 100_000_000 + 10_000_000)
        for i in range(3)
    ]
    result = evaluate_causal_sync(
        CausalClockFit.fit(samples), CausalSyncPolicy()
    )
    assert result.verdict == "INSUFFICIENT EVIDENCE"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest simulation/digital_twin/tests/test_v1_twin_causal_sync.py -q`

Expected: FAIL because fitting, metrics, and gate behavior are not implemented.

- [ ] **Step 3: Implement the smallest deterministic fit and gate**

Reject negative RTT and non-finite regression results. If `samples` is empty, fitting must raise `ValueError`; if the gate has fewer than `min_exchanges`, return `INSUFFICIENT EVIDENCE`; if enough samples exist but a policy threshold is exceeded, return `FAIL`; only all thresholds passing may return `PASS`.

- [ ] **Step 4: Add regression tests for bad evidence**

Cover negative RTT, high RTT, residual outlier, and a valid exchange set. Assert that bad evidence fails rather than being silently dropped. Keep the policy thresholds explicit in the test.

- [ ] **Step 5: Run focused and existing sync tests**

Run: `python -m pytest simulation/digital_twin/tests/test_v1_twin_causal_sync.py simulation/digital_twin/tests/test_v1_twin_sync.py -q`

Expected: PASS with existing `ClockSync` behavior unchanged.

### Task 3: Make the report boundary explicit

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Modify: `simulation/digital_twin/v1_twin/v1_twin_causal_sync.py`
- Test: `simulation/digital_twin/tests/test_capture_sync_report.py`

**Interfaces:**
- `build_causal_sync_report(exchange_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]`
- `build_sync_report(..., causal_sync=None)` keeps the existing coarse alignment fields and adds a separate `causal_sync` object.

- [ ] **Step 1: Write the failing report tests**

```python
def test_report_marks_missing_clock_exchanges_insufficient_evidence():
    report = build_causal_sync_report([])
    assert report["verdict"] == "INSUFFICIENT EVIDENCE"
    assert report["reason"] == "no clock exchange samples recorded"


def test_coarse_alignment_pass_does_not_promote_causal_sync():
    report = build_sync_report_with_causal_sync(
        alignment_verdict="PASS",
        causal_sync=build_causal_sync_report([]),
    )
    assert report["alignment_verdict"] == "PASS"
    assert report["causal_sync"]["verdict"] == "INSUFFICIENT EVIDENCE"
```

- [ ] **Step 2: Run the report tests and verify RED**

Run: `python -m pytest simulation/digital_twin/tests/test_capture_sync_report.py -q`

Expected: FAIL because the causal report helper and independent report field do not exist.

- [ ] **Step 3: Implement report serialization without changing old verdict semantics**

The report must retain `clock.fit = "fit_batched"` for historical compatibility, add `alignment_verdict` and `causal_sync`, and never copy the coarse verdict into the causal verdict. The top-level verdict must not claim a complete sync pass while causal sync is insufficient: it is `INSUFFICIENT EVIDENCE` until causal sync passes, and `FAIL` if causal sync fails. A run with no exchange file must explicitly include `sample_count: 0`, `verdict: "INSUFFICIENT EVIDENCE"`, and the missing-evidence reason.

- [ ] **Step 4: Replay the frozen real run offline**

Run the report/replay helper against:
`simulation/digital_twin/logs/v1_b3_real_sync_20260810/c260810121905472`

Expected: existing coarse `alignment` evidence remains unchanged, while `causal_sync.verdict` is `INSUFFICIENT EVIDENCE` because the old run has no four-timestamp exchanges. Do not rewrite the run directory.

- [ ] **Step 5: Run the relevant Python suite**

Run: `python -m pytest simulation/digital_twin/tests/test_capture_sync_report.py simulation/digital_twin/tests/test_v1_twin_sync.py simulation/digital_twin/tests/test_temporal_observation.py -q`

Expected: PASS.

### Task 4: Implement the existing-chain firmware contract, without flashing

**Files:**
- Modify: `firmware/stm32_line_follower/User/twin_control_protocol.c`
- Modify: `firmware/stm32_line_follower/User/twin_control_protocol.h`
- Modify: `firmware/stm32_line_follower/User/esp_runtime_transport.c`
- Modify: `firmware/stm32_line_follower/User/esp_runtime_transport.h`
- Modify: `firmware/stm32_line_follower/User/main.c`
- Modify: `tools/shakedown_toolchain/transport_soak.py`
- Test: `simulation/digital_twin/tests/test_twin_control_protocol.c`
- Test: `simulation/digital_twin/tests/test_clock_sync_firmware_contract.py`
- Test: `simulation/digital_twin/tests/test_clock_sync_protocol.py`

**Interfaces:**
- Proposed request: existing XOR-framed ASCII `Q,<sequence>,<checksum>\n`.
- Proposed response: existing ASCII path `T,<sequence>,<mcu_rx_tick_ms>,<mcu_tx_tick_ms>,<checksum>\n`.
- `mcu_rx_tick_ms` is captured when the complete Q frame is accepted by the existing protocol parser.
- `mcu_tx_tick_ms` is captured immediately before the existing CIPSEND transaction is started. This is a conservative MCU dispatch timestamp, not a claim about the exact ESP wire-byte time; prompt/transport delay remains in the measured RTT and can only make the gate stricter.
- The response must be recorded with PC `t1` immediately before the existing TCP send request and PC `t4` immediately after the complete response line is received.

- [ ] **Step 1: Document the handoff and safety boundary**

State that this task adds only a clock-exchange result to the existing `twin_control_protocol`, `esp_runtime_transport`, and CIPSEND path, must not alter `P/R/H`, telemetry payload length, heartbeat lease, or motor safety behavior, and must be built with Keil before any hardware authorization.

- [ ] **Step 2: Specify independent acceptance**

The offline gate may be `PASS` only with enough exchange samples and passing RTT/residual/uncertainty thresholds. Hardware synchronization remains `INSUFFICIENT EVIDENCE` until the new firmware is flashed under explicit authorization and a real run stores `t1,t2,t3,t4` records.

- [ ] **Step 3: Stop at the handoff**

Do not flash, reset, connect to, or command the physical car in this plan. After the offline firmware and host implementation builds cleanly, stop at the explicit hardware authorization boundary.

## Verification Checklist

- [ ] Existing `ClockSync` unit tests pass.
- [ ] New causal-sync tests pass, including malformed and high-delay evidence.
- [ ] Frozen real run is not modified.
- [ ] Frozen real run remains `causal_sync = INSUFFICIENT EVIDENCE`.
- [ ] No hardware command, flash, reset, or new data collection is performed.
- [ ] Git diff contains only the plan, causal-sync code/tests, and report integration explicitly listed above.

### Task 5: Remove active-run Q/T queue contamination

**Evidence that motivates this task:** the real run
`simulation/digital_twin/logs/causal_sync_real_20260810_retry/c260810143527776`
has `mcu_tx_tick_ms - mcu_rx_tick_ms` values up to hundreds of milliseconds.
That is firmware-side response queue time, not merely PC-side timestamp noise:
the Q request is accepted while another single-channel CIPSEND transaction is in
flight. The current response priority can only run after that transaction
returns to idle. Aborting an in-flight CIPSEND on the same ESP-01S connection is
not an acceptable offline fix because it can leave the module in prompt/data
mode and corrupt the existing transport lifecycle.

**Boundary:** collect causal clock exchanges only in quiet windows: before
`R,...,START` and after matching `R,...,STOP` confirmation. Do not send active
Q probes during the physical experiment. Keep all exchange records, including
high-delay and timeout evidence; do not filter samples to pass the policy.

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Test: `simulation/digital_twin/tests/test_causal_clock_capture_policy.py`
- Modify: this plan

**Acceptance:**
- [x] The offline session test proves no Q command is sent between matching START
  and STOP commands.
- [x] Every recorded exchange has `pre_start_quiet` or `post_stop_quiet` phase.
- [x] Existing P/R/H, telemetry payload, heartbeat lease, cleanup, and safety
  behavior remain unchanged.
- [x] The frozen real run is never rewritten; the current FAIL remains FAIL until a
  future authorized run produces new four-timestamp evidence.

**Offline verification record (2026-08-10):**

- [x] The first policy test was RED against the old active-run probe behavior.
- [x] Focused causal/cleanup suite: `70 passed`.
- [x] Digital-twin test suite: `824 passed, 5 skipped` under Python 3.11.
- [x] `capture_sync_run.py` compile and repository diff checks pass.
- [x] Read-only replay of `c260810143527776` remains `FAIL`, with 44 samples,
  RTT p95 about 89.6 ms, and uncertainty p95 about 45.3 ms.
- [x] No hardware was connected, flashed, reset, or controlled.

## Independent Verification Record (2026-08-10)

- [x] Targeted Python suite under `py -3.11`: 17 passed.
- [x] C controller protocol suite: `PASS test_twin_control_protocol`, `PASS all`.
- [x] C IPD/transport suites: `PASS test_ipd_integration`, `PASS test_esp_transport_gen`.
- [x] Keil `Target 1` build: 0 errors, 0 warnings; no flash operation executed.
- [x] Frozen real-run report hash remains `F0C3A9A396BDC1778062B0CA04ACD7B4F0D1E047D63468D06C54D33CD988B5F9`; no legacy clock-exchange file was added.
- [x] No hardware was connected, flashed, reset, or controlled during this task.
- [ ] Full repository pytest collection remains environment-blocked by missing `pypdf` in the active Python 3.7 environment; this is not a causal-sync test failure.
