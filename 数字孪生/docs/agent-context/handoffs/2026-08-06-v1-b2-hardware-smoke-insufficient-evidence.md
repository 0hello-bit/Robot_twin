# V1-B Task B2 Hardware Safety Smoke Handoff

Task/Gate: V1-B B2, Hardware Safety Smoke
Gate result: FAIL for the authorized <=0.5 s safety-duration contract
Evidence status: INSUFFICIENT_EVIDENCE for final B2 acceptance
Recorded run: 2026-08-06, approximately 12:13:27-12:13:30 Asia/Shanghai

The user explicitly authorized one C960/ESP-01S TCP smoke run with the wheels
elevated, no ground contact, no flash, no reset, and a maximum duration of
0.5 s. The canonical `ground_shakedown.py --execute` path was invoked once.
It returned `SHAKEDOWN_PASS`, but the raw timestamps prove that the physical
RUNNING state lasted longer than the authorized limit. The report's
`requested_duration_s=0.5` is not sufficient evidence of actual motor-on
duration: the current path bounds its collection window, then drains input
before sending terminal STOP.

No second hardware run was performed. A later request to rerun would have
created a second START/STOP experiment beyond the explicit one-run B2 scope;
no automatic retry or extra START was sent. The host-side timing fix below was
validated offline only; it has not been applied to or verified on the car.

## Changed files

- `docs/agent-context/handoffs/2026-08-06-v1-b2-hardware-smoke-insufficient-evidence.md`
  - Updated with the real run, raw evidence, timing audit, and gate boundary.
- `tools/shakedown_toolchain/ground_shakedown.py`
  - Sends terminal STOP immediately after a confirmed RUNNING window instead
    of allowing a continuous-input drain to extend motor-on time.
- `simulation/digital_twin/tests/test_ground_shakedown.py`
  - Adds a deterministic regression test for continuous RX at the deadline.
- Generated evidence only:
  - `simulation/digital_twin/logs/v1_ground_shakedown_260806121324434/camera.mkv`
  - `simulation/digital_twin/logs/v1_ground_shakedown_260806121324434/camera_ffmpeg.log`
  - `simulation/digital_twin/logs/v1_ground_shakedown_260806121324434/raw_io.json`
  - `simulation/digital_twin/logs/v1_ground_shakedown_260806121324434/shakedown_report.json`
- No STM32 firmware source, control algorithm, protocol implementation,
  camera path, TCP path, UI, MCP, PCB, or second-robot file was changed.
- Existing user changes were preserved: `CLAUDE.md`, `README.md`,
  `docs/agent-context/CURRENT_STATUS.md`,
  `docs/superpowers/plans/2026-08-05-v1-b-real-calibration-holdout.md`,
  `docs/agent-context/PROJECT_MEMORY.md`, and `docs/superpowers/prompts/`.

## Commands and results

All project commands used the formal workspace
`C:\Users\24668\Desktop\stm32小车\数字孪生` unless stated otherwise.

1. `git status --short --branch`
   - Exit code: `0`.
   - Branch: `master`.
   - The pre-existing dirty paths listed above were not reverted.

2. Read-only network discovery:
   `Get-NetConnectionProfile`, `Get-NetIPConfiguration`, `ipconfig /all`,
   `route print`, and `arp -a`.
   - Exit code: `0` for each.
   - SSID/profile: `@Ruijie-sC384 2` on `WLAN`.
   - Local WLAN address: `192.168.110.89/24`; gateway `192.168.110.1`.

3. `Get-NetNeighbor -InterfaceIndex 8 -AddressFamily IPv4`
   - Exit code: `0`.
   - Candidate `192.168.110.236`, MAC `84-F3-EB-85-C6-DE`.
   - The MAC vendor interpretation was not used as sole identity evidence.

4. `Test-NetConnection -ComputerName 192.168.110.236 -Port 8888 -InformationLevel Detailed`
   - Exit code: `0`.
   - `TcpTestSucceeded: True`, source `192.168.110.89`, name
     `ESP-85C6DE.lan`, interface `WLAN`.

