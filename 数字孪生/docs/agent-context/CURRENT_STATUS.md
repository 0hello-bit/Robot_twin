# Robot Twin AI - Current Status

Snapshot: 2026-08-07
Canonical workspace: stm32小车/数字孪生

This file is the current authoritative status for the active workspace.
Historical status is preserved in CURRENT_STATUS_LEGACY_20260803.md and must
not override this file.

## V1-A Offline Foundation

Status: ACCEPTED_OFFLINE_ONLY

The following software path is verified:

initial pose + track map + PID candidate -> controller -> plant -> virtual sensor -> next pose

The candidate evaluator runs a baseline plus at least two candidates on one
frozen model and ranks candidates with these rules:

1. completed and no line loss is the only eligible tier;
2. eligible candidates are ordered by predicted completion time;
3. candidate ID is the deterministic tie-breaker;
4. no eligible candidate may be selected or reported READY.

Fresh verification from the canonical portable workspace after the final gate fix:

- V1 closed-loop, evaluator, calibration, and model-registry tests: 74 passed;
- complete simulation/digital_twin/tests: 649 passed, 5 skipped;
- cross-language protocol and C960 route-contract tests: 17 passed, 5 skipped;
- Python 3.11 compileall for simulation/digital_twin and tools: exit 0.

The skipped tests require the excluded real track image and homography assets;
they are not test failures.

## Evidence Boundary

### VERIFIED

- Controller, plant, virtual sensor, predictor, and evaluator are connected in
  one deterministic offline path.
- Different PID candidates can produce different predicted outcomes.
- A line-loss candidate is ranked below completed/no-loss candidates.
- Repeating identical inputs produces identical serialized output.
- Missing or overlapping calibration/holdout IDs cannot report real readiness.
- The evaluator cannot select a candidate when none completes without line
  loss. This was added after independent review found the missing gate.

### INFERENCE

- The exploratory plant wiring is numerically coherent enough for software
  regression and candidate comparison.
- The current controller/plant/sensor combination may be useful as the first
  calibration target.

### INSUFFICIENT EVIDENCE

- No real synchronized calibration fit has been supplied.
- No independent real holdout validation has been supplied.
- PWM-to-velocity, turn response, camera-to-ground mapping, and encoder-like
  speed are not verified by this V1-A task.
- No real-car B/C comparison has occurred.
- No AI-generated core algorithm patch or PCB has been validated.

## V1-B B2 Hardware Smoke

Status: bounded hardware smoke control path passes; latest Build 2 run
verified MPU initialization failure.

After the camera evidence fix and the canonical AXF flash, a fresh authorized
elevated-wheel run completed on 2026-08-06 at 15:55. The immutable evidence is
at `simulation/digital_twin/logs/v1_ground_shakedown_260806155533430` and the
report verdict is `SHAKEDOWN_PASS`.

### VERIFIED

- `control_verdict=PASS`; no primary failure, parser error, protocol anomaly,
  or cleanup error was reported.
- Runtime identity was observed as `fw_build_id=1` and `schema=1`.
- All five bounded speed updates `580, 480, 380, 280, 260` returned correlated
  `APPLIED/APPLIED` ACKs.
- The same campaign/run confirmed START/RUNNING, host heartbeat, terminal
  STOP/STOPPED, quiescence, and socket connect/close exactly once.
- `camera_verdict=PASS`; the recorded stream is MJPEG at `1280x720` and
  `30/1` FPS, while the same FFmpeg input log proves source `MJPG`.
- `camera.mkv`, `camera_ffmpeg.log`, `raw_io.json`, and
  `shakedown_report.json` are present.
- The final report records `stop_confirmed=true`, `forced_termination=false`,
  `cut_power_warning=false`, and `imu_evidence_status` explicitly remains
  `UNVERIFIED_NO_VALIDITY_BIT`.

The Matroska container still reports codec tag `[0][0][0][0]`; this is now
classified as container-unspecified rather than source failure. The source
FourCC is verified from the same FFmpeg input log, which is why the camera
contract passes. The detailed handoff is
`docs/agent-context/handoffs/2026-08-06-v1-b2-hardware-smoke-pass.md`.

The latest post-flash elevated-wheel gate completed on 2026-08-06 at 22:47
with the same canonical entrypoint. Its immutable evidence is at
`logs/v1_ground_shakedown_260806224756564`. It returned `SHAKEDOWN_PASS` for
the control/camera lifecycle, but raw 26-byte telemetry re-decoded to
`imu_init_status=0x21` (`WHO_AM_I_MISMATCH`), with validity `0x14` once and
`0x04` thereafter. It therefore does not pass the MPU gate and must not be
used as evidence of valid IMU pose input. The report adapter currently drops
these two fields; the raw I/O is the authoritative evidence until that offline
gap is repaired.

### INFERENCE

- The existing ESP-01S transport, runtime protocol, bounded parameter path,
  telemetry path, camera recorder, and STOP cleanup can complete one real
  hardware smoke session through the canonical entrypoint.

### INSUFFICIENT EVIDENCE

- This run does not measure actual wheel speed or displacement, because it is
  an elevated-wheel smoke rather than a ground experiment.
- It does not prove no-line-loss, faster high-speed sharp-turn behavior, a
  real A/B/C candidate improvement, digital-twin calibration quality, or
  AI-generated algorithm/hardware improvement.
- The health snapshot includes `health_dropped=62` and `health_failed=0`;
  preserve this counter for later observability analysis instead of treating
  it as a performance result.

## V1-B B3 Sync Gate

Status: the latest synchronized run passes the fixed B3 sync gate, but
downstream data readiness remains blocked by sparse AprilTag detection

Two authorized synchronized captures completed real sessions, and both failed
the fixed synchronization contract. The raw runs are immutable at:

`simulation/digital_twin/data/product/sessions/v1_b/c260806085721909`

`simulation/digital_twin/data/product/sessions/v1_b/c260806092135369`

### VERIFIED

- The run used the C960 at `MJPG / 1280x720 / 30 fps`.
- START/RUNNING and the matching STOP/STOPPED status were observed for the
  same `run_id`.
- The host sent 57 H heartbeats during the 12 second session.
- Cleanup completed: socket closed, camera released, reader joined.
- Raw counts are 355 pose frames and 296 telemetry frames.
- Independent recomputation from `pose.jsonl` and `telemetry.jsonl` agrees with
  the report: coverage `84.8%`, p95 time difference `70.7 ms`, telemetry
  interval p95 `78.0 ms`, and maximum telemetry gap `327.9 ms`.
- The telemetry stream has 99 distinct PC receive timestamps for 296 frames;
   each receive group contains 2 or 3 frames. This is direct evidence of
   batched delivery, not a report arithmetic error.
- The diagnostic rerun used the updated capture entrypoint and persisted
  `raw_health.json` and `raw_io.json` for run `c260806092135369`.
- The rerun used the C960 at `MJPG / 1280x720 / 30 fps`, observed
  START/RUNNING and matching STOP/STOPPED, sent 58 H heartbeats, and cleaned
  up socket, camera, and reader successfully.
- Rerun raw counts are 356 pose frames and 305 telemetry frames. Independent
  recomputation gives coverage `87.6%`, p95 time difference `64.8 ms`,
  telemetry interval p95 `80.0 ms`, and maximum telemetry gap `296.2 ms`.
- Independent parsing of `raw_io.json` found 117 RX events and 317 valid
  binary frames with zero checksum failures. 102 RX events carried telemetry:
  101 events carried exactly three 29-byte telemetry frames and one carried
  two frames. This is reproducible batch delivery, not parser corruption.
- Runtime health snapshots show, over the observed interval,
  `telemetry_generated` 540 -> 1000, `telemetry_overwritten` 223 -> 408,
  `telemetry_tx_started` 106 -> 197, `telemetry_tx_ok` 105 -> 196, and
  `cipsend_started` 124 -> 226 with `cipsend_ok` 122 -> 224. CIPSEND last
  durations were `95-146 ms` and the observed maximum was `261 ms`; no
  CIPSEND error or UART overflow occurred.

