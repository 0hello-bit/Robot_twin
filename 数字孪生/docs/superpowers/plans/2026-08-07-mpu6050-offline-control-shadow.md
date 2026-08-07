# MPU6050 Offline Control Shadow Plan

Date: 2026-08-07

## Goal

Prepare a narrow offline interface for allowing MPU6050 yaw to participate in
a future control decision and for measuring the quality of synchronized IMU
evidence, without changing firmware control or claiming a digital-twin
calibration result.

## Current hardware boundary

The latest authorized elevated-wheel run is evidence that the current
firmware reported `imu_init_status=0x00` and valid IMU flags (`0x0F` on normal
frames; one `0x1F` frame had `DT_CLAMPED`). This verifies initialization and
sample-read/update status for that run. All observed yaw values were `0.0`
degrees, so dynamic yaw response, axis sign, scale, drift, and control benefit
remain `INSUFFICIENT EVIDENCE`.

The exact raw evidence is:

- `logs/v1_ground_shakedown_260807160902261/shakedown_report.json`
- `logs/post_flash_passive/soak_20260807_160450/transport_report.json`

## Offline implementation

### 1. Control shadow

`v1_twin_imu_control.py` adds `V1ImuControlShadow`. It consumes an existing
`V1PoseFusionRecord`, a desired yaw, and the baseline integer turn. Only a
record with `USED_IMU`, known validity, all required freshness bits, no
`DT_CLAMPED`, known successful initialization, and finite fused yaw may alter
the hypothetical turn. Otherwise it returns the baseline turn unchanged and
records a reason.

The correction gain, sign, correction limit, and turn limit are explicit
parameters. The result contains `hardware_applied=false`; it is not wired to
the STM32, motor mapping, safety stop, or current closed-loop plant.

### 2. Evidence summary

`summarize_imu_evidence()` computes IMU-use coverage, fallback counts,
monotonic timestamp status, maximum fusion gap, camera/IMU incremental yaw
residual p95, propagation-versus-camera residual p95, and fallback reasons.
Synthetic records always remain `INSUFFICIENT_EVIDENCE`. `REAL_SYNC` only
produces `VERIFIED` when the structural prerequisites are present; that label
means the quality summary is supported by a real synchronized record set, not
that the sensor or twin is accurate.

The existing capture path writes this summary as additive
`imu_evidence.json`; raw files and the B3 gate remain unchanged.

## Acceptance

- Valid IMU yaw changes only the hypothetical turn decision.
- Unknown, stale, initialization-failed, or clamped IMU data cannot change the
  baseline turn.
- Correction and output are bounded and deterministic.
- Synthetic replay cannot become verified real evidence.
- Real-sync evidence is rejected when timestamps are non-monotonic.
- Existing Python tests and capture lifecycle remain green.

## Next hardware interface

Stop at this boundary. Before any firmware control change, perform one bounded
elevated-wheel observation that produces a non-zero yaw response and identifies
the yaw sign/scale. Then replay that real synchronized evidence through the
new report and shadow path. Only after that evidence is accepted should a
separate plan consider applying the same constrained correction to the real
controller.

No flash, START, STOP, camera session, or motor command is part of this plan.
