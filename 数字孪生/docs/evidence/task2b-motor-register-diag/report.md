# Task 2B: Motor-Register Diagnostic Report

**Date:** 2026-07-30
**State:** NOT FLASHED
**Author:** Claude

## Summary

Added minimal diagnostic instrumentation that emits exactly one binary AA55-0x7E frame per START transition, capturing the real TIM2/TIM4 peripheral register snapshot after motor outputs have been written. The frame is informational only — unknown type 0x7E is safely ignored by existing production consumers.

## What Was Created

| File | Description |
|------|-------------|
| `User/motor_register_diag.h` | Pure-function encoder header (ARMCC5 + MSVC compatible). Defines `MotorRegSnapshot` struct and `motor_reg_diag_encode()`. Frame format: AA 55 | 0x7E | 24 | 12×uint16 LE | XOR checksum. |
| `User/motor_register_diag.c` | Encoder implementation — no hardware dependencies, testable on host. |
| `tests/test_motor_register_diag.c` | Host C test suite (7 tests): header, type, length, LE encoding, XOR checksum, deterministic values, index ordering, buffer bounds. |
| `tests/test_motor_register_diag.py` | Python test suite (6 tests): FrameParser detection, zero/large/deterministic values, type-0x7E coexistence with 0x01, checksum rejection. |

## What Was Modified

| File | Change |
|------|--------|
| `User/main.c` | Added `#include "motor_register_diag.h"`, shared `ESP_SendCIPSEND()` helper refactored from duplicated CIPSEND pattern, `ESP_SendDiagFrame()` and `Diag_CaptureAndSendOnce()` functions, one-shot latch `g_diag_armed` with transition detection from inhibited→running, TIM2/TIM4 register capture via `TIMx->CR1/ARR/CCRn` after each `MotorOut()` call. Resets latch on motion-inhibited path. |
| `User/esp_runtime_transport.c` | (unchanged) |
| `project.uvprojx` | Added `motor_register_diag.c` and `motor_register_diag.h` to the User group. |
| `real_world/frame_parser.py` | Added `FRAME_TYPE_MOTOR_REG_DIAG = 0x7E`, `PAYLOAD_LEN_MOTOR_REG_DIAG = 24`, and `decode_motor_register_diag(payload)` function. |

## Diagnostic Frame Contract

```
Offset  Size  Field
0x00    2     Header AA 55
0x02    1     Type 0x7E
0x03    1     Length 24
0x04    24    Payload: 12 × uint16 LE
                TIM2_CR1, TIM2_ARR, TIM2_CCR1, TIM2_CCR2,
                TIM2_CCR3, TIM2_CCR4, TIM4_CR1, TIM4_ARR,
                TIM4_CCR1, TIM4_CCR2, TIM4_CCR3, TIM4_CCR4
0x1C    1     XOR checksum (type ^ length ^ payload[0..23])
Total: 29 bytes
```

## One-Shot Latch Behavior

1. On `twin_control_init()` and any motion-inhibited iteration: `g_diag_armed = 0`
2. On transition from motion-inhibited → running: `g_diag_armed = 1` (tracked via local static `g_was_inhibited`)
3. On the first `MotorOut()` call in a running epoch: capture TIM2/TIM4 registers, encode frame, send via `ESP_SendCIPSEND()`, clear `g_diag_armed`
4. Subsequent `MotorOut()` calls in the same epoch: no-op (latch already consumed)

## Test Results

### Host C Tests
```
All motor_register_diag tests PASSED.    (7/7)
PASS test_twin_control_protocol          (38/38)
PASS test_ipd_parser                     (18/18)
```

### Python Tests
```
79 passed (6 new motor-register-diag + 73 existing)
```

### Cross-Language
```
test_runtime_protocol_cross_language.py — all 18 tests PASSED
(Python-encoded parameters round-trip through C ACK encoder)
```

### Keil Target 1 Rebuild
```
".\Objects\Project.axf" - 0 Error(s), 0 Warning(s).
Build Time Elapsed: 00:00:05
Fresh AXF: 2026-07-30 19:05:36 (471272 bytes)
```

## Secret Leakage Scan

Scanned all new/modified source files (`motor_register_diag.c/h`, `test_motor_register_diag.c/py`, `frame_parser.py` modifications) for secrets (password, WIFI, credential, token, API key patterns). No leakage detected. Existing Wi-Fi credentials in `main.c` lines 16-17 were not read, printed, or copied.

## Remaining Hardware Unknowns

The following cannot be verified without flashing to hardware and running on a vehicle:

1. **TIM register addresses**: The diagnostic captures `TIM2->CR1/ARR/CCRn` and `TIM4->CR1/ARR/CCRn` via the CMSIS register structs. These addresses are correct per the STM32F103 reference manual (TIM2 at 0x40000000, TIM4 at 0x40000800), but actual hardware behavior (what values appear after PWM output) is unverified.
2. **ESP CIPSEND prompt timing**: `ESP_WaitPrompt(200)` uses a 200 ms timeout. On real hardware with ESP01S at 38400 baud, the `AT+CIPSEND=id,29` prompt response timing is unknown — the 200 ms may need calibration.
3. **g_diag_armed transition detection**: The static `g_was_inhibited` flag assumes `twin_control_motion_inhibited()` returns 1 on the first loop iteration after init. Verified in C tests, but hardware boot-order timing relative to ESP CONNECT is unconfirmed.
4. **Diagnostic frame RX-path handling**: The PC-side `FrameParser` correctly parses type 0x7E frames. However, the `StreamDemuxer` (which separates ASCII lines from binary AA55 frames) uses a simplified single-byte heuristic that may need widening for the new 29-byte diagnostic frame if it arrives interleaved with other data.
5. **Cannot flash**: No ST-Link/VCP debugger was connected. The AXF was rebuilt but not downloaded.

## Boundaries Preserved

- ❌ No hardware, flash, reset, debug, serial, network, TCP, or motor action performed
- ❌ PID values, PWM configuration, MotorOut, Motor.c, direction polarity unchanged
- ❌ 0x01 telemetry contents and send logic unchanged (CIPSEND refactored to shared helper, same wire format)
- ❌ Default motion inhibition preserved (starts inhibited, only R,...,START clears)
- ❌ Automatic STOP/TIMEOUT behavior preserved
- ❌ No ISR register captures — all TIM reads in main context
- ❌ No Wi-Fi credential lines read, printed, or logged

## File Inventory (new + modified)

```
程序/3. 麦轮巡线小车/User/motor_register_diag.h       (new)
程序/3. 麦轮巡线小车/User/motor_register_diag.c       (new)
程序/3. 麦轮巡线小车/User/main.c                       (modified)
程序/3. 麦轮巡线小车/project.uvprojx                   (modified)
simulation/digital_twin/tests/test_motor_register_diag.c (new)
simulation/digital_twin/tests/test_motor_register_diag.py (new)
simulation/digital_twin/real_world/frame_parser.py      (modified)
```