### VERIFIED ATTRIBUTION

- The current firmware source defined a fixed latest-three telemetry batch and
  sends that batch as one CIPSEND transaction. The runtime counters and raw
  TCP bytes agree with that implementation: the car is producing telemetry
  faster than its serialized CIPSEND path can transmit it, overwriting old
  pending telemetry and delivering 2-3 frames at a time.
- The primary B3 failure is therefore verified as a firmware telemetry
  batching/throughput problem. ESP/TCP may add buffering, but it is not needed
  to explain the observed loss and timing failure; this run does not contain
  packet-level evidence to quantify any additional ESP/TCP contribution.

### VERIFIED OFFLINE REMEDIATION

- The minimal source remediation enlarges the droppable telemetry batch from
  3 to 5 frames and the CIPSEND payload buffer from 112 to 145 bytes. The
  telemetry frame remains 29 bytes; START/STOP, heartbeat, ACK/STATUS
  priority, parser, rollback, and safety boundaries are unchanged.
- TDD RED was observed before the source change: the new five-frame batch
  assertion failed at the fifth frame, and the 145-byte CIPSEND start was
  rejected by the old 112-byte limit.
- Targeted Host C tests are GREEN for the five-frame batch and 145-byte
  CIPSEND payload. The compatible Host C regression set is 18/19 GREEN; the
  one excluded result is the pre-existing `test_motor_pwm_contract` host
  compile, which lacks the STM32 peripheral host shim and is not part of this
  transport change.
- Fresh Python regression is `656 passed, 5 skipped`; Python compileall for
  `simulation/digital_twin` and `tools` exits 0.
- The same full regression exposed a same-millisecond capture run-ID
  collision. A deterministic regression now covers that case, and the
  runtime identifier generator advances the emitted millisecond when needed.
- Canonical Keil `Target 1` rebuild is `0 Error(s), 0 Warning(s)`. The compiler
  reports `Code=23832`, `RO-data=460`, `RW-data=152`, `ZI-data=3032`.
- The new offline image is
  `firmware/stm32_line_follower/Objects/Project.axf` with SHA-256
  `2E230EB6ACC09B9942757A7C08C76B4B3D92F8F0B7309AAF61AB46CE3D3B6191`.
  No separate HEX or BIN was produced by this build.
- The build evidence and detailed boundary are recorded in
  `docs/agent-context/handoffs/2026-08-06-v1-b3-telemetry-throughput-remediation.md`.

### VERIFIED HARDWARE FLASH

- After explicit authorization, the recorded Build 2 AXF was flashed through
  Keil with the connected ST-Link on 2026-08-06 at 18:52:02.
- The flash log records `Erase Done`, `Programming Done`, `Verify OK`, and
  `Application running`.
- The flashed artifact path and SHA-256 remain the recorded Build 2 values;
  no `START`, `STOP`, or synchronized capture was sent in this action.

### VERIFIED BUILD 2 CAPTURE ATTEMPT; SETUP INVALID

The first post-flash capture used run ID
`c260806105643209` and is preserved at
`simulation/digital_twin/data/product/sessions/v1_b/c260806105643209`.

- Runtime health frames observed `fw_build_id=2` and `schema=1` in all 12
  health snapshots.
- The canonical session sent `START`, observed `RUNNING`, sent 54 heartbeats,
  sent `STOP`, observed matching `STOPPED`, and completed socket/camera/reader
  cleanup.
- The camera was actually `1280x720`, `MJPG`, approximately `30 fps`; 182
  frames were read successfully, but 0 produced a valid pose.
- The session received 444 telemetry frames. Health counters changed from
  `telemetry_generated=24`, `telemetry_overwritten=1`, `telemetry_tx_ok=3`
  to `487`, `65`, and `88`; this is diagnostic evidence only.
- The operator confirmed after the run that the car had not been placed under
  the camera. The resulting `insufficient_data` report is a setup-invalid
  capture, not a B3 synchronization verdict.

### VERIFIED B3 CAPTURE ATTEMPT; REAL RUN ENDED BY LINE_LOST

The first valid-pose post-flash capture used run ID
`c260806113250821` and is preserved at
`simulation/digital_twin/data/product/sessions/v1_b/c260806113250821`.

- The camera contract passed at `1280x720`, `MJPG`, and approximately 30 fps;
  the preflight detected the AprilTag in 30/30 frames before the run.
- The canonical session sent `START`, observed `RUNNING`, sent 58 heartbeats,
  observed a firmware `STOPPED/LINE_LOST` event, then completed the explicit
  STOP/STOPPED gate and closed the socket, camera, and reader cleanly.
- The runtime health frames reported `fw_build_id=2` and `schema=1`.
- The raw run contains 343 pose frames and 102 telemetry frames. Telemetry
  covers only 2.662 seconds of MCU tick time before the `LINE_LOST` event.
- The fixed B3 gate failed: coverage is `93.939%` (required `>=95%`) and p95
  pose/telemetry time difference is `36.408 ms` (required `<=33.3 ms`).
- Independent recomputation from `pose.jsonl` and `telemetry.jsonl` matches
  the report exactly: 66 common poses, the same coverage, the same p95, and
  verdict `FAIL`.
- Raw I/O shows 145-byte telemetry batches and no CIPSEND error in this run,
  but the short post-line-loss telemetry window is not enough to claim that
  the throughput remediation improved the full run.

### EVIDENCE BOUNDARY AFTER THIS RUN

#### VERIFIED

- This is a real Build 2 run with a valid camera pose stream and complete
  cleanup evidence.
- The firmware reported `LINE_LOST` during the run, and the synchronized gate
  failed under the unchanged thresholds.
- The report arithmetic is independently reproduced from the raw JSONL data.

#### INFERENCE

- The immediate B3 failure is dominated by the early line-loss termination,
  not by a camera setup failure.
- The run is useful evidence that the current closed-loop trajectory does not
  yet provide a stable synchronization dataset; it does not isolate whether
  the cause is control logic, sensor/motor mapping, track setup, or telemetry
  throughput.

#### INSUFFICIENT EVIDENCE

- No B3 pass, calibration fit, holdout validation, or V1-C comparison may
  consume this run as a passed synchronization dataset.
- No claim that Build 2 improved telemetry throughput over the complete
  12-second run.
- No claim that the left/right turn direction in the firmware is correct or
  incorrect; that requires a separate code-path and hardware-mapping audit.

### INSUFFICIENT EVIDENCE

- No calibration fit, holdout validation, or V1-C candidate comparison may
  consume either failed run as a passed synchronization dataset.
- Build 2 has been flashed and verified by Keil, and its runtime identity was
  confirmed in both post-flash captures. The setup-invalid run has no pose
  stream; the valid-pose run has a computed but failing B3 verdict.

### Diagnostic preparation and attribution

`capture_sync_run.py` now reuses the existing `MixedStreamParser`,
`decode_health`, `compute_health_summary`, and `RawIoLogger` to persist
`raw_health.json` and `raw_io.json`. The complete diagnostic evidence and
independent raw-I/O parsing are recorded in
`docs/agent-context/handoffs/2026-08-06-v1-b3-diagnostic-attribution.md`.

## Current Next Interface

B1 remains accepted as `ACCEPTED_OFFLINE_ONLY`. B2 is accepted only for the
bounded `SHAKEDOWN_PASS` hardware smoke described above. B3 remains `FAIL`;
do not enter B4 or B5 and do not collect another run merely to hide the
failure. The offline throughput remediation is built, independently tested,
and the recorded Build 2 AXF has been flashed and verified. The next
interface is an offline audit of the line-following direction chain and the
sensor/motor mapping, followed by a constrained change only if that audit
finds a verified defect. Do not claim B3 success from either failed capture,
the Build 2 flash result, or the offline regression alone.

Do not declare the real twin READY from this smoke, the failed B3 run,
synthetic evidence, or offline tests alone.

### VERIFIED OFFLINE MPU6050 POSE FUSION PATH (PRIOR BUILD)

