# TwinTrack-STM32 巡迹孪生平台

> **Digital-twin foundation for an AI-driven robot R&D loop**
> V1 starts with bounded PID candidates; the project is not a PID tuner.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)](https://windows.com)

---

## What Is This?

A digital-twin foundation for an AI-driven robot research and development loop,
currently instantiated on an STM32 mecanum line-following car. The long-term
purpose is to let an AI agent use real observations and feedback to propose,
screen, and iterate algorithm, firmware, and hardware/PCB changes. Real-car
trajectory accuracy still depends on camera, synchronization, and motion-model
calibration.

V1 uses bounded runtime PID parameters as the first candidate type so the
offline twin can be connected to repeatable real-car validation. That payload
is a way to exercise the loop, not the research endpoint. Simulation results
alone do not prove real improvement or autonomous hardware design.

**Core workflow**: Observe real behavior -> formulate a candidate -> simulate
and screen -> deploy the unchanged candidate when authorized -> compare real
results -> feed the evidence back into the twin and the next iteration.

## Key Features

- **2D Simulator** — Pygame visualization with real-time PID tuning
- **3D Perspective View** — Camera-following perspective with virtual K230 camera
- **3D Scan Integration** — Load phone 3D scans (LiDAR/photogrammetry) and simulate in real environment
- **4-Channel IR Sensors** — Discrete (0/1) and continuous analog (0-1023) simulation
- **PID / Adaptive PID** — With real-time gain adjustment
- **STM32 Faithful Controller** — Behavior-level reimplementation of C code
- **RL Environment** — Gymnasium-compatible, PPO/SAC ready
- **4-Level Curriculum Tracks** — Ellipse, Sine wave, Figure-8, Rounded rectangle
- **WiFi Telemetry** — ESP01S wireless (TCP) real-time data from real car
- **System Identification** — Auto-calibrate simulation from real car data
- **Control Sandbox** — PID parameter evaluation with stability scoring
- **Hardware-in-the-Loop** — Real car drives while Python shows synchronized state

## Quick Start

### Installation

```bash
git clone https://github.com/your-username/stm32-digital-twin.git
cd stm32-digital-twin
pip install -r requirements.txt
```

### Run 2D Simulator

```bash
python main.py
```

| Key | Action |
|-----|--------|
| SPACE | Toggle Auto/Manual |
| R | Reset |
| UP/DOWN | Kp +/- 0.05 |
| LEFT/RIGHT | Kd +/- 0.01 |
| 1-4 | Control Hz (10/20/50/100) |
| N | Toggle noise |
| T | Toggle trail |
| C | Toggle charts |
| ESC | Quit |

### Run 3D Simulator

```bash
python main_3d.py
```

| Key | Action |
|-----|--------|
| 1-4 | Track level |
| F/G | FOV +/- 5 |
| H/J | Camera height +/- 3 |
| T/Y | Tilt angle +/- 3 |
| V/B | View distance +/- 30 |
| L | Load real image |
| O | Load video / webcam |
| P | Pause video |
| N | Next frame |

### Run 3D Scan Pipeline

```bash
# Demo mode (generated test model)
python main_scan.py --demo

# Load your phone scan
python main_scan.py --scan path/to/room.obj
```

### Train RL Agent

```bash
python train_ppo.py
```

## System Architecture

```
                         +-----------------+
                         |   Real STM32    |
                         |   Mecanum Car   |
                         +--------+--------+
                                  |
                          ESP01S WiFi (TCP)
                                  |
                         +--------v--------+
                         |  WifiBridge    |
                         |  (Telemetry)    |
                         +--------+--------+
                                  |
              +-------------------+-------------------+
              |                   |                   |
    +---------v--------+ +-------v-------+ +---------v--------+
    |   Calibration    | |  HIL Manager  | |   Replay Engine  |
    |   (Auto-fit)     | |  (Real-time)  | |   (Playback)     |
    +---------+--------+ +-------+-------+ +---------+--------+
              |                   |                   |
              +-------------------+-------------------+
                                  |
                         +--------v--------+
                         |   Plant Model   |
                         | (Learnable)     |
                         +--------+--------+
                                  |
              +-------------------+-------------------+
              |                   |                   |
    +---------v--------+ +-------v-------+ +---------v--------+
    |   PID Controller | |  RL Policy    | |  Camera Follow   |
    |   (Adaptive)     | |  (PPO/SAC)    | |  (K230 Sim)      |
    +---------+--------+ +-------+-------+ +---------+--------+
              |                   |                   |
              +-------------------+-------------------+
                                  |
                         +--------v--------+
                         |  Safety Filter  |
                         | (Slew + Limit)  |
                         +--------+--------+
                                  |
                         +--------v--------+
                         |   MecanumCar    |
                         | (Physics Sim)   |
                         +--------+--------+
                                  |
                         +--------v--------+
                         |   4ch Sensors   |
                         | (Discrete+Ana)  |
                         +-----------------+
```

## Project Structure

```
digital_twin/
|-- main.py                    2D pygame simulator
|-- main_3d.py                 3D perspective simulator
|-- main_scan.py               3D scan -> simulation pipeline
|-- train_ppo.py               PPO training entry
|-- config.py                  Global configuration
|
|-- simulator/                 Core physics + rendering
|-- control/                   PID / Adaptive / Safety
|-- rl_env/                    Gymnasium RL environment
|-- tracks/                    Curriculum track generator
|-- calibration/               System identification
|-- control_sandbox/           PID sandbox evaluation
|-- real_world/                Real car interface (ESP01S WiFi)
|-- hil/                       Hardware-in-the-Loop
|-- training/                  Training pipeline
|-- replay/                    Session replay
|-- analysis/                  Evaluation metrics
|-- scanner/                   3D scan pipeline
|-- stm32_compat/              STM32 HAL compatibility
|-- virtual_hw/                Virtual hardware bus
|-- ui/                        Pygame UI panels
|-- examples/                  STM32 code migration examples
|-- docs/                      Documentation
|-- tests/                     Test suite
```

## 4-Level Curriculum Tracks

| Level | Type | Difficulty | Purpose |
|-------|------|------------|---------|
| 1 | Ellipse | Low | Baseline stability |
| 2 | Sine Wave | Medium | Variable curvature |
| 3 | Figure-8 | High | Crossing + shortcut penalty |
| 4 | Rounded Rect | Medium | Sharp turns |

## RL Environment

- **Observation**: 10D (4 sensors + error + speed + angular velocity + curvature)
- **Actions**: Discrete(5) or Continuous(steering, speed)
- **Rewards**: Modular (tracking + smooth + speed + completion - penalties)
- **Domain Randomization**: Friction, sensor noise, motor delay, track width

## Hardware Requirements (for real car)

- STM32F103/F407 board
- 4x Mecanum wheels + DC motors
- 4x TCRT5000 IR sensors
- ESP01S WiFi module
- K230 AI camera (optional)
- See [docs/hardware.md](docs/hardware.md)

## Documentation

- [System Architecture](docs/architecture.md)
- [Digital Twin Guide](docs/digital_twin.md)
- [RL Training](docs/rl_training.md)
- [Sim2Real Transfer](docs/sim2real.md)
- [Hardware Guide](docs/hardware.md)

## Roadmap

- [x] 2D simulator with PID
- [x] 4-channel sensor simulation
- [x] STM32 faithful controller
- [x] ESP01S WiFi telemetry
- [x] 3D perspective simulator
- [x] RL environment (Gymnasium)
- [x] Curriculum tracks (4 levels)
- [x] Control sandbox + PID optimizer
- [x] System identification + calibration
- [x] Hardware-in-the-Loop
- [x] 3D scan integration
- [ ] ROS2 bridge
- [ ] SLAM integration
- [ ] Multi-car simulation
- [x] Web-based dashboard
- [ ] OTA firmware update

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file.

## Acknowledgments

- STM32 HAL documentation
- Gymnasium (OpenAI Gym)
- Stable-Baselines3
- Pygame community
- OpenCV
