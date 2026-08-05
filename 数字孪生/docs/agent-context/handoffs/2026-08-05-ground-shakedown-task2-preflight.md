# Ground Shakedown Task 2 Preflight

Status: BLOCKED_ON_TASK1_ACCEPTANCE

This is an offline design preflight. It authorizes no Task 2 implementation,
camera access, TCP connection, flash, or hardware motion. Task 2 may be
dispatched only after Task 1 has a clean independent re-review and fresh test
evidence.

## Verified Environment

- Python 3.11.7 is available through `py -3.11`.
- `ffmpeg` and `ffprobe` 7.1.1 are available at
  `D:/ffmpeg-7.1.1-essentials_build/ffmpeg-7.1.1-essentials_build/bin/`.
- No established TCP connection to remote port 8888 existed during this
  offline preflight.
- Camera identity and availability were not checked because the user powered
  the camera off.

## Binding Interface Decisions For Task 2

The Task 2 brief must define these interfaces before implementation:

```python
validate_duration(duration_s, allow_extended=False) -> float
make_evidence_dir(root, timestamp) -> pathlib.Path
normalize_telemetry_units(report) -> dict
publish_report_atomic(evidence_dir, report) -> pathlib.Path
compute_shakedown_verdict(control_report, camera_report, artifacts) -> str

FfmpegCameraRecorder(
    evidence_dir,
    popen_factory=subprocess.Popen,
    ffprobe_runner=subprocess.run,
    executable_resolver=shutil.which,
    sleep_fn=time.sleep,
)

orchestrate_shakedown(
    recorder,
    session_runner,
    evidence_dir,
    run_kind,
) -> dict
```

Production defaults are used only by the CLI. Tests inject all external
process, resolver, and sleep boundaries and never open a real camera or TCP
connection.

## Unique Control Identity

The CLI must derive one evidence timestamp first, then create fresh ASCII
identifiers from it. Example shapes:

```text
campaign_id = s260805013045123
run_id      = e260805013045123
```

The format is one prefix character plus `YYMMDDHHMMSSmmm`, exactly 16 ASCII
characters. Use `s` for campaign, `e` for elevated-wheel run, and `g` for a
ground run. Both identifiers must pass the existing runtime-protocol maximum
of 16 characters; longer descriptive values are invalid.
Parameter versions remain exactly 1 through 5. Reusing literal campaign
`shake` or a prior run ID is prohibited because ACK/status schemas have no
cryptographic session nonce; Task 1's per-command receive boundary remains
required even with fresh identifiers.

## Camera Final Validation

Startup still gates only on a writable evidence directory and a live ffmpeg
process after the injected one-second wait. Final validation occurs only after
bounded recorder cleanup and requires all of:

- ffmpeg exited cleanly without terminate/kill;
- `camera.mkv` exists and is non-empty;
- ffprobe exited 0 and returned valid JSON;
- at least one video stream reports `codec_name=mjpeg`;
- width is 1280 and height is 720;
- parsed average frame rate is finite and within 0.5 fps of 30.0.

Resolve both ffmpeg and ffprobe before creating the evidence directory or any
camera/TCP resource. Missing executables are a preflight rejection, not a
partially executed run.

The ffprobe command must be recorded verbatim and include at least
`codec_name,width,height,avg_frame_rate`. Invalid JSON, no video stream,
wrong codec/mode, timeout, or a known ffprobe process failure is structured
camera failure.

## Report Schema And Ownership

Task 2 is the only owner of the overall `verdict`. Task 1 returns only
`control_verdict` and control evidence. The final report has this minimum
shape:

```json
{
  "schema_version": 1,
  "run_kind": "elevated-wheels",
  "phase": "complete",
  "verdict": "SHAKEDOWN_PASS",
  "campaign_id": "s260805013045123",
  "run_id": "e260805013045123",
  "requested_duration_s": 0.5,
  "imu_evidence_status": "UNVERIFIED_NO_VALIDITY_BIT",
  "control": {},
  "camera": {},
  "artifacts": {
    "camera": "camera.mkv",
    "camera_log": "camera_ffmpeg.log",
    "raw_io": "raw_io.json",
    "report": "shakedown_report.json"
  },
  "missing_artifacts": [],
  "errors": []
}
```