- Task 1-3 decoder, firmware validity, and pure camera-anchored fusion work
  remain offline-verified only. IMU yaw is still observation data and does not
  feed PID, motor control, direction decisions, or safety stops.
- The existing synchronized capture path now passes current 26-byte IMU fields
  through the existing telemetry model and writes additive fusion.jsonl from
  existing nearest-timestamp ds.sync_frames. Raw pose/telemetry files and the
  B3 verdict path remain separate.
- Focused capture/fusion tests: 88 passed. Full current Python regression:
  669 passed, 5 skipped using
  py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests.
  compileall and git diff --check exit 0.
- Fresh Host C contracts for telemetry batch, CIPSEND TX, and MPU6050 validity
  compile and run exit 0. The prior pose-fusion build of Keil
  project.uvprojx, Target 1, reported 0 Error(s), 0 Warning(s); its AXF
  SHA-256 was
  2AF108A40D2C008F4D945804541DBA342F86CBE720576DD17C65F30F527071E4.
- After explicit user authorization, that prior pose-fusion AXF was flashed
  through Keil Target 1 with ST-Link. The flash log records Erase Done,
  Programming Done, Verify OK, and Application running; its AXF SHA-256 was
  2AF108A40D2C008F4D945804541DBA342F86CBE720576DD17C65F30F527071E4.
  Physical MPU validity, camera/IMU synchronization, and any real improvement
  remain INSUFFICIENT EVIDENCE. The next interface is stationary runtime
  validity verification, documented in
  docs/agent-context/handoffs/2026-08-06-mpu6050-pose-fusion-offline.md.

### VERIFIED OFFLINE MPU6050 INITIALIZATION REPAIR

Status: `FLASH_VERIFIED`; elevated-wheel START gate completed; MPU
initialization failed on hardware.

- Initialization now performs one complete sequence plus at most three retries,
  for a maximum of four complete attempts. It keeps address `0x68`, resets
  bias state for every attempt, and fails closed after exhaustion.
- Stable stage status codes distinguish configuration writes, WHO_AM_I read
  failure, WHO_AM_I mismatch, and bias-read failure. A nonzero boot status
  cannot enter IMU fusion, and a later readable sample cannot promote a failed
  boot to initialized.
- The existing 31-byte wire frame and 26-byte payload are unchanged. Payload
  byte 24 remains `imu_validity`; payload byte 25 (wire byte 29) carries
  `imu_init_status`. Legacy 24-byte payloads remain accepted with the status
  marked unknown.
- PID, motor mapping, line-loss handling, speed limits, turn logic, safety
  stops, transport ownership, and capture lifecycle were not changed by this
  repair.

Fresh offline verification for this repair:

- `py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests`:
  `671 passed, 5 skipped`.
- `py -3.11 -m compileall -q simulation/digital_twin tools`: exit 0.
- `git diff --check`: exit 0; only Git's existing LF/CRLF warnings were
  emitted.
- Host C `test_mpu6050_validity`: compile and run exit 0;
  `PASS test_mpu6050_validity`.
- Host C `test_telemetry_batch`: compile and run exit 0;
  `telemetry_batch: all tests passed`.
- Host C `test_cipsend_tx`: compile and run exit 0;
  `PASS test_cipsend_tx`.
- Keil Target enumeration found exactly `Target 1`. The canonical rebuild
  reported `0 Error(s), 0 Warning(s)`, Code=24020, RO-data=460,
  RW-data=156, ZI-data=3052.
- The current offline artifact is
  `firmware/stm32_line_follower/Objects/Project.axf` with SHA-256
  `DEF9E50B261B5D289DA3ABF8A0F905B1864D7756EE749DC5B0AA3F6F46CC58C8`.
  Build evidence is at
  `.embeddedskills/build/2026-08-06-mpu6050-init-repair/keil/project-Target 1-rebuild.log`.

#### VERIFIED

- The bounded initialization, status propagation, legacy parser compatibility,
  schema round-trip, and fusion rejection behavior are verified offline by
  tests and Host C contracts.
- The current source builds successfully for Keil Target 1.
- After explicit user authorization, the exact current AXF was flashed through
  Keil Target 1 with ST-Link. The flash log records `Erase Done`,
  `Programming Done`, `Verify OK`, and `Application running`. No START/STOP,
  serial send, camera session, or motor motion was performed.
- A five-second passive TCP observation connected to the flashed
  `fw_build_id=2` image and received six RX events, including five health
  frames. It sent zero bytes and received zero telemetry frames. All health
  snapshots reported `motion_state=0`, `lease_active=0`, and
  `telemetry_generated=0`.

#### VERIFIED REAL-HARDWARE ELEVATED-WHEEL GATE

- After the separate elevated-wheel authorization, the canonical
  `ground_shakedown.py` entrypoint ran `START -> telemetry collection -> STOP`
  for `0.5s` on 2026-08-06 22:47. No ground motion was authorized or used.
- Immutable evidence is at
  `logs/v1_ground_shakedown_260806224756564/`; the flashed AXF identity is
  `DEF9E50B261B5D289DA3ABF8A0F905B1864D7756EE749DC5B0AA3F6F46CC58C8`.
- The report returned `SHAKEDOWN_PASS` and `control_verdict=PASS`. All five
  speed updates (`580, 480, 380, 280, 260`) received correlated
  `APPLIED/APPLIED` ACKs. The same run observed `START/RUNNING`, two
  heartbeats, terminal `STOP/STOPPED`, `stop_confirmed=true`, and proven
  quiescence. No parser error, protocol anomaly, primary failure, or cleanup
  error was recorded.
- Raw I/O contains 14 RX events and 10 TX events. Independent parsing of the
  immutable raw bytes found 14 valid binary frames and zero checksum or
  resynchronization errors, including 12 telemetry frames and two health
  frames. The health snapshots report `fw_build_id=2`, `schema=1`, no
  heartbeat timeout, and no CIPSEND/UART error.
- The camera recorder completed cleanly at `1280x720` and `30/1` FPS. The
  input log verifies source `MJPG`; the Matroska output tag remains
  container-unspecified (`[0][0][0][0]`).

#### VERIFIED HARDWARE FAILURE ATTRIBUTION

- Re-decoding the raw 26-byte telemetry payload with the existing
  `decode_telemetry` parser found `imu_init_status=0x21` on all 12 frames,
  which is the firmware's `WHO_AM_I_MISMATCH` status.
- The first telemetry frame carried `imu_validity=0x14`; subsequent frames
  carried `0x04`. Thus the read bit was present, but the required
  `INIT|BIAS|READ|UPDATED` mask (`0x0F`) was never present. The first frame
  also carried `DT_CLAMPED` (`0x10`). `yaw=0.0` throughout is therefore not
  evidence of a valid stationary pose; the firmware correctly kept fusion
  unavailable after failed initialization.
- This is a verified real-hardware initialization failure, not merely missing
  evidence. The exact physical cause remains unresolved: the raw status does
  not distinguish wiring/power, address selection, or the connected module's
  WHO_AM_I response.

#### VERIFIED OFFLINE EVIDENCE ADAPTER REPAIR

- `_SessionLoop._on_telemetry()` now preserves `imu_yaw_deg_x100`,
  `imu_validity`, `imu_validity_known`, `imu_init_status`, and
  `imu_init_status_known` in each report frame.
- `summarize_imu_evidence()` now separates `VERIFIED` evidence from
  `INSUFFICIENT_EVIDENCE`. A verified frame set also carries a separate
  `verdict=PASS/FAIL`, so known MPU failure cannot be mistaken for missing
  data or a successful sensor.
- Replaying the existing raw run through the new offline path gives
  `status=VERIFIED`, `verdict=FAIL`, `imu_init_status=0x21`, validity values
  `0x14/0x04`, and one `DT_CLAMPED` frame. The old immutable report is not
  rewritten; it was generated before this adapter repair.
- The timestamp regression in the existing execution path was fixed with one
  regression test. Focused ground-shakedown tests are `106 passed`; the full
  Python suite is `675 passed, 5 skipped`.

