# PWM Permille Scale Repair Design

## Goal

Make the motor command contract internally consistent: values `0..999` map to
approximately `0..99.9%` PWM duty on both TIM2 and TIM4.

## Verified Problem

- `_MotorSet()` clamps every command to `-999..999`.
- TIM2 and TIM4 currently use `PSC=71`, `ARR=4234`.
- The current effective duty is therefore `abs(command) / 4235`, so `260` is
  6.14% and `650` is 15.35%.
- A historical test implementation uses `PSC=71`, `ARR=999`, matching the
  documented `0..999` speed range and producing 1 kHz PWM.
- The current direction probe passed. Direction constants, motor grouping,
  sensor ordering, PID, and lost-line behavior are outside this repair.

## Selected Design

Use one shared compile-time motor PWM maximum of `999` and derive the timer
period from it. Both TIM2 and TIM4 will use `ARR=999` with `PSC=71`, producing
1 kHz PWM from the 72 MHz timer clock. `_MotorSet()` will clamp against the same
shared maximum so the command range and timer range cannot silently diverge.

No changes are allowed to:

- `M1_DIR..M4_DIR` or channel selection;
- `MotorOut()` left/right grouping;
- PID gains, speed bounds, smoothing, or lost-line search;
- runtime command protocol, heartbeat, STOP, rollback, or transport logic.

## Test Design

1. Add a test-only STM32 header stub and
   `simulation/digital_twin/tests/test_motor_pwm_contract.c`. Compile the real
   production `Motor.c`, call `Motor_Init()` and `Motor_Write()`, and assert the
   captured TIM2/TIM4 timebase and CCR effects.
2. Run the host executable before production edits and record the expected RED
   assertion (`ARR=4234`, expected 999).
3. Make the minimal `Motor.c` change and rerun the focused host test GREEN.
4. Run the focused host test together with
   `simulation/digital_twin/tests/test_runtime_protocol.py` and
   `simulation/digital_twin/tests/test_frame_parser_health.py`.
5. Rebuild `程序/3. 麦轮巡线小车/project.uvprojx`, target `Target 1`, and
   require 0 errors and 0 warnings.

## Hardware Gate

This design note does not authorize flashing or motion.

After a separate explicit authorization:

1. Flash only the freshly verified Keil artifact.
2. Keep all wheels elevated and the operator beside the power switch.
3. Confirm pre-STOP, then apply the existing ACK-checked speed steps down to
   `speed_max=260` before START.
4. Run once for 0.5 seconds with 200 ms heartbeats and final STOP confirmation.
5. Do not automatically retry START. Cut motor power if STOPPED is not confirmed.
6. Only after all four wheels are visually sane may a separate 0.5-second ground
   probe at speed 260 be authorized.

## Acceptance

- Focused RED then GREEN evidence exists.
- The named focused and protocol regression tests pass.
- Keil rebuild reports 0 errors and 0 warnings.
- The diff is limited to the PWM contract and its tests.
- No flash or real-car motion is claimed by software-only acceptance.
