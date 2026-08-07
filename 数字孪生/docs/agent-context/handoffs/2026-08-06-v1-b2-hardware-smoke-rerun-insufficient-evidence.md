# V1-B B2 Hardware Safety Smoke Rerun Handoff

Task/Gate: V1-B B2, Hardware Safety Smoke
Status: INSUFFICIENT_EVIDENCE
Tool result: SHAKEDOWN_PASS
Run date: 2026-08-06 Asia/Shanghai

This is the one authorized rerun after the host-side timing fix. The canonical
CLI was invoked once with explicit host and port. B1 was not executed or
repeated. B3, B4, and B5 were not run.

## Scope and hardware actions

User authorization for this run explicitly covered:

- C960 camera;
- ESP-01S TCP at `192.168.110.236:8888`;
- four wheels elevated;
- one B2 START/STOP smoke with a maximum running duration of 0.5 seconds;
- no flash, reset, ground contact, or ground motion.

Observed actions:

- connected: C960 YES; ESP-01S TCP YES at `192.168.110.236:8888`;
- flashed: NO;
- reset: NO;
- START: one `R,...,START`;
- STOP: one pre-condition `R,...,STOP` and one final `R,...,STOP`;
- motion: elevated-wheel run only, based on the user's stated setup; no ground
  contact or ground motion was authorized or performed;
- serial/debugger/Keil: not connected or started.

## Changed files

This rerun did not modify host code, tests, STM32 firmware, control logic, or
hardware. It added this handoff only. The host timing fix and its regression
tests were already present in the dirty worktree before this rerun:

- `tools/shakedown_toolchain/ground_shakedown.py`;
- `simulation/digital_twin/tests/test_ground_shakedown.py`.

Generated evidence is under the run directory below and is not calibration or
holdout data.

## Commands and results

All commands were run from:
`C:\Users\24668\Desktop\stm32小车\数字孪生`

- `git status --short --branch`
  - Exit code: `0`.
  - Branch `master`; pre-existing dirty paths were preserved.
- `py -3.11 -m pytest -q simulation\digital_twin\tests\test_ground_shakedown.py`
  - Exit code: `0`; `83 passed`.
- `py -3.11 -m pytest -q simulation\digital_twin\tests`
  - Exit code: `0`; `631 passed, 5 skipped`.
- `py -3.11 -m compileall -q simulation\digital_twin tools`
  - Exit code: `0`.
- `git diff --check`
  - Exit code: `0`; only existing LF-to-CRLF normalization warnings.
- `py -3.11 tools\shakedown_toolchain\ground_shakedown.py --host 192.168.110.236 --port 8888 --duration 0.5 --run-kind elevated-wheels --out-root simulation\digital_twin\logs --execute`
  - Exit code: `0`.
  - Output: `VERDICT: SHAKEDOWN_PASS`.
  - This was the only real C960/TCP/START/STOP execution in this rerun.
- Read-only evidence audit of `raw_io.json`, `shakedown_report.json`, and
  `camera_ffmpeg.log`
  - Exit code: `0`.
- Read-only post-run process and TCP cleanup checks
  - Exit code: `0`.
  - `ffmpeg/ffprobe` process count: `0`.
  - Matching TCP connections to `192.168.110.236:8888`: `0`.

## Run identity and evidence

- Campaign ID: `s260806135302106`
- Run ID: `e260806135302106`
- Run kind: `elevated-wheels`
- Requested duration: `0.5 s`
- Evidence directory:
  `simulation/digital_twin/logs/v1_ground_shakedown_260806135302106`
- Raw I/O: `raw_io.json`, 9 TX events and 16 RX events, 25 frozen events.
- Raw wall-clock event span recorded by the logger:
  `2026-08-06T13:53:03` through `2026-08-06T13:53:05` (logger precision is
  one second; dedicated socket connect/disconnect timestamps are not emitted).

Evidence SHA-256:

- `camera.mkv`: `82E03B1DF0561140351565A6CA1474FA6ACCE2632B05CD018C0CDE5E9A3B4D11`
- `camera_ffmpeg.log`: `1DD2A92F081AA1C07DC49C8540B18A46AE95BF2B24846BEFD5E7FE32D55ECED3`
- `raw_io.json`: `884E05BCD425FDA376D9F2C16C06298071DBB9F83404CA130C5E2365054C8963`
- `shakedown_report.json`: `88CDFB8B80F29A52E83516A5ECB7538F12093D45027050B64F9BE7DD94521B55`

## VERIFIED

### Camera

The canonical FFmpeg/dshow path opened `EMEET SmartCam C960`. The independent
ffprobe result in `shakedown_report.json` was:

- `codec_name=mjpeg`;
- `width=1280`;
- `height=720`;
- `avg_frame_rate=30/1` (`30.0 fps`);
- ffprobe return code `0`;
- camera `clean_exit=true`, `q_sent=true`, `exit_code=0`,
  `forced_termination=false`, and `cleanup_errors=[]`.

The raw FFmpeg input log separately contains `MJPG / 0x47504A4D`. This is
reported as an FFmpeg stream observation, not inferred from the request flags
or relabeled from `codec_name=mjpeg`.

### TCP, parameters, heartbeat, START, and STOP

The raw stream contains the following control sequence, all with the same
campaign and run identity:

