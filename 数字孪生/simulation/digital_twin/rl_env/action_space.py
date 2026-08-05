# -*- coding: utf-8 -*-
"""
action_space.py - 动作空间设计

支持离散 (5 档) 和连续 (steering + speed) 两种模式。
"""

import numpy as np


# ── 离散动作定义 ──

DISCRETE_ACTIONS = {
    0: {'name': 'LEFT',         'steering': -1.0, 'speed_factor': 0.7},
    1: {'name': 'SLIGHT_LEFT',  'steering': -0.5, 'speed_factor': 0.85},
    2: {'name': 'STRAIGHT',     'steering':  0.0, 'speed_factor': 1.0},
    3: {'name': 'SLIGHT_RIGHT', 'steering':  0.5, 'speed_factor': 0.85},
    4: {'name': 'RIGHT',        'steering':  1.0, 'speed_factor': 0.7},
}

DISCRETE_NAMES = [DISCRETE_ACTIONS[i]['name'] for i in range(5)]


class ActionEncoder:
    """
    将 RL 动作转换为 (left_pwm, right_pwm)。

    支持:
        - 离散: 5 档方向 + 固定速度
        - 连续: (steering, speed) ∈ [-1,1] × [0,1]
    """

    def __init__(self, mode='discrete', base_speed=200, max_pwm=999):
        """
        参数:
            mode:       'discrete' 或 'continuous'
            base_speed: 基础 PWM 速度
            max_pwm:    最大 PWM 值
        """
        self.mode = mode
        self.base_speed = base_speed
        self.max_pwm = max_pwm

    def encode(self, action):
        """
        将 RL 动作编码为 (left_pwm, right_pwm)。

        参数:
            action: int (离散) 或 np.ndarray/list (连续)

        返回:
            tuple: (left_pwm, right_pwm) ∈ [0, max_pwm]
        """
        if self.mode == 'discrete':
            return self._encode_discrete(int(action))
        else:
            return self._encode_continuous(action)

    def _encode_discrete(self, action_idx):
        a = DISCRETE_ACTIONS.get(action_idx, DISCRETE_ACTIONS[2])
        steering = a['steering']
        speed_f = a['speed_factor']

        base = self.base_speed * speed_f
        diff = steering * base * 0.5

        left = max(0, min(self.max_pwm, base + diff))
        right = max(0, min(self.max_pwm, base - diff))
        return (left, right)

    def _encode_continuous(self, action):
        steering = float(np.clip(action[0], -1.0, 1.0))
        speed = float(np.clip(action[1], 0.0, 1.0))

        base = self.base_speed * (0.3 + 0.7 * speed)
        diff = steering * base * 0.5

        left = max(0, min(self.max_pwm, base + diff))
        right = max(0, min(self.max_pwm, base - diff))
        return (left, right)

    def get_num_actions(self):
        if self.mode == 'discrete':
            return 5
        else:
            return 2  # (steering, speed)

    def get_action_space_info(self):
        if self.mode == 'discrete':
            return {
                'type': 'discrete',
                'n': 5,
                'actions': DISCRETE_NAMES,
            }
        else:
            return {
                'type': 'continuous',
                'shape': (2,),
                'low': np.array([-1.0, 0.0], dtype=np.float32),
                'high': np.array([1.0, 1.0], dtype=np.float32),
            }

    def random_action(self, rng=None):
        if rng is None:
            rng = np.random
        if self.mode == 'discrete':
            return rng.randint(0, 5)
        else:
            return np.array([
                rng.uniform(-1.0, 1.0),
                rng.uniform(0.0, 1.0),
            ], dtype=np.float32)