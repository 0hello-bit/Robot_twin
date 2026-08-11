# UDP ClockSync Transport Isolation Design

Date: 2026-08-11
Status: DESIGN APPROVED FOR OFFLINE CONTRACT IMPLEMENTATION

## Problem

The current ESP-01S path is verified only as a normal-mode TCP server:
`CIPMUX=1`, `CIPMODE=0`, and `CIPSERVER=1,8888`. The repository contains an
`AT+GMR` command but no captured firmware-version response, so UDP support for
the installed module is not established. The existing firmware also owns one
client id and one serialized CIPSEND state machine.

The next experiment must therefore isolate the transport variable without
quietly turning into a telemetry migration or a concurrent TCP/UDP routing
refactor.

## Decision

Add a pure-Python ClockSync transport contract and observation ledger. The
contract describes a future TCP or UDP ClockSync-only run; it does not open a
socket, emit an AT command, change firmware, or modify the existing capture
session.

The canonical comparison is:

```text
Run A: TCP Q/T on the existing quiet path
Run B: UDP Q/T on an isolated UDP-capable firmware/configuration profile
```

Both runs use the same Q/T payload, sequence semantics, probe count, probe
period, PC clock source, ESP hardware, Wi-Fi conditions, and quiet-window
policy. The primary probe has one outstanding request and no application-level
retry. A timeout is recorded as loss; a late reply is retained as unmatched
evidence and cannot be silently reassigned to a replacement sequence.

## Components

### `ClockSyncTransportProfile`

Create `simulation/digital_twin/v1_twin/clock_sync_transport.py` with a
frozen profile type and validation helpers.

Required profile invariants:

- `transport` is exactly `"tcp"` or `"udp"`.
- `mode` is exactly `"clock_sync_only"`.
- `payload_contract` is exactly `"q_t_v1"`; the Q/T wire fields are unchanged.
- `single_outstanding` is true.
- `primary_retries` is false.
- `pc_clock_source` is exactly `"perf_counter_ns"`.
- `telemetry_migrated`, `health_migrated`, and `control_migrated` are false.

The UDP profile additionally requires explicit capability evidence containing an
actual `AT+GMR` response, `CIPMUX`, `CIPMODE`, UDP support, and the incoming
`+IPD` header mode. Missing capability evidence returns
`INSUFFICIENT EVIDENCE`; it must not be interpreted as UDP support.

### `ClockSyncTransportObservation`

Each observation represents one primary sent sequence and contains:

- `sequence`;
- `pc_tx_ns` and optional `pc_rx_ns`, both from `perf_counter_ns`;
- optional `rtt_total_ns` and `rtt_transport_ns` for a matched reply;
- `duplicate_count`;
- `reordered`;
- an explicit matched/lost state.

The observation type rejects negative durations, duplicate sequence records,
and a matched result without a receive timestamp. It does not discard a large
RTT.

### `summarize_clock_sync_transport`

The ledger summary reports the denominator and all transport outcomes:

- sent, matched, lost, duplicate, and reordered counts;
- loss ratio;
- p50, p95, and maximum total RTT over every matched sample;
- p50, p95, and maximum derived transport RTT over every matched sample.

The summary is descriptive. It does not decide the existing causal ClockSync
gate and does not remove outliers. A separate causal fit continues to use the
existing formal-sample policy and reports `INSUFFICIENT EVIDENCE` when packet
loss leaves too few formal exchanges.

## Data Flow

```text
profile validation
       |
one Q sequence sent
       |
matched T / timeout / late or duplicate reply
       |
ClockSyncTransportObservation
       |
summary with denominator + RTT distributions
       |
existing causal fit and independent transport comparison
```

The contract layer is deliberately independent of `capture_sync_run.py`.
After the ESP capability evidence and firmware profile are verified, a separate
bounded integration task may adapt the existing quiet sampler to a UDP socket.

## Error Handling

- Invalid profile settings raise a contract validation error.
- Missing or incomplete ESP capability evidence produces
  `INSUFFICIENT EVIDENCE`.
- A timeout increases `lost_count` and remains in the sent denominator.
- A duplicate or late reply is retained and counted; it is not used to replace
  the original sequence.
- A high RTT remains in the matched RTT population.
- No summary can be promoted to `PASS` solely because its matched RTT is low.

## Out Of Scope

- ESP firmware version querying or hardware access;
- firmware `ESP_Setup()` changes;
- UDP socket creation in the capture tool;
- telemetry, health, or control migration;
- concurrent TCP/UDP link routing;
- changing the Q/T payload, `seq`, `tick_ms`, CIPSEND state machine, or control
  safety behavior;
- changing the existing causal-sync thresholds.

## Offline Acceptance

The contract tests must prove:

1. TCP and UDP profiles share every non-transport ClockSync setting.
2. A UDP profile cannot be valid with telemetry, health, or control migration.
3. A UDP profile without actual capability evidence is
   `INSUFFICIENT EVIDENCE`.
4. The ledger counts sent, matched, lost, duplicate, and reordered outcomes.
5. The p95 population includes a deliberately high RTT sample.
6. A matched record uses one PC clock source and valid named boundaries.
7. No test opens a real socket or sends an AT command.

## Later Hardware Boundary

Only after these offline contracts pass should a hardware-preflight task read
`AT+GMR`, `AT+CIPMUX?`, `AT+CIPMODE?`, `AT+CIPDINFO?`, and the current link
status. Those reads must be saved as evidence before selecting the exact UDP
setup command. A new firmware build and explicit flash authorization are
required before any real UDP A/B capture.
