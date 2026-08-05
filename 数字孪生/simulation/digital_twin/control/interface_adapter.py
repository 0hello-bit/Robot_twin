# -*- coding: utf-8 -*-
"""
interface_adapter.py - 统一控制接口适配器

实现 PID / RL / Hybrid 三种控制模式的统一接口。
使 RL policy 输出、PID 控制器输出、STM32 兼容控制
全部通过同一个 ControlAdapter 传递给小车。

使用方式:
    adapter = ControlAdapter(mode='pid', pid_controller=my_pid)
    left, right = adapter.step(sensor_input, dt)

    adapter = ControlAdapter(mode='rl', rl_policy=my_policy)
    left, right = adapter.step(sensor_input, dt)

    adapter = ControlAdapter(mode='hybrid', pid_controller=my_pid,
                             rl_policy=my_rl, blend=0.5)
    left, right = adapter.step(sensor_input, dt)
"""

from enum import Enum
import numpy as np

from control.base_controller import BaseController, ControllerOutput, LineFollowController
from control.safety_filter import SafetyFilter


class ControlMode(Enum):
    PID     = 'pid'
    RL      = 'rl'
    HYBRID  = 'hybrid'


class ControlAdapter:
    """
    统一控制适配器。

    将不同来源的控制信号 (PID / RL / Hybrid) 统一为:
        (left_speed, right_speed) 归一化速度 (-1 ~ 1)

    同时:
        - 记录每一步的控制来源
        - 携带传感器读数和误差信息
        - 经过 SafetyFilter 后输出
    """

    def __init__(self, mode='pid', pid_controller=None, rl_policy=None,
                 blend=0.5, safety_filter=None, base_speed=200):
        """
        参数:
            mode:            'pid' / 'rl' / 'hybrid'
            pid_controller:  BaseController 实例 (LineFollowController)
            rl_policy:       RL policy 对象, 需有 predict(obs) -> action
            blend:           hybrid 模式下 RL 占比 (0~1)
            safety_filter:   SafetyFilter 实例 (None 则自动创建)
            base_speed:      基础 PWM 速度
        """
        self.mode = ControlMode(mode)
        self.pid_controller = pid_controller
        self.rl_policy = rl_policy
        self.blend = max(0.0, min(1.0, blend))
        self.base_speed = base_speed

        if pid_controller is None and self.mode in (ControlMode.PID, ControlMode.HYBRID):
            self.pid_controller = LineFollowController(base_speed=base_speed)

        self.safety = safety_filter or SafetyFilter()

        # RL action encoder (from rl_env.action_space)
        self._rl_encoder = None
        if self.rl_policy is not None:
            from rl_env.action_space import ActionEncoder
            self._rl_encoder = ActionEncoder(
                mode='continuous', base_speed=base_speed)

        # 记录
        self._last_mode_source = 'pid'
        self._step_count = 0
        self._last_output = None

    def step(self, sensor_input, dt, observation=None):
        """
        执行一步控制。

        参数:
            sensor_input:  [S0, S1, S2, S3] 传感器状态
            dt:            时间步长 (s)
            observation:   RL 观测向量 (RL/hybrid 模式需要)

        返回:
            ControllerOutput: 统一控制输出
        """
        if self.mode == ControlMode.PID:
            return self._step_pid(sensor_input, dt)
        elif self.mode == ControlMode.RL:
            return self._step_rl(sensor_input, dt, observation)
        elif self.mode == ControlMode.HYBRID:
            return self._step_hybrid(sensor_input, dt, observation)
        return ControllerOutput()

    def _step_pid(self, sensor_input, dt):
        out = self.pid_controller.update(sensor_input, dt)
        out = self.safety.filter(out)
        out.metadata['source'] = 'pid'
        self._last_mode_source = 'pid'
        self._step_count += 1
        self._last_output = out
        return out

    def _step_rl(self, sensor_input, dt, observation):
        if self.rl_policy is None or self._rl_encoder is None:
            return self._step_pid(sensor_input, dt)

        if observation is None:
            observation = np.zeros(10, dtype=np.float32)

        action, _ = self.rl_policy.predict(observation, deterministic=True)
        left_pwm, right_pwm = self._rl_encoder.encode(action)

        left_norm = (left_pwm / 999.0) * 2.0 - 1.0
        right_norm = (right_pwm / 999.0) * 2.0 - 1.0

        out = ControllerOutput()
        out.left_speed = max(-1.0, min(1.0, left_norm))
        out.right_speed = max(-1.0, min(1.0, right_norm))
        out.sensor_reading = list(sensor_input)

        position = 0.0
        black_count = 0
        for i, s in enumerate(sensor_input):
            if s == 0:
                position += [-3, -1, 1, 3][i]
                black_count += 1
        out.error = position

        out = self.safety.filter(out)
        out.metadata['source'] = 'rl'
        out.metadata['rl_action'] = (
            action.tolist() if hasattr(action, 'tolist') else action)
        self._last_mode_source = 'rl'
        self._step_count += 1
        self._last_output = out
        return out

    def _step_hybrid(self, sensor_input, dt, observation):
        pid_out = self.pid_controller.update(sensor_input, dt)
        pid_left = pid_out.left_speed
        pid_right = pid_out.right_speed

        rl_left, rl_right = pid_left, pid_right
        if self.rl_policy is not None and self._rl_encoder is not None:
            if observation is None:
                observation = np.zeros(10, dtype=np.float32)
            action, _ = self.rl_policy.predict(observation, deterministic=True)
            left_pwm, right_pwm = self._rl_encoder.encode(action)
            rl_left = (left_pwm / 999.0) * 2.0 - 1.0
            rl_right = (right_pwm / 999.0) * 2.0 - 1.0

        alpha = self.blend
        out = ControllerOutput()
        out.left_speed = max(-1.0, min(1.0,
            pid_left * (1 - alpha) + rl_left * alpha))
        out.right_speed = max(-1.0, min(1.0,
            pid_right * (1 - alpha) + rl_right * alpha))
        out.sensor_reading = list(sensor_input)
        out.error = pid_out.error
        out.raw_pid = pid_out.raw_pid

        out = self.safety.filter(out)
        out.metadata['source'] = 'hybrid'
        out.metadata['blend'] = alpha
        self._last_mode_source = 'hybrid'
        self._step_count += 1
        self._last_output = out
        return out

    def set_mode(self, mode):
        self.mode = ControlMode(mode)

    def set_blend(self, blend):
        self.blend = max(0.0, min(1.0, blend))

    def set_rl_policy(self, policy):
        self.rl_policy = policy
        if policy is not None:
            from rl_env.action_space import ActionEncoder
            self._rl_encoder = ActionEncoder(
                mode='continuous', base_speed=self.base_speed)
        else:
            self._rl_encoder = None

    def reset(self):
        if self.pid_controller:
            self.pid_controller.reset()
        self._step_count = 0
        self._last_output = None

    def get_info(self):
        return {
            'mode': self.mode.value,
            'source': self._last_mode_source,
            'steps': self._step_count,
            'blend': self.blend if self.mode == ControlMode.HYBRID else 0,
            'safety_stats': self.safety.get_stats(),
        }
