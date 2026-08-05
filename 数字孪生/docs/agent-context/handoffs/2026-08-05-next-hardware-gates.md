READY_FOR_FRESH_USER_AUTHORIZATION

# Next Hardware Gates

This is an offline-only handoff checklist. It authorizes no device access,
flash, camera use, network access, serial/debugger connection, or motion in
the current session.

## Verified Software Facts

- Accepted production source: `程序/3. 麦轮巡线小车/Hardware/Motor.c`
  - SHA-256: `80DEB484B98C5B3D73D5E1CDC8431DFA830DDFA571B86964222CA84B83D07743`
- Accepted build artifact: `程序/3. 麦轮巡线小车/Objects/Project.axf`
  - SHA-256: `088EFD4E1492CC9FE6075BADD7962EEB7D193E9863CACD2BA53FBDA2457C2351`
- These hashes identify the reviewed software artifacts only. They are not
  hardware proof and do not prove the flashed image, timer clock, wiring,
  direction, wheel motion, telemetry, STOP behavior, or vehicle safety.

## Preconditions Before Any Hardware Session

- Task 1 software acceptance is explicitly recorded as `PASS`.
- Task 2 recorder acceptance is explicitly recorded as `PASS`.
- A fresh, explicit authorization covers this hardware session and its exact
  bounded actions.
- The authorized operator has the accepted AXF above and verifies its SHA-256
  before flashing.

## Pending Hardware Checks

Perform these checks only after all preconditions hold, in this order:

1. Flash only the accepted AXF identified above.
2. Keep all wheels elevated, turn the camera on, and keep the user beside the
   power switch.
3. Set `speed_max=260` with five bounded `P` updates in this exact sequence:
   `680 -> 580 -> 480 -> 380 -> 280 -> 260`. For every update, record a
   correlated acknowledgement with outcome/reason exactly `APPLIED/APPLIED`
   before sending the next update.
4. Send exactly one elevated-wheel `START` for 0.5 seconds. Keep the heartbeat
   interval at 200 ms.
5. Require a final correlated `STOPPED/STOP` status after that run.
6. Review the captured evidence. Only after a separate fresh authorization may
   one 0.5-second ground run be allowed.

## STOP And Cut-Power Response

- Do not automatically retry `START` under any circumstance.
- If any acknowledgement is missing, mismatched, late, or indicates failure,
  do not proceed to the next step; send/confirm `STOP` where the existing
  control protocol remains available.
- Cut motor power immediately if `STOPPED` is not confirmed, motion is
  unexpected, a wheel direction is unsafe, camera evidence is unavailable, or
  the operator directs it.
- After STOP or cut power, preserve the recorder evidence and require a new
  review plus fresh authorization before any further motion attempt.

## Prohibited Until A Later Authorized Session

- No flashing any other artifact.
- No unelevated or ground movement before evidence review and separate fresh
  authorization.
- No repeated or automatic `START` attempt.
- No change to firmware, motor parameters outside the stated bounded `P`
  sequence, control protocol, heartbeat interval, or safety/rollback behavior.
