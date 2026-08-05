# RL Architecture - STM32 数字孪生 RL 环境

## 概述

本模块将 STM32 麦轮巡线小车数字孪生平台升级为标准 RL 训练环境，
兼容 Gymnasium 协议，可直接接入 Stable-Baselines3。

---

## 目录结构

```
rl_env/
├── __init__.py                  # 模块入口
├── car_env.py                   # Gymnasium 兼容环境
├── observation.py               # 状态空间设计
├── action_space.py              # 动作空间设计
├── reward.py                    # 模块化奖励函数
├── curriculum.py                # 课程学习系统
├── domain_randomization.py      # 域随机化
└── training_monitor.py          # 训练监控

tracks/
└── random_track_generator.py    # 随机赛道生成器
```

---

## 1. 状态空间 (Observation Space)

10 维归一化连续向量:

| Index | 名称 | 范围 | 说明 |
|-------|------|------|------|
| 0-3 | sensor_0~3 | [0, 1] | 4路连续灰度传感器 (归一化) |
| 4 | line_error | [-1, 1] | 行线偏差 (加权位置/3) |
| 5 | line_error_rate | [-1, 1] | 偏差变化率 |
| 6 | speed | [0, 1] | 当前速度 (归一化) |
| 7 | angular_velocity | [-1, 1] | 角速度 (归一化) |
| 8 | distance_from_center | [0, 1] | 到赛道中心距离 |
| 9 | track_curvature | [0, 1] | 赛道曲率 (角速度近似) |

**设计原则:**
- 所有状态归一化到固定范围
- 不使用图像 (低维高效)
- 支持未来扩展 (IMU / 编码器)

---

## 2. 动作空间 (Action Space)

### 模式 1: 离散 (Discrete)

```
0: LEFT         → steering=-1.0, speed=70%
1: SLIGHT_LEFT  → steering=-0.5, speed=85%
2: STRAIGHT     → steering= 0.0, speed=100%
3: SLIGHT_RIGHT → steering=+0.5, speed=85%
4: RIGHT        → steering=+1.0, speed=70%
```

### 模式 2: 连续 (Continuous)

```
action = [steering, speed]
steering ∈ [-1.0, +1.0]   # 转向
speed    ∈ [ 0.0,  1.0]   # 速度系数
```

---

## 3. 奖励函数 (Reward Function)

模块化设计, 权重可配置:

| 分项 | 权重 | 说明 |
|------|------|------|
| tracking | 1.0 | 误差越小奖励越高 |
| center | 0.5 | 鼓励居中行驶 |
| smooth | 0.3 | 鼓励转向平滑 |
| speed | 0.2 | 鼓励维持速度 |
| completion | 0.0 | 沿赛道前进距离 |
| penalty_lost | -5.0 | 丢线惩罚 |
| penalty_osc | -0.5 | 震荡惩罚 |
| penalty_collision | -10.0 | 碰撞惩罚 (预留) |

使用方式:
```python
from rl_env.reward import RewardCalculator, RewardConfig
config = RewardConfig(tracking=1.5, penalty_lost=-10.0)
calc = RewardCalculator(config)
```

---

## 4. 赛道生成 (Track Generation)

支持赛道类型:

| 类型 | 说明 |
|------|------|
| oval | 椭圆赛道 (默认) |
| figure8 | 8 字赛道 |
| s_curve | S 弯赛道 |
| cross | 十字赛道 |
| random_oval | 随机参数椭圆 |
| random_combo | 随机组合 |

随机赛道生成器:
```python
from tracks.random_track_generator import TrackGenerator
gen = TrackGenerator(seed=42)
points = gen.generate('random_combo')
track.add_polyline(points)
```

---

## 5. 课程学习 (Curriculum)

4 级难度递进:

| 阶段 | 赛道 | 噪声 | 速度 | 最大步数 |
|------|------|------|------|----------|
| easy | oval | 无 | 0.8x | 500 |
| medium | oval | 有 | 1.0x | 1000 |
| hard | figure8 | 有 | 1.0x | 1500 |
| expert | random | 有 | 1.2x | 2000 |

自动升级: 当最近 50 个 episode 平均奖励 > 阈值时自动进入下一阶段。

---

## 6. 域随机化 (Domain Randomization)

随机化参数:

| 参数 | 范围 |
|------|------|
| motor_gain | 0.7x ~ 1.3x |
| motor_offset | ±0.05 |
| steering_K | 0.8x ~ 1.2x |
| steering_tau | 0.7x ~ 1.3x |
| velocity_damping | 0.9x ~ 1.1x |
| angular_damping | 0.9x ~ 1.1x |
| sensor_noise_prob | 0 ~ 10% |
| motor_noise_std | 0 ~ 8% |
| position_noise_std | 0 ~ 2px |

---

## 7. 接入方案

### Q-Learning

```python
from rl_env import CarEnv
env = CarEnv(action_mode='discrete', track_type='oval')
# 离散状态 → 离散化到 grid → Q-table
```

### DQN

```python
from rl_env import CarEnv
env = CarEnv(action_mode='discrete')
# 10维状态 → 5个离散动作
# 输入: Box(10,), 输出: Discrete(5)
```

### PPO

```python
from rl_env import CarEnv
env = CarEnv(action_mode='continuous')
# 10维状态 → 2维连续动作
# 输入: Box(10,), 输出: Box(2,)
```

### Stable-Baselines3

```python
from rl_env import CarEnv
from stable_baselines3 import PPO, DQN

env = CarEnv(action_mode='continuous', track_type='oval')
model = PPO('MlpPolicy', env, verbose=1)
model.learn(total_timesteps=100000)
```

---

## 8. 设计决策

1. **不依赖 gymnasium 包** — 实现协议而非依赖包
2. **不修改现有代码** — 所有 RL 代码在新目录
3. **支持双动作模式** — 离散/连续可切换
4. **归一化状态** — 方便神经网络训练
5. **模块化奖励** — 可自由组合
6. **域随机化** — 提高 Sim2Real 能力

---

## 9. 未来扩展方向

- [ ] 堆叠帧 (连续多步观测)
- [ ] 课程学习自动调度
- [ ] 多目标奖励 (Pareto)
- [ ] 虚拟串口映射真实 STM32
- [ ] 图像观测 (可选)
- [ ] 多智能体 (多车)