The control object carries the five structured ACKs, statuses, heartbeat
outcome, telemetry, `rollback_requested`, and `stop_confirmed`. Artifact paths
are relative to the immutable evidence directory. A missing artifact is never
listed as present.

Overall verdict precedence is fixed:

1. Any known control/parser/transport/STOP/camera/cleanup/publication failure:
   `SHAKEDOWN_FAIL`.
2. Otherwise, missing required telemetry or video evidence:
   `INSUFFICIENT_EVIDENCE`.
3. Only control PASS, camera PASS, at least one telemetry frame, and all four
   readable required artifacts: `SHAKEDOWN_PASS`.

`normalize_telemetry_units()` changes only the new in-memory report. If a
frame contains both `yaw_rad` and `yaw_deg` with conflicting values, fail
closed instead of overwriting either value.

Renaming the unit does not validate the MPU6050. Until firmware exposes a
latched initialization result, sample tick, angular rate, and validity bits,
the report must set `imu_evidence_status=UNVERIFIED_NO_VALIDITY_BIT`. Numeric
`yaw_deg` is preserved as an exploratory observation only; it cannot authorize
motion, affect the bounded shakedown verdict, or enter motor/PID control.

## Recorder Cleanup Contract

`FfmpegCameraRecorder.stop()` is idempotent and records every transition:

1. If running, write and flush `b"q\n"`.
2. Wait at most five seconds.
3. On write/wait failure or timeout, call `terminate()` and wait for a bounded
   interval.
4. If still alive, call `kill()` and wait for a bounded interval.
5. Close stdin and the camera log exactly once on every path.

The result records `graceful_stop`, `forced_termination`, `exit_code`, and
`cleanup_errors`. Any terminate/kill path is camera failure. Cleanup errors do
not replace the primary control error.

Once the evidence directory exists, orchestration owns one outer
`try/finally`: stop/finalize the recorder once, attempt a minimal atomic report
once, and either return the completed report or raise after the failure report
has been published. `session_runner` is invoked at most once. There is no
automatic START retry.

## CLI Safety Boundary

- `--run-kind` is required and limited to `elevated-wheels` or `ground`.
- Duration must be finite and positive. Above 3 seconds requires
  `--allow-extended`; above 20 seconds is always rejected.
- Without `--execute`, the CLI only validates and prints the resolved plan. It
  creates no evidence directory, process, socket, or control command.
- A real run requires `--execute` plus a fresh user authorization immediately
  before invocation. The tool's internal pre-STOP must then receive correlated
  `STOPPED/STOP` before any P or START command. This replaces the ambiguous
  wording that placed a second user confirmation between internal pre-STOP and
  START; no hidden interactive prompt is added.
- The first elevated-wheel and first ground invocations are each exactly 0.5
  seconds and require separate authorizations. The 3-second escalation remains
  a later gate.

## Required Offline Tests

Task 2 RED/GREEN evidence must independently cover:

1. non-finite/bounded duration rejection before any resource factory;
2. evidence timestamp collision without overwrite or auto-suffix;
3. yaw rename and conflicting dual-field failure;
4. missing ffmpeg/ffprobe before evidence creation;
5. Popen failure closes the log and never calls the session runner;
6. immediate ffmpeg exit blocks the session and publishes a minimal failure
   report after directory creation;
7. graceful q shutdown and valid MJPEG/1280x720/30fps metadata;
8. broken pipe, wait timeout, terminate, kill, and idempotent repeated stop;
9. ffprobe timeout/nonzero/invalid JSON/no stream/wrong mode failures;
10. session exception still stops camera and publishes the primary error;
11. deterministic verdict precedence and missing-artifact lists;
12. dry-run/help/import create no process or socket;
13. exact first hardware command contains `--execute`, duration 0.5, no PID
    arguments, no extended flag, and no retry option.

## Exit Condition

This handoff remains `BLOCKED_ON_TASK1_ACCEPTANCE` until the Task 1 fix round
passes focused tests, independent re-review, and Codex fresh verification.
