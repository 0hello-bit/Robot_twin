# UART TX Backpressure and AprilTag Diagnostics Handoff

Date: 2026-08-07 Asia/Shanghai
Status: OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED

## Scope

The car was kept powered off. This task addressed the two offline items from
the latest real synchronized capture:

1. UART TX ring pressure observed in `logs/c260807133939203/`.
2. Missing evidence needed to separate AprilTag visibility from detector
   candidate rejection and processing throughput.

No firmware was flashed and no START, STOP, reset, or motor command was sent.

## UART TX finding

The latest real run reported:

- `uart_tx_overflow`: `0 -> 15`;
- `uart_tx_high_water`: reached `128`;
- `telemetry_overwritten`: `0`;
- `telemetry_tx_failed`: `0`;
- `cipsend_error`: `0`;
- raw telemetry checksum parsing: zero errors.

The active firmware can create one droppable telemetry payload of 248 bytes,
while `UART_RING_SIZE` was 128 bytes. `cipsend_tx_send_pending()` retains its
byte position when the sink rejects a byte, so the current evidence indicates
transient producer backpressure rather than proven wire corruption. The
health counter is nevertheless a real capacity warning and should not be
ignored.

## UART offline change

- `UART_RING_SIZE`: `128 -> 256` in
  `firmware/stm32_line_follower/User/uart_ring.h`.
- `test_uart_ring.c` now requires the ring to accept one complete
  `CIPSEND_TX_MAX_DATA` payload without an overflow.

TDD boundary:

- The new static capacity contract failed before the source change:
  `TX ring 128 cannot hold max CIPSEND payload 248`.
- The same contract passes after the change with `ring=256` and
  `max_payload=248`.
- A native Host C compiler was not installed in the current environment, so
  the newly edited Host C executable was not run. Existing prebuilt binaries
  were not treated as evidence for the new source.

## AprilTag offline change

`PoseTracker._detect_with_diagnostics()` now records:

- rejected detector candidate count per attempted scale;
- total rejected candidate count;
- `failure_reason=candidates_rejected` when candidates exist but no marker
  is accepted;
- `failure_reason=no_markers` only when all attempted scales return no marker
  candidates.

The existing capture loop already persists these diagnostics in
`frame_index.jsonl`; no second camera, parser, or capture lifecycle was added.

TDD boundary:

- The new blank-frame and blurred-small-tag tests failed against the old
  diagnostics contract.
- Focused pose-tracker regression after the change: `11 passed`.

## Evidence classification

### VERIFIED

- Python regression excluding archive: `707 passed, 5 skipped`.
- Python compileall for `simulation/digital_twin` and `tools`: exit 0.
- `git diff --check`: no whitespace errors; line-ending warnings only.
- Keil `Target 1` rebuild: `0 Error(s), 0 Warning(s)`.
- Current AXF SHA-256:
  `B0C252541C67E2E2D4EB3500FA8D8448C1E1BDABD88A6D3F0AD32B55D4970219`.
- Current build log:
  `.embeddedskills/build/2026-08-07-uart-camera-diagnostics/project-Target 1-rebuild.log`.
- On an older retained video with a stable visible tag, the current detector
  achieved `60/60` detections at roughly 20 ms median with scale `1.0`.

### INFERENCE

- The 15 TX overflow increments in the latest run are consistent with the
  128-byte ring being smaller than the 248-byte telemetry burst. They are not
  proof that TCP bytes were lost because the transaction retains its position
  and the run had no checksum errors.
- The latest AprilTag run's long initial failure interval followed by grouped
  successful detections is consistent with changing visibility, camera
  framing, or motion blur. It is not enough to select one cause.

### INSUFFICIENT EVIDENCE

- The 256-byte ring has not yet been tested on the physical car.
- The latest run did not retain camera images, so its `no_markers` frames
  cannot be retrospectively classified as out-of-view, blur, occlusion, or
  detector failure.
- AprilTag continuous detection is not fixed or accepted yet.
- B3 synchronization, IMU calibration, motion accuracy, and vehicle
  improvement remain unverified by this offline task.

## Next interface

After explicit flash authorization, use the current AXF through the existing
Keil/ST-Link process and run one bounded synchronized capture with the full
AprilTag visible at the start. Inspect, at minimum:

- `uart_tx_overflow`, `telemetry_overwritten`, `telemetry_tx_failed`, and
  `cipsend_error` remain unchanged at zero during the run;
- `frame_index.jsonl` counts for `no_markers` versus
  `candidates_rejected`, detector duration, and longest pose gap;
- unchanged B3 gates: coverage `>=95%` and p95 time difference `<=33.3 ms`;
- failed sync must keep IMU and camera-motion evidence at
  `INSUFFICIENT_EVIDENCE`.

Do not flash or start motion from this handoff without a new explicit user
authorization.
