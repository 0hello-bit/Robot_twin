# MPU6050 identity diagnostic and pre-flash plan

Date: 2026-08-07 Asia/Shanghai
Boundary: offline implementation and Keil build only. No flash, reset,
START/STOP, serial command, or motor motion is part of this plan.

## Problem statement

The last real run produced `imu_init_status=0x21` on all 12 telemetry frames.
This verifies a WHO_AM_I mismatch after a completed read transaction, but the
old telemetry did not preserve the returned ID byte. The physical cause is
therefore not yet identified. A different sensor, a clone, a bad bus read,
and an address or wiring problem remain separate hypotheses.

## Minimal implementation

- Read WHO_AM_I before any reset or configuration write.
- Clear the observed ID at the start of every initialization attempt. Preserve
  the completed WHO_AM_I value for the final attempt through
  `MPU6050_GetObservedID()`; report zero when that final read transaction does
  not complete, so retries cannot be mixed into one diagnostic snapshot.
- Preserve the existing fixed address, fail-closed validity gate, retry limit,
  register configuration, yaw math, line-following algorithm, motor output,
  safety behavior, and 26-byte telemetry frame.
- Reuse the existing ESP/CIPSEND path for one additive type `0x7D` frame:
  `AA 55 7D 04 [observed_id init_status validity_flags reserved] checksum`.
  Keep the frame pending until the existing CIPSEND transaction returns
  `SEND OK`; use a distinct TX tag so the old `0x7E` diagnostic cannot clear
  the IMU pending state.
- Decode the frame in the existing `FrameParser`; do not add a second parser,
  socket, heartbeat sender, ACK registry, or capture lifecycle.
- Set `FW_BUILD_ID=3` so the diagnostic image cannot be confused with the
  previously flashed build 2 image.

## Offline acceptance

- [x] Host C regression for raw ID retention and identity-before-write order.
- [x] Host C encoder and checksum contract for type `0x7D`.
- [x] Python parser contract for raw ID, init status, and validity flags.
- [x] Existing Python regression: 676 passed, 5 skipped.
- [x] Python compileall and `git diff --check`.
- [x] Prior Host C MPU, telemetry batch, CIPSEND, and health-frame tests;
      the pre-existing IMU diagnostic executable predates the final delivery
      predicate assertions and is not reused as current evidence.
- [ ] Current Host C runtime execution for the changed test source (no host C
      compiler is available in the current environment).
- [x] ARMCC C99 source compilation for the updated IMU diagnostic and MPU
      validity tests.
- [x] Keil `Target 1` rebuild with 0 errors and 0 warnings.
- [x] AXF SHA-256 recorded in the handoff below.

## Hardware decision gate

After a fresh explicit authorization, flash the exact AXF and passively attach
the existing TCP observation path while the car remains motion-inhibited.
Inspect the one `0x7D` frame and the health frame identity before any START:

| Observed diagnostic result | Interpretation | Next action |
| --- | --- | --- |
| `id=0x68`, `status=0x00` | Identity and init sequence passed | Run a separate stationary validity gate |
| `id=0x70` or `0x71`, `status=0x21` | Stable alternate sensor identity | Do not auto-accept; add an explicitly tested compatible-model path |
| `id=0x00`, `status=0x20` | WHO_AM_I transaction did not complete | Inspect power, common ground, SDA/SCL, pull-ups, and bus timing |
| other stable ID, `status=0x21` | Unknown responder or clone | Confirm module marking and register compatibility before changes |
| changing IDs across boots/reads | Unstable bus or electrical condition | Capture wiring/power/timing evidence before software compatibility work |

The diagnostic frame is evidence about the responder, not evidence that IMU
pose, synchronization, or vehicle performance is valid. Ground motion remains
blocked until the existing validity and safety gates pass.
