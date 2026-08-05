TwinTrack STM32 temporary safety-stop firmware

Purpose:
- Disable TIM2 and TIM4 PWM.
- Force PA0-PA3 and PB6-PB9 low.
- Do not start motors, sensors, MPU6050, or ESP-01S.

This is a separate temporary target. The original project.uvprojx and
User/main.c are not modified.

Restoring the original car firmware requires rebuilding and flashing
project.uvprojx again.
