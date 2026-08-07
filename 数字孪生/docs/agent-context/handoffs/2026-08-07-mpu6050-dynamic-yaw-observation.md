# MPU6050 dynamic yaw observation handoff

Date: 2026-08-07 Asia/Shanghai

## Run

The user authorized a bounded elevated-wheel test and manually rotated the
car slowly to the right. The existing canonical entrypoint was reused:

```text
py -3.11 tools/shakedown_toolchain/transport_soak.py \
  --host 192.168.110.236 --port 8888 --run --duration 10 \
  --out logs/imu_yaw_rotation
```

The session completed `START -> telemetry collection -> STOP` with the start
and terminal stop handshakes confirmed. The immutable evidence directory is:

`logs/imu_yaw_rotation/soak_20260807_173821/`

Important files:

- `raw_telemetry.json`
- `raw_io.json`
- `transport_report.json`
- `raw_health.json`

## Observed result

- Raw telemetry contains 371 frames. The transport report's gated collection
  window contains 366 frames; the difference is boundary-frame filtering.
- `imu_init_status` is `0x00` for every raw telemetry frame.
- `imu_validity` values are `0x0F` and `0x1F`; the latter includes the known
  `DT_CLAMPED` bit.
- yaw range is `-0.41..11.68` degrees, with first `0.00` degrees and last
  `11.68` degrees.
- Across 370 consecutive raw transitions: 260 were positive, 22 negative,
  and 88 unchanged; maximum single-step change was `0.33` degrees.
- Parser errors were zero. The run received 101 RX events and 10 health
  frames.
- The transport cadence gate passed. The independent main-loop nonblocking
  gate failed with `blocking_ratio_median=5.45`; this is a transport/runtime
  gate result, not evidence that the IMU yaw response failed.

## Evidence boundary

### VERIFIED

- The current firmware reported successful IMU initialization and valid
  read/update flags during the run.
- The IMU yaw output changed substantially during the authorized manual-right
  rotation rather than remaining at the previous stationary `0.0` value.
- The canonical START/STOP lifecycle and binary parsing completed without
  parser errors.

### INFERENCE

- The positive yaw trend is consistent with the user's manual right rotation.
  The mapping from positive sensor yaw to the car's control-coordinate
  definition of right still needs an explicit axis/mounting calibration.
- The dynamic signal is now usable as an input to offline replay and the
  existing control-shadow path.

### INSUFFICIENT EVIDENCE

- Absolute angle accuracy, degrees-per-real-degree scale, bias, drift, and
  long-run timing quality.
- Any claim that MPU6050 has changed firmware control or improved line loss,
  speed, or sharp-turn performance.
- Digital-twin calibration/holdout validity or AI-generated improvement.

## Next interface

Do not change real firmware control yet. The next offline action can replay
this raw yaw sequence through the fusion/control-shadow path. Before applying
any correction to firmware, perform a known-angle sign/scale check (for
example, a marked fixed-angle rotation) and preserve a baseline.
