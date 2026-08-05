# Ground Shakedown Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a fail-closed recorder that temporarily lowers only `speed_max` to 260, captures C960 video plus raw telemetry, and supports the staged 0.5-second elevated-wheel and ground gates before any longer run.

**Architecture:** A new standalone tool loads the already-tested transport helpers from the historical `v1_task4b4/transport_soak.py` by explicit file path without modifying that evidence. A local mixed-stream adapter preserves its binary parser but forwards both parameter `A,` ACKs and run `S,` statuses. The session applies five bounded speed updates before START, records a C960 MKV through ffmpeg, and writes one new immutable evidence directory. Scripted transports exercise the real command parser and state-machine code before any hardware run.

**Tech Stack:** Python 3.11, pytest, existing `real_world.runtime_protocol`, existing `transport_soak.py`, Windows DirectShow, ffmpeg 7.1.1.

## Global Constraints

- Do not flash firmware and do not change Kp=35, Ki=0, or Kd=10.
- Apply only `speed_max`: `680 -> 580 -> 480 -> 380 -> 280 -> 260`.
- Require a correlated `APPLIED/APPLIED` ACK after every parameter command.
- Do not send START after any missing, malformed, rejected, or mismatched ACK.
- The first post-PWM motion window is exactly 0.5 seconds with wheels elevated; the first ground window is a separately authorized 0.5 seconds. No automatic START retry.
- Send a command heartbeat every 200 ms while RUNNING.
- Attempt STOP on every exit path and require correlated `STOPPED/STOP` after START.
- Record rollback requested and STOPPED confirmed separately; do not claim that numeric 680 was measured after STOP.
- Save artifacts only under a new timestamped directory; never overwrite historical evidence.
- Treat telemetry's historical `yaw_rad` key as degrees and emit `yaw_deg` in new evidence.
- Do not perform Git writes in this hardware session.
- This implementation session is offline only. Do not run the hardware command, open the camera, or connect to TCP while building and testing the tool.
- `main()` is deny-by-default: only an explicit `--execute` may open the
  camera or TCP connection. Parsing, validation, `--help`, and the default
  dry-run path must not touch hardware.
- Production control identities are derived from the evidence timestamp and
  are exactly 16 ASCII characters: campaign `sYYMMDDHHMMSSmmm`, elevated run
  `eYYMMDDHHMMSSmmm`, or ground run `gYYMMDDHHMMSSmmm`.
- Final camera acceptance requires MJPEG, 1280x720, and a finite average frame
  rate within 0.5 fps of 30.0, in addition to clean recorder shutdown.

## File Structure

- Create `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`: camera lifecycle, ACK-aware control session, artifact writing, and CLI.
- Create `simulation/digital_twin/tests/test_ground_shakedown.py`: scripted-transport safety and evidence tests.
- Read only `.embeddedskills/build/v1_task4b4/transport_soak.py`: reuse `SocketTransport`, `RawIoLogger`, `MixedStreamParser`, telemetry decoding, heartbeat, and status helpers.
- Read only `simulation/digital_twin/real_world/runtime_protocol.py`: use `ParameterCommand`, `RunCommand`, `parse_ack`, and `validate_parameter_update`.

---

### Task 1: ACK-Aware Fail-Closed Ground Session

**Files:**
- Create: `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`
- Test: `simulation/digital_twin/tests/test_ground_shakedown.py`

**Interfaces:**
- Consumes: `transport_soak._SessionCtx`, `transport_soak._send`, `transport_soak.wait_for_status`, `transport_soak.status_matches`, `transport_soak._heartbeat_loop`, `transport_soak._final_stop`, `transport_soak._finalize`.
- Produces: `ControlAwareMixedStreamParser`, `AckSessionContext`, `wait_for_parameter_ack(ctx, campaign_id, version, timeout_s)`, `validate_speed_plan()`, and `run_ground_session(transport, campaign_id, run_id, duration_s, raw_logger=None) -> dict`.

- [ ] **Step 1: Write the failing success-sequence test**

Before the scripted session test, add a parser contract that proves the new
adapter receives fragmented `A,` and `S,` lines while ignoring newline and
`A,` bytes inside a checksum-valid binary telemetry frame:

