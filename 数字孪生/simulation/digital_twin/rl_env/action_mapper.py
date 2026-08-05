# -*- coding: utf-8 -*-
"""
action_mapper.py - RL Action → STM32 Motor 映射

将 RL policy 输出 (离散/连续) 统一映射为:
    - ControllerOutput (与 PID 输出格式完全一致)
    - STM32 兼容的 motor command

确保:
    1. RL action 和 PID output 可以直接对比
    2. 同一个小车模型接收两种控制信号
    3. 映射关系可配置、可记录
"""

import numpy as np
from control.base_controller import ControllerOutput
from rl_env.action_space import ActionEncoder


class ActionMapper:
    """
    RL 动作到电机控制的映射器。

    职责:
        - 将 RL policy 输出转换为 ControllerOutput
        - 确保与 PID 输出格式一致
        - 可记录映射历史
    """

    def __init__(self, mode='continuous', base_speed=200, max_pwm=999):
        self.encoder = ActionEncoder(mode=mode, base_speed=base_speed, max_pwm=max_pwm)
        self.base_speed = base_speed
        self.max_pwm = max_pwm
        self._history = []

    def map_to_output(self, action, sensor_input=None):
        """
        将 RL action 映射为 ControllerOutput。

        参数:
            action:        RL policy 输出
            sensor_input:  传感器读数 [S0..S3] (可选)

        返回:
            ControllerOutput: 与 PID 格式一致
        """
        left_pwm, right_pwm = self.encoder.encode(action)

        out = ControllerOutput()
        out.left_speed = (left_pwm / self.max_pwm) * 2.0 - 1.0
        out.right_speed = (right_pwm / self.max_pwm) * 2.0 - 1.0
        out.left_speed = max(-1.0, min(1.0, out.left_speed))
        out.right_speed = max(-1.0, min(1.0, out.right_speed))

        if sensor_input is not None:
            out.sensor_reading = list(sensor_input)
            weights = [-3.0, -1.0, 1.0, 3.0]
            position = 0.0
            for i, s in enumerate(sensor_input):
                if s == 0:
                    position += weights[i]
            out.error = position

        out.metadata['source'] = 'rl_action_mapper'
        if hasattr(action, 'tolist'):
            out.metadata['raw_action'] = action.tolist()
        else:
            out.metadata['raw_action'] = action
        out.metadata['left_pwm'] = left_pwm
        out.metadata['right_pwm'] = right_pwm

        self._history.append({
            'action': out.metadata['raw_action'],
            'left_pwm': left_pwm,
            'right_pwm': right_pwm,
            'left_speed': out.left_speed,
            'right_speed': out.right_speed,
        })

        return out

    def get_history(self):
        return list(self._history)

    def clear_history(self):
        self._history.clear()

    def set_mode(self, mode):
        self.encoder = ActionEncoder(
            mode=mode, base_speed=self.base_speed, max_pwm=self.max_pwm)

    def set_base_speed(self, speed):
        self.base_speed = speed
        self.encoder.base_speed = speed
