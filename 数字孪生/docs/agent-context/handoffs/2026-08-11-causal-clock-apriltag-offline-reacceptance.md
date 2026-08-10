# Causal clock and AprilTag offline re-acceptance handoff

Date: 2026-08-11
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED`

This handoff is deliberately hardware-free. No camera device, TCP socket,
ST-Link, firmware flash, or vehicle motion was used in this round.

## Causal clock result

### Root cause

The previous firmware path sampled `mcu_tx_tick_ms` when it started
`AT+CIPSEND`. The actual clock-sync payload could only be written after the
ESP prompt (`>`), so the measured real run contained an approximately
40-48 ms command/prompt interval. That timestamp described command setup, not
payload transmission.

### Offline change

- Added late payload materialization to `cipsend_tx`.
- The clock response is encoded after the prompt with a fixed 38-byte wire
  length, preserving the payload length reserved in `AT+CIPSEND`.
- A pending clock sample is peeked before starting a transaction and consumed
  only for `CIPSEND_TX_TAG_DIAG` with `CTS_RESULT_OK`.
- `ERROR`, `CLOSED`, transaction rejection, and timeout leave the pending
  sample retryable according to the existing transport boundary.
- A payload callback rejection is a normal failed transaction; it is not
  reported as a prompt or `SEND OK` timeout.

### TDD and build evidence

- RED: the Python firmware-contract test failed because pending data was
  consumed in the clock-start block (`3 passed, 1 failed`).
- RED: temporarily restoring `timeout_abort = 1` caused the C regression to
  fail at `test_cipsend_tx.c:169`, as expected.
- GREEN: firmware-contract, causal-clock policy, and V1 causal-sync tests:
  `11 passed`.
- GREEN: Host C `test_cipsend_tx`: `PASS test_cipsend_tx`.
- GREEN: Host C `test_twin_control_protocol`: `PASS test_twin_control_protocol`.
- Full Python regression: `826 passed, 5 skipped`.
- Python compileall for `simulation/digital_twin` and `tools`: exit `0`.
- `git diff --check`: no whitespace errors.
- Keil `Target 1` rebuild: `0 Error(s), 0 Warning(s)`.
- Build log:
  `.embeddedskills/build/causal-clock-candidate/project-Target 1-rebuild.log`
- Current AXF:
  `firmware/stm32_line_follower/Objects/Project.axf`
- Current AXF SHA-256:
  `9F7A433712984B72A31BC57E2D062C46AB7A3F6CB2D162CBD3DB7D005B06ECD8`
- Keil program size: `Code=27072 RO-data=460 RW-data=168 ZI-data=4272`.

## AprilTag retained-video result

The delegated offline replay used only this retained video:

`simulation/digital_twin/logs/causal_sync_real_20260810_quiet/c260810154900868/camera.avi`

Independent file checks confirm:

- `1920x1080`, `30 fps`, `MJPG`, `213` frames;
- SHA-256:
  `8259cfd9f5799cd8dc58ae907a2947873992b3f1096a208f3350b778052517e8`;
- the original evidence recorded `91` failed frames, all classified as
  `candidates_rejected`, with `4` retained failure images.

The same-video offline candidate replay reported:

| Candidate | Detection | Max gap | p95 processing |
| --- | ---: | ---: | ---: |
| baseline/default | 116/213 = 54.46% | 18 frames | 103.58 ms |
| subpix | 119/213 = 55.87% | 18 frames | 101.04 ms |
| adaptive_wide | 202/213 = 94.84% | 3 frames | 115.69 ms |
| r1_gray1x | 128/213 = 60.09% | 10 frames | 81.49 ms |

`adaptive_wide` is an offline-only, single-variable candidate already
represented by `adaptiveThreshWinSizeMax = 53` in
`tools/camera_toolchain/apriltag_parameter_matrix.py`. It is not a production
tracker change. The declared production gate remains detection `>=95%`, max
gap `<=2` frames, and p95 `<=33.33 ms`; this candidate fails that gate.

## Evidence boundary

### VERIFIED

- The firmware source now materializes the causal timestamp at the payload
  boundary and consumes it only after `SEND OK`.
- The changed firmware passes the focused tests, full Python regression, and
  a clean Keil rebuild.
- The AprilTag replay used the retained 1080p video and its hash is confirmed.
- On that replay, all observed failed detections were recorded as
  `candidates_rejected`; the bounded candidate measurements above are
  offline replay measurements.

### INFERENCE

- The late-materialized timestamp should remove the known command/prompt
  timestamp bias when the new firmware is actually running.
- The wide adaptive threshold improves recovery on this video, but the
  remaining gap and processing cost indicate that detector strictness alone is
  not the complete cause. ROI/tracker lag is a plausible contributor.

### INSUFFICIENT EVIDENCE

- No new hardware run proves the AXF is flashed or that the causal clock meets
  an RMS/residual gate.
- No physical wheel motion, real-car line-following, or synchronized sensor
  fusion claim is established here.
- The internal geometric reason for each rejected OpenCV candidate is not
  exposed by the current production diagnostics.
- Motion blur and camera exposure are not proven as the cause by this video
  alone.
- `adaptive_wide` is not production-ready and must not be flashed or used for
  a real-car conclusion without an independently reviewed next step.

## Next interface

The offline boundary is complete for this round. The next action is a fresh,
bounded real synchronized capture using the current AXF, but it requires an
explicit hardware authorization. Before that authorization, do not flash,
open the camera, connect TCP, or move the vehicle.
