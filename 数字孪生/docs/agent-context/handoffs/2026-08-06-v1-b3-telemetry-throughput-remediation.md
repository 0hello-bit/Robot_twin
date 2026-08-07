# V1-B B3 telemetry throughput remediation handoff

Task/Gate: V1-B B3 synchronized capture and data integrity
Status: OFFLINE REMEDIATION BUILT; BUILD 2 FLASHED; B3 HARDWARE GATE PENDING
Date: 2026-08-06 Asia/Shanghai

## Scope

This handoff records one minimal firmware change for the verified B3 failure
and the subsequent authorized Build 2 flash. One post-flash capture attempt
was made, but it stopped at insufficient pose data because the car was not
under the camera; it did not produce a B3 synchronization verdict.

The previous diagnostic runs remain `FAIL` and must not be promoted into
calibration, holdout, or V1-C data.

## Root cause carried forward

The diagnostic run `c260806092135369` verified that the firmware generated
telemetry faster than its serialized CIPSEND path could transmit it. The source
kept only the latest three 29-byte frames, while health counters and raw TCP
parsing showed repeated groups of three frames and telemetry overwrites.

The fixed B3 thresholds were not changed:

- coverage >= 95%
- p95 pose/telemetry time difference <= 33.3 ms

## Source change

Changed files:

- `firmware/stm32_line_follower/User/telemetry_batch.h`
- `firmware/stm32_line_follower/User/telemetry_batch.c`
- `firmware/stm32_line_follower/User/cipsend_tx.h`
- `firmware/stm32_line_follower/User/health_frame.h`
- `firmware/stm32_line_follower/User/main.c`
- `simulation/digital_twin/real_world/runtime_protocol.py`
- `simulation/digital_twin/tests/test_telemetry_batch.c`
- `simulation/digital_twin/tests/test_cipsend_tx.c`
- `simulation/digital_twin/tests/test_runtime_protocol.py`

Behavioral change:

- latest telemetry batch: 3 frames -> 5 frames
- maximum telemetry batch payload: 87 bytes -> 145 bytes
- CIPSEND TX payload capacity: 112 bytes -> 145 bytes

The telemetry frame format remains 29 bytes. Critical ACK/STATUS handling,
heartbeat, START/STOP lifecycle, parser, connection-boundary cleanup, and
safety behavior were not changed.

The full offline regression also exposed a separate evidence-directory risk:
the capture run ID retained microsecond state but emitted only milliseconds,
so two calls within one output millisecond could collide. The runtime
identifier now compares the truncated millisecond value and advances it by
1 ms when necessary. The wire format remains the same 16-character ID, and
the fix does not change firmware behavior or the B3 thresholds.

## TDD evidence

Before the production change, the new tests were run against the old source:

- the five-frame batch test failed when the fifth frame overwrote the oldest;
- the CIPSEND test rejected a 145-byte telemetry payload.

After the production change:

- telemetry batch Host C test: compile 0, run 0;
- CIPSEND TX Host C test: compile 0, run 0;
- both tests use the current firmware sources, not an archived mirror.

## Regression evidence

- compatible Host C regression: 18/19 suites passed;
- the only non-passing item is the pre-existing `test_motor_pwm_contract`
  host compile, which requires a missing STM32 peripheral host shim. The
  canonical Keil build below compiles the real Motor source successfully;
- Python: `656 passed, 5 skipped`;
- Python compileall for `simulation/digital_twin` and `tools`: exit 0.

## Keil build evidence

Canonical project and target:

```text
firmware/stm32_line_follower/project.uvprojx
Target 1
```

Command:

```text
py -3.11 C:\Users\24668\.codex\skills\keil\scripts\keil_build.py rebuild --uv4 F:\keil\UV4\UV4.exe --project firmware\stm32_line_follower\project.uvprojx --target "Target 1" --log-dir .embeddedskills\build\b3-throughput-remediation-build2 --json
```

Result:

- exit code: 0
- errors: 0
- warnings: 0
- compiler size: `Code=23832 RO-data=460 RW-data=152 ZI-data=3032`
- AXF: `firmware/stm32_line_follower/Objects/Project.axf`
- AXF SHA-256: `2E230EB6ACC09B9942757A7C08C76B4B3D92F8F0B7309AAF61AB46CE3D3B6191`
- build log: `.embeddedskills/build/b3-throughput-remediation-build2/project-Target 1-rebuild.log`
- no separate HEX or BIN was produced.

The source runtime identity constant in the recorded image is now
`fw_build_id=2`. The Build 2 image has been flashed and memory-verified by
Keil, and the setup-invalid capture below observed `fw_build_id=2` in all
12 health snapshots. Therefore a future hardware run must retain the exact
AXF hash and flash log; the runtime identity is now verified, while the hash
and flash record provide the stronger artifact identity.

## Flash evidence

- Authorization: explicit user authorization with ST-Link connected.
- Command: Keil `flash` for the same project and `Target 1`, using the AXF
  above; log:
  `.embeddedskills/build/b3-throughput-remediation-build2/project-Target 1-flash.log`