```text
R,s260806135302106,e260806135302106,STOP,70
P,s260806135302106,1,35,0,10,580,23
A,s260806135302106,1,APPLIED,APPLIED,38
P,s260806135302106,2,35,0,10,480,21
A,s260806135302106,2,APPLIED,APPLIED,3B
P,s260806135302106,3,35,0,10,380,27
A,s260806135302106,3,APPLIED,APPLIED,3A
P,s260806135302106,4,35,0,10,280,21
A,s260806135302106,4,APPLIED,APPLIED,3D
P,s260806135302106,5,35,0,10,260,2E
A,s260806135302106,5,APPLIED,APPLIED,3C
R,s260806135302106,e260806135302106,START,28
S,s260806135302106,e260806135302106,RUNNING,START,0,5E
H,s260806135302106,e260806135302106,5E
R,s260806135302106,e260806135302106,STOP,70
S,s260806135302106,e260806135302106,STOPPED,STOP,0,08
```

Verified from raw/report evidence:

- five P commands, once each, using `Kp=35`, `Ki=0`, `Kd=10` and the existing
  bounded speed plan `580 -> 480 -> 380 -> 280 -> 260`;
- five same-campaign, same-version `APPLIED/APPLIED` ACKs;
- one H heartbeat in raw TX evidence, no heartbeat failure, and heartbeat
  deactivated before final STOP;
- one START, matching `RUNNING/START`, with no START retry;
- final STOP `send_outcome=COMPLETED`, matching `STOPPED/STOP`;
- `control_verdict=PASS`, `stop_confirmed=true`, `cut_power_warning=false`,
  `cleanup_errors=[]`, `raw_io.published=true`, and `quiescence.proven=true`.

### Timing

Independent timing from `raw_io.json`:

- `R START` TX: monotonic `1526087.109`;
- `S RUNNING/START` RX: monotonic `1526087.265`;
- final `R STOP` TX: monotonic `1526087.484`;
- final `S STOPPED/STOP` RX: monotonic `1526087.687`;
- `R START -> R STOP`: `0.375 s`;
- `S RUNNING -> S STOPPED`: `0.422 s`;
- `S RUNNING -> R STOP`: `0.219 s`.

Both relevant intervals are below the authorized `0.5 s` maximum. The host
timing fix therefore passed this one hardware rerun; it does not change the
historical failed run or prove any performance improvement.

## Firmware identity

Canonical source/configuration identity checked before the run:

- Keil project: `firmware/stm32_line_follower/project.uvprojx`;
- target: `Target 1`;
- baseline in source: `Kp=35.0`, `Ki=0.0`, `Kd=10.0`, `speed_max=680`;
- declared heartbeat lease: `1000 ms`;
- no current `Objects/Project.axf`, `.hex`, `.bin`, or equivalent build output
  exists under `firmware/stm32_line_follower`.

Current workspace SHA-256 values:

- `project.uvprojx`: `5BD666BB6A83707E404B47D0CF826FE23572DA3405C679AA8ADB7E40C9DD7116`
- `User/main.c`: `60B36C89B8F07C049773FDE7449A11CF42A07EB5B9F56C585E8C7E99CA04ADBA`
- `User/esp_runtime_transport.c`: `F8E5E1C728E728E51FFBE2026F8833FCA6A75CB2121061C8073E1184F806FA98`
- `User/esp_runtime_transport.h`: `A132E99FBC9E345DD0DCC2D5AB8D2F46DC10F05CA008517518BCEDBEC1CE3A27`
- `User/esp_tx_coordinator.c`: `904DF1C143B2A659220F26443F4A95FD0B0FC3537AC57369A7FD7B4C7A066DFE`
- `User/esp_tx_coordinator.h`: `906056C442C835D1FA95BB9123C638670B1C3036D46507815B827BD23E2AAACA`
- `User/twin_control_protocol.c`: `CBF060969A9C26EA270EE80FCCE8727F03AE0CF6394E7043A49B58D9D82A9841`
- `User/twin_control_protocol.h`: `F45A37B2561F0B90AFD2DBAF9F2A2EA9B598DECD300EEF9CE4ACBFD1ABC33481`

Runtime health reported `fw_build_id=1` and `fw_schema_version=1`, but there
is no current binary or independent mapping from those fields to the source
hashes above. Historical handoff or archive hashes were not promoted to live
firmware identity, and no flash/reset was performed.

## INSUFFICIENT EVIDENCE

- The live STM32 firmware image cannot be proven equal to the current source
  identity because no current build artifact or independent live-image hash is
  available. The smoke therefore cannot be accepted as a complete B2 PASS.
- The report does not serialize dedicated socket connect/disconnect timestamps
  or an exactly-once socket close counter. It does provide `quiescence.proven`,
  no control cleanup errors, raw freeze/publication, and a post-run zero active
  connection; the missing fields remain an evidence limitation.
- The structured camera contract verifies `codec_name=mjpeg`, resolution, and
  frame rate. The FFmpeg log contains the separate `MJPG / 0x47504A4D` input
  label, but `codec_name=mjpeg` alone is not claimed as device-level FourCC.
  If an evaluator requires a separately structured exact-FourCC field, that
  gate remains insufficient without creating a second B2 control path.
- User-provided wheel elevation and absence of ground contact are not measured
  by software; they are recorded as the authorized physical setup.
- `imu_evidence_status=UNVERIFIED_NO_VALIDITY_BIT`; no IMU or calibration claim
  is made.

## INFERENCE

- The bounded timing fix is hardware-consistent for this one rerun because raw
  START/STOP timing is below 0.5 seconds, but this is not a performance test
  and is not a statistical guarantee.
- Runtime health fields are compatible with the checked protocol source, but
  compatibility is not live firmware identity.

## Data boundary and next interface

This SMOKE run is not calibration or holdout data and must not be added to
either dataset. It does not equal the B3 synchronization Gate, does not prove
high-speed performance improvement, and does not prove that the digital twin
has been calibrated.

The next interface is B3 only after independent Codex acceptance of this B2
evidence package and a fresh user authorization specifically covering new
ground data collection. Stop here; do not run B3, B4, or B5 automatically.
