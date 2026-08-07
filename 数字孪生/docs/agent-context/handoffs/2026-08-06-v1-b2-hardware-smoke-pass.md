# V1-B B2 Hardware Smoke Pass

Task/Gate: V1-B B2 bounded hardware smoke  
Status: `SHAKEDOWN_PASS` for the smoke boundary only  
Date: 2026-08-06 Asia/Shanghai

## Authorized run

- The car was re-powered, the ST-Link was removed, and the car remained in
  the previously authorized elevated-wheel condition.
- Canonical command:
  `py -3.11 tools/shakedown_toolchain/ground_shakedown.py --host 192.168.110.236 --port 8888 --duration 0.5 --run-kind elevated-wheels --out-root simulation/digital_twin/logs --execute`
- Evidence directory:
  `simulation/digital_twin/logs/v1_ground_shakedown_260806155533430`
- Run ID: `e260806155533430`.
- Tool output: `VERDICT: SHAKEDOWN_PASS`.

## VERIFIED

- Overall report verdict: `SHAKEDOWN_PASS`.
- Control verdict: `PASS`; no primary failure, parser error, protocol
  anomaly, or cleanup error.
- Firmware identity: `fw_build_id=1`, `fw_schema_version=1`.
- Five speed updates `580, 480, 380, 280, 260`: all correlated
  `APPLIED/APPLIED`.
- START/RUNNING and terminal STOP/STOPPED were confirmed for the same
  campaign and run; host heartbeat completed with no timeout.
- Socket connect and close each completed once; quiescence was proven; raw
  I/O was published.
- Camera verdict: `PASS`; FFprobe reports MJPEG, `1280x720`, `30/1` FPS, and
  the same FFmpeg DirectShow input log reports source `MJPG`.
- Required artifacts exist: `camera.mkv`, `camera_ffmpeg.log`, `raw_io.json`,
  and `shakedown_report.json`.
- Final report: `stop_confirmed=true`, `forced_termination=false`, and
  `cut_power_warning=false`.

## Evidence qualifications

- The Matroska output tag is `[0][0][0][0]`; the validator classifies this as
  `CONTAINER_UNSPECIFIED` and relies on the same-run DirectShow input log for
  the source FourCC. This is a camera evidence-contract decision, not proof
  of a different codec.
- `imu_evidence_status=UNVERIFIED_NO_VALIDITY_BIT`; no IMU validity claim is
  made.
- The health snapshot contains `health_dropped=62` and `health_failed=0`.
  This counter is retained for later observability work and is not interpreted
  as a line-following or speed result.

## INFERENCE

The existing ESP-01S transport, runtime protocol, bounded parameter update
path, telemetry parsing, camera recorder, and STOP cleanup completed one real
hardware session through the canonical `ground_shakedown.py` entrypoint.

## INSUFFICIENT EVIDENCE

- No actual wheel speed, displacement, or ground contact was measured.
- No no-line-loss or high-speed sharp-turn result was measured.
- No A/B/C candidate comparison, digital-twin calibration result, or
  AI-generated algorithm/PCB improvement was demonstrated.

## Boundary

B2 bounded hardware Smoke is complete at `SHAKEDOWN_PASS`. Do not repeat the
Smoke, run the car on the ground, or enter B3 automatically. Any next device
action requires a separate experiment plan and fresh explicit authorization.
