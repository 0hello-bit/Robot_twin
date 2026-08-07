# MPU6050 Initialization Retry and Failure Attribution Design

Date: 2026-08-06
Status: PROPOSED_FOR_USER_REVIEW

## Decision Under Review

Repair the MPU6050 boot path so a transient I2C failure does not leave the
firmware in an ambiguous state, while a persistent failure remains fail-closed
and becomes diagnosable from the existing telemetry stream.

This design does not change PID gains, line-following direction, speed limits,
turn logic, safety stops, or the camera-anchored fusion algorithm. It only
repairs initialization observability and the gate that decides whether IMU
data is eligible for observation/fusion.

## Evidence and Problem Boundary

The latest real run `c260806132130349` produced 199 telemetry frames. The
frames reported `imu_validity=0x04`, which is the `READ` bit only; it does not
contain `INIT`, `BIAS`, or `UPDATED`. The resulting fusion records were all
`CAMERA_ONLY` with fallback reason `imu_not_fresh`, and yaw remained zero.

Therefore the current evidence proves:

- the later 14-byte sensor read path can return successfully;
- the full IMU validity contract was not satisfied in that run;
- the current telemetry cannot identify whether configuration, WHO_AM_I, or
  bias sampling failed.

It does not yet prove which physical connection or initialization step failed.
That attribution is the purpose of this repair.

## Goals

1. Run the complete existing initialization sequence again after a failure,
   with a finite retry bound.
2. Record the last failed initialization stage in a stable one-byte status.
3. Preserve the existing fail-closed validity contract. A readable sensor must
   never be promoted to usable IMU data unless initialization and bias setup
   succeeded in the same boot.
4. Reuse the existing 26-byte telemetry payload and existing parser/capture
   path. No parallel transport, parser, or telemetry lifecycle is allowed.
5. Make the offline contract testable before another firmware flash.

## Non-goals

- Do not probe address `0x69` automatically. The firmware remains fixed at
  `MPU6050_ADDR=0x68`; an AD0 wiring error must remain visible.
- Do not redesign the software I2C driver.
- Do not add automatic hardware recovery beyond repeating the existing
  initialization sequence.
- Do not use IMU yaw to command motors or to alter a safety decision.
- Do not claim physical repair, valid wiring, or improved vehicle behavior
  from host tests or a Keil build.

## Initialization State Contract

`MPU6050_Init()` retains its existing `void` API. Internally it performs one
complete attempt in this fixed order:

1. reset (`PWR_MGMT_1=0x80`);
2. wake/clock (`PWR_MGMT_1=0x01`);
3. sample-rate divider (`SMPLRT_DIV=0x04`);
4. low-pass configuration (`CONFIG=0x03`);
5. gyro range (`GYRO_CONFIG=0x08`);
6. accelerometer range (`ACCEL_CONFIG=0x08`);
7. `WHO_AM_I` read and exact comparison with `0x68`;
8. 100 existing Z-gyro bias samples with the existing 2 ms spacing.

The retry interpretation is explicit: the first attempt plus at most three
retries, for at most four complete attempts total. A retry starts the whole
sequence again and resets the temporary bias sum; it does not continue from a
partially configured stage. A short fixed recovery delay between attempts is
allowed, but no unbounded retry or background retry is allowed.

On success:

- `INIT` and `BIAS` validity bits are set;
- `ready` remains gated by those bits and a later successful `ReadAll()`;
- initialization status becomes `MPU6050_INIT_STATUS_OK`;
- the existing yaw, sign, scale, filter, and bias calculation are unchanged.

On exhaustion:

- `INIT`, `BIAS`, `READ`, and `UPDATED` are clear;
- `ready` is zero;
- yaw and bias are reset to their boot-safe values;
- the status retains the last failed stage;
- later `ReadAll()` calls may report `READ`, but may not set `ready`, `INIT`, or
  `BIAS` and may not make `MPU6050_ValidityAllowsFusion()` return true.

The status is boot-attempt evidence. A later runtime read error is represented
by the existing per-cycle validity bits and must not overwrite a successful
boot status with a misleading initialization-stage code.

## One-Byte Initialization Status

The current telemetry frame already has a 26-byte payload. Payload byte 24 is
the existing `imu_validity` byte and payload byte 25 is reserved. The repair
uses only payload byte 25, which is byte 29 of the complete 31-byte wire
frame. The checksum remains byte 30 and continues to cover the unchanged
payload length and all 26 payload bytes.

The status codes are stable protocol values:

| Code | Name | Meaning |
| --- | --- | --- |
| `0x00` | `INIT_STATUS_OK` | Full configuration, ID check, and bias setup succeeded. |
| `0x01` | `INIT_STATUS_NOT_ATTEMPTED` | No complete initialization attempt has been recorded. |
| `0x10` | `INIT_STATUS_RESET_WRITE` | Reset register write/ACK failed. |
| `0x11` | `INIT_STATUS_WAKE_WRITE` | Wake/clock register write/ACK failed. |
| `0x12` | `INIT_STATUS_SAMPLE_RATE_WRITE` | Sample-rate divider write/ACK failed. |
| `0x13` | `INIT_STATUS_CONFIG_WRITE` | Low-pass configuration write/ACK failed. |
| `0x14` | `INIT_STATUS_GYRO_CONFIG_WRITE` | Gyro-range write/ACK failed. |
| `0x15` | `INIT_STATUS_ACCEL_CONFIG_WRITE` | Accelerometer-range write/ACK failed. |
| `0x20` | `INIT_STATUS_WHO_AM_I_READ` | WHO_AM_I transaction did not complete. |
| `0x21` | `INIT_STATUS_WHO_AM_I_MISMATCH` | WHO_AM_I completed but was not `0x68`. |
| `0x30` | `INIT_STATUS_BIAS_READ` | A bias sample read failed. |

