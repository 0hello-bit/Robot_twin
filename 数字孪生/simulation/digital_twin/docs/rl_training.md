# RL Training Guide

## Environment

Gymnasium-compatible `CarEnv` with:

### Observation Space (10D)
```
[sensor0, sensor1, sensor2, sensor3,
 line_error, line_error_rate,
 speed, angular_velocity,
 distance_from_center, track_curvature]
```

### Action Space
- **Discrete(5)**: LEFT, SLIGHT_LEFT, STRAIGHT, SLIGHT_RIGHT, RIGHT
- **Continuous(2)**: [steering, speed] in [-1,1] x [0,1]

## Curriculum Tracks

| Level | Type | Points | Complexity |
|-------|------|--------|------------|
| 1 | Ellipse | 159 | Baseline |
| 2 | Sine Wave | 238 | Variable curvature |
| 3 | Figure-8 | 603 | Crossing + penalty |
| 4 | Rounded Rect | 257 | Sharp turns |

## Training

```bash
# Basic PPO training
python train_ppo.py

# With specific level
python train_ppo.py --level 1

# Test trained model
python train_ppo.py --test --model models/ppo_car.zip
```

## Reward Function

Modular reward with configurable weights:
- tracking_reward: stay on line
- center_reward: prefer line center
- smooth_reward: penalize jitter
- speed_reward: encourage movement
- completion_reward: lap progress
- penalty_lost_line: lost line penalty
- penalty_oscillation: oscillation penalty

Gaussian soft penalty fields replace hard penalties for differentiable gradients.