```python
def binary_frame(frame_type, payload):
    checksum = frame_type ^ len(payload)
    for value in payload:
        checksum ^= value
    return bytes([0xAA, 0x55, frame_type, len(payload)]) + payload + bytes([checksum])


def test_control_parser_forwards_fragmented_ack_and_status_not_binary_noise():
    lines = []
    parser = ControlAwareMixedStreamParser(on_line=lines.append)
    binary_payload = bytes([0x0A, ord("A"), ord(",")]) + bytes(21)
    blob = (
        frame("A,shake,1,APPLIED,APPLIED").encode("ascii")
        + binary_frame(0x01, binary_payload)
        + frame("S,shake,gnd00000001,STOPPED,STOP,2").encode("ascii")
    )
    for chunk in (blob[:7], blob[7:19], blob[19:43], blob[43:]):
        for value in chunk:
            parser.feed(value)
    assert lines == [
        frame("A,shake,1,APPLIED,APPLIED"),
        frame("S,shake,gnd00000001,STOPPED,STOP,2"),
    ]
```

Add an ACK-gate test whose transport returns a checksum-invalid `A,` line for
the first parameter command. Assert that START is never sent, a correlated
STOP is the last control command, the parse error is recorded, and the waiter
returns immediately rather than consuming its full timeout.

Create this deterministic `FirmwareScriptTransport` in the test file. It feeds real checksum-valid `A` and `S` lines in response to transmitted commands and records the exact TX command bodies:

```python
class FirmwareScriptTransport:
    def __init__(self, reject_speed=None, reject_reason="STEP_LIMIT",
                 drop_final_stop_status=False):
        self.reject_speed = reject_speed
        self.reject_reason = reject_reason
        self.drop_final_stop_status = drop_final_stop_status
        self.control_bodies = []
        self._rx = queue.Queue()
        self._stop_count = 0
        self._closed = False

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        self.control_bodies.append(body)
        parts = body.split(",")
        if parts[0] == "P":
            speed = int(parts[6])
            outcome = "REJECTED" if speed == self.reject_speed else "APPLIED"
            reason = self.reject_reason if outcome == "REJECTED" else "APPLIED"
            self._rx.put(frame(
                "A,{0},{1},{2},{3}".format(parts[1], parts[2], outcome, reason)
            ).encode("ascii"))
        elif parts[0] == "R" and parts[3] == "START":
            self._rx.put(frame(
                "S,{0},{1},RUNNING,START,1".format(parts[1], parts[2])
            ).encode("ascii"))
        elif parts[0] == "R" and parts[3] == "STOP":
            self._stop_count += 1
            if not (self.drop_final_stop_status and self._stop_count > 1):
                self._rx.put(frame(
                    "S,{0},{1},STOPPED,STOP,2".format(parts[1], parts[2])
                ).encode("ascii"))

    def recv(self, _max_bytes):
        if self._closed:
            return None
        try:
            return self._rx.get(timeout=0.01)
        except queue.Empty:
            return b""

    def close(self):
        self._closed = True
```

The test must assert this literal ordering before implementation exists:

```python
def test_ground_session_applies_all_speed_steps_before_start_and_stops():
    transport = FirmwareScriptTransport()
    result = run_ground_session(
        transport, "shake", "gnd00000001", 0.05
    )
    assert transport.control_bodies[:7] == [
        "R,shake,gnd00000001,STOP",
        "P,shake,1,35,0,10,580",
        "P,shake,2,35,0,10,480",
        "P,shake,3,35,0,10,380",
        "P,shake,4,35,0,10,280",
        "P,shake,5,35,0,10,260",
        "R,shake,gnd00000001,START",
    ]
    assert transport.control_bodies[-1] == "R,shake,gnd00000001,STOP"
    assert result["speed_override"]["applied_speeds"] == [580, 480, 380, 280, 260]
    assert result["start"]["confirmed"] is True
    assert result["stop"]["confirmed"] is True
    assert result["control_verdict"] == "PASS"
```

- [ ] **Step 2: Run the parser and success tests and verify RED**

