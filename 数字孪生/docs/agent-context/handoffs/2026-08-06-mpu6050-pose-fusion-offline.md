# MPU6050 pose fusion offline handoff

Date: 2026-08-06 Asia/Shanghai
Task: offline completion of the camera-anchored MPU6050 pose-fusion path
Status: OFFLINE VERIFIED; AXF FLASH VERIFIED; IMU STATIC GATE PENDING

## Scope

This task adds an additive, offline-only fusion evidence path. The camera
remains the global position and yaw anchor. Valid IMU yaw may propagate yaw
through a short camera gap, but the fused result does not feed line-following
control, motor commands, safety stops, or the B3 synchronization verdict.

The existing ESP transport, mixed-stream parser, clock fit, nearest-timestamp
association, capture lifecycle, cleanup, and raw evidence files were reused.
No second TCP client, parser, heartbeat, ACK registry, or capture lifecycle was
created.

## Changes

- tools/camera_toolchain/capture_sync_run.py now passes
  imu_yaw_deg_x100, imu_validity, and imu_validity_known from the existing
  decoder into V1TelemetryFrame, generates fusion records from existing
  ds.sync_frames, and writes additive fusion.jsonl with explicit angle units.
- simulation/digital_twin/tests/test_capture_sync_cleanup.py covers current
  26-byte field preservation, additive artifact output, unit metadata, legacy
  camera-only fallback, and unchanged raw JSONL contents.
- simulation/digital_twin/v1_twin/v1_twin_pose_fusion.py is the pure
  camera-anchored state machine from the preceding task.

## TDD evidence

RED was observed before the Task 4 production change:

- the writer test failed because fusion.jsonl did not exist;
- passing fusion_records raised an unexpected-keyword error;
- the legacy path had no build_fusion_records API.

A separate RED was observed for the telemetry callback before its field
forwarding change: a valid 26-byte frame became
imu_yaw_deg_x100=None, imu_validity=0, and
imu_validity_known=False. The minimal forwarding change then made the test
pass.

## Verification

Focused capture/fusion/schema tests:

~~~
py -3.11 -m pytest -q simulation/digital_twin/tests/test_capture_sync_cleanup.py simulation/digital_twin/tests/test_v1_twin_capture.py
-> 36 passed

py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_pose_fusion.py simulation/digital_twin/tests/test_capture_sync_cleanup.py simulation/digital_twin/tests/test_v1_twin_capture.py simulation/digital_twin/tests/test_v1_twin_schema.py simulation/digital_twin/tests/test_v1_twin_dataset.py
-> 88 passed
~~~

Full current Python regression, excluding the known archived legacy tree that
causes old numpy binary collection conflicts and duplicate module imports:

~~~
py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
-> 669 passed, 5 skipped
py -3.11 -m compileall -q simulation/digital_twin tools
-> exit 0
git diff --check
-> exit 0
~~~

Fresh Host C builds used MSVC
D:\vs2022\VC\Tools\MSVC\14.42.34433\bin\Hostx64\x64\cl.exe with
/nologo /TC /W4 /WX /source-charset:utf-8. Outputs are under
数字孪生/.embeddedskills/build/mpu6050-pose-fusion-offline/hostc/:

- test_telemetry_batch.c + User/telemetry_batch.c: compile exit 0, run
  exit 0, telemetry_batch: all tests passed.
- test_cipsend_tx.c + User/cipsend_tx.c +
  User/cipsend_transaction.c + User/send_response_parser.c: compile exit 0,
  run exit 0, PASS test_cipsend_tx.
- test_mpu6050_validity.c + Hardware/mpu6050.c with the existing
  tests/mpu_stubs include boundary: compile exit 0, run exit 0,
  PASS test_mpu6050_validity.

Keil target enumeration used the canonical project:

~~~
py -3.11 C:\Users\24668\.codex\skills\keil\scripts\keil_project.py targets --project 数字孪生\firmware\stm32_line_follower\project.uvprojx --json
-> Target 1

py -3.11 C:\Users\24668\.codex\skills\keil\scripts\keil_build.py rebuild --uv4 F:\keil\UV4\UV4.exe --project 数字孪生\firmware\stm32_line_follower\project.uvprojx --target "Target 1" --log-dir 数字孪生\.embeddedskills\build\mpu6050-pose-fusion-offline\keil --json
-> exit 0; 0 Error(s), 0 Warning(s)
~~~

The build log reports Code=24044 RO-data=460 RW-data=156 ZI-data=3052.
The AXF is
数字孪生/firmware/stm32_line_follower/Objects/Project.axf with SHA-256
2AF108A40D2C008F4D945804541DBA342F86CBE720576DD17C65F30F527071E4.

Before explicit user authorization, no flash, reset, START, STOP, serial,
ST-Link, camera, or network action was performed for this handoff. After the
user connected ST-Link and authorized flashing, the exact AXF above was
flashed through Keil Target 1.

Flash log:

数字孪生/.embeddedskills/build/mpu6050-pose-fusion-offline/keil/project-Target 1-flash.log

The log contains `Erase Done`, `Programming Done`, `Verify OK`, and
`Application running ...` at 21:01:16. The AXF hash remains
`2AF108A40D2C008F4D945804541DBA342F86CBE720576DD17C65F30F527071E4`.
This verifies programming and memory verification only; it does not verify
runtime MPU initialization, validity flags, axis sign, or vehicle behavior.

## Evidence boundary

### VERIFIED

- Versioned 24-byte/26-byte telemetry decoding and model fields are covered by
  the current Python tests.
- Firmware validity flags, 26-byte telemetry payload, five-frame batch, and
  CIPSEND capacity contracts pass Host C tests and Keil build.
- Pure camera-anchored fusion math and explicit fallback states pass offline
  tests.
- The existing capture path emits additive fusion.jsonl without replacing
  raw pose/telemetry files or changing the existing B3 gate code.
- The exact current AXF was flashed through Keil Target 1 with ST-Link, and
  the flash log reports programming and memory verification success.
- Current offline Python, Host C, and Keil results are recorded above.

### INFERENCE

- The artifact path is ready to expose real IMU/camera disagreement and
  short-gap yaw propagation once a valid synchronized run exists.
- It may help diagnose pose continuity, but no performance or synchronization
  improvement follows from the offline result alone.

### INSUFFICIENT EVIDENCE

- Physical MPU6050 wiring, WHO_AM_I success, initialization, bias quality, axis
  sign, scale, drift, timing, and validity flags on the actual car.
- A real synchronized capture containing valid camera and current 26-byte IMU
  records.
- Any claim that fusion improves line following, prevents line loss, or makes
  high-speed sharp turns faster.
- Any B3 pass, calibration fit, holdout result, or real-world AI iteration.

## Next interface

Stop at the hardware gate. The next run requires fresh explicit user
authorization to:

1. keep the car stationary and verify current telemetry reports known validity
   with INIT, BIAS, READ, and UPDATED set and DT_CLAMPED clear;
2. perform a bounded elevated-wheel sign/scale observation before any ground
   run;
3. place the car and camera in valid capture geometry, then run one synchronized
   collection and inspect raw plus fusion.jsonl evidence.

The prior B3 line-loss/coverage failure remains a failed real run and must not
be promoted to calibration or holdout evidence by this offline task.
