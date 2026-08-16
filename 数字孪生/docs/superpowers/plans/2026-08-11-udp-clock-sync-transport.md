# UDP ClockSync Transport Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline-only contract and evidence ledger that can compare TCP and UDP ClockSync runs without changing the current TCP, firmware, or control paths.

**Architecture:** Keep the transport experiment contract in a new pure-Python module under the existing V1 twin package. A frozen profile validates the ClockSync-only invariants and gates UDP readiness on explicit ESP capability evidence. A frozen observation type plus a summary function preserves the sent denominator, loss, duplicate, reorder, and all matched RTT values. No socket or AT command is created by this change.

**Tech Stack:** Python 3.7-compatible standard library, dataclasses, typing, pytest.

## Global Constraints

- Do not modify `capture_sync_run.py`, `transport_soak.py`, firmware, protocol fields, CIPSEND state, telemetry, health, control, or historical evidence.
- Keep the Q/T payload contract as `q_t_v1` and the sequence semantics unchanged.
- Require `single_outstanding=True`, `primary_retries=False`, and `pc_clock_source="perf_counter_ns"`.
- Set `mode="clock_sync_only"`; `telemetry_migrated`, `health_migrated`, and `control_migrated` must remain false.
- Treat missing UDP capability evidence as `INSUFFICIENT EVIDENCE`, never as support.
- Preserve every sent observation and every high RTT; never filter to manufacture a passing result.
- Run only offline tests. Do not open a real socket, send an AT command, connect to the car, flash, or collect hardware data.

### Task 1: Add the failing transport contract tests

**Files:**
- Create: `simulation/digital_twin/tests/test_clock_sync_transport.py`
- Create: `simulation/digital_twin/v1_twin/clock_sync_transport.py` (empty module only after the RED test is prepared)

**Interfaces:**
- Test the future `ClockSyncTransportProfile`, `EspUdpCapabilityEvidence`, `ClockSyncTransportObservation`, and `summarize_clock_sync_transport` interfaces defined in Task 2.

- [x] **Step 1: Write the failing profile tests**

Add tests that import the new module and assert:

```python
def test_tcp_and_udp_profiles_share_non_transport_contract():
    tcp = ClockSyncTransportProfile("tcp")
    udp = ClockSyncTransportProfile("udp")
    tcp.validate()
    udp.validate()
    assert tcp.to_dict()["transport"] == "tcp"
    assert udp.to_dict()["transport"] == "udp"
    for key in tcp.to_dict():
        if key != "transport":
            assert tcp.to_dict()[key] == udp.to_dict()[key]


def test_udp_without_at_capability_evidence_is_insufficient():
    result = ClockSyncTransportProfile("udp").readiness()
    assert result["verdict"] == "INSUFFICIENT EVIDENCE"


def test_udp_requires_complete_capability_evidence():
    evidence = EspUdpCapabilityEvidence(
        at_gmr="AT version: captured",
        cipmux=1,
        cipmode=0,
        udp_supported=True,
        ipd_header_mode="link_id_length",
    )
    assert ClockSyncTransportProfile("udp").readiness(evidence)["verdict"] == "READY"


@pytest.mark.parametrize("field", [
    "telemetry_migrated", "health_migrated", "control_migrated",
])
def test_profile_rejects_stream_migration(field):
    values = {field: True}
    with pytest.raises(ClockSyncTransportContractError):
        ClockSyncTransportProfile("udp", **values).validate()
```

- [x] **Step 2: Write the failing observation and summary tests**

Use five observations: three matched replies with total RTTs of 10 ms, 20 ms,
and 1,000 ms; one lost request; and one lost request with a retained late
reply. Set one duplicate and one reordered flag on the high-RTT observation.
Assert:

```python
summary["sent_count"] == 5
summary["matched_count"] == 3
summary["lost_count"] == 2
summary["duplicate_count"] == 1
summary["reordered_count"] == 1
summary["late_reply_count"] == 1
summary["total_rtt_max_ns"] == 1_000_000_000
summary["total_rtt_p95_ns"] > 20_000_000
```

Also assert that duplicate sequence records and a matched observation without
`pc_rx_ns` raise `ClockSyncTransportContractError`.

- [x] **Step 3: Run the focused tests and verify RED**

Run:

```text
py -3.11 -m pytest simulation/digital_twin/tests/test_clock_sync_transport.py -q
```

Expected: collection fails because the new production module and its exported
interfaces do not exist. Fix only test typos if needed; do not implement the
module before this failure is observed.

### Task 2: Implement the minimal offline contract module

**Files:**
- Modify: `simulation/digital_twin/v1_twin/clock_sync_transport.py`
- Test: `simulation/digital_twin/tests/test_clock_sync_transport.py`

**Interfaces:**