5. Bounded local scan of `192.168.110.0/24:8888` using 0.35 s TCP probes,
   excluding the local address and scanning no external network.
   - Exit code: `0`.
   - `open_hosts=192.168.110.236`, `open_count=1`.
   - This uniquely established the explicit host used below; the CLI default
     was not relied upon.

6. `git rev-parse --show-toplevel`, `git rev-parse HEAD`, and read-only
   firmware artifact inspection.
   - Exit code: `0`.
   - Repository root: `C:\Users\24668\Desktop\stm32小车`.
   - Commit: `9d9e1df68d4ab36b073191fcbab30ac899175673`.
   - No `.hex`, `.bin`, `.elf`, `.axf`, or `.out` exists under
     `firmware/stm32_line_follower`.

7. Current source hash inspection with `Get-FileHash -Algorithm SHA256`.
   - Exit code: `0`.
   - Hashes are recorded below. They identify workspace source only and do not
     prove the image running on the STM32.

8. Canonical hardware command, invoked exactly once:
   `py -3.11 tools\\shakedown_toolchain\\ground_shakedown.py --host 192.168.110.236 --port 8888 --duration 0.5 --run-kind elevated-wheels --out-root simulation\\digital_twin\\logs --execute`
   - Exit code: `0`.
   - Key output: `VERDICT: SHAKEDOWN_PASS`.
   - Evidence directory:
     `simulation/digital_twin/logs/v1_ground_shakedown_260806121324434`.
   - This was the only C960/TCP/START/STOP execution.

9. Evidence inspection of `shakedown_report.json`, `raw_io.json`, and
   `camera_ffmpeg.log`.
   - Exit code: `0` for each read.
   - No parse errors, protocol anomalies, primary failure, secondary errors,
     camera errors, or control cleanup errors were reported.

10. Offline regression:
    `py -3.11 -m pytest -q simulation\\digital_twin\\tests\\test_ground_shakedown.py simulation\\digital_twin\\tests\\test_runtime_protocol.py simulation\\digital_twin\\tests\\test_runtime_protocol_cross_language.py simulation\\digital_twin\\tests\\test_frame_parser_health.py simulation\\digital_twin\\tests\\test_stream_demuxer.py`
    - Exit code: `0`.
    - Result: `148 passed in 13.98s` after the offline timing fix.

11. `py -3.11 -m compileall -q simulation\\digital_twin tools`
    - Exit code: `0`.

12. `py -3.11 tools\\shakedown_toolchain\\ground_shakedown.py --help`
    - Exit code: `0`.
    - The CLI exposes explicit `--host`, `--port`, `--duration`, `--run-kind`,
      and `--execute`.

13. Read-only timing audit of `raw_io.json` and the report.
    - Exit code: `0`.
    - `R START` TX monotonic time: `1520110.812`.
    - `S RUNNING/START` RX monotonic time: `1520111.000`.
    - Final `R STOP` TX monotonic time: `1520112.187`.
    - Final `S STOPPED/STOP` RX monotonic time: `1520112.265`.
    - `R START` to final `R STOP` TX interval: `1.375 s`.
    - `S RUNNING` to final `S STOPPED` RX interval: `1.265 s`.
    - The raw evidence therefore disproves compliance with the authorized
      maximum of `0.5 s`, even though the report records `0.5` as requested.

14. `Get-FileHash -Algorithm SHA256` over the four evidence files.
    - Exit code: `0`.
    - Hashes are recorded below.

15. Final cleanup/state verification:
    - `Get-Process | Where-Object { $_.ProcessName -in @('ffmpeg','ffprobe') }`
      reported `ffmpeg_process_count=0`.
    - A read-only TCP query for `192.168.110.236:8888` returned no matching
      connection object after the session. The Windows CIM query reports this
      as "no matching MSFT_NetTCPConnection object", not as a live connection.
    - `git diff --check` exit code: `0`; only existing LF-to-CRLF warnings.