#### INFERENCE

- The mismatch was observed after a successful read transaction, but the raw
  evidence alone cannot identify whether the board has an I2C wiring/power
  problem, an address/AD0 mismatch, or a different responding device.

#### INSUFFICIENT EVIDENCE

- The physical root cause of the `WHO_AM_I` mismatch, bias quality after a
  repaired initialization, axis sign/scale, camera/IMU synchronization, and
  any vehicle improvement remain unverified.
- No ground no-line-loss or high-speed sharp-turn improvement was tested.

The next interface is a physical I2C/power/address/WHO_AM_I audit. Only after
those are resolved should another separately authorized elevated-wheel session
require `imu_validity=0x0F`, `DT_CLAMPED=0`, and `imu_init_status=0x00`; ground
motion remains prohibited. The detailed handoff is
`docs/agent-context/handoffs/2026-08-06-mpu6050-init-repair-offline.md`.

### VERIFIED OFFLINE MPU6050 IDENTITY DIAGNOSTIC

Status: `COMPATIBILITY_PATCH_FLASHED`; post-flash TCP observation is currently
blocked before any IMU frame is received.

- The previous real run remains verified as `imu_init_status=0x21`, but the
  physical cause is still unresolved because the old telemetry did not carry
  the raw WHO_AM_I byte.
- The current source reads WHO_AM_I before any reset/configuration write and
  clears the observed ID at the start of every initialization attempt. The
  diagnostic ID therefore belongs to the final attempt; if that attempt's
  WHO_AM_I transaction fails, the ID is `0x00` instead of an ID from an older
  retry.
- The additive `0x7D` frame uses the existing ESP/CIPSEND path and a distinct
  `CIPSEND_TX_TAG_IMU_DIAGNOSTIC`. Its pending flag remains set through busy,
  ERROR, timeout, or CLOSED outcomes and is cleared only after the matching
  transaction returns `SEND OK`. Existing `0x7E`, health, ACK, STATUS, and
  telemetry arbitration remain unchanged.

### VERIFIED REAL-HARDWARE IDENTITY OBSERVATION

The authorized passive session used the existing `transport_soak.py` path on
2026-08-07 from 12:04:19 through 12:04:31. It sent zero bytes and recorded
the immutable raw evidence at
`logs/v1_mpu6050_identity_260807/soak_20260807_120419/`.

- Independent decoding of `raw_io.json` found 13 valid binary frames and zero
  checksum or resynchronization failures.
- The first binary frame was `0x7D` with
  `observed_id=0x70`, `init_status=0x21`, `validity_flags=0x00`, and
  `reserved=0x00`.
- Twelve health frames all reported `fw_build_id=3`, `motion_state=0`, and
  `lease_active=0`. The passive session sent `n_tx=0`; no START, STOP,
  heartbeat, or motion command was sent.
- The `0x70` response is stable and the WHO_AM_I transaction is therefore
  verified as readable. The current failure is an identity whitelist failure,
  not evidence of a read timeout or a collision.
- An independent recheck after a power cycle at 12:25:31-12:25:41 is
  preserved at
  `logs/v1_mpu6050_identity_recheck_260807/soak_20260807_122531/`.
  It sent zero bytes, decoded 11 valid binary frames with zero checksum or
  resynchronization failures, and again observed
  `observed_id=0x70`, `init_status=0x21`, and `validity_flags=0x00`.
  All 10 health frames again reported `fw_build_id=3`, `motion_state=0`, and
  `lease_active=0`.

### POST-FIX OBSERVATION BLOCKED

After the compatibility AXF was flashed, three passive attempts at
12:31:31, 12:32:15, and 12:34:11-12:34:19 received `WinError 10061` from
`192.168.110.236:8888`. Ping and ARP still verified the ESP host was online,
but the TCP service actively refused connections even after the firmware's
approximately 16.5 second ESP setup window. No MCU bytes were sent and no
post-fix IMU frame was received. This is a communication/startup observation
gap, not evidence that the compatibility initialization passed or failed.

Fresh verification for the current source:

- `py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests`:
  `676 passed, 5 skipped`.
- `py -3.11 -m compileall -q simulation/digital_twin tools`: exit 0.
- `git diff --check`: exit 0; only existing LF/CRLF warnings were emitted.
- ARMCC C99 source compilation passed for `test_imu_diagnostic.c`,
  `test_mpu6050_validity.c`, and the changed `mpu6050.c`.
- Keil `Target 1` rebuilt the compatibility source with `0 Error(s),
  0 Warning(s)`; Code=24284, RO-data=460, RW-data=156, ZI-data=3052.
  The authoritative build log is
  `.embeddedskills/build/2026-08-07-mpu6500-compat/keil/project-Target 1-rebuild.log`.
- Current AXF:
  `firmware/stm32_line_follower/Objects/Project.axf`
- Current compatibility AXF SHA-256:
  `FEB4D761F4AF714D1A5BB0D70728A60724374A3542AF040D37D2E2F316553DDB`
- After explicit authorization on 2026-08-07 at 12:29:47, this exact
  compatibility AXF was flashed through Keil Target 1 with ST-Link. The flash
  log records `Erase Done`, `Programming Done`, `Verify OK`, and
  `Application running`. No START, STOP, or motion command was sent.

#### VERIFIED

- The source and current AXF are aligned by the fresh Keil rebuild.
- The new diagnostic frame format and parser contract execute in the Python
  regression suite; the final-attempt ID and SEND-OK delivery assertions
  compile under ARMCC C99. Current Host C runtime execution is intentionally
  not claimed.
- The exact compatibility AXF was flashed and verified through Keil; this is
  programmer evidence only, not proof that the IMU initialized successfully.
- The observed `0x70` case is now covered by the compatibility test contract;
  unknown `0x71` remains fail-closed.

#### INFERENCE

- `0x70` is consistent with an MPU6500-class responder, but the exact module
  marking is not independently verified. The current driver only uses the
  register subset shared by the two explicitly accepted identities, so the
  compatibility path is a bounded inference that still requires hardware
  confirmation.

#### INSUFFICIENT EVIDENCE

- The post-fix physical init result is still unknown; no passive observation
  has been collected after flashing the compatibility AXF.
- The current environment has no host C compiler available; the pre-existing
  Host C executables were not reused as evidence for the latest test-source
  changes. ARMCC source compilation and Keil firmware compilation passed.
- Power, common ground, pull-ups, AD0, SDA/SCL integrity, and the actual
  component marking remain unverified. Valid IMU bias, axis sign/scale, and
  vehicle improvement were not tested.

The compatibility AXF is now flashed. First restore the existing TCP service
and verify a passive health/diagnostic connection. Keep motion inhibited and do
not send START or permit ground motion until the new `0x7D` status is observed.

## 2026-08-07 Compatibility Regression Recovery

Status: `RECOVERY_FLASHED_PASSIVE_DIAGNOSTIC_VERIFIED`

The compatibility AXF was flashed at 12:29:47. After the expected ESP setup
window, the existing TCP endpoint remained actively refused while the ESP IP
continued to answer ping. This is a verified runtime regression observation,
but it does not by itself prove whether the MCU stopped during MPU startup or
the ESP server was not re-established.

Source audit identified the only hardware-path change after the previously
observable Build 3 image: `mpu6050.c` changed `0x70` from a diagnostic mismatch
to an accepted identity, then entered reset/configuration and 100-sample bias
sampling. The exact model compatibility was an inference, not a verified
driver contract.

Recovery change:

- `0x68` remains the only identity accepted by the verified MPU6050 driver.
- `0x70` remains observable through the diagnostic frame but is fail-closed
  before any reset/configuration write.
- The corresponding Host C regression now asserts `observed_id=0x70`,
  `init_status=0x21`, and zero reset writes.

Fresh offline verification:

- Host C `test_mpu6050_validity`: `PASS test_mpu6050_validity`.
- Python regression: `676 passed, 5 skipped`.
- Python compileall: exit 0.
- Keil `Target 1`: `0 Error(s), 0 Warning(s)`; Code=24280,
  RO-data=460, RW-data=156, ZI-data=3052.
