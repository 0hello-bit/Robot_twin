# Ground Shakedown Recorder Design

Date: 2026-08-04
Status: OFFLINE_IMPLEMENTATION_AUTHORIZED; HARDWARE_RUN_REQUIRES_FRESH_AUTHORIZATION

## 2026-08-05 Offline Design Correction

The approved fail-closed behavior is unchanged, but the implementation boundary
is corrected after source review:

- The historical `transport_soak.MixedStreamParser` forwards only `S,` lines.
  The new tool must install a local `ControlAwareMixedStreamParser` that reuses
  the historical binary-frame state machine while forwarding both `A,` and
  `S,` control lines. The historical evidence file remains read-only.
- A malformed `A,` line is an immediate ACK-gate failure. The parser records
  the raw line and parse error, wakes the waiter, attempts correlated STOP, and
  never sends START. A stale or mismatched campaign/version ACK fails the same
  way; it is not skipped in search of a later matching ACK.
- The historical module is loaded by an explicit path resolved from the
  workspace root. The test and CLI must not depend on the current directory or
  on `.embeddedskills` being a Python package.
- ffmpeg startup is gated by the process remaining alive after one second and
  by a writable output destination. MKV size is not a startup requirement
  because container metadata may be finalized at close. Final camera success
  requires a clean ffmpeg exit, a non-empty file, and a readable video stream
  reported by ffprobe. stderr is captured in `camera_ffmpeg.log`.
- After the PWM scale repair, the first hardware gate is an elevated-wheel
  0.5-second run at `speed_max=260`. A separate fresh authorization is required
  for a 0.5-second ground run. A 3-second ground run is a later escalation, not
  the first post-repair motion.

## Purpose

Run the first supervised ground shakedown without claiming digital-twin,
4B-3, or 4B-4 acceptance. The run is a bounded data-collection exercise for
discovering motor-direction, line-following, stopping, telemetry, camera, and
MPU6050 problems.

## Fixed Scope

- The user remains beside the car and can disconnect motor power immediately.
- The EMEET C960 is an auxiliary observer; the user is the primary safety
  observer.
- Do not flash firmware and do not change Kp, Ki, or Kd.
- Temporarily reduce only `speed_max` from the baseline 680 to 260 through the
  existing runtime protocol.
- The first post-repair motion window is 0.5 seconds with wheels elevated. A
  separate 0.5-second ground run requires review and fresh authorization. A
  later 3-second run requires another review; 20 seconds remains the absolute
  tool limit and requires explicit extended-run authorization.
- Every artifact is written to a new timestamped evidence directory. Existing
  evidence is never overwritten.

## Preflight

The run may proceed only when all of these conditions pass:

1. C960 identity and `1280x720 / MJPG / 30 fps` mode are confirmed.
2. ESP TCP `192.168.110.236:8888` is reachable.
3. A uniquely identified preflight STOP receives the correlated
   `STOPPED/STOP` status.
4. The user gives an immediate ready confirmation after preflight.

These conditions were confirmed in an earlier session, but camera power,
DirectShow index, TCP reachability, firmware identity, and STOP status are
time-varying. All four conditions must be renewed immediately before each
future hardware run.

## Runtime Sequence

One TCP connection owns the complete sequence:

1. Start raw C960 recording before any control command.
2. Send a uniquely identified STOP and require correlated `STOPPED/STOP`.
3. Keep Kp=35, Ki=0, and Kd=10 unchanged. Apply speed steps
   `580 -> 480 -> 380 -> 280 -> 260` with unique monotonically increasing
   versions. Require a correlated `APPLIED/APPLIED` ACK after every step.
4. If any ACK is missing, malformed, rejected, or mismatched, do not send
   START. Attempt STOP, close the connection, and mark the run failed.
5. Send START and require correlated `RUNNING/START`.
6. Send a command heartbeat every 200 ms while collecting for the explicitly
   authorized duration. The first elevated-wheel and ground gates are each
   exactly 0.5 seconds.
