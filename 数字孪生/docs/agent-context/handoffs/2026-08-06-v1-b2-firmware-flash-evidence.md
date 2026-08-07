# V1-B B2 Firmware Flash Evidence

Task/Gate: V1-B B2, canonical firmware image programming
Status: FLASH_VERIFIED_PENDING_B2_SMOKE
Date: 2026-08-06 Asia/Shanghai

## Authorization

The user explicitly authorized flashing after confirming that the ST-Link was
connected. This authorization covered the Keil download action only. It did
not authorize a camera session, ESP TCP control session, START/STOP frames, or
physical motion.

## VERIFIED

- Windows enumerated the connected probe as `STM32 STLink`
  (`VID_0483`, `PID_3748`).
- Keil 5 executable: `F:\keil\UV4\UV4.exe`.
- Project: `firmware/stm32_line_follower/project.uvprojx`.
- Target: `Target 1`.
- Device selected by the project: `STM32F103C8`.
- Flash artifact:
  `firmware/stm32_line_follower/Objects/Project.axf`.
- Artifact SHA-256:
  `5E409FA4B5080E0AEA9F44E08CE51F4CD969753CF93E671B6CB74FA8498FBB7A`.
- Keil flash log:
  `.embeddedskills/build/b2-fw-identity/project-Target 1-flash.log`.
- Keil log records: `Erase Done`, `Programming Done`, `Verify OK`,
  `Application running`, `Flash Load finished`, and `errorlevel=0`.
- The artifact hash was rechecked after the flash and was unchanged.

## INFERENCE

- The target was left running the just-programmed application, because the
  programmer log reports `Application running` after `Verify OK`.
- The running application is expected to expose the recorded
  `fw_build_id=1` and schema `1`, but this has not yet been independently
  observed through the runtime control/telemetry path.

## INSUFFICIENT EVIDENCE

- No post-flash B2 camera/ESP Smoke has been run in this authorization.
- No post-flash `START`/`STOP`, heartbeat, ACK, socket lifecycle, or cleanup
  evidence has been collected.
- No independent physical wheel-motion measurement exists.
- No real-car B/C comparison or high-speed sharp-turn improvement has been
  demonstrated.

## Next boundary

The next action is the existing bounded B2 Smoke through
`tools/shakedown_toolchain/ground_shakedown.py`, with the fixed ramp and
duration in the active B2 prompt. Obtain explicit authorization for the
camera/TCP/control-frame session before running it. Do not enter B3 or claim a
real-twin readiness result from the flash alone.
