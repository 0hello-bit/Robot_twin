# V1-B3 Transport A/C Final Handoff

Date: 2026-08-09
Workspace: `数字孪生`

## Offline result

- A is an offline flash candidate. It preserves the existing AA55 protocol,
  P/R/A/S control path, heartbeat, safety stop, and session storage boundary.
- Pending telemetry and the current CIPSEND payload are now separate. Only
  `SEND OK` commits the in-flight prefix. Errors, busy, and timeouts retain
  it for same-connection retry. CLOSED and connection-generation changes
  clear both queues.
- A full pending queue protects the in-flight prefix and drops only the
  oldest not-yet-in-flight telemetry frame.
- C is an offline transparent-TCP state machine only. It records capability
  inputs, enforces the guarded `+++` exit rule, and requests local stop on
  link loss. It is not connected to runtime code and sends no AT commands.

## Verification

- Python: `755 passed, 5 skipped`.
- Python compileall for `simulation/digital_twin` and `tools`: pass.
- `git diff --check`: pass; only existing LF/CRLF warnings were reported by
  Git.
- Host C: telemetry batch/delivery, transparent session, CIPSEND transaction
  and TX, retry queue, transport generation, and coordinator tests compiled
  with the production source files and passed.
- Keil Target 1 rebuild: `0 Error(s), 0 Warning(s)`.
- Build log:
  `.embeddedskills/build/2026-08-09-v1-b3-transport-a-c-final/project-Target 1-rebuild.log`
- Offline artifact:
  `firmware/stm32_line_follower/Objects/Project.axf`
- SHA-256:
  `53B1CD3F13B56436855FCEA65D75BF6DEB3948EE779D64B7DEEBB17D6D3937C8`

## Evidence boundary

`VERIFIED`: offline ownership rules, capture-window filtering, Host C replay,
Python regression, and Keil build.

`INSUFFICIENT EVIDENCE`: real-car delivery after this source change, live
firmware identity, physical motion, measured wheel speed, clock
synchronization, AprilTag observation quality, B3 gate pass, and ESP module
support for transparent TCP.

## Next interface

Stop here. The recommended next action is a separately authorized flash of A,
then a bounded hardware run using the existing canonical entrypoint. Do not
flash C or implement nRF24L01 in this round. Do not claim B3 pass from this
offline result.