7. In all paths after START, attempt STOP and require correlated
   `STOPPED/STOP`. A missing STOP confirmation requires immediate physical
   power removal.
8. STOP requests the firmware's baseline rollback and requires a final
   `STOPPED/STOP` status. That status proves motion inhibition, not the exact
   numeric parameter values on an unverified flashed binary. The report records
   the rollback request and status without claiming a measured value of 680.

## Evidence

The timestamped run directory contains:

- raw C960 video;
- raw TCP TX/RX bytes with wall and monotonic timestamps;
- decoded telemetry including sensors, signed PWM, error, PID output, tick,
  and MPU yaw;
- every parameter ACK and START/STOP status;
- camera mode, requested speed plan, run duration, and action outcomes;
- a bounded `SHAKEDOWN_PASS`, `SHAKEDOWN_FAIL`, or
  `INSUFFICIENT_EVIDENCE` verdict.

The report is published atomically: write JSON to a uniquely named temporary
file in the new evidence directory, flush and close it, then replace it with
`shakedown_report.json`. A partially written final report is never valid
evidence. Timestamp-derived directory names are fail-closed: if the target
already exists, creation fails rather than selecting, deleting, or overwriting
an existing directory. The caller must choose a new timestamp/run identifier.

Failure is still an evidence-producing outcome. Once an evidence directory has
been created, every later failure attempts to publish a minimal report
containing the phase, exception or timeout reason, attempted actions, known
artifact paths, and an explicit `missing_artifacts` list. It must not claim
that absent video, raw I/O, telemetry, or final camera metadata exists.

The existing telemetry field named `yaw_rad` is actually decoded in degrees in
the historical transport tool. The new report must label the unit as degrees
and must not silently reinterpret historical files.

## Safety And Failure Handling

- The user immediately disconnects motor power for abnormal direction,
  violent rotation, track departure, unexpected noise, or failure to stop
  after the authorized motion window.
- The camera cannot authorize continued motion or replace the human cutoff.
- No automatic retry may send another START.
- TCP disconnect, command error, parser error, ACK mismatch, or camera startup
  failure is fail-closed.
- The current workspace binary is not proven identical to the firmware on the
  car. Runtime ACKs and observed telemetry are evidence of actual behavior;
  source inspection alone is not.
- Resource ownership is single-owner and explicit. The unchanged Task 1 session
  owns its transport, reader, heartbeat, STOP attempt, and transport close.
  Task 2 orchestration owns only its camera recorder, camera log, and final
  report publication, using one `try/finally` cleanup path to stop/finalize
  the camera once and publish the report once. Resources are never shared
  across those ownership boundaries.
- Camera cleanup is bounded: request ffmpeg `q`, wait at most five seconds,
  then `terminate`, wait a short bounded interval, and finally `kill` if still
  alive. Any terminate/kill path is a camera failure even if a playable file
  remains. Cleanup exceptions are recorded and must not suppress the primary
  control failure.
- CLI execution is deny-by-default. Argument parsing, plan validation, and
  `--help` perform no TCP/camera action. A real run additionally requires
  `--execute`; without it the tool may print the resolved plan but exits before
  creating a camera process or opening a socket.

## Verdict Boundary

`SHAKEDOWN_PASS` means only that the bounded command sequence completed, STOP
was confirmed, useful telemetry/video were captured, and no observed safety
failure occurred. It does not unlock or complete any formal Robot Twin AI
gate.

Verdicts use this fixed precedence, so cleanup order cannot change the result:
`SHAKEDOWN_FAIL` for any control, parser, transport, STOP-confirmation, or
camera-start/finalization failure; otherwise `INSUFFICIENT_EVIDENCE` when
required telemetry/video evidence is absent or unreadable; otherwise
`SHAKEDOWN_PASS`. A duration that is non-finite (`NaN`, `Infinity`, or
`-Infinity`), non-positive, or above the configured bound is rejected before
any evidence directory, camera, or TCP resource is created.