```python
class ClockSyncTransportContractError(ValueError):
    pass

@dataclass(frozen=True)
class EspUdpCapabilityEvidence:
    at_gmr: Optional[str] = None
    cipmux: Optional[int] = None
    cipmode: Optional[int] = None
    udp_supported: Optional[bool] = None
    ipd_header_mode: Optional[str] = None

@dataclass(frozen=True)
class ClockSyncTransportProfile:
    transport: str
    mode: str = "clock_sync_only"
    payload_contract: str = "q_t_v1"
    single_outstanding: bool = True
    primary_retries: bool = False
    pc_clock_source: str = "perf_counter_ns"
    telemetry_migrated: bool = False
    health_migrated: bool = False
    control_migrated: bool = False

    def validate(self) -> None: ...
    def readiness(self, capabilities=None) -> Dict[str, Any]: ...
    def to_dict(self) -> Dict[str, Any]: ...

@dataclass(frozen=True)
class ClockSyncTransportObservation:
    sequence: int
    pc_tx_ns: int
    matched: bool
    pc_rx_ns: Optional[int] = None
    rtt_transport_ns: Optional[int] = None
    duplicate_count: int = 0
    reordered: bool = False
    late_reply: bool = False
    pc_clock_source: str = "perf_counter_ns"

    @property
    def rtt_total_ns(self) -> Optional[int]: ...
    def to_dict(self) -> Dict[str, Any]: ...

def summarize_clock_sync_transport(
    observations: Sequence[ClockSyncTransportObservation],
) -> Dict[str, Any]: ...
```

Implement these rules:

- Profile validation rejects unsupported transport names, changed mode or
  payload contract, disabled single-outstanding behavior, primary retries,
  another PC clock source, or any stream migration.
- UDP readiness checks non-empty `at_gmr`, `cipmux == 1`, `cipmode == 0`,
  `udp_supported is True`, and `ipd_header_mode == "link_id_length"`. Return a
  structured `INSUFFICIENT EVIDENCE` result with a `missing` list for any
  absent/mismatched item; return `READY` only when all checks pass. TCP
  readiness does not invent a UDP capability claim.
- Observation validation rejects non-positive or boolean sequences, negative
  timestamps, `pc_rx_ns < pc_tx_ns`, matched observations without a receive
  timestamp, negative transport RTT, negative duplicate counts, non-boolean
  flags, `late_reply=True` without a receive timestamp, and any observation
  clock source other than `perf_counter_ns`.
- A non-matched observation contributes to `lost_count`; a retained late reply
  is still lost for the primary exchange and contributes to
  `late_reply_count`. It is excluded from matched RTT percentiles.
- Summary validation rejects duplicate sequence ids instead of silently
  deduplicating them.
- Percentiles use deterministic linear interpolation over sorted matched
  values. Empty matched populations serialize percentile and maximum metrics
  as `None`.

- [x] **Step 1: Implement validation and serialization**

Write the dataclasses, explicit validation error messages, readiness result,
and JSON-compatible `to_dict` methods. Do not import `socket`, call any network
API, or depend on firmware files.

- [x] **Step 2: Implement all-outcome summary statistics**

Count every supplied observation exactly once. Compute loss ratio as
`lost_count / sent_count`, or `0.0` when no observations exist. Compute total
and derived transport RTT p50/p95/max only from matched observations, retaining
all matched values including the deliberately high one.

- [x] **Step 3: Run the focused tests and verify GREEN**

Run:

```text
py -3.11 -m pytest simulation/digital_twin/tests/test_clock_sync_transport.py -q
```

Expected: all new tests pass with no warnings or hardware side effects.

### Task 3: Regression verification and handoff

**Files:**
- Verify: `simulation/digital_twin/v1_twin/clock_sync_transport.py`
- Verify: `simulation/digital_twin/tests/test_clock_sync_transport.py`
- Verify: all existing dirty files remain untouched by this plan

- [x] **Step 1: Run focused and causal-sync regressions**

Run:

```text
py -3.11 -m pytest \
  simulation/digital_twin/tests/test_clock_sync_transport.py \
  simulation/digital_twin/tests/test_v1_twin_causal_sync.py \
  simulation/digital_twin/tests/test_capture_sync_report.py -q
```

Expected: all selected tests pass; existing causal-sync verdict and schema
behavior remain unchanged.

- [x] **Step 2: Run Python compilation and whitespace checks**

Run:

```text
py -3.11 -m py_compile simulation/digital_twin/v1_twin/clock_sync_transport.py simulation/digital_twin/tests/test_clock_sync_transport.py
git diff --check
```

Expected: both commands exit successfully. No firmware build or flash is part
of this plan.

- [x] **Step 3: Inspect the final scope**

Run:

```text
git status --short
git diff --stat
```

Confirm that only the new offline module, its tests, and this implementation
plan are attributable to this task; preserve all pre-existing user changes.

- [x] **Step 4: Stop at the hardware boundary**

Report that the offline contract is ready for a later capability-preflight
task. Do not query `AT+GMR`, build a UDP firmware profile, flash, open a camera,
or run TCP/UDP A/B in this plan.
