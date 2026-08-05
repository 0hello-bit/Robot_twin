# -*- coding: utf-8 -*-
"""
safety_filter.py - 控制安全过滤层

限制:
    - PWM 最大变化率 (slew rate)
    - 转向最大变化量 (per tick)
    - 反震荡阻尼
    - 输出限幅

任何控制器输出在到达小车之前必须经过此层。
"""

from control.base_controller import ControllerOutput


class SafetyFilter:
    """
    控制输出安全过滤器。

    模拟真实 STM32 中 PWM 限幅和斜率限制,
    防止 RL policy 输出导致小车失控。
    """

    def __init__(self,
                 max_speed=1.0,
                 min_speed=-1.0,
                 max_slew_rate=0.15,
                 max_steering_delta=0.3,
                 damping=0.0,
                 anti_oscillation_window=5,
                 anti_oscillation_threshold=0.4):
        """
        参数:
            max_speed:                 最大归一化速度
            min_speed:                 最小归一化速度 (负值 = 后退)
            max_slew_rate:             每 tick 最大速度变化量
            max_steering_delta:        每 tick 最大转向变化量
            damping:                   震荡阻尼系数 (0=关闭)
            anti_oscillation_window:   震荡检测窗口
            anti_oscillation_threshold: 震荡检测阈值
        """
        self.max_speed = max_speed
        self.min_speed = min_speed
        self.max_slew_rate = max_slew_rate
        self.max_steering_delta = max_steering_delta
        self.damping = damping
        self.anti_osc_window = anti_oscillation_window
        self.anti_osc_threshold = anti_oscillation_threshold

        self._prev_left = 0.0
        self._prev_right = 0.0
        self._prev_steering = 0.0
        self._osc_history = []
        self._clip_count = 0
        self._slew_count = 0
        self._osc_count = 0

    def filter(self, output):
        """
        过滤控制输出。

        参数:
            output: ControllerOutput

        返回:
            ControllerOutput: 过滤后的输出
        """
        left = output.left_speed
        right = output.right_speed

        left = max(self.min_speed, min(self.max_speed, left))
        right = max(self.min_speed, min(self.max_speed, right))

        left = self._limit_slew(left, self._prev_left)
        right = self._limit_slew(right, self._prev_right)

        steering = left - right
        steering_delta = steering - self._prev_steering
        if abs(steering_delta) > self.max_steering_delta:
            sign = 1.0 if steering_delta > 0 else -1.0
            steering = self._prev_steering + sign * self.max_steering_delta
            avg = (left + right) / 2.0
            left = avg + steering / 2.0
            right = avg - steering / 2.0
            left = max(self.min_speed, min(self.max_speed, left))
            right = max(self.min_speed, min(self.max_speed, right))
            self._osc_count += 1

        if self.damping > 0:
            left = left * (1 - self.damping) + self._prev_left * self.damping
            right = right * (1 - self.damping) + self._prev_right * self.damping

        if self._detect_oscillation(steering):
            left = left * 0.7 + self._prev_left * 0.3
            right = right * 0.7 + self._prev_right * 0.3

        self._prev_left = left
        self._prev_right = right
        self._prev_steering = left - right

        output.left_speed = left
        output.right_speed = right
        output.metadata['safety_filtered'] = True
        return output

    def _limit_slew(self, new_val, prev_val):
        delta = new_val - prev_val
        if abs(delta) > self.max_slew_rate:
            sign = 1.0 if delta > 0 else -1.0
            self._slew_count += 1
            return prev_val + sign * self.max_slew_rate
        return new_val

    def _detect_oscillation(self, steering):
        self._osc_history.append(steering)
        if len(self._osc_history) > self.anti_osc_window:
            self._osc_history.pop(0)
        if len(self._osc_history) < 3:
            return False
        sign_changes = 0
        for i in range(1, len(self._osc_history)):
            if self._osc_history[i] * self._osc_history[i-1] < 0:
                sign_changes += 1
        if sign_changes >= len(self._osc_history) - 1:
            magnitudes = [abs(x) for x in self._osc_history]
            if sum(magnitudes) / len(magnitudes) > self.anti_osc_threshold:
                self._osc_count += 1
                return True
        return False

    def reset(self):
        self._prev_left = 0.0
        self._prev_right = 0.0
        self._prev_steering = 0.0
        self._osc_history.clear()
        self._clip_count = 0
        self._slew_count = 0
        self._osc_count = 0

    def get_stats(self):
        return {
            'slew_limited': self._slew_count,
            'osc_dampened': self._osc_count,
        }
