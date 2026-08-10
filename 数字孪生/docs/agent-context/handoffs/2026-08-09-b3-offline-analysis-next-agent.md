# B3 Agent Handoff: Offline Evidence Analysis

Date: 2026-08-09
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Branch: `master`
Current HEAD before this handoff: `be32024`

## Status and scope

Status: `OFFLINE_ANALYSIS_AUTHORIZED; HARDWARE_NOT_AUTHORIZED`

The next agent is responsible for offline analysis of the latest ground
telemetry delivery and the retained B3 observation evidence. This handoff
does not authorize a camera open, TCP connection, START, STOP, motor motion,
firmware flash, reset, or any other hardware action.

Do not treat the latest ground `SHAKEDOWN_PASS` as B3 completion. It is a
bounded control and evidence-lifecycle result only.

## Read order

Read these files first, in this order:

1. `docs/agent-context/CURRENT_STATUS.md`
2. `docs/agent-context/handoffs/2026-08-09-workspace-freeze-b3-a.md`
3. This handoff
4. The evidence paths listed below

Use the current status file for project history, but use the immutable
evidence files for numerical conclusions. Do not silently promote historical
or synthetic evidence.

## Global constraints

- Keep `VERIFIED`, `INFERENCE`, and `INSUFFICIENT EVIDENCE` separate.
- Preserve all raw evidence. Never overwrite a prior report or session.
- Reuse existing parser, session, transport, and report interfaces. Do not
  create a second TCP client, AA55 parser, heartbeat sender, ACK registry,
  STOP lifecycle, or experiment-storage format.
- `m1..m4` are command telemetry. They are not measured wheel speed or RPM.
- The MPU6050 is an observed data source only. Do not connect it to PID,
  motor output, turn decisions, or safety logic in this handoff.
- Do not introduce Scheme C, nRF24L01, encoders, YOLO, EKF, high-speed
  control changes, PCB changes, or hardware redesign.
- Do not lower the 1080p requirement or bypass calibration and observation
  gates.
- If a real capture becomes necessary, stop and report the exact missing
  evidence. Wait for a new explicit user authorization.

## Latest ground telemetry run

Evidence directory:

`simulation/digital_twin/logs/v1_ground_shakedown_260809224324662`

Canonical command that produced it:

```text
py -3.11 tools\shakedown_toolchain\ground_shakedown.py --host 192.168.110.236 --port 8888 --duration 3 --run-kind ground --out-root simulation\digital_twin\logs --execute
```

Freshly verified facts:

- `run_id=g260809224324662`, `run_kind=ground`, `verdict=SHAKEDOWN_PASS`.
- `fw_build_id=3`, schema `1`.
- Five bounded parameter updates returned `APPLIED/APPLIED`.
- START/RUNNING and STOP/STOPPED were confirmed.
- Rollback was requested, stop was confirmed, and quiescence was proven.
- The report contains 89 decoded telemetry frames.
- Camera input evidence is `EMEET SmartCam C960`, `MJPG`, `1920x1080`,
  `30 fps`; the retained video was independently counted at 137 frames.
- `imu_init_status=0` in all known telemetry records.
- `imu_validity` was `0x1F` in some records and `0x0F` in others. Therefore
  initialization is observed as successful, but continuous full validity is
  not established; the report's IMU verdict is `FAIL`.
- Three sampled video frames show a change in vehicle position. This is
  visual motion evidence only, not a speed or RPM measurement.

Files to inspect without modifying:

- `shakedown_report.json`
- `raw_io.json`
- `camera_ffmpeg.log`
- `camera.mkv`

## Retained B3 observation evidence

The main 1080p synchronized capture is:

`simulation/digital_twin/data/product/sessions/v1_b/c260809100608075`

Its stored observation report is:

`docs/evidence/v1_b3_observation_gate_20260809_1080p_c260809100608075/report.json`

Verified report values:

- Sync gate: `PASS`; observation gate: `FAIL`.
- 166 camera records, 90 pose records, 90 detections, detection ratio
  `54.2168%`.
- 76 `candidates_rejected` frames.
- Maximum pose gap `34.946622` frame periods.
- Detector processing p95 `75.541850 ms`, over the 33.333333 ms frame budget.
- The capture was actually 1080p according to the session evidence; this is
  not a valid reason to downgrade to 720p.

Two later retained observation reports must be treated as separate evidence,
not as an automatic improvement:

- `c260809101540981`: 140 camera records, 68 poses, detection ratio
  `48.5714%`, 72 rejected frames, maximum gap `14.522472` frame periods,
  processing p95 `91.179740 ms`, sync gate `PASS`, observation gate `FAIL`.
- `c260809102554685`: 223 camera records, 205 poses, detection ratio
  `91.9283%`, 18 rejected frames, maximum gap `7.537272` frame periods,
  processing p95 `67.960160 ms`, sync gate `FAIL`, overall evidence status
  `INSUFFICIENT_EVIDENCE`.

Their evidence reports are under:

```text
docs/evidence/v1_b3_observation_gate_20260809_1080p_c260809101540981/report.json
docs/evidence/v1_b3_observation_gate_20260809_1080p_c260809102554685/report.json
```

## Required offline work

### Task 1: Audit the latest ground run

Use the existing JSON and video artifacts to produce a small machine-readable
analysis under:

`docs/evidence/v1_b3_ground_telemetry_20260809_g260809224324662/report.json`

The analysis must record at least:

- run ID, firmware build ID, schema, requested duration;
- parameter ACK count and outcomes;
- START/RUNNING, STOP/STOPPED, rollback, cleanup, and quiescence;
- telemetry frame count, raw RX/TX event counts, parser/protocol errors;
- camera device, source codec, resolution, FPS, and frame count;
- IMU initialization values and validity values;
- an explicit statement that no measured wheel speed exists.

Acceptance for Task 1:

- The new report agrees with the immutable `shakedown_report.json` and
  `raw_io.json`.
- It does not call `SHAKEDOWN_PASS` a B3 pass.
- It labels physical motion as visual evidence only and labels wheel speed as
  `INSUFFICIENT EVIDENCE`.
- Existing Python tests remain unchanged and no hardware resource is opened.

### Task 2: Replay and compare the B3 observation reports

Reuse the existing offline entrypoint:

`tools/camera_toolchain/analyze_b3_observation.py`

For each retained session, write replay output to a new evidence path and
never overwrite the stored report. Example:

```text
py -3.11 tools\camera_toolchain\analyze_b3_observation.py --session-dir simulation\digital_twin\data\product\sessions\v1_b\c260809100608075 --output docs\evidence\v1_b3_observation_gate_20260809_1080p_c260809100608075\replay_report.json --source REAL_SYNC
```

Repeat the same replay for `c260809101540981` and
`c260809102554685`, changing only the session and output paths.

Inspect, but do not alter:

- `failure_frame_summary.json`
- `frame_index.jsonl`
- `failed_frames/`
- `camera_motion.jsonl`
- `motion_evidence.json`
- `sync_report.json`

Acceptance for Task 2:

- Replay arithmetic matches each stored report, or any mismatch is explained
  by a specific parser/version difference and remains `INSUFFICIENT EVIDENCE`.
- Rejected frames are categorized using actual retained thumbnails and
  diagnostics. Do not infer "algorithm too strict" solely from the reason
  string.
- The comparison keeps detection ratio, longest pose gap, processing p95,
  sync gate, and evidence status as separate columns.
- No detector threshold, resolution, calibration, firmware, or control change
  is bundled into this analysis.

### Task 3: Decide whether a minimal offline fix is justified

Only if Task 2 proves a deterministic software defect, make one constrained
offline change inside the existing observation boundary. Before changing
code:

1. Write a focused regression test that reproduces the defect.
2. Run it and record the failing result.
3. Apply the smallest compatible fix.
4. Run the focused test, the observation-gate tests, and the relevant full
   regression.

If the evidence only shows poor visibility, motion blur, calibration mismatch,
or insufficient real samples, do not change thresholds or invent a new
detector. Report the cause as `INFERENCE` or `INSUFFICIENT EVIDENCE` and stop.

Acceptance for Task 3:

- Any code change has a focused regression and a clear before/after metric.
- Existing protocol, camera mode, calibration identity, and safety behavior
  remain unchanged.
- No hardware readiness or B3 completion claim is made from offline output.

## Stop and hand back to Codex

Stop after the offline analysis and hand back:

- changed files and why each changed;
- exact commands and exit codes;
- evidence report paths;
- `VERIFIED`, `INFERENCE`, and `INSUFFICIENT EVIDENCE` findings;
- whether a real test is required and the exact authorization boundary;
- any unresolved ambiguity.

Do not flash, connect, start, stop, reset, or control the car in this task.