- Recovery AXF SHA-256:
  `76689F796C4FD1AFDD478352B49A84F21F719301F36FFB339C9CAD17B2786B32`.
- After explicit authorization, the recovery AXF was flashed through Keil
  Target 1 at 12:54:36. The flash log records a successful operation; no
  START, STOP, or motion command was sent.
- The first passive retest at 12:55:22 still received WinError 10061 from
  `192.168.110.236:8888`. Ping remained available. No diagnostic frame was
  received, so physical MPU initialization is still unclassified.
- The compatibility-identity acceptance is therefore not proven to be the
  sole cause of the TCP regression. The next hardware variable is a complete
  car/ESP power cycle, followed by one more passive connection attempt.

Power-cycle retest after the recovery flash:

- The car was powered from the Li-ion battery and the existing passive
  `transport_soak.py` path connected successfully to `192.168.110.236:8888`.
- The run recorded 4 RX events / 270 RX bytes and 0 TX events / 0 TX bytes;
  parser errors were zero.
- The diagnostic frame was `AA 55 7D 04 70 21 00 00 28`, meaning
  `observed_id=0x70`, `init_status=0x21`, and `validity_flags=0x00`.
- Two health frames reported `fw_build_id=3`, `motion_state=0`,
  `lease_active=0`, `loop_last_gap_ms=5`, and no UART or CIPSEND errors.
- This verifies the recovery firmware and the passive transport path after a
  complete power cycle. It does not verify MPU initialization or permit
  START/ground motion; motion remains blocked at the identity gate.

## Mandatory Reuse Rule

Every agent must read `docs/agent-context/PROJECT_MEMORY.md` before changing
the project. V1-B B2 must use
`tools/shakedown_toolchain/ground_shakedown.py` as its canonical hardware
Smoke entrypoint. It already reuses the ESP transport, runtime protocol,
speed/ACK gates, H heartbeat, STOP safety lifecycle, telemetry parsing, raw
logging, and cleanup. Do not build a second TCP client, heartbeat sender,
parser, ACK registry, or capture lifecycle. `capture_sync_run.py` remains a
later synchronized-collection path, not a B2 control path.

### LATEST OFFLINE MPU6050 CONTROL-SHADOW PREPARATION (2026-08-07)

- The latest authorized elevated-wheel evidence at
  `logs/v1_ground_shakedown_260807160902261/shakedown_report.json` reports
  `imu_init_status=0x00` and normal `imu_validity=0x0F` frames, with one
  `0x1F` frame carrying `DT_CLAMPED`. This verifies initialization and
  read/update status for that run; all yaw values were `0.0` degrees.
- Dynamic yaw response, axis sign, scale, drift, and any control benefit are
  still `INSUFFICIENT EVIDENCE`. MPU6050 is not currently used by firmware
  control; its yaw is still telemetry/fusion input only.
- The offline-only `V1ImuControlShadow` now proves that an eligible fused IMU
  record can change a bounded hypothetical turn while invalid or unknown IMU
  data fails closed to the baseline. It has no hardware side effect.
- The existing synchronized capture path now writes additive
  `imu_evidence.json`. Synthetic records remain `INSUFFICIENT_EVIDENCE`; a
  `REAL_SYNC` summary is `VERIFIED` only for structural evidence prerequisites
  and is not a claim of sensor or twin accuracy.
- Focused tests passed (`7 + 27 + 41`); the full current Python regression is
  `685 passed, 5 skipped`, compileall exits 0, and `git diff --check` reports
  no whitespace errors.
- Detailed handoff and next gate:
  `docs/agent-context/handoffs/2026-08-07-mpu6050-offline-control-shadow.md`.
  The next hardware interface is a bounded elevated-wheel rotation
  observation for non-zero yaw response and sign; do not change real firmware
  control before it passes.

### LATEST VERIFIED MPU6050 DYNAMIC YAW OBSERVATION (2026-08-07)

- The authorized elevated-wheel run used the existing
  `transport_soak.py --run` path for 10 seconds while the user slowly rotated
  the car to the right. Evidence is preserved at
  `logs/imu_yaw_rotation/soak_20260807_173821/`.
- The raw telemetry contains 371 frames. `imu_init_status=0x00` appears on
  every frame; validity is `0x0F` or `0x1F` (one `DT_CLAMPED` sample).
- yaw changed from `0.00` to `11.68` degrees. Of 370 transitions, 260 were
  positive, 22 negative, and 88 unchanged; maximum single-step change was
  `0.33` degrees. This verifies a dynamic yaw response during the authorized
  maneuver.
- START/RUNNING and STOP/STOPPED were confirmed and parser errors were zero.
  The transport cadence gate passed; the independent main-loop nonblocking
  gate failed at `blocking_ratio_median=5.45`, which is a separate runtime
  transport result and does not invalidate the observed yaw change.
- The sign mapping, absolute scale, drift, and any control improvement remain
  `INFERENCE` or `INSUFFICIENT EVIDENCE`. Do not change firmware control yet.
- Detailed handoff:
  `docs/agent-context/handoffs/2026-08-07-mpu6050-dynamic-yaw-observation.md`.

### LATEST OFFLINE NO-ENCODER MOTION OBSERVER (2026-08-07)

- The active car has no wheel encoder feedback. Current `m1..m4` telemetry is
  commanded PWM, not measured wheel speed or RPM.
- `simulation/digital_twin/v1_twin/v1_twin_motion_observer.py` now derives
  whole-car planar velocity, planar speed, and camera-frame yaw rate from
  adjacent calibrated `V1Pose` records. It uses millimeters/seconds and
  shortest-angle yaw differences.
- The observer rejects the first sample, non-monotonic timestamps, and pose
  gaps above its bound. It resets the predecessor after a rejected sample and
  never bridges an invalid interval.
- Focused observer and IMU-shadow/fusion tests pass: `22 passed`.

#### VERIFIED

- The finite-difference math, angle wrap handling, input immutability, and
  fail-closed timestamp behavior are verified offline.
- The result is explicitly labeled `CAMERA_POSE_DERIVATIVE` and is external
  whole-car motion evidence only.

#### INSUFFICIENT EVIDENCE

- No wheel RPM, four-wheel speed, or motor-side feedback is available.
- Real camera-derived speed, camera/IMU synchronized calibration, calibrated
  vehicle-frame direction, and any control improvement remain unverified.
- This offline observer does not permit B3, real firmware control, or a real
  high-speed sharp-turn claim.

### LATEST OFFLINE CAMERA MOTION EVIDENCE ADAPTER (2026-08-07)

Status: `OFFLINE_VERIFIED_REAL_SYNC_PENDING`

- Added the pure offline report builder at
  `simulation/digital_twin/v1_twin/v1_twin_motion_evidence.py`.
- Extended the existing observer serialization with explicit `ns`, `s`,
  `mm`, `mm/s`, and `rad/s` unit metadata.
- Extended the canonical
  `tools/camera_toolchain/capture_sync_run.py` artifact writer with additive
  `camera_motion.jsonl` and `motion_evidence.json` outputs.
- The writer still uses the existing TCP/camera/session lifecycle. No new
  protocol client, parser, heartbeat, ACK registry, or capture loop was added.
- A camera motion report can be `VERIFIED` only when `source=REAL_SYNC`, the
  existing synchronization verdict is `PASS`, and a valid motion interval is
  present. Synthetic data and `REAL_SYNC` with a failed gate remain
  `INSUFFICIENT_EVIDENCE`.

#### VERIFIED

- Camera-pose finite differences, summary statistics, unit serialization,
  additive artifact writing, and failed-sync fail-closed behavior are covered
  by tests.
- Focused regression: `41 passed`.
- Full Python regression: `699 passed, 5 skipped`.
- `py -3.11 -m compileall -q simulation/digital_twin tools`: exit `0`.
- `git diff --check`: no whitespace errors; existing LF/CRLF conversion
  warnings remain.

#### INFERENCE