Run:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py::test_control_parser_forwards_fragmented_ack_and_status_not_binary_noise simulation/digital_twin/tests/test_ground_shakedown.py::test_ground_session_applies_all_speed_steps_before_start_and_stops
```

Expected: collection/import failure because `ground_shakedown.py`,
`ControlAwareMixedStreamParser`, and `run_ground_session` do not exist.

- [ ] **Step 3: Implement the mixed-stream adapter and minimal ACK-aware session**

Resolve the workspace root from `Path(__file__).resolve().parents[3]`, load
`.embeddedskills/build/v1_task4b4/transport_soak.py` with
`importlib.util.spec_from_file_location()`, and fail at import with a path-rich
error if the historical module is absent.

Implement a local `ControlAwareMixedStreamParser` with the same binary path as
the historical parser. On newline, forward the suffix beginning at the last
`A,` or `S,` occurrence. Do not modify `transport_soak.py`:

```python
class ControlAwareMixedStreamParser(soak.MixedStreamParser):
    def feed(self, byte):
        if self._fp.busy:
            self._feed_binary(byte)
            return
        if byte == 0xAA:
            self._feed_binary(byte)
            return
        if byte == 0x0A:
            self._ascii.append(byte)
            line = self._ascii.decode("ascii", errors="replace")
            self._ascii.clear()
            if self._on_line is None:
                return
            index = max(line.rfind("A,"), line.rfind("S,"))
            if index >= 0:
                self._on_line(line[index:])
            return
        if byte == 0x0D:
            return
        if 0x20 <= byte <= 0x7E:
            self._ascii.append(byte)
        else:
            self._ascii.clear()
```

Then implement these session behaviors:

```python
SPEED_STEPS = (580, 480, 380, 280, 260)
BASELINE = ParameterCommand("baseline", 1, 35.0, 0.0, 10.0, 680)

class AckSessionContext(soak._SessionCtx):
    def __init__(self, transport, raw_logger):
        self.parameter_acks = []
        self.ack_events = []
        super().__init__(transport, raw_logger)
        self._mixed = ControlAwareMixedStreamParser(
            on_telemetry=self._on_telemetry,
            on_line=self._on_line,
            on_health=self._on_health,
        )

    def _on_line(self, line):
        if line.startswith("A,"):
            with self.cv:
                try:
                    ack = parse_ack(line)
                except Exception as exc:
                    self.ack_events.append(
                        {"kind": "error", "line": line, "error": repr(exc)}
                    )
                    self.parse_errors.append({"line": line, "error": repr(exc)})
                else:
                    self.parameter_acks.append(ack)
                    self.ack_events.append({"kind": "ack", "ack": ack})
                self.cv.notify_all()
            return
        super()._on_line(line)
```

`wait_for_parameter_ack()` consumes the first ACK event after each P send. A
parse error, campaign/version mismatch, or outcome/reason other than
`APPLIED/APPLIED` is an immediate failure; it must not be ignored while
waiting for a later frame. `validate_speed_plan()` constructs five
`ParameterCommand` instances with versions 1..5 and calls
`validate_parameter_update()` against the prior command, beginning with the
680 baseline. `run_ground_session()` starts one reader, confirms pre-STOP,
sends each P frame and consumes exactly one ACK event, confirms START, starts
the existing 200 ms heartbeat, collects for the requested duration, stops the
heartbeat, confirms final STOP, finalizes evidence, writes raw I/O once, and
closes the transport once in `finally`.

- [ ] **Step 4: Run the success test and verify GREEN**

Run the Step 2 command. Expected: `1 passed` and exit code 0.

- [ ] **Step 5: Write the failing rejected-ACK test**

```python
def test_rejected_speed_step_never_sends_start_and_attempts_stop():
    transport = FirmwareScriptTransport(reject_speed=380, reject_reason="STEP_LIMIT")
    result = run_ground_session(
        transport, "shake", "gnd00000002", 0.05
    )
    assert not any(",START" in body for body in transport.control_bodies)
    assert transport.control_bodies[-1] == "R,shake,gnd00000002,STOP"
    assert result["speed_override"]["failure_reason"] == "STEP_LIMIT"
    assert result["control_verdict"] == "FAIL"
