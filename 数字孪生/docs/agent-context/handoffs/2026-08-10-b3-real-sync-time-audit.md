# B3 real capture and time synchronization audit

Date: 2026-08-10
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `ALIGNMENT_PASS_CAUSAL_SYNC_UNVERIFIED`

## Hardware run

- Run ID: `c260810121905472`
- Firmware was not flashed or changed in this run.
- Entry point: `tools/camera_toolchain/capture_sync_run.py`
- Host target: `192.168.110.236:8888`
- Duration: 8 seconds
- Camera: `1920x1080`, `MJPG`, `30.00003 FPS`
- Lifecycle: `START -> RUNNING -> STOP -> STOPPED`
- Poses: 80
- Telemetry frames: 256

The raw run directory is intentionally ignored by Git and remains on disk:
`simulation/digital_twin/logs/v1_b3_real_sync_20260810/c260810121905472/`.
The structured report is `sync_report.json` in that directory.

## Time evidence

- Alignment coverage: `100%`
- Nearest mapped pose/telemetry p95: `15.8065 ms`
- Current matching tolerance: `33.3333 ms`
- Telemetry interval max/p95: `33.0242 / 33.0242 ms`
- Clock fit residual RMS: `28.8033 ms`
- Clock fit residual max: `91.4979 ms`
- Distinct telemetry frames used: `72`
- Maximum telemetry reuse: `2`
- 256 telemetry frames arrived in 67 PC receive batches; the largest batch
  contained 7 frames spanning about 190 ms of MCU ticks.

The existing sync gate is `PASS` because it checks coverage and nearest-match
p95. This verifies coarse data association for this run. It does not verify a
shared physical clock or the exact sensor sampling instant: the fit maps MCU
`tick_ms` to PC receive time, and packet batching remains visible in raw I/O.

## Real-video replay

The retained video SHA-256 is:
`d415b66c8ab716f5b74d1bf69be679492dd74de580e5f1fc8768a821c5cfbf10`.

The same real video was replayed offline with production and
`fast_recovery_wide`:

| Candidate | True tag decode | Pose output | Max gap | Processing p95 |
| --- | ---: | ---: | ---: | ---: |
| production | 57.55% | 57.55% | 8 frames | 89.81 ms |
| fast_recovery_wide | 100.00% | 100.00% | 1 frame | 31.24 ms |

The replay report is:
`docs/evidence/v1_b3_real_sync_replay_20260810/report.json`.

This is a strong result for one real video and qualifies the candidate for one
bounded real A/B. It is not a general arbitrary-speed result, not a live
candidate run, and not a full B3 pass. Prior retained videos still failed the
fixed observation gate. The exploratory relative-plane calibration and lack
of encoder feedback remain separate evidence limits.

## Next boundary

Freeze this state before modifying time synchronization. The next offline task
is to define a device-sample-time and two-way clock-exchange contract, retain
raw arrival/batch metadata, and add clock residual/drift/uncertainty checks to
an independent causal-synchronization gate. Do not relabel the current
alignment `PASS` as causal synchronization.