16. Post-fix targeted regression:
    `py -3.11 -m pytest -q simulation\\digital_twin\\tests\\test_ground_shakedown.py -k "terminal_stop_is_sent_at_running_deadline_without_input_drain or running_deadline_includes_start_command_latency or terminal_stop_reserves_transport_send_budget"`
    - Exit code: `0` after the fix; `3 passed, 80 deselected`.
    - Each test was run before its corresponding production edit and failed
      for the expected timing reason.

17. Post-fix `py -3.11 -m compileall -q simulation\\digital_twin tools` and
    `git diff --check`.
    - Exit code: `0` for each.

## Current source hashes

These are current workspace source/configuration hashes, not live-firmware
identity evidence:

- `firmware/stm32_line_follower/User/esp_runtime_transport.c`
  - `F8E5E1C728E728E51FFBE2026F8833FCA6A75CB2121061C8073E1184F806FA98`
- `firmware/stm32_line_follower/project.uvprojx`
  - `5BD666BB6A83707E404B47D0CF826FE23572DA3405C679AA8ADB7E40C9DD7116`
- `firmware/stm32_line_follower/User/esp_runtime_transport.h`
  - `A132E99FBC9E345DD0DCC2D5AB8D2F46DC10F05CA008517518BCEDBEC1CE3A27`
- `firmware/stm32_line_follower/User/esp_tx_coordinator.c`
  - `904DF1C143B2A659220F26443F4A95FD0B0FC3537AC57369A7FD7B4C7A066DFE`
- `firmware/stm32_line_follower/User/esp_tx_coordinator.h`
  - `906056C442C835D1FA95BB9123C638670B1C3036D46507815B827BD23E2AAACA`
- `firmware/stm32_line_follower/User/twin_control_protocol.c`
  - `CBF060969A9C26EA270EE80FCCE8727F03AE0CF6394E7043A49B58D9D82A9841`
- `firmware/stm32_line_follower/User/twin_control_protocol.h`
  - `F45A37B2561F0B90AFD2DBAF9F2A2EA9B598DECD300EEF9CE4ACBFD1ABC33481`

Runtime health frames reported `fw_build_id=1` and `fw_schema_version=1`.
There is no current build artifact or independent mapping from those runtime
fields to the source hashes above. The historical AXF hash was not reused as
current hardware evidence. No flash or reset was performed as a remedy.

Host-side post-run source hashes:

- `tools/shakedown_toolchain/ground_shakedown.py`
  - `1ADE01C68693B31BCD634BDBBE4D6CD17C44236BB75ED7EB0B49869E98352F3F`
- `simulation/digital_twin/tests/test_ground_shakedown.py`
  - `2E34A7E7BA0F98D08DADB169CF105B47BE9164B6D70BEFB235C77C8BD3E98F86`

## Root cause and offline fix

- Root cause 1: `_phase_running()` used `duration_s` only as the
  collection-loop deadline after `S RUNNING` confirmation. START confirmation
  latency was outside the limit.
- Root cause 2: after that deadline, `_terminal_stop()` called
  `_drain_until_bounded_timeout()`. With continuous telemetry, the drain could
  keep receiving data while the firmware remained RUNNING, delaying R STOP.
- Root cause 3: the STOP transport call itself has a bounded but non-zero
  `IO_CALL_BUDGET_S=0.15 s`; without reserving it, command completion could
  still exceed the requested cap.
- Fix: the session now records the START send start time, computes the running
  deadline from that origin with the `0.15 s` STOP-send budget reserved, and
  skips the terminal drain once RUNNING has been confirmed. If confirmation
  arrives after the deadline, it sends no first H and converges directly on
  STOP. Pre-start failures retain the bounded drain. The stop record now
  records `boundary_mode` and `drain_ok`.
- The fix uses the existing single-owner transport, parser, heartbeat, status
  gate, raw logging, and cleanup lifecycle. No second control path was added.
- This is an offline host-side fix. No hardware rerun, flash, reset, or new
  START/STOP was authorized or performed after the original smoke.

## Real run evidence

