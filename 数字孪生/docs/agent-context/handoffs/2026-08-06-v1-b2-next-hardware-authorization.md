# V1-B B2 Next Hardware Authorization Handoff

Task/Gate: V1-B B2, next hardware rerun authorization boundary
Status: BLOCKED_PENDING_USER_AUTHORIZATION
Date: 2026-08-06 Asia/Shanghai

The offline B2 evidence-contract remediation is complete and independently
reviewed. No hardware action was performed by that remediation.

## Verified offline preparation

- canonical entrypoint remains `tools/shakedown_toolchain/ground_shakedown.py`;
- no parallel TCP client, protocol, parser, ACK registry, heartbeat loop, or
  capture lifecycle was added;
- camera FourCC/tag evidence is structured from ffprobe and fail-closed when
  missing or wrong;
- socket connect/close evidence is structured and participates in the final
  verdict;
- wrapper and canonical cleanup paths preserve close evidence across ordinary
  and `BaseException` failures;
- `simulation/digital_twin/tests/test_ground_shakedown.py`: `101 passed`;
- `simulation/digital_twin/tests`: `649 passed, 5 skipped`;
- `py -3.11 -m compileall -q tools simulation/digital_twin`: exit `0`.

## Current real evidence boundary

The latest real B2 evidence is still
`2026-08-06-v1-b2-hardware-smoke-rerun-1412-insufficient-evidence.md` and
remains `INSUFFICIENT_EVIDENCE` because:

- no live firmware image/hash mapping was established;
- the previous report did not have the new structured socket/FourCC fields;
- no independent physical wheel-motion measurement was collected.

The current local canonical build is:

- project: `firmware/stm32_line_follower/project.uvprojx`;
- target: `Target 1`;
- artifact: `firmware/stm32_line_follower/Objects/Project.axf`;
- artifact SHA-256:
  `5E409FA4B5080E0AEA9F44E08CE51F4CD969753CF93E671B6CB74FA8498FBB7A`;
- runtime source identity: `fw_build_id=1`, `fw_schema_version=1`.

This local build is not evidence that the current car already runs the AXF.

## What requires a new user authorization

An ordinary B2 rerun would authorize only the following bounded actions:

1. Open and validate the C960 at the actual `MJPG / 1280x720 / 30 fps` mode.
2. Connect to the already confirmed ESP-01S TCP endpoint.
3. Keep all four wheels elevated, keep the user beside power/emergency stop,
   and use the existing ramp `680 -> 580 -> 480 -> 380 -> 280 -> 260`.
4. Send one short `START`, run for at most `0.5 s`, then send one `STOP`.
5. Preserve raw I/O, ACK/status, socket lifecycle, camera cleanup, hashes, and
   the final `STOPPED/STOP` evidence.

The ordinary B2 prompt does not authorize firmware flashing or reset. If the
user wants live identity closed by flashing the exact AXF above, that must be
authorized separately, including the reset consequence. Without that separate
authorization or an independent live-image readback, a future no-flash Smoke
must keep the firmware-identity conclusion at `INSUFFICIENT_EVIDENCE`.

## Hardware actions performed for this handoff

- camera connected: none;
- TCP connected: none;
- flashed: none;
- reset: none;
- START/STOP/P/H sent: none;
- physical motion: none.

## Stop boundary

Do not connect, flash, reset, send control frames, or run another camera
session until the user provides a new explicit authorization. B3 calibration,
holdout collection, and any performance experiment are outside this boundary.
