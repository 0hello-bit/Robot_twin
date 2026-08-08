# B3 timestamp clock repair handoff

Date: 2026-08-08
Workspace: `C:\Users\24668\Desktop\stm32小车\数字孪生`
Status: `OFFLINE_VERIFIED_HARDWARE_RERUN_REQUIRED`

## Problem and root cause

The real run `c260808033248336` contained equal adjacent camera timestamps at
frames 380 and 381. The previous capture path used `time.monotonic_ns()` for
camera frames and telemetry receive timestamps. On this Windows installation,
Python reports that clock as `GetTickCount64()` with a `15.625 ms` resolution.
Equal adjacent values are therefore possible even though the clock does not
go backwards. This is a host timestamp-resolution problem, not evidence of a
camera frame-order reversal.

## Offline change

- Added `capture_pc_clock_ns()` to
  `tools/camera_toolchain/capture_sync_run.py`.
- The camera frame timestamp, telemetry `pc_recv_ns`, and health-frame
  `pc_recv_ns` now use the same high-resolution `perf_counter_ns()` clock
  domain.
- START/STOP timeout and heartbeat scheduling clocks remain unchanged.
- The raw run `c260808033248336` was not rewritten, normalized, or silently
  reclassified.

The capture path still records timestamps at frame-read/receive time and the
existing `ClockSync` fit continues to operate within one run using the same
PC clock domain for both streams.

## TDD and verification

- RED: the two new clock-domain tests failed because
  `capture_pc_clock_ns()` did not exist.
- GREEN: the focused clock tests passed `2/2`.
- Capture cleanup and diagnostic tests: `33 passed`.
- Full Python regression excluding archive: `729 passed, 5 skipped`.
- Python compileall for `simulation/digital_twin` and `tools`: exit `0`.
- `git diff --check`: no whitespace errors; only existing LF/CRLF warnings.
- A live clock probe reported `QueryPerformanceCounter`, `100 ns` nominal
  resolution, and no decreasing values across 10,000 samples. Immediate
  equal values can still occur at sub-resolution call intervals; real frame
  timestamps are separated by the camera/read and detector work, so the
  next real run is required to verify the actual artifact contract.

## Evidence boundary

### VERIFIED

- The root cause of the observed duplicate timestamp is identified in the
  host clock implementation and resolution.
- New camera and telemetry evidence timestamps use one high-resolution clock
  function.
- Offline regression and compilation pass.

### INFERENCE

- The next real capture should no longer reproduce the observed 15.625 ms
  quantization collision under the current detector workload.

### INSUFFICIENT EVIDENCE

- No new hardware run has verified the new timestamp artifacts.
- The previous raw run remains formally blocked because it predates this fix;
  its duplicate timestamp is not retroactively repaired.
- AprilTag observation continuity remains below the declared gate and no
  detector change has been validated.

## Next interface

After explicit authorization, run one fresh bounded synchronized capture with
the raised camera. Verify that `frame_index.jsonl` has no non-increasing
readable-frame timestamps, then run the B3 observation analyzer. Do not infer
that the detector is fixed from the offline change alone.