```

- [ ] **Step 6: Run the rejected-ACK test and verify RED**

Expected: FAIL because the initial implementation does not yet issue a fail-closed STOP and report the rejection.

- [ ] **Step 7: Implement fail-closed parameter handling**

On timeout, parse failure, identity mismatch, or any ACK other than `APPLIED/APPLIED`, set `start.cmd_sent=false`, send the same correlated STOP, wait for `STOPPED/STOP`, record the exact failure reason, and return `control_verdict=FAIL`. Task 1 never emits the overall shakedown verdict. Do not retry the P command and do not send START.

- [ ] **Step 8: Add final-STOP and heartbeat regression tests**

Add tests that independently catch these breaks:

```python
def test_missing_final_stopped_sets_cut_power_warning():
    transport = FirmwareScriptTransport(drop_final_stop_status=True)
    result = run_ground_session(transport, "shake", "gnd00000003", 0.05)
    assert result["stop"]["confirmed"] is False
    assert result["cut_power_warning"] is True
    assert result["control_verdict"] == "FAIL"

def test_running_window_sends_heartbeat_before_final_stop():
    transport = FirmwareScriptTransport()
    run_ground_session(transport, "shake", "gnd00000004", 0.45)
    heartbeat_indexes = [i for i, body in enumerate(transport.control_bodies) if body.startswith("H,")]
    final_stop_index = len(transport.control_bodies) - 1
    assert len(heartbeat_indexes) >= 2
    assert max(heartbeat_indexes) < final_stop_index
```

- [ ] **Step 9: Run all Task 1 tests**

Run:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py
```

Expected: all Task 1 tests pass with exit code 0.

---

### Task 2: Camera Lifecycle, Immutable Evidence, And CLI

**Files:**
- Modify: `.embeddedskills/tools/shakedown_toolchain/ground_shakedown.py`
- Modify: `simulation/digital_twin/tests/test_ground_shakedown.py`

**Interfaces:**
- Consumes: the independently accepted `run_ground_session(...)` from Task 1;
  ffmpeg and ffprobe resolved before evidence-directory creation.
- Produces: `validate_duration(duration_s, allow_extended=False) -> float`,
  `make_evidence_dir(root, timestamp) -> pathlib.Path`,
  `normalize_telemetry_units(report) -> dict`,
  `publish_report_atomic(evidence_dir, report) -> pathlib.Path`,
  `compute_shakedown_verdict(control_report, camera_report, artifacts) -> str`,
  `FfmpegCameraRecorder(evidence_dir, popen_factory=subprocess.Popen,
  ffprobe_runner=subprocess.run, executable_resolver=shutil.which,
  sleep_fn=time.sleep)`, `orchestrate_shakedown(recorder, session_runner,
  evidence_dir, run_kind) -> dict`, and `main(argv=None) -> int`.

**Testability and ownership contract:** `FfmpegCameraRecorder` accepts injected
`popen`, `ffprobe`, executable-resolver, and `sleep` callables;
`orchestrate_shakedown` accepts an injected session runner. Production defaults
are used only by the CLI. The independently accepted Task 1 interface solely
owns transport/session/raw-I/O cleanup;
Task 2 orchestration solely owns the recorder, camera log, and report
publication, with one `try/finally` cleanup path for those resources. Tests
must not require a real camera, ffmpeg, ffprobe, socket, or wall-clock sleep.
After evidence-directory creation, a camera startup failure must first publish
one atomic minimal failure report and then raise `CameraStartError`. Other
controlled execution failures return a structured failure report after bounded
cleanup; unexpected exceptions are re-raised only after the same minimal
failure report has been published. The session runner is never retried.

- [ ] **Step 1: Write failing evidence and unit-normalization tests**

```python
def test_evidence_directory_refuses_existing_target(tmp_path):
    target = tmp_path / "v1_ground_shakedown_20260804_220000"
    target.mkdir()
    with pytest.raises(FileExistsError):
        make_evidence_dir(tmp_path, "20260804_220000")

def test_new_report_labels_historical_yaw_value_as_degrees():
    report = {"telemetry": {"frames": [{"yaw_rad": 12.5}]}}
    normalize_telemetry_units(report)
    assert report["telemetry"]["frames"] == [{"yaw_deg": 12.5}]
```

