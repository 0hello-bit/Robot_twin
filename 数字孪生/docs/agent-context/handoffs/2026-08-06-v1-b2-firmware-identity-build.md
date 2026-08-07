# V1-B B2 Firmware Identity Build Handoff

Task/Gate: V1-B B2 remediation, firmware identity preparation
Status: INSUFFICIENT_EVIDENCE
Run date: 2026-08-06 Asia/Shanghai

This handoff records an offline build of the canonical STM32 firmware. It does
not prove that the physical car currently runs this image and does not grant
permission to flash, reset, or control hardware.

## Canonical project

- project: `firmware/stm32_line_follower/project.uvprojx`
- target: `Target 1`
- source of runtime identity constants:
  `firmware/stm32_line_follower/User/health_frame.h`
- `HEALTH_FRAME_FW_SCHEMA_VERSION`: `1`
- `FW_BUILD_ID`: `1`

## Build evidence

Command:

```text
py -3.11 C:\Users\24668\.codex\skills\keil\scripts\keil_build.py build --uv4 F:\keil\UV4\UV4.exe --project firmware\stm32_line_follower\project.uvprojx --target "Target 1" --log-dir .embeddedskills\build\b2-fw-identity --json
```

Result:

- exit code: `0`
- build summary: `errors=0 warnings=0`
- artifact: `firmware/stm32_line_follower/Objects/Project.axf`
- artifact SHA-256: `5E409FA4B5080E0AEA9F44E08CE51F4CD969753CF93E671B6CB74FA8498FBB7A`
- project SHA-256: `5BD666BB6A83707E404B47D0CF826FE23572DA3405C679AA8ADB7E40C9DD7116`
- `health_frame.h` SHA-256: `2FEFFCE31DD7F763AE8908E785DCC4EE0E35E4BB5DB2834246E9F85F3D46F47B`
- build log: `.embeddedskills/build/b2-fw-identity/project-Target 1-build.log`
- build log SHA-256: `E768C2DB27C89011AEA89F17B53B602DD39A793E4AAF09EA76D10FDEF0F7133B`
- compiler-reported program size: `Code=23832`, `RO-data=460`, `RW-data=152`, `ZI-data=2936`

## VERIFIED

- The canonical `Target 1` project builds successfully with no compiler or
  linker errors and no warnings.
- The built AXF is tied to the recorded project and health-header hashes in
  this workspace snapshot.
- The runtime identity values reported by the source are `fw_build_id=1` and
  `fw_schema_version=1`.

## INSUFFICIENT EVIDENCE

- No live STM32 image readback or independent in-band identity challenge maps
  the currently powered car to this AXF.
- The previous B2 Smoke was not flashed or reset, so this build must not be
  retroactively labeled as the image used by that run.
- The Keil wrapper reports the AXF as its flash artifact for this project; no
  separate HEX/BIN artifact was produced by this build command.

## INFERENCE

- If a future authorized run first flashes this exact AXF and records the
  flash result, then a same-run health frame with `fw_build_id=1` and schema
  `1` can be correlated to this build, subject to the remaining live evidence
  checks.

## Hardware actions

- connected: NO
- flashed: NO
- reset: NO
- START/STOP/P/H: NONE
- physical motion: NONE

## Next interface

Parent agent must independently review this artifact and the B2 evidence
contract changes. A fresh user authorization is required before any flash,
reset, camera/TCP connection, or B2 rerun.
