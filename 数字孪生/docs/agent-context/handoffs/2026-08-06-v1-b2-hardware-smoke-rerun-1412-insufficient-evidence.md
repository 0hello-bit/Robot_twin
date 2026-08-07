# V1-B B2 Hardware Safety Smoke Rerun 1412 Handoff

Task/Gate: V1-B B2, Hardware Safety Smoke
Status: INSUFFICIENT_EVIDENCE
Tool result: SHAKEDOWN_PASS
Run date: 2026-08-06 Asia/Shanghai

This is the second authorized fixed-profile rerun after the host timing fix.
It used the canonical `ground_shakedown.py --execute` path once. No PWM value
was increased. B1 was not executed or repeated. B3, B4, and B5 were not run.

## Hardware actions

- connected: C960 YES; ESP-01S TCP YES at `192.168.110.236:8888`;
- flashed: NO;
- reset: NO;
- START: one `R,...,START`;
- STOP: one pre-condition STOP and one final STOP;
- motion: elevated-wheel run only, with no ground contact or ground motion;
- serial/debugger/Keil: not connected or started.

The requested PWM increase was not executed because B2 fixes the approved
speed plan and does not permit an ad hoc actuator experiment.

## Changed files

This run changed no code, firmware, control algorithm, or hardware. It added
this evidence handoff only. The existing host timing fix remains in:

- `tools/shakedown_toolchain/ground_shakedown.py`;
- `simulation/digital_twin/tests/test_ground_shakedown.py`.

## Commands and results

Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`

- `git status --short --branch`
  - Exit code `0`; existing dirty paths were preserved.
- `Get-FileHash -Algorithm SHA256 tools\shakedown_toolchain\ground_shakedown.py`
  - Exit code `0`; host source hash unchanged:
    `1ADE01C68693B31BCD634BDBBE4D6CD17C44236BB75ED7EB0B49869E98352F3F`.
- `py -3.11 tools\shakedown_toolchain\ground_shakedown.py --host 192.168.110.236 --port 8888 --duration 0.5 --run-kind elevated-wheels --out-root simulation\digital_twin\logs --execute`
  - Exit code `0`; output `VERDICT: SHAKEDOWN_PASS`.
  - This was the only hardware control execution in this rerun.
- Read-only JSON/raw evidence audit
  - Exit code `0`.
- Read-only post-run process/TCP check
  - Exit code `0`; no ffmpeg/ffprobe process; TCP state was `TimeWait` with
    no owning process, not an established connection.

## Run and evidence

- campaign_id: `s260806141221838`
- run_id: `e260806141221838`
- run_kind: `elevated-wheels`
- requested_duration_s: `0.5`
- evidence directory:
  `simulation/digital_twin/logs/v1_ground_shakedown_260806141221838`

Evidence SHA-256:

- `raw_io.json`: `43BB7BBDA4DD4EC6C3E7BC2F13A6DC4B81BEDC4630D94E52D93538CC92DE4456`
- `shakedown_report.json`: `D590A93B1EEFE2290BD1753C27536A18C1C8FB2861F4CB101310CB2D59D974AD`
- `camera.mkv`: `7CB0E15B78DEB0F10656B42A7CD1F168993E4E4ABA457B66648AED03E91B712F`
- `camera_ffmpeg.log`: `E1CD92EB2456C7801489E7F7881DACC38C83E3B3260E773754F847DD7F503A96`

## VERIFIED

### Camera

The actual FFmpeg/ffprobe result was `codec_name=mjpeg`, `1280x720`, and
`30.0 fps` (`30/1`). Camera validation returned `PASS`, clean exit was true,
forced termination was false, and camera cleanup errors were empty. The raw
FFmpeg log separately reports the MJPG input label; `codec_name=mjpeg` is not
being relabeled as FourCC by inference.

### Control path

- five P commands were sent once each with `Kp=35`, `Ki=0`, `Kd=10`;
- approved speed plan was `580 -> 480 -> 380 -> 280 -> 260`;
- five same-campaign/version `APPLIED/APPLIED` ACKs were received;
- one H heartbeat was present in raw TX evidence and reported without failure;
- one same-run `S RUNNING/START` was received;
- one same-run final `S STOPPED/STOP` was received;
- `control_verdict=PASS`, `stop_confirmed=true`, `raw_io.published=true`,
  `quiescence.proven=true`, and `cleanup_errors=[]`.

### Timing and telemetry

Raw timing:

- `R START` TX: `1527246.187`;
- `S RUNNING/START` RX: `1527246.343`;
- final `R STOP` TX: `1527246.562`;
- `S STOPPED/STOP` RX: `1527246.703`;
- `R START -> R STOP`: `0.375 s`;
- `S RUNNING -> S STOPPED`: `0.360 s`.

Four telemetry frames reported `m1=m2=m3=m4=260`. This verifies the command
value reported by firmware, not physical wheel RPM or visible mechanical
motion. No encoder, current, tachometer, or wheel-focused independent video
measurement was collected in B2.

## INSUFFICIENT EVIDENCE

- No current STM32 binary/build artifact or independent live-image hash maps
  the running firmware to the current source hashes. Historical hashes are
  not reused as live identity evidence.
- The B2 report has no dedicated socket connect/disconnect timestamp or
  serialized exactly-once socket-close counter. Post-run TCP `TimeWait` is
  consistent with a closed connection, but it is not a new control action.
- The run proves command delivery and status/telemetry evidence, but cannot
  prove that the wheels physically rotated. The user's visual observation is
  therefore not resolved by the current data.
- The smoke remains outside calibration and holdout datasets.

## INFERENCE

- The lack of visible motion may be caused by the short 0.375-second interval,
  the fixed final command of 260, motor/driver dead zone, power/wiring, or
  another actuator-side condition. The current evidence cannot choose among
  these causes.
- Increasing PWM would be a separate actuator diagnostic, not a valid B2
  rerun, and requires a separately reviewed command profile and authorization.

## Gate boundary

B2 execution and evidence capture are complete for the authorized fixed
profile, but the gate status remains `INSUFFICIENT_EVIDENCE`. This does not
equal the B3 synchronization Gate, does not prove high-speed performance, and
does not prove digital-twin calibration.

The next action is independent Codex review of the raw evidence and this
handoff. No further hardware action or PWM change should occur until that
review and a separately authorized diagnostic gate are complete. Do not run
B3, B4, or B5 automatically.
