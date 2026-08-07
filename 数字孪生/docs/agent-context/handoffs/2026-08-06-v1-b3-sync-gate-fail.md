# V1-B B3 Sync Gate Failure Handoff

Task/Gate: V1-B B3 synchronized capture and data integrity
Status: FAIL; blocked at the sync gate
Date: 2026-08-06 Asia/Shanghai

## Changed files in this handoff

- `tools/camera_toolchain/capture_sync_run.py`: offline diagnostic support for
  health-frame decoding and raw TCP I/O logging, reusing existing shared
  parsers and `RawIoLogger`.
- `simulation/digital_twin/tests/test_capture_sync_cleanup.py`: regression
  coverage for health counters and raw I/O diagnostics.
- `docs/agent-context/CURRENT_STATUS.md`: current B3 boundary and next gate.

No firmware source, firmware image, PID algorithm, PCB, or safety boundary was
changed for this diagnostic preparation.

## Real run evidence

- Run ID: `c260806085721909`
- Raw directory:
  `simulation/digital_twin/data/product/sessions/v1_b/c260806085721909`
- Report:
  `simulation/digital_twin/data/product/sessions/v1_b/c260806085721909/sync_report.json`
- Raw pose:
  `simulation/digital_twin/data/product/sessions/v1_b/c260806085721909/pose.jsonl`
- Raw telemetry:
  `simulation/digital_twin/data/product/sessions/v1_b/c260806085721909/telemetry.jsonl`

## VERIFIED

- C960 actual mode: `MJPG / 1280x720 / 30 fps`.
- START/RUNNING and matching STOP/STOPPED were observed.
- 57 H heartbeats were sent during a 12 second session.
- Socket close, camera release, and reader join completed.
- Raw counts: 355 pose frames and 296 telemetry frames.
- Independent raw-data recomputation agrees with the report:
  - coverage `84.8%` (< `95%` required);
  - p95 time difference `70.7 ms` (> `33.3 ms` required);
  - telemetry interval p95 `78.0 ms`;
  - maximum telemetry gap `327.9 ms`.
- The 296 telemetry frames have 99 distinct PC receive timestamps, with 2 or
  3 frames sharing each receive timestamp. This confirms grouped delivery.

## INFERENCE

The current data is consistent with the firmware/ESP/TCP path delivering
telemetry in batches. The existing run cannot distinguish these possibilities:

1. telemetry frames overwritten in the firmware latest-wins/batch queue;
2. CIPSEND transactions starting or completing too slowly;
3. ESP/TCP grouping or buffering after the firmware has successfully sent.

## INSUFFICIENT EVIDENCE

- The existing B3 run did not record health frames or raw TCP I/O.
- The source already contains health counters, but they were not subscribed to
  by the old capture invocation, so no counter value may be inferred for this
  run.
- B3 sync gate is not passed. B4 dataset freeze, B5 model fitting/holdout, and
  V1-C are blocked.

## Offline verification

- Targeted RED test before implementation: failed because
  `run_sync_capture_session()` did not accept the diagnostics contract.
- Targeted GREEN test: `1 passed`.
- Capture lifecycle regression: `24 passed`.
- Full digital-twin suite: `655 passed, 5 skipped`.
- Health/protocol regression subset: `23 passed`.
- `py -3.11 -m compileall -q tools simulation/digital_twin`: exit `0`.
- `git diff --check`: exit `0` apart from normal LF/CRLF warnings.

## Hardware actions

For the recorded run: camera connected, TCP connected, START sent, 57 H
heartbeats sent, STOP sent and confirmed, socket/camera/reader cleaned up.
No firmware flash or reset occurred in the diagnostic preparation after that
run. No second B3 run has been performed with the new diagnostic code.

## Blocked next interface

Run one new, short B3 diagnostic session with a new run ID, using the updated
capture entrypoint and the already flashed/verified firmware. Preserve
`raw_health.json` and `raw_io.json`. Then independently classify the cause as
firmware generation/overwrite, CIPSEND transaction throughput, or ESP/TCP
delivery grouping. Do not change the B3 thresholds or call the run a pass
unless the original fixed gate is met.

The next hardware run requires an explicit current authorization covering the
C960, ESP TCP session, START/STOP, duration, and the physical safety posture.
