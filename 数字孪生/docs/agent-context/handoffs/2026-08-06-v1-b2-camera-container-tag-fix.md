# V1-B B2 Camera Container Tag Fix

Task/Gate: V1-B B2, repair the camera evidence boundary after a real Smoke
Status: OFFLINE_FIX_VERIFIED_PENDING_FRESH_HARDWARE_AUTHORIZATION
Date: 2026-08-06 Asia/Shanghai

## Original hardware run

- Command:
  `py -3.11 tools/shakedown_toolchain/ground_shakedown.py --host 192.168.110.236 --port 8888 --duration 0.5 --run-kind elevated-wheels --out-root simulation/digital_twin/logs --execute`
- Evidence directory:
  `simulation/digital_twin/logs/v1_ground_shakedown_260806154311594`
- Run ID: `e260806154311594`.
- Original verdict: `SHAKEDOWN_FAIL`.
- The car was elevated, powered, and the ST-Link was removed.
- The run sent one bounded START and one terminal STOP; the car was powered
  off after STOPPED and cleanup were confirmed.

## VERIFIED from the original raw evidence

- Control verdict: `PASS`.
- `fw_build_id=1`, `fw_schema_version=1`.
- All five speed updates `580, 480, 380, 280, 260` returned correlated
  `APPLIED/APPLIED` ACKs.
- START/RUNNING and STOP/STOPPED were confirmed for the same campaign and run.
- Heartbeat succeeded with zero timeout count.
- Socket connect and close each completed once; raw I/O was published and
  quiescence was proven.
- FFmpeg DirectShow input log recorded `MJPG / 0x47504A4D`, `1280x720`, and
  `30 fps` for `EMEET SmartCam C960`.
- The recorded video FFprobe result was MJPEG, `1280x720`, and `30/1` FPS.

## Root cause

The recorder stores the copied MJPEG stream in Matroska as `camera.mkv`.
Matroska does not preserve this stream's FourCC in the FFprobe output: the
output reports `codec_tag_string=[0][0][0][0]` and `codec_tag=0x0000` even
though the FFmpeg input and output log lines identify `MJPG / 0x47504A4D`.
Treating that container-level absence as a wrong camera tag caused a false
camera failure.

## Fix

- `tools/shakedown_toolchain/ground_shakedown.py` now classifies the Matroska
  zero tag as `CONTAINER_UNSPECIFIED`, not as a valid camera tag.
- When that condition occurs, it requires a separately parsed DirectShow
  input stream line from the same `camera_ffmpeg.log` to prove `mjpeg` and
  `MJPG / 0x47504A4D`.
- It continues to fail closed for missing input evidence, wrong input tags,
  wrong output tags, wrong codec, wrong dimensions, or wrong FPS.
- `simulation/digital_twin/tests/test_ground_shakedown.py` adds a regression
  test for this exact Matroska/DirectShow boundary.

## OFFLINE VERIFICATION

- New regression: `1 passed`.
- Camera regression subset: `20 passed`.
- Full B2 test file: `102 passed`.
- Full `simulation/digital_twin/tests`: `650 passed, 5 skipped`.
- Python 3.11 compileall for `tools` and `simulation/digital_twin`: exit `0`.
- Offline re-evaluation of the original camera artifacts now returns
  `camera_verdict=PASS`, with input FourCC evidence `PASS` and no camera
  errors. This re-evaluation did not connect to hardware or send control
  frames and does not rewrite the original report.

## INSUFFICIENT EVIDENCE

- The original overall hardware report remains `SHAKEDOWN_FAIL` and is
  immutable evidence of the run under the old validator.
- No new hardware run has tested the repaired recorder.
- No physical wheel-motion measurement, ground run, B/C comparison, or high-
  speed sharp-turn improvement has been demonstrated.

## Next boundary

Obtain fresh explicit authorization before running the same bounded B2 Smoke
again with the repaired recorder. Do not reuse the original overall verdict
as a pass, do not enter B3, and do not run a ground or performance experiment.
