# Workspace Freeze and B3-A Hardware Handoff

Date: 2026-08-09
Workspace: `数字孪生`
Branch: `master`

## Scope

This checkpoint freezes the current offline B3-A transport work and the
1080p camera-observation work. It is a versioning and handoff boundary, not a
hardware authorization.

## Included in the checkpoint

- Existing AA55 protocol, P/R/A/S control path, heartbeat, safety stop, and
  session storage remain the canonical interfaces.
- Transport A separates pending and in-flight telemetry ownership and retains
  the in-flight prefix for retry until `SEND OK`.
- Transport C is an offline transparent-TCP state machine only. It is not
  connected to runtime code and is not a hardware candidate.
- Camera capture uses the configured 1080p profile and retains synchronized
  session evidence plus failure-frame metadata.
- Reproducible source, tests, JSON controls/reports, plans, specifications,
  and handoffs are eligible for Git.

## Local-only artifacts

Raw calibration video and PNG frame captures remain in the canonical workspace
for later inspection but are excluded from Git because the current dated set
is more than 450 MiB. The JSON controls and reports remain versioned so that
the calibration decisions are inspectable without putting large media into the
rollback checkpoint.

The tracked Keil `uvoptx` files are included in the checkpoint as the current
project state because one contains the newly registered source entries used by
the offline build. Untracked per-user `uvguix.*` files are ignored as IDE UI
state.

Generated root `.obj` files were moved, without deletion, to:

`archive/generated_workspace_20260809/project_root_objects/`

## Evidence boundary

### VERIFIED

- The offline A/C handoff records Python regression `755 passed, 5 skipped`,
  Python compileall success, Host C replay success, and a Keil Target 1 build
  with `0 Error(s), 0 Warning(s)`.
- The fresh offline A candidate rebuilt at `2026-08-09 21:18:57` is
  `firmware/stm32_line_follower/Objects/Project.axf` with SHA-256
  `1161FA2EEE9C86A3D2409120125AD0BC6D7A7BE237144849564C8A868130E379`.
  Keil Target 1 rebuilt with `0 Error(s), 0 Warning(s)`; the build reported
  Code `26044`, RO-data `460`, RW-data `160`, and ZI-data `4240`.
- The real 1080p capture `c260809100608075` passed its synchronization gate:
  166 camera records, 260 telemetry records, 100% coverage, and p95 camera /
  telemetry difference `15.294889 ms`.
- The same real capture failed the independent observation gate: 90/166
  AprilTag detections (`54.2168%`), 76 rejected frames, maximum pose gap
  `34.946622` frame periods, and detector processing p95 `75.541850 ms`.
- The same run reported `imu_init_status=0` and `imu_validity=0x0F` for all
  telemetry records. This is runtime validity evidence only; it is not yaw
  calibration or a control-benefit result.

### INFERENCE

- A is the correct first hardware candidate because it changes transport
  delivery ownership while preserving the existing application protocol and
  safety boundaries.
- The observation bottleneck is not explained by a global 720p configuration
  mistake; the run was actually `1920x1080/MJPG/30`. The rejected candidates
  still require image inspection before any detector change.

### INSUFFICIENT EVIDENCE

- No real-car delivery after the current A source change.
- No independently verified live firmware identity for the current artifact.
- No measured wheel speed, displacement, formal 1080p ground homography,
  continuous AprilTag observation, or complete B3 pass.
- No evidence that camera/IMU fusion improves control.
- No AI-generated algorithm or hardware change has been validated on the car.

## Next authorized interface

After the fresh offline gate and Git checkpoint are verified, request explicit
ST-Link authorization to flash only scheme A. Then use the existing canonical
`ground_shakedown.py --execute` entrypoint for a bounded run. Keep scheme C,
nRF24L01, encoder integration, detector-threshold changes, and control changes
out of that first hardware comparison.