Add failure/publication tests: reject `float("nan")`, either infinity, zero,
and negative duration before any injected recorder/resolver is called; reject
conflicting `yaw_rad`/`yaw_deg` fields; reject missing ffmpeg or ffprobe before
creating the evidence directory; inject
a camera-start failure after evidence-dir creation and assert an atomic minimal
`SHAKEDOWN_FAIL` report exists with `camera.mkv` in `missing_artifacts`; assert
no temporary report remains after publication.

- [ ] **Step 2: Verify both tests fail for the missing functions**

Run the two tests directly with pytest. Expected: FAIL for undefined functions.

- [ ] **Step 3: Implement immutable output and yaw normalization**

`make_evidence_dir()` creates exactly one timestamped directory with
`exist_ok=False`; a timestamp collision raises `FileExistsError` and is never
auto-suffixed. `normalize_telemetry_units()` replaces `yaw_rad` with `yaw_deg`
only in the new in-memory report and adds `telemetry_yaw_unit="degree"`; it
never edits historical artifacts. If a frame contains both keys with unequal
values, fail closed without overwriting either. Add `publish_report_atomic(evidence_dir,
report)`: serialize to a uniquely named temporary JSON in that directory,
flush/close it, then `os.replace()` to `shakedown_report.json`; remove a
leftover temporary file only in that same owned directory.

- [ ] **Step 4: Write the failing camera-startup gate test**

Use an injected process factory whose process exits immediately with code 1. Pass that recorder to `orchestrate_shakedown()` with a session callback that increments a counter. Assert `CameraStartError` and a counter value of zero, proving that camera startup failure cannot reach the control session.

- [ ] **Step 5: Implement the ffmpeg recorder with two-stage validation**

Build this DirectShow input contract:

```text
ffmpeg -hide_banner -loglevel info -f dshow -rtbufsize 256M
       -video_size 1280x720 -framerate 30 -vcodec mjpeg
       -i "video=EMEET SmartCam C960" -an -c:v copy camera.mkv
```

Open `camera_ffmpeg.log` before process creation and route ffmpeg stderr to that
file; route stdout to `DEVNULL`. Start with piped stdin and a hidden Windows
process flag. Before starting, require the evidence directory to exist and be
writable. Inject `popen`, `ffprobe`, and `sleep` into the recorder; production
defaults remain `subprocess.Popen`, the local ffprobe invocation, and
`time.sleep`. After one injected second, require only that the process is still running;
MKV nonzero size is not a startup gate because container metadata may be
finalized at close. If the process exited, close the log and raise
`CameraStartError` before opening the control session.

Resolve both ffmpeg and ffprobe before creating the evidence directory or any
camera/TCP resource. `stop()` sends `q`, waits up to five seconds, then bounded `terminate` and
bounded `kill` if required; it records each action/exit code and closes the
log handle exactly once. A forced termination is camera failure. Final
validation runs ffprobe on `camera.mkv` and requires: clean ffmpeg exit, file
exists and is non-empty, ffprobe exit 0, and at least one video stream with
`codec_name=mjpeg`, width 1280, height 720, and a finite parsed average frame
rate within 0.5 fps of 30.0. The ffprobe JSON and command are stored in the
report; final validation never runs as part of the startup gate.

- [ ] **Step 6: Implement the CLI and report boundary**

The CLI accepts `--host`, `--port`, `--duration`, `--out-root`, required `--run-kind`
(`elevated-wheels` or `ground`), `--allow-extended`, and explicit `--execute`.
Reject `NaN`, either infinity, non-positive durations, duration greater than 3
seconds unless `--allow-extended` is supplied, and all durations above 20
seconds before making an evidence directory or allocating a camera/TCP
resource. Without `--execute`, validate and print the plan then exit without
hardware access. Record `run_kind` in the report. The first post-PWM command
uses `--run-kind elevated-wheels --duration 0.5`; the first ground command is
separately authorized and uses `--run-kind ground --duration 0.5`. Write:

Derive the evidence timestamp once, then generate the 16-character production
identities from it. Use `s` for the campaign, `e` for an elevated run, and `g`
for a ground run. Parameter versions remain exactly 1 through 5.
`session_runner` is invoked at most once. It supplies only Task 1 control
evidence (`control_verdict`, ACKs, statuses, initial status, heartbeat outcome,
telemetry, rollback/STOP fields, cleanup errors, and raw-I/O publication
result); Task 2 must neither recreate Task 1 resources nor accept an overall
shakedown verdict from Task 1.

