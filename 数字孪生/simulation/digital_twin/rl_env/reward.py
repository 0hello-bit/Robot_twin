# -*- coding: utf-8 -*-
"""
reward.py - RL Robust Reward System v3

模块化奖励函数, 支持:
- tracking error reward
- center reward
- smoothness penalty (加剧)
- speed bonus
- recovery bonus (丢线后重新找回奖励)
- shortcut penalty (level-specific)

核心原则: RL should learn CONTROL LAW, not track memorization.
禁止纯"贴线奖励主导", 必须多维度平衡。
"""

import math


# Level-specific shortcut penalty presets
# Level 3 (figure-8) gets devastating penalty to prevent crossing shortcuts
# Soft penalty config: replaced hard -100 with Gaussian fields
# penalty(x,y) = amplitude * exp(-dist^2 / (2*sigma^2))
# Continuous, differentiable, RL can learn gradients
SOFT_PENALTY_CONFIG = {
    1: {'sigma': 30.0, 'amplitude': -3.0, 'shortcut_jump_threshold': 0.15},
    2: {'sigma': 25.0, 'amplitude': -4.0, 'shortcut_jump_threshold': 0.12},
    3: {'sigma': 20.0, 'amplitude': -5.0, 'shortcut_jump_threshold': 0.08},
    4: {'sigma': 30.0, 'amplitude': -3.0, 'shortcut_jump_threshold': 0.15},
}


class RewardConfig:
    """奖励权重配置"""
    def __init__(self, **kwargs):
        # Positive rewards
        self.tracking = kwargs.get('tracking', 1.0)
        self.center = kwargs.get('center', 0.5)
        self.smooth = kwargs.get('smooth', 0.5)
        self.speed = kwargs.get('speed', 0.2)
        self.completion = kwargs.get('completion', 0.0)
        self.recovery_bonus = kwargs.get('recovery_bonus', 3.0)

        # Negative penalties
        self.penalty_lost = kwargs.get('penalty_lost', -5.0)
        self.penalty_osc = kwargs.get('penalty_osc', -1.0)
        self.penalty_collision = kwargs.get('penalty_collision', -10.0)
        self.soft_penalty_sigma = kwargs.get('soft_penalty_sigma', 25.0)
        self.soft_penalty_amplitude = kwargs.get('soft_penalty_amplitude', -5.0)
        self.shortcut_jump_threshold = kwargs.get('shortcut_jump_threshold', 0.12)
        self.penalty_control_effort = kwargs.get('penalty_control_effort', -0.1)


