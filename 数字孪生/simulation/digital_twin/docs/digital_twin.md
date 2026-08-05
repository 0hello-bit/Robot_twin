# Digital Twin System

## Concept

The digital twin is a software replica of the physical STM32 car that runs
entirely on the computer. It models:

- **Kinematics**: Mecanum wheel motion (forward, lateral, rotational)
- **Sensors**: 4-channel IR sensors (discrete + continuous analog)
- **Control**: PID with configurable gains
- **Physics**: Motor response, steering dynamics, friction, noise

## Purpose

Tune all parameters on computer first, then flash to real car once confirmed working.

## Key Features

### 2D Simulator (main.py)
- Pygame-based visualization
- Real-time PID tuning (keyboard controls)
- Noise injection (sensor, motor, control delay)
- HIL mode with ESP01S WiFi telemetry
- Replay recorded sessions

### 3D Simulator (main_3d.py)
- Perspective ground view with camera following car
- Virtual K230 camera simulation
- Adjustable camera parameters (FOV, height, tilt, distance)

### 3D Scan Pipeline (main_scan.py)
- Load phone 3D scans (OBJ/PLY/GLB via trimesh)
- Auto-extract floor plane (RANSAC)
- Detect track lines on floor
- Run simulation in real scanned environment

## Noise Model

Configurable non-ideal factors:
- Sensor misread probability (0~5%)
- Edge blur (probability-based detection)
- Control delay (1~5 cycle buffer)
- Motor response lag (first-order tau)
- Velocity perturbation (ground unevenness)

All noise sources can be toggled independently.