- `campaign_id`: `s260806121324434`
- `run_id`: `e260806121324434`
- `run_kind`: `elevated-wheels`
- `requested_duration_s`: `0.5`
- `speed plan`: baseline declaration `680`, then override values
  `580, 480, 380, 280, 260`.
- Baseline gains used by every P command: `Kp=35`, `Ki=0`, `Kd=10`.

### Camera

The canonical FFmpeg/dshow path opened `EMEET SmartCam C960` and stopped it
cleanly. Actual ffprobe output from the recorded `camera.mkv` was:

- `codec_name=mjpeg`
- `width=1280`
- `height=720`
- `avg_frame_rate=30/1` (`30.0 fps`)
- ffprobe return code: `0`
- camera `clean_exit=true`, `q_sent=true`, `exit_code=0`,
  `forced_termination=false`, and `cleanup_errors=[]`.

This records the actual FFmpeg/ffprobe stream. It is not written as an
independent device-level `FourCC=MJPG` verification. The FFmpeg log contains
its own input stream label, but the structured acceptance evidence remains
`codec_name=mjpeg`; exact FourCC is therefore still `INSUFFICIENT EVIDENCE`
under the strict requirement.

### TCP, P ACK, H, R, and S

Raw I/O contains 11 TX events and 25 RX events, with 430 TX bytes and 1106
RX bytes. The five P commands were sent once each with the same campaign and
the baseline gains:

```text
P,s260806121324434,1,35,0,10,580,26
P,s260806121324434,2,35,0,10,480,24
P,s260806121324434,3,35,0,10,380,22
P,s260806121324434,4,35,0,10,280,24
P,s260806121324434,5,35,0,10,260,2B
```

Each received same-campaign ACK was `APPLIED/APPLIED`:

```text
A,s260806121324434,1,APPLIED,APPLIED,3D
A,s260806121324434,2,APPLIED,APPLIED,3E
A,s260806121324434,3,APPLIED,APPLIED,3F
A,s260806121324434,4,APPLIED,APPLIED,38
A,s260806121324434,5,APPLIED,APPLIED,39
```

The existing safety entrypoint sent one pre-condition STOP before P/START,
one R START, and one final R STOP. It did not retry START:

```text
R,s260806121324434,e260806121324434,STOP,70       # pre-STOP
R,s260806121324434,e260806121324434,START,28      # one START
R,s260806121324434,e260806121324434,STOP,70       # final STOP
```

Matching status evidence included:

```text
S,s260806121324434,e260806121324434,RUNNING,START,0,5E
S,s260806121324434,e260806121324434,STOPPED,STOP,0,08
```

The final STOP was confirmed with `stop_confirmed=true`, `send_outcome=COMPLETED`,
and the matching run/campaign IDs. The H heartbeat was sent three times at
approximately 200 ms scheduling intervals, was present in raw I/O, had no
failure, and was stopped before final STOP. The live health evidence showed
`heartbeat_timeout_count=0` and `lease_active=1` during the running portion.

### Cleanup and timestamps

- Control `cleanup_errors=[]`, `raw_io.published=true`,
  `raw_io.write_error=null`, and `quiescence.proven=true`.
- Camera stop completed as described above.
- Final process check found no ffmpeg/ffprobe process, and the TCP query found
  no remaining matching `192.168.110.236:8888` connection.
- The report does not publish a dedicated socket-open timestamp,
  socket-close timestamp, or close-count field. Raw I/O provides only the
  observable event interval `2026-08-06T12:13:27` through
  `2026-08-06T12:13:30`; exact connection/disconnection times are therefore
  `INSUFFICIENT EVIDENCE`.

## Evidence hashes

- `simulation/digital_twin/logs/v1_ground_shakedown_260806121324434/camera.mkv`
  - `9BD629C8ACA1016F7FA2E646F20170055B5A1F924F65FC185B027524430CBF15`
- `simulation/digital_twin/logs/v1_ground_shakedown_260806121324434/camera_ffmpeg.log`
  - `33C06F86DA11741FDA74C16564C34EBC94CAF126725E5E25F63211CE93238916`