class RewardCalculator:
    """
    模块化奖励计算器 v3.

    每步返回:
        float: 总奖励
        dict:  各分项明细
    """

    def __init__(self, config=None):
        self.config = config or RewardConfig()
        self._prev_error = 0.0
        self._prev_steering = 0.0
        self._osc_count = 0
        self._step_count = 0
        self._total_distance = 0.0
        self._prev_track_idx = 0
        self._track_level = 1
        self._soft_penalty_sigma = self.config.soft_penalty_sigma
        self._soft_penalty_amplitude = self.config.soft_penalty_amplitude
        self._shortcut_threshold = self.config.shortcut_jump_threshold
        # Recovery tracking
        self._was_lost = False
        self._recovery_count = 0
        self._prev_left_pwm = 0.0
        self._prev_right_pwm = 0.0

    def set_level(self, level):
        """Set track level to apply level-specific soft penalties."""
        self._track_level = level
        preset = SOFT_PENALTY_CONFIG.get(level, {})
        self._soft_penalty_sigma = preset.get('sigma', self.config.soft_penalty_sigma)
        self._soft_penalty_amplitude = preset.get('amplitude', self.config.soft_penalty_amplitude)
        self._shortcut_threshold = preset.get('shortcut_jump_threshold', self.config.shortcut_jump_threshold)

    def compute(self, line_error, line_error_rate, speed, angular_velocity,
                is_lost, steering=0.0, dt=0.03, distance_along_track=0.0,
                track_idx=0, track_total=1,
                left_pwm=0.0, right_pwm=0.0):
        """
        计算一步奖励。

        参数:
            line_error:       归一化行线误差 [-1, 1]
            line_error_rate:  误差变化率
            speed:            归一化速度 [0, 1]
            angular_velocity: 归一化角速度 [-1, 1]
            is_lost:          是否丢线
            steering:         当前转向 [-1, 1]
            dt:               时间步长
            distance_along_track: 沿赛道前进距离
            left_pwm, right_pwm: 电机输出 (用于control effort计算)

        返回:
            (total_reward, breakdown_dict)
        """
        cfg = self.config
        breakdown = {}
        self._step_count += 1

        # 1. Tracking reward: 误差越小越好
        tracking = cfg.tracking * (1.0 - abs(line_error))
        breakdown['tracking'] = round(tracking, 4)

        # 2. Center reward: 鼓励居中
        center = cfg.center * max(0.0, 1.0 - abs(line_error) * 2.0)
        breakdown['center'] = round(center, 4)

        # 3. Smooth reward: 鼓励平滑转向 (v3: 更严格)
        steering_change = abs(steering - self._prev_steering)
        smooth = cfg.smooth * max(0.0, 1.0 - steering_change * 2.0)
        breakdown['smooth'] = round(smooth, 4)
        self._prev_steering = steering

        # 4. Speed reward: 鼓励维持速度
        speed_r = cfg.speed * speed
        breakdown['speed'] = round(speed_r, 4)

        # 5. Completion reward: 沿赛道前进
        completion = cfg.completion * distance_along_track * 0.01
        breakdown['completion'] = round(completion, 4)

        # 6. Recovery bonus: 丢线后重新找回巡线 (v3新增)
        recovery = 0.0
        if self._was_lost and not is_lost:
            recovery = cfg.recovery_bonus
            self._recovery_count += 1
        self._was_lost = is_lost
        breakdown['recovery'] = round(recovery, 4)

        # 7. Penalties
        penalty_lost = 0.0
        if is_lost:
            penalty_lost = cfg.penalty_lost
        breakdown['penalty_lost'] = round(penalty_lost, 4)

        # Oscillation penalty (v3: 加剧)
        penalty_osc = 0.0
        if self._step_count > 2:
            if line_error * self._prev_error < 0:
                self._osc_count += 1
                if self._osc_count > 3:
                    penalty_osc = cfg.penalty_osc * (self._osc_count - 3)
        breakdown['penalty_osc'] = round(penalty_osc, 4)

        self._prev_error = line_error

        # 8. Control effort penalty: 惩罚剧烈PWM变化 (v3新增)
        penalty_effort = 0.0
        if self._step_count > 1:
            d_left = abs(left_pwm - self._prev_left_pwm)
            d_right = abs(right_pwm - self._prev_right_pwm)
            effort = (d_left + d_right) / 2000.0
            penalty_effort = cfg.penalty_control_effort * effort
        self._prev_left_pwm = left_pwm
        self._prev_right_pwm = right_pwm
        breakdown['penalty_effort'] = round(penalty_effort, 4)

        # 9. Soft penalty: Gaussian field instead of hard penalty
        # Uses continuous differentiable penalty that RL can learn gradients from
        penalty_soft = 0.0
        if self._step_count > 1 and track_total > 0:
            progress_jump = abs(track_idx - self._prev_track_idx)
            normalized_jump = progress_jump / track_total
            if normalized_jump > self._shortcut_threshold:
                # Gaussian soft penalty: smooth falloff, not dead zone
                penalty_soft = self._soft_penalty_amplitude * math.exp(
                    -(normalized_jump ** 2) / (2.0 * self._soft_penalty_sigma * self._soft_penalty_sigma * 0.0001)
                )
        breakdown['penalty_soft'] = round(penalty_soft, 4)
        self._prev_track_idx = track_idx

        # Total
        total = sum(breakdown.values())
        breakdown['total'] = round(total, 4)

        return total, breakdown

    def reset(self):
        self._prev_error = 0.0
        self._prev_steering = 0.0
        self._osc_count = 0
        self._step_count = 0
        self._total_distance = 0.0
        self._prev_track_idx = 0
        self._was_lost = False
        self._recovery_count = 0
        self._prev_left_pwm = 0.0
        self._prev_right_pwm = 0.0

    def get_stats(self):
        return {
            'total_steps': self._step_count,
            'osc_count': self._osc_count,
            'recovery_count': self._recovery_count,
        }