The value is the last failed stage after retry exhaustion, not a claim that
the physical cause is known. For example, `WHO_AM_I_READ` identifies the
failed transaction boundary; it does not distinguish wiring, power, pull-up,
or software-I2C timing without additional evidence.

The header exposes the enum-like constants and a read-only
`MPU6050_GetInitStatus()` accessor. The host parser exposes
`imu_init_status` and `imu_init_status_known` for 26-byte payloads. A legacy
24-byte payload remains `imu_init_status_known=false`; it must never be
interpreted as initialization success.

## Fail-Closed Fusion Rule

The required current-cycle validity remains:

```text
INIT | BIAS | READ | UPDATED
```

and `DT_CLAMPED` must be clear. In addition, host-side fusion accepts an IMU
sample only when the current payload has a known initialization status equal to
`INIT_STATUS_OK`. This duplicate check is intentional: validity bits describe
the cycle, while `imu_init_status` describes the boot initialization result.

The following examples are explicit:

- `imu_validity=0x04`, any init status: `CAMERA_ONLY` or insufficient evidence;
- `imu_validity=0x0F`, `imu_init_status=0x21`: reject for fusion;
- `imu_validity=0x0F`, `imu_init_status=0x00`, `DT_CLAMPED=0`: eligible;
- legacy 24-byte payload, even with a numeric yaw: status unknown, reject;
- successful boot followed by one failed runtime read: no fresh IMU sample for
  that cycle; do not rewrite the boot status.

## Minimal Implementation Surface

Only these existing boundaries may change:

- `firmware/stm32_line_follower/Hardware/mpu6050.h/.c`: status constants,
  bounded whole-sequence retry, stage recording, and accessor;
- `firmware/stm32_line_follower/User/main.c`: write the status into the
  existing payload byte 25 and keep the checksum/frame size unchanged;
- `simulation/digital_twin/real_world/frame_parser.py`: decode the payload-25
  status while preserving 24-byte compatibility;
- `simulation/digital_twin/v1_twin/v1_twin_schema.py` and the existing capture
  forwarding path: carry the additive status fields without changing existing
  constructor compatibility or raw artifact names;
- focused existing tests plus
  `simulation/digital_twin/tests/test_mpu6050_validity.c`.

No new TCP client, frame parser, camera collector, session store, heartbeat,
or firmware control path may be introduced.

## Test-First Acceptance Contract

Before production edits, the host-C validity test must fail for the missing
behavior, then pass after the minimal implementation. The focused tests must
cover:

1. full initialization success reports `INIT_STATUS_OK`, sets `INIT|BIAS`,
   and does not set per-cycle `READ|UPDATED` before the first read/update;
2. a failure at a named write stage is attributed to that stage;
3. a WHO_AM_I transaction failure and a WHO_AM_I mismatch produce different
   statuses;
4. a bias sample failure is attributed to the bias stage;
5. a transient failure followed by recovery succeeds within the bounded retry
   budget and resets the temporary bias sum between attempts;
6. persistent failure stops after at most four total attempts, leaves the
   system fail-closed, and is not promoted by a later readable `ReadAll()`;
7. a successful boot followed by a runtime read failure clears current-cycle
   read/update evidence without changing the boot status;
8. `DT_CLAMPED` still blocks fusion even when all other validity bits are set.

The parser/schema tests must additionally cover:

- current 26-byte payload status decoding and round-trip preservation;
- legacy 24-byte payload status unknown;
- nonzero failure status never being treated as `INIT_STATUS_OK`;
- frame checksum and 31-byte wire framing remaining unchanged.

## Offline and Build Gates

The implementation gate is complete only when all of the following are
verified:

- focused Host C tests pass, including the named-stage and retry tests;
- affected Python parser/schema/fusion/capture tests pass;
- the full non-archive Python regression passes;
- `py -3.11 -m compileall -q simulation/digital_twin tools` passes;
- `git diff --check` passes;
- canonical Keil `Target 1` rebuild reports `0 Error(s), 0 Warning(s)` and the
  AXF hash is recorded;
- no production code path changed PID, motor, line-loss, or safety behavior.

These gates establish `VERIFIED` offline/build evidence only. They do not
establish physical MPU wiring, initialization, axis sign, scale, drift, or
vehicle improvement.

## Hardware Boundary

After the offline/build gate, a separate fresh authorization is required for
each hardware action. The next hardware sequence is:

1. user authorizes flashing the tested AXF through the established Keil/ST-Link
   path;
2. with the car stationary or wheels safely elevated, collect telemetry and
   confirm `imu_validity` contains `0x0F`, `DT_CLAMPED` is clear, and
   `imu_init_status=0x00`;
3. if status is nonzero, stop and inspect the recorded stage before any ground
   motion;
4. only after the stationary gate passes, request a bounded sign/scale test;
5. only after that test passes, request a synchronized ground capture.

No flash, reset, START/STOP, serial send, or motor motion is authorized by
this design document. A real run with a nonzero status or incomplete validity
must be recorded as `INSUFFICIENT EVIDENCE`, not as a successful repair.

## Review Questions

The user should review these choices before implementation:

- Is “three retries” intended as the first attempt plus three retries (four
  total attempts), as specified here?
- Are the proposed one-byte stage codes sufficient for the next hardware
  diagnostic, or is a separate attempt counter required?
- Is reusing payload byte 25 acceptable as the versioned current-frame status
  field while retaining 24-byte legacy decoding?

