TwinTrack STM32 hardware diagnostic firmware

Safety:
- TIM2 and TIM4 are disabled continuously.
- PA0-PA3 and PB6-PB9 are forced low continuously.
- This stage does not move any motor.

Checks:
- PB1, PB0, PB4, PB5: live state, low/high observations, transition counts.
- PB10/PB11: MPU6050 ID, ready flag, accelerometer and gyroscope changes.
- PA9/PA10: repeated ESP-01S "AT" command and response counters.
- Motor PWM timers and output registers remain disabled/zero.

The original Keil project and User/main.c are not modified.
