# B3 real A/B connectivity block

Date: 2026-08-10
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`

## Boundary

The offline-qualified `fast_recovery_wide` candidate was prepared for one
explicit real A/B. The first production baseline attempt did not reach START:
the camera opened and confirmed 1920x1080, but the TCP connection timed out.
No firmware was flashed, no START/STOP command was sent, and no motor motion
was requested by this failed attempt.

## Evidence

- Run directory:
  `simulation/digital_twin/logs/c260810113550890`
- `sync_report.json` outcome: `connect_failed`
- `n_poses=0`, `n_telemetry=0`
- Video evidence: disabled for this failed pre-START path; no new video was
  created.
- Target: `192.168.110.236:8888`
- Host WLAN IPv4: `192.168.124.38/24`
- Route table: no `192.168.110.0/24` route
- TCP check: `0/1` reachable, timeout
- `192.168.124.0/24:8888` bounded scan: zero open ports
- Neighbor state for `192.168.110.236`: `Unreachable`

## Classification

- VERIFIED: this attempt failed before the application session and produced no
  physical-motion or observation evidence.
- INFERENCE: the PC is currently not connected to the Wi-Fi/LAN containing the
  ESP address, or the ESP/car is powered off; the exact physical cause is not
  distinguishable from host-side evidence alone.
- INSUFFICIENT EVIDENCE: baseline A behavior, candidate B behavior, and B3
  real observation status.

## Code boundary now available

`capture_sync_run.py` keeps production as the default. A candidate run must
explicitly select both:

```text
--recovery-policy fast_recovery_wide
--allow-experimental-recovery
```

The selected recovery policy and detector parameters are written into the
successful synchronized report. The exact same candidate remains qualified
offline by the r3 replay report:
`docs/evidence/v1_b3_fast_recovery_wide_replay_20260810_r3/report.json`.

## Next interface

Do not retry capture while the target is unreachable. Reconnect the PC to the
car's Wi-Fi/LAN or provide the current ESP IP, then rerun one bounded baseline
A and one candidate B under the same track and camera conditions. If B fails,
retain both runs and return to offline algorithm analysis; do not recollect a
replacement video merely to pass the gate.
