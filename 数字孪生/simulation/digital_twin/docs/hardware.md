# Hardware Guide

## STM32 Car Specifications

- **MCU**: STM32F103 (Blue Pill)
- **Motors**: 4x Mecanum wheels with DC motors (line-following uses differential drive)
- **Sensors**: 4x TCRT5000 IR sensors (front-mounted, parallel)
- **IMU**: MPU6050 (6-axis, software I2C) — yaw used for telemetry / track reconstruction
- **Communication**: ESP01S WiFi module (USART1, TCP server) — replaces the old HC-06 Bluetooth
- **Camera**: K230 AI camera (optional)

## Pin Assignments

| Function | Pin | Notes |
|----------|-----|-------|
| Motor M1 (left)  | PA0 / PA1 (TIM2 CH1/2) | left wheels  |
| Motor M2 (right) | PA2 / PA3 (TIM2 CH3/4) | right wheels |
| Motor M3 (right) | PB6 / PB7 (TIM4 CH1/2) | right wheels |
| Motor M4 (left)  | PB8 / PB9 (TIM4 CH3/4) | left wheels  |
| IR Sensor 0 | PB1 | Left-most |
| IR Sensor 1 | PB0 | Left-center |
| IR Sensor 2 | PB4 | Right-center |
| IR Sensor 3 | PB5 | Right-most |
| ESP01S TX -> | PA10 | USART1_RX |
| ESP01S RX <- | PA9  | USART1_TX |
| MPU6050 SCL | PB10 | software I2C |
| MPU6050 SDA | PB11 | software I2C |

> Left wheels = M1 + M4, right wheels = M2 + M3. Line-following drives them as a
> differential pair (mecanum lateral motion is not used while following the line).

## Power (important for ESP01S)

The ESP01S draws current spikes of 300-400 mA when its WiFi radio transmits, while the
MPU6050 only needs ~4 mA. If both share the STM32 3.3V rail over a breadboard, the ESP's
spikes can sag the rail and (a) drop the WiFi link and (b) corrupt the MPU6050 yaw — which
is exactly the signal used for sim calibration. Recommended:

- Give the ESP01S its own regulator: **AMS1117-3.3, 5V in -> 3.3V out**.
- Add a 470-1000 uF bulk cap (+ 0.1 uF) across the ESP01S VCC-GND.
- Keep the MPU6050 on the STM32 3.3V (it is light and quiet).
- **Common ground**: AMS1117 GND, ESP GND and STM32 GND must be tied together, or the
  USART has no shared reference and telemetry will not work.
- ESP01S CH_PD (EN) -> 3.3V (required for the module to run).
- Motors need their own supply (e.g. 7.4V 2S LiPo); do not power them from the 5V adapter.

## Assembly Notes

- Sensors must be parallel, mounted in front of the front wheels
- Mecanum wheel orientation: roller angle 45 degrees

## WiFi Telemetry

The ESP01S runs as a TCP server (port 8888); the PC connects as a client. Frame format
(binary): `0xAA 0x55 | type | len | payload | XOR`, 29 bytes total, sent at ~20-50 Hz.
Payload: 4 sensor bits, 4 motor PWM (int16 LE), error, PID output, tick counter, and
MPU6050 yaw (x100). Parsed by `real_world/frame_parser.py`.

The link is one-way (car -> PC) — the firmware's PID gains are compile-time `#define`s,
not adjustable over the air.