```text
camera.mkv
camera_ffmpeg.log
raw_io.json
shakedown_report.json
```

The report includes camera mode, speed plan, ACKs, statuses, telemetry, action outcomes, `rollback_requested`, `stop_confirmed`, and only the bounded shakedown verdict. `control_verdict=PASS` is necessary but not sufficient: overall `SHAKEDOWN_PASS` additionally requires successful camera finalization and at least one decoded telemetry frame; a clean control session with missing camera or telemetry evidence is `INSUFFICIENT_EVIDENCE`. Verdict precedence is deterministic: any control, parser, transport, STOP, camera startup, or camera finalization failure is `SHAKEDOWN_FAIL`; only then consider missing evidence as `INSUFFICIENT_EVIDENCE`; otherwise emit `SHAKEDOWN_PASS`. After evidence-dir creation, failure paths publish a minimal atomic report with `phase`, failure reason, attempted actions, known paths, and `missing_artifacts`.

The top-level report has `schema_version=1`, `run_kind`, `phase`, `verdict`,
`campaign_id`, `run_id`, `requested_duration_s`,
`imu_evidence_status="UNVERIFIED_NO_VALIDITY_BIT"`, `control`, `camera`,
relative artifact paths, `missing_artifacts`, and `errors`. A path is listed as
present only when that artifact is readable. Numeric MPU yaw remains exploratory
and cannot affect control or the shakedown verdict.

Before Step 7, focused RED/GREEN tests must independently cover all thirteen
contracts: duration rejection before resources; evidence collision; yaw rename
and dual-field conflict; missing executables; Popen failure; immediate ffmpeg
exit; graceful valid MJPEG/1280x720/30 fps shutdown; broken pipe/timeout/
terminate/kill/idempotent stop; all ffprobe failure modes; session exception
cleanup; deterministic verdict and missing-artifact precedence; dry-run/help/
import zero side effects; and the exact future hardware command.

- [ ] **Step 7: Run the focused tests and broader protocol regressions**

Run:

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_ground_shakedown.py simulation/digital_twin/tests/test_runtime_protocol.py simulation/digital_twin/tests/test_task2_bridge.py .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py
```

Expected: all selected tests pass, exit code 0.

- [ ] **Step 8: Compile and inspect the exact hardware command without executing it**

Run:

```powershell
py -3.11 -m py_compile .embeddedskills/tools/shakedown_toolchain/ground_shakedown.py
py -3.11 .embeddedskills/tools/shakedown_toolchain/ground_shakedown.py --help
```

Then construct, but do not run, this first elevated-wheel command:

```powershell
py -3.11 .embeddedskills/tools/shakedown_toolchain/ground_shakedown.py --host 192.168.110.236 --port 8888 --duration 0.5 --run-kind elevated-wheels --out-root .embeddedskills/build --execute
```

Verify that it has no flash option, no PID arguments, no automatic retry, and
no extended-run flag. The `--execute` flag is deliberate: it prevents an
otherwise valid pasted command from moving the car without a current human
authorization.

- [ ] **Step 9: Stop offline implementation and obtain a new immediate authorization later**

Do not execute a hardware command in this implementation session. In a later
session, first flash only the independently accepted PWM artifact under fresh
authorization. Then ask the user to confirm the wheels are elevated, the
camera is on, they are beside the power switch, and power can be removed
immediately. Only after that reply, execute the exact elevated-wheel command
from Step 8 once. Do not retry START automatically after any failure. A ground
command requires review of that evidence and another immediate authorization.

- [ ] **Step 10: Verify artifacts before reporting completion**

Read the new `shakedown_report.json`, `raw_io.json`, and camera metadata. Confirm correlated pre-STOP, five APPLIED ACKs, RUNNING, heartbeats, final STOPPED, video readability, telemetry count, signed PWM, tick monotonicity, and `yaw_deg`. Combine this software evidence with the user's physical observation. Report only `SHAKEDOWN_PASS`, `SHAKEDOWN_FAIL`, or `INSUFFICIENT_EVIDENCE`.
