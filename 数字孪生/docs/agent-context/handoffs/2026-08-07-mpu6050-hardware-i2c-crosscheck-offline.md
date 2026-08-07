# MPU identity cross-check: offline handoff

Date: 2026-08-07 Asia/Shanghai
Status: OFFLINE_READY_WAITING_FOR_EXPLICIT_FLASH_AUTHORIZATION

## Current verified boundary

The recovery firmware has repeatedly read a stable responder at address `0x68`:

`AA 55 7D 04 70 21 00 00 28`

This means the existing software-I2C transaction reached a responding device and
returned `WHO_AM_I=0x70`. The fail-closed driver then reports `init_status=0x21`
before any reset/configuration write, so the current failure is an identity
mismatch, not an observed no-ACK failure.

`0x70` is consistent with an MPU6500-class responder, but that remains an
inference. A stable software-I2C value alone cannot distinguish a mislabeled or
compatible die from a repeatable software-I2C read-timing error.

## Offline change prepared

- Added `Hardware/mpu6050_hardware_i2c_diag.c`.
- The new path performs exactly one read-only `WHO_AM_I` transaction through
  STM32 hardware I2C2 on the same PB10/PB11 pins.
- It performs no IMU writes and is called before the normal software-I2C init.
- It is released before the existing software-I2C driver takes ownership.
- The result is carried in byte 4 of the existing `0x7D` diagnostic payload;
  zero means the independent hardware-I2C read failed.
- `0x68` remains the only accepted initialization identity. No compatibility
  path, motion enable, or START behavior was added.

## Offline verification

- Keil `Target 1` rebuild: `0 Error(s), 0 Warning(s)`.
- New source is present in the Keil project group and in the build log.
- ARMCC C99 compilation passed for `test_imu_diagnostic.c`,
  `test_mpu6050_validity.c`, and the unchanged software-I2C driver object.
- Python regression: `676 passed, 5 skipped` in `simulation/digital_twin/tests`.
- Python compileall: exit `0`.
- `git diff --check`: exit `0` apart from normal LF/CRLF warnings.
- Diagnostic AXF SHA-256:
  `DD68CF7644D5AE1F19A120EFC18ED079F1DEB62945A97318AD8F2492ECF45304`.
- No ST-Link operation, reset, flash, socket, START, STOP, or physical motion
  was performed in this handoff.

## Required hardware result

After explicit flash authorization and a passive power-cycle observation:

- software-I2C ID `0x70`, hardware-I2C2 ID `0x70`: identity mismatch is the
  confirmed root cause; next read-only step is register-map/readback evidence
  before considering a bounded MPU6500 compatibility path;
- software-I2C ID `0x70`, hardware-I2C2 ID `0x68`: software-I2C timing/read
  logic is the confirmed root-cause direction; do not accept `0x70`;
- hardware-I2C2 ID `0x00`: the independent hardware path failed and the result
  is insufficient evidence for either conclusion.

The car must remain motion-inhibited. No `START` is allowed from this
diagnostic result alone.