- `simulation/digital_twin/logs/v1_ground_shakedown_260806121324434/raw_io.json`
  - `607D8375AD4ED0639943AF2B30140B24B84A25A933052402EE03BA80B720D050`
- `simulation/digital_twin/logs/v1_ground_shakedown_260806121324434/shakedown_report.json`
  - `1DCB6A929EE814477F982A278A4D36E53C7D583988702117DCB7744D40696D5B`

## VERIFIED

- The explicit host/port `192.168.110.236:8888` was uniquely identified on
  the current `@Ruijie-sC384 2` local network and accepted TCP.
- The canonical `ground_shakedown.py --execute` path was used once; no second
  TCP client, parser, ACK registry, heartbeat thread, or lifecycle was added.
- The C960 recorded stream actually probed as MJPEG, 1280x720, and 30 fps.
- All five P ACKs were same-campaign `APPLIED/APPLIED`.
- One START was confirmed as same-run/campaign `S RUNNING/START`.
- The final STOP was confirmed as same-run/campaign `S STOPPED/STOP`.
- H heartbeat evidence was present and parsed with no reported failure.
- Camera cleanup, raw publication, control cleanup error list, and quiescence
  evidence completed without reported errors.
- The bounded offline regression set passed: `148 passed`.
- The continuous-RX, delayed-START, and slow-STOP timing regressions passed;
  compileall passed.
- Host-side shakedown code and its test changed; no firmware source or build
  output was changed.

## INFERENCE

- The user-provided elevated-wheel setup is treated as the physical safety
  condition for this run; it was not independently measured by the software.
- `fw_build_id=1` and `fw_schema_version=1` identify runtime-reported fields,
  but cannot be mapped to the current source hashes without a current build
  artifact or independent firmware identity channel.
- The FFmpeg log's stream label is not promoted to an independent device-level
  FourCC proof.

## FAIL / INSUFFICIENT EVIDENCE

- FAIL: raw evidence shows `1.375 s` from R START send to final R STOP send
  and `1.265 s` from S RUNNING to final S STOPPED, exceeding the authorized
  maximum `0.5 s`.
- INSUFFICIENT EVIDENCE: no current firmware binary hash proves which image is
  running on the STM32.
- INSUFFICIENT EVIDENCE: exact device-level `FourCC=MJPG` is not independently
  established by the canonical structured camera evidence.
- INSUFFICIENT EVIDENCE: dedicated socket connection/disconnection times and
  a serialized exactly-once socket close record are absent from the report.
- `imu_evidence_status=UNVERIFIED_NO_VALIDITY_BIT`; no IMU/model calibration
  claim is made.
- This smoke telemetry and camera file must not be added to calibration or
  holdout datasets.

## Hardware actions

- `connected`: C960 `YES`; ESP-01S TCP `YES` at explicit
  `192.168.110.236:8888`; no serial/debugger connection.
- `flashed`: `NO`.
- `reset`: `NO`.
- `START`: `YES`, exactly one R START.
- `STOP`: `YES`, one existing pre-STOP plus one final R STOP; final STOP
  confirmed. No automatic START retry occurred.
- `motion`: run kind was `elevated-wheels`; motor telemetry showed the bounded
  motor command while the user stated the four wheels were lifted. No ground
  contact or ground motion was authorized or performed.
- B1 was not executed or repeated. B3, B4, and B5 were not run.

## Gate boundary

B2 is not accepted as PASS. The tool's `SHAKEDOWN_PASS` is subordinate to the
explicit hardware safety-duration contract and does not override the raw
timing evidence above. No firmware, control algorithm, or hardware change is
authorized as an after-the-fact remedy in this handoff. The host-side fix is
not hardware-verified and does not retroactively change the original run.

B2 does not equal the B3 synchronization Gate, does not prove high-speed
performance, does not prove digital-twin calibration, and produces no data
eligible for model fitting.

The next interface is B3 only after independent Codex acceptance of a corrected
B2 evidence package and a fresh user authorization specifically covering new
ground data collection. Stop here; do not run B3, B4, or B5 automatically.
