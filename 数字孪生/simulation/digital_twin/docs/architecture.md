# System Architecture

## Overview

The STM32 Digital Twin Platform is a modular simulation and control development
environment for STM32-based mecanum line-following cars.

## Module Map

```
digital_twin/
|-- config.py                  Global configuration
|-- main.py                    2D pygame simulator (primary)
|-- main_3d.py                 3D perspective simulator (K230 camera)
|-- main_scan.py               3D scan -> simulation pipeline
|-- train_ppo.py               PPO training entry point
|
|-- simulator/                 Core physics engine
|   |-- car.py                 MecanumCar entity
|   |-- physics.py             MotorModel + SteeringDynamics
|   |-- sensor.py              Discrete IR sensor (4-channel)
|   |-- analog_sensor.py       Continuous analog sensor
|   |-- camera_simulator.py    Virtual K230 camera
|   |-- map.py                 TrackMap (line segments)
|   |-- pid.py                 PID controller
|   |-- renderer.py            Pygame renderer
|   |-- noise_model.py         World noise model
|   |-- timing.py              Control cycle timer
|
|-- control/                   Controllers
|   |-- base_controller.py     BaseController ABC
|   |-- line_follow.py         Standard PID line following
|   |-- camera_line_follow.py  Camera-based line following
|   |-- adaptive_pid.py        Adaptive PID (EMA micro-tuning)
|   |-- stm32_faithful_controller.py  STM32 behavior reimplementation
|   |-- safety_filter.py       PWM slew rate + anti-oscillation
|   |-- interface_adapter.py   PID/RL/Hybrid unified interface
|   |-- state_machine.py       Mode switching
|
|-- rl_env/                    Gymnasium RL environment
|   |-- car_env.py             CarEnv (10D obs, 5 discrete / 2 continuous)
|   |-- reward.py              Modular reward calculator
|   |-- observation.py         ObservationBuilder
|   |-- action_space.py        ActionEncoder
|   |-- curriculum.py          Curriculum manager
|   |-- domain_randomization.py
|   |-- training_monitor.py
|
|-- tracks/                    Track generation
|   |-- curriculum_track_generator.py  4-level curriculum
|   |-- reward_field.py        Gaussian soft penalty
|   |-- track_difficulty.py    Difficulty calculation
|   |-- real_world_mapper.py   Real track reconstruction
|   |-- validation/            Action feasibility + curriculum sanity
|
|-- calibration/               System identification
|   |-- calibration_loop.py    Single/batch calibration
|   |-- model_updater.py       EMA + momentum optimization
|   |-- trajectory_matcher.py  DTW trajectory alignment
|   |-- steering_model.py
|   |-- latency_model.py
|   |-- parameter_fitter.py
|
|-- control_sandbox/           PID sandbox evaluation
|   |-- controller_emulator.py STM32 SimpleController + AdvancedController
|   |-- plant_model.py         Learnable physics model
|   |-- sandbox_runner.py      Closed-loop simulation
|   |-- pid_optimizer.py       Grid search optimizer
|   |-- pid_ab_test.py         A/B/C controller comparison
|
|-- real_world/                Real car interface
|   |-- wifi_bridge.py         ESP01S WiFi (TCP) bridge
|   |-- real_car_env.py        Real car Gymnasium wrapper
|   |-- manifest_store.py      Data storage
|   |-- data_logger.py
|   |-- frame_parser.py        Binary frame parser
|   |-- telemetry_protocol.py
|
|-- hil/                       Hardware-in-the-Loop
|   |-- hil_sync_manager.py
|   |-- realtime_injector.py
|   |-- latency_estimator.py
|   |-- hil_controller_bridge.py
|
|-- training/                  Training pipeline
|   |-- train_pipeline.py      Unified training
|   |-- early_stopping.py      Patience-based
|   |-- checkpoint_manager.py  Save best + periodic
|   |-- curve_plotter.py       Training visualization
|
|-- replay/                    Replay system
|-- analysis/                  Analysis and evaluation
|-- scanner/                   3D scan pipeline
|-- stm32_compat/              STM32 HAL compatibility
|-- virtual_hw/                Virtual hardware bus
|-- behavior_match/            Behavior matching
|-- ui/                        Pygame UI panels
```

## Data Flow

```
[Real Car] --WiFi/TCP--> [WifiBridge] --Telemetry--> [Calibration Loop]
                                                            |
                                                            v
                                                     [PlantModel]
                                                            |
                                                            v
[PID/RL Controller] --> [PlantModel] --> [Sensor Sim] --> [Reward]
       ^                                         |
       |                                         v
       +------ [Safety Filter] <--- [Control Output]
```

## Control Modes

| Mode | Description | Controller |
|------|-------------|------------|
| PID | Standard IR sensor PID | LineFollowController |
| Camera | K230 camera-based PID | CameraLineFollower |
| STM32 | Faithful STM32 reimplementation | STM32FaithfulController |
| RL | Reinforcement learning | PPO/SAC policy |
| Hybrid | PID + RL blended | ControlAdapter |
| HIL | Real car driven | WifiBridge + VirtualHW |