- After a qualifying real synchronized run, camera-derived planar speed and
  yaw rate may provide a useful external body-level reference for calibrating
  the digital twin of this no-encoder car.

#### INSUFFICIENT EVIDENCE

- No real camera-motion artifact has been produced by this offline change.
- Wheel RPM, per-wheel speed, slip, calibrated IMU sign/scale/drift, and any
  control improvement remain unverified.
- No Kalman filter or firmware control change has been made.

#### NEXT INTERFACE

- Stop before running `capture_sync_run.py`. The next action requires explicit
  user authorization for a synchronized camera + TCP + MPU6050 run with the
  camera over the fixed track and the physical safety boundary confirmed.

### LATEST OFFLINE FUSION TIMESTAMP REPAIR (2026-08-07)

Status: `OFFLINE_VERIFIED_REAL_REPLAY_PENDING_HARDWARE_RERUN`

- Root cause confirmed in the existing synchronized capture path: telemetry
  alignment already used `tick_ms -> ClockSync`, but `V1PoseFusion.update()`
  discarded that aligned time and used raw `pc_recv_ns`. The real run had 342
  telemetry frames, 270 equal consecutive receive timestamps, and the old
  fusion report therefore classified 33 matches as
  `non_monotonic_timestamp`.
- The offline fix keeps raw `pc_recv_ns` unchanged and passes an explicit
  ClockSync-derived `timestamp_ns` into fusion. Each fusion record now carries
  both timestamps as `timestamp_ns` and `raw_pc_recv_ns`.
- `build_fusion_records()` skips repeated `tick_ms` associations. Raw
  synchronized frames remain in the original artifacts; the skip only prevents
  the same MCU observation from being applied twice to fusion state.
- Replaying the immutable real run at
  `simulation/digital_twin/logs/c260807104516439/` with the fixed code yields
  54 unique fusion records: `46 USED_IMU`, `8 CAMERA_ONLY`, zero
  `non_monotonic_timestamp`, and eight explicit `imu_gap_exceeded` records.
  The derived summary has strictly monotonic aligned timestamps. This is an
  offline replay result, not a new hardware run.

#### VERIFIED

- TDD regression tests cover explicit aligned timestamps, raw timestamp
  preservation, and duplicate telemetry association handling.
- Focused fusion/capture tests: `39 passed`.
- Full Python regression: `702 passed, 5 skipped`.
- `py -3.11 -m compileall -q simulation/digital_twin tools`: exit `0`.

#### INFERENCE

- The old `non_monotonic_timestamp` majority was a host-side batching artifact,
  not evidence that the MPU6050 produced out-of-order samples.

#### INSUFFICIENT EVIDENCE

- The existing real artifact files still contain the old implementation's
  `imu_evidence.json` and `fusion.jsonl`; they were intentionally not
  overwritten. A new authorized camera + TCP + MPU6050 capture is required to
  produce fresh runtime artifacts with the repaired fusion path.
- The eight replayed long gaps remain unexplained at the physical capture
  layer and must remain explicit until a new run shows whether they are camera
  pose gaps, delivery gaps, or another timing issue.
- No firmware, controller, Kalman filter, IMU calibration, or vehicle
  performance claim follows from this repair.

#### NEXT INTERFACE

- Keep the car powered off until the user explicitly authorizes the next
  synchronized camera + TCP + MPU6050 run. No ST-Link, firmware flash, START,
  STOP, or motor action is part of this offline repair.

### LATEST REAL SYNC RERUN AFTER TIMESTAMP REPAIR (2026-08-07)

Status: `REAL_CAPTURE_COMPLETED_SYNC_GATE_FAILED`

- The user explicitly authorized control and camera with the car powered. The
  existing `capture_sync_run.py` ran `START -> 10 s capture -> STOP` using the
  repaired host code. No firmware was rebuilt or flashed.
- Evidence is preserved at
  `simulation/digital_twin/logs/c260807112623168/`.
- Runtime lifecycle is verified: `RUNNING`, normal `STOP/STOPPED`, TCP close,
  camera release, and reader cleanup all completed. The stop reason was the
  commanded `STOP`, not `LINE_LOST`.
- The camera opened at `1280x720 / MJPG`. It read 169 frames but produced only
  35 poses (20.7% detection ratio). Pose gaps reached 1.125 s. Telemetry had
  343 frames and 8 MCU tick gaps over 100 ms.
- Synchronization gate: `FAIL`; coverage `88.6%`, p95 nearest-time error
  `48.0 ms` against the `33.3 ms` bound. Therefore
  `motion_evidence.json` is correctly `INSUFFICIENT_EVIDENCE`.
- The timestamp repair survived a real run: fresh `imu_evidence.json` has no
  `non_monotonic_timestamp` fallback. It contains 30 unique fusion records,
  `17 USED_IMU`, `13 CAMERA_ONLY`, and 13 explicit `imu_gap_exceeded` records.
  Its `VERIFIED` status is only a structural fusion summary; it does not
  promote the failed synchronized run to motion or performance evidence.

#### VERIFIED

- The repaired host fusion path handled real batched telemetry without false
  non-monotonic timestamp failures.
- The existing TCP/control lifecycle and safety cleanup completed normally.

#### INFERENCE

- The immediate gate failure is dominated by sparse camera pose detection and
  real telemetry gaps, not by the repaired timestamp comparison. Whether the
  sparse detections are caused by tag visibility, camera placement, or tracker
  throughput is not yet proven.

#### INSUFFICIENT EVIDENCE

- No qualifying real camera-motion evidence was produced in this run.
- No IMU calibration, camera/IMU physical synchronization quality, high-speed
  behavior, or controller improvement is established.

#### NEXT INTERFACE

- Keep the car powered off. Before another hardware run, stabilize the camera
  view/marker visibility and decide whether the capture path needs offline
  throughput work. A new run requires explicit authorization again; no
  firmware flash is currently indicated.

### LATEST UART TX AND APRILTAG DIAGNOSTICS (2026-08-07)

Status: `OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED`

- The latest real run `simulation/digital_twin/logs/c260807133939203/`
  reported `uart_tx_overflow 0 -> 15`, TX high-water `128`, while
  `telemetry_overwritten`, `telemetry_tx_failed`, `cipsend_error`, RX
  overflow, and ORE remained zero. The firmware's maximum droppable
  telemetry payload is 248 bytes, so the old 128-byte ring was undersized.
- The offline change raises `UART_RING_SIZE` to 256 and adds a regression
  requiring the ring to accept one maximum telemetry payload. A native Host C
  compiler was unavailable, so the new Host C executable was not run.
- `PoseTracker` now records rejected detector candidates per scale and
  distinguishes `candidates_rejected` from `no_markers`; the existing capture
  path persists the fields in `frame_index.jsonl`.

#### VERIFIED

- Python regression excluding archive: `707 passed, 5 skipped`.
- Python compileall and `git diff --check` passed.
- Keil `Target 1` rebuild: `0 Error(s), 0 Warning(s)`.
- Current AXF SHA-256:
  `B0C252541C67E2E2D4EB3500FA8D8448C1E1BDABD88A6D3F0AD32B55D4970219`.
- The focused pose-tracker regression is `11 passed`.
- A retained older video with a stable visible tag produced `60/60`
  detections at approximately 20 ms median with scale `1.0`.

#### INFERENCE

- The old TX overflow is consistent with transient backpressure from the
  undersized ring; it is not proof of corrupted TCP bytes.
- The latest AprilTag failure pattern is compatible with framing, visibility,
  motion blur, or processing throughput; the cause is not isolated.

#### INSUFFICIENT EVIDENCE

- No physical test has yet verified the 256-byte ring.
- The latest capture did not retain images, so its `no_markers` frames cannot
  be retrospectively attributed.
- AprilTag continuous detection and B3 synchronization are not accepted.

#### NEXT INTERFACE

- Keep the car powered off until explicit flash authorization. Then use the
  recorded AXF for one bounded synchronized capture with the full tag visible
  from the first frame, and inspect the new UART and detector diagnostics.

