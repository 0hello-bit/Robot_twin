# PC Causal Endpoint Uncertainty Design

Date: 2026-08-22

Status: APPROVED FOR OFFLINE IMPLEMENTATION

## Problem

The Build 6 hardware capture returned all four MCU clock-boundary timestamps,
but every formal exchange was excluded from causal fitting because the PC
`sendall()` and `recv()` endpoint uncertainty fields were `null`. The collector
must preserve the distinction between a host observation and a physical wire
timestamp while providing a defensible, sample-specific bound for the host
application boundary.

## Decision

Measure a host endpoint as an application-call interval:

- capture `perf_counter_ns()` immediately before and after the PC `sendall()`
  call;
- capture `perf_counter_ns()` immediately before and after the PC `recv()` call
  that yields the complete T reply;
- use the interval midpoint as the reported PC event time;
- use the interval half-width, rounded up, as the event uncertainty;
- retain both interval endpoints and the model identifier in each exchange
  record.

The event remains a PC application boundary. It is not relabeled as a TCP wire
timestamp, ESP `SEND OK`, or physical MCU transmission boundary. Existing
records with unknown endpoint uncertainty remain excluded from formal fitting.

## Data Contract

Formal exchange records gain these diagnostic fields:

- `pc_tx_boundary_start_ns`, `pc_tx_boundary_end_ns`;
- `pc_rx_boundary_start_ns`, `pc_rx_boundary_end_ns`;
- `pc_endpoint_uncertainty_model` = `application_call_interval_midpoint_v1`.

The existing `pc_tx_ns` and `pc_rx_ns` fields become the corresponding
midpoints. The existing event identities, clock domains, validity labels, and
MCU fields remain unchanged. A malformed or incomplete interval remains
fail-closed and cannot enter the fit.

## Rationale

Python documents `perf_counter_ns()` as a high-resolution monotonic counter,
but its value is still an observation made around a blocking socket call.
Python documents `sendall()` and `recv()` as socket operations with their own
call semantics; the call duration is therefore the locally observable bound
for the application boundary. This design records that bound explicitly and
does not claim knowledge of bytes on the physical TCP/Wi-Fi path.

References:

- https://docs.python.org/3/library/time.html#time.perf_counter_ns
- https://docs.python.org/3/library/socket.html#socket.socket.sendall
- https://docs.python.org/3/library/socket.html#socket.socket.recv

## Out Of Scope

- no firmware or protocol change;
- no fixed guessed PC uncertainty constant;
- no promotion of `t_payload_generated` to a physical wire boundary;
- no change to historical evidence;
- no hardware rerun in this patch.

## Verification

Tests must prove that complete measured intervals produce populated PC
uncertainty and formal fit admission, while missing or invalid intervals remain
fail-closed. Existing legacy, v2, and v3 contracts must continue to pass.
