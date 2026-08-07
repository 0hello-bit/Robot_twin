# V1-B B3 diagnostic attribution handoff

Task/Gate: V1-B B3 synchronized capture and data integrity
Status: FAIL; blocked at the sync gate
Date: 2026-08-06 Asia/Shanghai

## Diagnostic run

- Run ID: `c260806092135369`
- Raw directory:
  `simulation/digital_twin/data/product/sessions/v1_b/c260806092135369`
- Entry point: `tools/camera_toolchain/capture_sync_run.py`
- Firmware identity observed in health frames: `fw_build_id=1`, schema `1`
- Camera: C960, `MJPG / 1280x720 / 30 fps`
- Duration: 12 seconds

## VERIFIED

- START/RUNNING and matching STOP/STOPPED were observed for the same run ID.
- 58 host H heartbeats were sent.
- Socket close, camera release, and reader join all completed.
- Raw counts are 356 pose frames and 305 telemetry frames.
- Independent recomputation agrees with the report:
  - coverage `87.6%` (< `95%` required);
  - p95 time difference `64.8 ms` (> `33.3 ms` required);
  - telemetry interval p95 `80.0 ms`;
  - maximum telemetry gap `296.2 ms`.
- `raw_health.json` contains 12 valid health snapshots. The first-to-last
  counter changes are:
  - `telemetry_generated`: `540 -> 1000` (+460);
  - `telemetry_overwritten`: `223 -> 408` (+185);
  - `telemetry_tx_started`: `106 -> 197` (+91);
  - `telemetry_tx_ok`: `105 -> 196` (+91);
  - `cipsend_started`: `124 -> 226` (+102);
  - `cipsend_ok`: `122 -> 224` (+102).
- `cipsend_error`, prompt timeout, SEND OK timeout, and UART overflow counters
  did not increase in the observed health snapshots. CIPSEND last-duration
  samples were `95-146 ms`, with a recorded maximum of `261 ms`.
- Independent parsing of `raw_io.json` with the existing
  `simulation/digital_twin/real_world/frame_parser.py` found 117 RX events,
  305 telemetry frames, 12 health frames, 317 valid binary frames total, and
  zero bad frames or resynchronizations.
- 102 RX events contained telemetry: 101 contained exactly three 29-byte
  telemetry frames and one contained two. This matches the firmware's
  `TELEMETRY_BATCH_MAX_FRAMES=3` and 29-byte frame size.

## VERIFIED ATTRIBUTION

The firmware source in `firmware/stm32_line_follower/User/main.c` and
`telemetry_batch.c` defines a latest-three, droppable telemetry batch. A batch
is consumed by one serialized CIPSEND transaction. The runtime counters and
the raw TCP receive groups agree with this design. The producer is generating
telemetry faster than the serialized CIPSEND path can transmit it, so old
pending samples are overwritten and the host receives groups of 2-3 frames.

This is sufficient to explain the B3 failure. Additional ESP/TCP buffering may
exist, but this run has no packet-level evidence to quantify it and does not
need that hypothesis to explain the failure.

## INSUFFICIENT EVIDENCE

- B3 remains FAIL. The two failed runs must not enter calibration, holdout, or
  V1-C ranking as passed synchronized data.
- No throughput remediation has been changed, built, flashed, or validated.
- No conclusion about line loss, high-speed sharp-turn performance, twin
  calibration quality, or AI-generated algorithm/hardware improvement follows
  from this diagnostic run.

## Required next interface

1. Offline: design the smallest firmware transport remediation that addresses
   the verified batching/throughput root cause without changing the safety
   handshake or B3 thresholds.
2. Add or update host-side and firmware host tests for the changed queue/TX
   contract, then build and record the new firmware identity.
3. Stop and request explicit authorization before flashing or starting the
   car again.
4. After authorization, run one new B3 capture with `raw_health.json` and
   `raw_io.json`, independently recompute the unchanged Gate, and stop at the
   B3 verdict.