### LATEST OFFLINE EVIDENCE AND TELEMETRY REMEDIATION (2026-08-07)

Status: `OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED`

- `summarize_imu_evidence()` now accepts the actual sync Gate. An explicit
  non-PASS Gate downgrades the IMU report to `INSUFFICIENT_EVIDENCE`, and the
  canonical artifact writer passes the same Gate to both IMU and camera-motion
  evidence.
- `PoseTracker.track_with_diagnostics()` and the canonical capture loop now
  retain attempted detector scales, matched scale, tag pixel size, failure
  reason, and detection duration in `frame_index.jsonl`.
- The firmware telemetry contract is now eight 31-byte frames per droppable
  batch, a 248-byte CIPSEND payload, and a 30 ms generation interval. The
  scheduler treats uint32 clock wrap/regression as due so it cannot stall.

#### VERIFIED

- Focused Python regression: `94 passed`.
- Full Python regression excluding archive: `706 passed, 5 skipped`.
- Python compileall: exit `0`.
- MSVC Host C telemetry-batch and CIPSEND tests compile and run passed.
- Keil `Target 1`: `0 Error(s), 0 Warning(s)`.
- Fresh AXF SHA-256:
  `22B978BA1BA1DD76354C39A307C3DDCC5AB6504026AC9205F733DD1B6DC5C29A`.

#### INSUFFICIENT EVIDENCE

- The real run `c260807115454101` remains a failed synchronization capture;
  it is not retroactively upgraded by this offline work.
- No physical evidence yet shows that the eight-frame/30 ms firmware improves
  telemetry overwrite, sync coverage, camera detection, or vehicle motion.

#### NEXT INTERFACE

- Keep the car powered off. The next action is explicit Keil/ST-Link flash
  authorization, followed by one bounded real-motion capture with the full
  AprilTag visible. Do not call B3 passed until the fresh coverage and p95
  gates pass.

### LATEST B3 REAL RERUN: SYNC PASS, APRILTAG DATA QUALITY INSUFFICIENT (2026-08-07)

Status: `SYNC_GATE_PASS_CAMERA_DETECTION_INSUFFICIENT`

- Authorized run: `simulation/digital_twin/logs/c260807144501519/`.
- The canonical capture path completed `START -> 12 s capture -> STOP`.
  `RUNNING`, matching `STOPPED/STOP`, socket close, camera release, reader
  join, and cleanup all completed without an error.
- The camera was `1280x720`, `MJPG`, approximately 30 fps. The firmware
  reported `fw_build_id=3` and schema version 1.
- The fixed B3 synchronization gate passed: coverage `100.0%` and p95
  pose/telemetry time difference `15.4 ms` against the `33.3 ms` bound.

#### VERIFIED

- The new UART/telemetry remediation has real-run support: health counters
  remained at `uart_tx_overflow=0`, `telemetry_overwritten=0`,
  `telemetry_tx_failed=0`, and `cipsend_error=0` during the captured health
  interval.
- The MPU6050 boot status was `0x00` in all 381 telemetry frames; validity was
  known in all frames. This verifies initialization/status propagation for
  this run, not calibration or control benefit.
- The AprilTag diagnostics classify 172 of 193 camera frames as
  `candidates_rejected`; 21 frames produced a pose. The detection ratio was
  `10.9%`, and the longest valid-pose gap was `2.75 s`.
- `imu_evidence.json` and `motion_evidence.json` inherited the PASS sync gate,
  but they are quality summaries with only 10 IMU-overlap records and 6 valid
  camera-motion intervals respectively.

#### INFERENCE

- The transport remediation likely removed the previously observed UART
  capacity pressure for this run; this is evidence of the counters staying
  clear, not a complete performance comparison campaign.
- The remaining capture limitation is on the AprilTag pose path rather than
  the fixed nearest-timestamp synchronization arithmetic. The exact cause of
  candidate rejection is still unverified.

#### INSUFFICIENT EVIDENCE

- Do not treat the 100% synchronization coverage as continuous camera
  tracking: it is 21 matched poses out of 193 camera frames.
- Do not enter calibration/holdout, claim digital-twin accuracy, claim wheel
  speed, or claim high-speed line-following improvement from this run.
- B3's fixed sync gate is verified PASS for this run, but B3 overall data
  readiness remains blocked until AprilTag detection continuity is improved
  or the acceptance contract explicitly limits the intended use to sparse
  pose observations.

#### NEXT INTERFACE

- Keep the car powered off. Perform an offline audit of the existing
  `PoseTracker` candidate rejection path and calibration/geometry assumptions
  using the retained `frame_index.jsonl`; do not add a second detector.
- The next hardware capture must be authorized separately and should be used
  only after a constrained diagnostic or camera/marker setup change. Preserve
  the same B3 sync thresholds and compare detection ratio and longest pose gap
  in addition to coverage and p95 time difference.

### OFFLINE APRILTAG ROOT-CAUSE AUDIT (2026-08-07)

Status: `CAUSE_NOT_YET_ISOLATED_NO_DETECTOR_FIX_APPLIED`

- The historical recording
  `simulation/digital_twin/logs/v1_ground_shakedown_260806154311594/camera.mkv`
  contains no visible car or AprilTag in the sampled frames. Its `0/76`
  detector result is therefore an invalid detector-quality benchmark, not
  evidence that the target tag was rejected.
- The same current tracker and 1280x720 calibration decoded the target in
  `91/91`, `90/91`, `76/76`, and `76/76` frames from other retained recordings.
- A direct live-camera mode probe verified that the C960 returns both
  `1280x720` and `1920x1080` at MJPG/30fps. Resolution support is therefore
  verified, but a resolution-only improvement is not.
- On separate live static samples, the default detector reached `19/20` at
  1280x720 and `18/20` at 1920x1080. This comparison was not a matched
  motion run and does not prove that 1080p is better.
- The single-parameter `wide_adaptive` detector variant reached `20/20` on
  the current static sample and improved one good retained video from `90/91`
  to `91/91`, but it remained `0/76` on the no-car recording. It has not been
  applied to the production tracker because the real moving-run failure has
  no retained images and the variant can increase worst-case processing time.

#### VERIFIED

- The label is visible in the current camera view and can be decoded at
  1280x720 without changing project code.
- The old `candidates_rejected` label describes OpenCV rejected quadrilateral
  candidates when no marker IDs were decoded; it does not prove that a
  decoded target tag was discarded by the application.
- The latest real run still has the unresolved pattern of only 21 poses from
  193 camera frames, with 2.75 s and 2.547 s pose gaps. No frame image exists
  for those failures.

#### INFERENCE

- The latest moving-run failure is more consistent with motion/visibility or
  camera-view changes than with a globally too-strict detector or a simple
  1280x720 capability limit. The exact cause remains unverified.

#### NEXT INTERFACE

- Do not change detector thresholds or replace the calibration yet. First add
  a bounded diagnostic artifact to the existing capture path that retains
  representative failed-frame thumbnails (and the matched scale/diagnostic
  metadata) without creating a second camera/session lifecycle.
- Use that artifact in one authorized run to distinguish tag out-of-view,
  blur/occlusion, low contrast, and detector rejection. Only then select one
  constrained change: a detector parameter, a camera setup change, or a new
  1920x1080 calibration profile.

### OFFLINE FAILURE-FRAME DIAGNOSTIC (2026-08-07)

Status: `OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED`

- The canonical `capture_sync_run.py` path now accepts an optional bounded
  failure-frame directory. The production entrypoint uses `failed_frames/`
  inside each new run directory and saves at most 12 JPEG thumbnails.
- Sampling is deterministic: the first frame of each observed failure reason
  is retained, followed by every 30th occurrence until the cap is reached.
  `frame_index.jsonl` records the failure reason, detector scales, timing,
  and the run-relative thumbnail path. `failure_frame_summary.json` records
  observed counts, saved counts, and save errors.
- The change reuses the existing camera/TCP/heartbeat/parser/session lifecycle.
  It does not alter AprilTag parameters, calibration, sync thresholds,
  firmware, or motor control.

#### VERIFIED