- Flash log result: `Erase Done.Programming Done.Verify OK.Application
  running ...`
- Flash completed at `2026-08-06 18:52:02 Asia/Shanghai`.
- This proves flash programming and memory verification. The subsequent
  setup-invalid capture independently confirmed the runtime health identity,
  but it did not produce a valid pose stream or prove that B3 synchronization
  passes.

## Build 2 capture attempt: setup invalid

- Run ID: `c260806105643209`
- Evidence directory:
  `simulation/digital_twin/data/product/sessions/v1_b/c260806105643209`
- Camera contract observed: `1280x720`, `MJPG`, approximately `30 fps`.
- Session lifecycle: `START/RUNNING`, 54 host heartbeats, `STOP/STOPPED`,
  socket close, camera release, and reader join all completed successfully.
- Raw counts: 182 camera frames were read successfully, 0 valid poses, and
  444 telemetry frames.
- Runtime identity: all 12 health snapshots reported `fw_build_id=2` and
  `fw_schema_version=1`.
- Health diagnostics changed from `telemetry_generated=24`,
  `telemetry_overwritten=1`, `telemetry_tx_ok=3` to `487`, `65`, and `88`;
  the observed maximum CIPSEND duration was `179 ms`, and UART TX overflow
  increased from `4` to `68`. These are diagnostic observations, not a B3
  pass or a claim of performance improvement.
- Report outcome: `insufficient_data`, `n_poses=0`, `n_telemetry=444`.
- Operator confirmation: the car was not placed under the camera during this
  attempt. Therefore the run is setup-invalid and cannot be used to compute
  coverage or p95 synchronization timing.

## Evidence classification

### VERIFIED

- The source-level capacity change is present in the canonical firmware.
- The new capacity contracts pass targeted Host C tests.
- The current digital-twin Python regression passes.
- The deterministic same-millisecond run-ID regression passes; capture output
  directories remain collision-resistant at the emitted ID precision.
- The canonical embedded project rebuilds with zero errors and warnings.
- The new AXF identity is recorded above.

### INFERENCE

- A five-frame batch is the smallest tested capacity that can carry the
  observed approximately 50 Hz telemetry production rate through an observed
  roughly 100 ms CIPSEND transaction without immediate three-frame overflow.
- The change may improve B3 coverage and timestamp continuity.

### INSUFFICIENT EVIDENCE

- No claim that B3 now passes.
- The Build 2 runtime identity is verified, but no valid pose stream or B3
  synchronization metrics have been collected after the flash.
- No claim that telemetry overwrites or CIPSEND timing improved on the car.
- No claim about line loss, high-speed sharp-turn performance, calibration, or
  digital-twin accuracy.

## Subsequent valid-pose capture: real run ended by LINE_LOST

- Run ID: `c260806113250821`
- Evidence directory:
  `simulation/digital_twin/data/product/sessions/v1_b/c260806113250821`
- The camera contract passed at `1280x720`, `MJPG`, and approximately 30 fps.
  The same calibration/pose path detected the AprilTag in 30/30 preflight
  frames before the run.
- The canonical session sent `START`, observed `RUNNING`, sent 58 heartbeats,
  observed `STOPPED/LINE_LOST`, then sent STOP, observed matching STOPPED,
  and completed socket/camera/reader cleanup.
- Runtime health frames reported `fw_build_id=2` and schema 1.
- Raw counts are 343 pose frames and 102 telemetry frames. Telemetry tick
  coverage ends 2.662 seconds after the first telemetry frame because of the
  line-loss stop.
- The fixed gate failed with coverage `93.939%` and p95 time difference
  `36.408 ms`; thresholds remain coverage `>=95%` and p95 `<=33.3 ms`.
- Independent recomputation from the raw JSONL files matches the report:
  66 common poses, identical coverage and p95, and verdict `FAIL`.
- Raw I/O contains 145-byte telemetry batches and no CIPSEND error in this
  run. This is not enough to claim complete-run throughput improvement because
  the trajectory ended early.

### Evidence classification for this run

#### VERIFIED

- This is a real Build 2 run with valid pose data and complete cleanup.
- Firmware status reported `LINE_LOST` during the run.
- The B3 gate failed under unchanged thresholds, and the report arithmetic is
  independently reproduced.

#### INFERENCE

- The immediate gate failure is dominated by early line-loss termination, not
  camera visibility or report arithmetic.
- The evidence does not yet isolate control-law direction, sensor ordering,
  motor wiring, track geometry, or telemetry throughput as the root cause.

#### INSUFFICIENT EVIDENCE

- Do not consume this run as a passed B3 synchronization dataset.
- Do not claim that the Build 2 throughput remediation passed or failed its
  intended full-run objective from this short trajectory.
- Do not claim that left/right turn direction in firmware is correct or
  inverted without a separate code-path and hardware-mapping audit.

## Next interface

Stop here. Audit the line-following direction chain and sensor/motor mapping
offline before another hardware capture or firmware flash. Only after a
verified defect is found and a constrained change is tested should another
authorized B3 run be considered. Do not enter B4/B5 until B3 actually passes.
