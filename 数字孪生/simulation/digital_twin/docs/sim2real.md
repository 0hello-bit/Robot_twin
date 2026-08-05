# Sim2Real Transfer

## Pipeline

```
1. Collect real car data via ESP01S WiFi telemetry
2. Calibrate PlantModel parameters (PWM->speed, steering, latency)
3. Validate simulation accuracy
4. Tune PID/RL in calibrated simulation
5. Deploy confirmed parameters to real car
```

## Telemetry Protocol

Binary frame format:
```
[0xAA][0x55][type][len] [S0 S1 S2 S3] [m1 m2 m3 m4] [error][pid][tick][yaw] [XOR]   (29 bytes)
```

## Calibration System

### System Identification
- PWM -> Velocity: linear / quadratic / piecewise-linear fitting
- Steering dynamics: first-order lag + delay
- Latency estimation: cross-correlation analysis

### Multi-trajectory Calibration
- Batch calibration across multiple sessions
- EMA + momentum parameter updates (prevents oscillation)
- Model confidence scoring

## Hardware-in-the-Loop (HIL)

Real car follows the line while Python displays synchronized state:
- Sensor readings
- PWM outputs
- PID values
- Virtual trajectory overlay

## Required Hardware

- STM32 mecanum car with 4x IR sensors
- ESP01S WiFi module (USART1, TCP server)
- K230 AI camera (optional, for camera-based control)