- Focused capture and pose-tracker regression: `42 passed`.
- Full Python regression excluding archive: `708 passed, 5 skipped`.
- Python compileall exits `0`; `git diff --check` reports no whitespace
  errors apart from the existing LF/CRLF conversion warnings.
- The test suite proves the thumbnail cap, relative-path binding, failure
  summary serialization, and compatibility with the existing capture tests.

#### INFERENCE

- The next authorized capture should make the latest sparse AprilTag result
  attributable to visibility, blur, occlusion, low contrast, or detector
  rejection. This is a diagnostic expectation, not yet a real-world result.

#### INSUFFICIENT EVIDENCE

- No new camera or car run was performed by this offline change.
- AprilTag continuous detection, synchronization quality after this change,
  digital-twin calibration, and vehicle performance remain unverified.
- Keil UV4 was not found in the current environment's known installation
  paths, so no fresh firmware build was claimed in this task.

#### NEXT INTERFACE

- After explicit hardware authorization, run one bounded synchronized capture
  with the full tag visible from the first frame. Inspect `frame_index.jsonl`,
  `failure_frame_summary.json`, and `failed_frames/` before changing a
  detector parameter, camera setup, or calibration profile.

### OFFLINE SNAPSHOT PREPROCESS PROBE (2026-08-07)

Status: `OFFLINE_CANDIDATE_ONLY`

- Existing local `live_1280.png` and `live_1920.png` snapshots were replayed
  through the current `APRILTAG_36h11` path. Raw frames returned
  `candidates_rejected`; global histogram equalization followed by the
  existing 2x attempt decoded ID 0 in both full-frame snapshots.
- The current three-scale production probe measured roughly 62 ms at 1280x720
  and 115 ms at 1920x1080 in this local replay. The preprocessing candidate is
  therefore a detection hypothesis, not yet a 30 fps implementation.
- This replay did not use frames from the latest synchronized run and did not
  change production code. The exact cause of the 172 failed frames remains
  `INSUFFICIENT EVIDENCE`.

The detailed evidence and the single-variable follow-up are recorded in
`docs/agent-context/handoffs/2026-08-07-b3-offline-snapshot-preprocess-probe.md`.

### B3 OFFLINE OBSERVATION GATE (2026-08-08)

Status: `OFFLINE_VERIFIED_B3_OBSERVATION_GATE_FAILED`

- A read-only analyzer now replays the existing `frame_index.jsonl` and
  `sync_report.json` through a separate B3 observation gate. It reuses the
  existing capture artifacts and does not create a detector, TCP client,
  parser, or session lifecycle.
- The declared screening profile is 30 fps, detected-pose ratio `>=0.95`,
  maximum detected-pose gap `<=2` frame periods, and detector p95 processing
  time `<=1` frame period. These are engineering screening thresholds, not
  physical accuracy claims.
- Replay of real run `c260807144501519` is independently verified as 193
  readable camera frames, 21 detected poses, `10.8808%` detection ratio,
  `2.75 s` maximum pose gap, and `70.36154 ms` detector p95. The existing sync
  sub-gate and overall capture verdict are both `PASS`; the observation gate
  is `FAIL` with evidence status `VERIFIED`.
- The derived report is tracked at
  `docs/evidence/v1_b3_observation_gate_20260808/report.json`. The raw run is
  unchanged and remains the authoritative source.
- Focused offline verification is `19 passed`. Full Python regression is
  `727 passed, 5 skipped`; compileall exits `0`.
- The CLI accepts `REAL_SYNC` only below the canonical capture roots
  `simulation/digital_twin/logs/` and
  `simulation/digital_twin/data/product/sessions/v1_b/`. This prevents an
  arbitrary temporary directory from being labeled as a real run, but file
  artifacts alone still cannot independently prove physical origin.

#### EVIDENCE BOUNDARY

- `VERIFIED`: the retained real run has sparse AprilTag observations and fails
  the declared observation gate.
- `INFERENCE`: detector processing time and candidate rejection may contribute
  to the sparse stream.
- `INSUFFICIENT EVIDENCE`: the exact cause is not isolated because this run
  predates failed-frame thumbnail retention; no detector or calibration change
  is promoted.

#### NEXT INTERFACE

- Keep B3 blocked. After explicit authorization, run one bounded capture using
  the existing failure-frame retention path, inspect the thumbnails and
  metadata, then select exactly one constrained observation experiment.

### B3 CAMERA-HEIGHT RERUN (2026-08-08)

Status: `REAL_CAPTURE_COMPLETED_OBSERVATION_STILL_BLOCKED`

- After the operator raised the camera, the existing canonical capture path
  ran `c260808033248336` for 20 seconds. No firmware was flashed and no
  detector or calibration code changed.
- The camera was verified at `1280x720`, `MJPG`, and `30.00003 fps`. The
  lifecycle completed `START/RUNNING -> capture -> STOP/STOPPED` with normal
  heartbeat, socket, camera, and reader cleanup. The stop reason was the
  commanded `STOP`, not `LINE_LOST`.
- The raw session contains 389 readable camera frames, 154 poses, and 631
  telemetry frames. All 235 failed detections were `candidates_rejected`;
  eight representative thumbnails were retained under the run directory.
- The fixed synchronization gate passed with 100% coverage and p95 time
  difference `15.36 ms`.
- Compared with `c260808033006893` (28/206 poses, 13.59%), this run produced
  154/389 poses, 39.59%. This is a verified run comparison and an inference
  that the higher camera position improved observation availability, not an
  isolated causal proof.
- The strict observation analyzer refused the new `frame_index.jsonl` because
  frames 380 and 381 have the same `t_pc_ns=1690493078000000`. The raw run is
  preserved; no timestamp was repaired in place. Direct diagnostic counts also
  remain below the observation profile: detection p95 `64.75 ms`, maximum pose
  gap 28 frame records, and detection ratio `39.59%`.

#### EVIDENCE BOUNDARY

- `VERIFIED`: real synchronized lifecycle, sync gate, increased pose count,
  retained failure images, and uniform `candidates_rejected` failures.
- `INFERENCE`: camera height/field of view likely contributed to the increase;
  the exact detector cause remains unverified.
- `INSUFFICIENT EVIDENCE`: continuous AprilTag observation, formal observation
  gate classification for this run, and a machine-readable start/finish event.

#### NEXT INTERFACE

- Keep B3 blocked. Audit the equal timestamp as an offline evidence-integrity
  issue, then run one constrained observation experiment selected from the
  retained thumbnails. Do not bundle detector, camera, and calibration changes.

### B3 TIMESTAMP CLOCK REPAIR (2026-08-08)

Status: `OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED`

- Root cause of the equal timestamp in `c260808033248336` was identified:
  Windows Python `time.monotonic_ns()` uses `GetTickCount64()` at about
  `15.625 ms` resolution, so adjacent frame reads can share a timestamp.
- `tools/camera_toolchain/capture_sync_run.py` now uses one shared
  `capture_pc_clock_ns()` based on high-resolution `perf_counter_ns()` for
  camera frame timestamps, telemetry `pc_recv_ns`, and health `pc_recv_ns`.
  START/STOP timeout and heartbeat scheduling clocks were not changed.
- TDD RED was observed for the missing clock API, then focused clock tests
  passed `2/2`. Capture tests are `33 passed`; full Python regression is
  `729 passed, 5 skipped`; compileall exits `0`.
- The old raw run was not rewritten. The next fresh authorized capture must
  verify the new timestamp artifact and replay through the observation gate.

#### EVIDENCE BOUNDARY

- `VERIFIED`: host-clock root cause, unified high-resolution timestamp source,
  and offline regression.
- `INFERENCE`: the new source should remove the observed 15.625 ms collision
  for the real detector workload.
- `INSUFFICIENT EVIDENCE`: no post-fix real timestamp artifact, continuous
  AprilTag observation, or detector improvement.

#### NEXT INTERFACE

- Keep hardware idle until explicit authorization. Run one fresh synchronized
  capture, check non-increasing timestamps, then run the observation analyzer.
