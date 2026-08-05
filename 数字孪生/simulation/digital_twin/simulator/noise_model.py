# -*- coding: utf-8 -*-
"""
noise_model.py - 真实世界误差建模
模拟传感器噪声、控制延迟、电机响应滞后、地面扰动等。
所有噪声源均可独立开关，不影响原系统结构。
"""

import random
import collections
import config as cfg


class SensorNoiseModel:
    """
    传感器噪声模型。
    
    1. 随机误判: 0~5% 概率翻转传感器状态
    2. 边缘模糊: 传感器在黑线边缘时概率性检测
    """

    def __init__(self):
        self.enabled = False
        self.misread_prob = 0.03      # 随机误判概率 (3%)
        self.edge_blur_prob = 0.15    # 边缘模糊概率
        self.edge_margin = 4.0        # 边缘模糊带宽 (px)

    def apply(self, sensor_states, sensor_positions, track_map):
        """
        对传感器读数注入噪声。
        
        参数:
            sensor_states: [S0..S3] 原始状态
            sensor_positions: [(x,y), ...] 传感器世界坐标
            track_map: TrackMap 对象 (用于计算边缘距离)
        
        返回:
            [S0..S3] 噪声后的状态
        """
        if not self.enabled:
            return sensor_states

        result = list(sensor_states)
        for i, (state, (sx, sy)) in enumerate(zip(sensor_states, sensor_positions)):
            # 随机误判
            if random.random() < self.misread_prob:
                result[i] = 1 - state  # 翻转
                continue

            # 边缘模糊: 距离黑线边缘在 edge_margin 内时概率翻转
            dist = track_map.get_distance_to_track(sx, sy)
            half_w = cfg.TRACK_WIDTH / 2.0
            edge_dist = abs(dist - half_w)
            if edge_dist < self.edge_margin:
                blur_chance = self.edge_blur_prob * (1.0 - edge_dist / self.edge_margin)
                if random.random() < blur_chance:
                    result[i] = 1 - state

        return result


class ControlDelayModel:
    """
    控制延迟模型。
    
    模拟 STM32 中断响应延迟 + PWM 输出滞后。
    使用 FIFO 队列实现 N 步延迟。
    """

    def __init__(self, delay_steps=2):
        """
        参数:
            delay_steps: 延迟步数 (1~3个控制周期)
        """
        self.enabled = False
        self.delay_steps = max(0, min(5, delay_steps))
        self._buffer = collections.deque(maxlen=self.delay_steps + 1)

    def push(self, left, right):
        """推入当前控制命令"""
        self._buffer.append((left, right))

    def pop(self):
        """
        弹出延迟后的控制命令。
        如果缓冲区未满，返回最新命令。
        """
        if not self.enabled or len(self._buffer) == 0:
            return (0.0, 0.0)
        if len(self._buffer) <= self.delay_steps:
            return self._buffer[0]
        return self._buffer.popleft()

    def set_delay(self, steps):
        """动态设置延迟步数"""
        self.delay_steps = max(0, min(5, steps))
        self._buffer = collections.deque(maxlen=self.delay_steps + 1)

    def clear(self):
        self._buffer.clear()


class MotorResponseModel:
    """
    电机响应延迟模型。
    
    模拟 PWM 变化到实际转速之间的惯性滞后。
    一阶低通滤波: actual += (target - actual) * tau
    """

    def __init__(self, tau=0.15):
        """
        参数:
            tau: 时间常数 (0~1), 越小越慢, 0=无限慢, 1=瞬时
        """
        self.enabled = False
        self.tau = tau
        self.actual_left = 0.0
        self.actual_right = 0.0

    def update(self, target_left, target_right, dt):
        """
        更新电机实际输出。
        
        返回:
            (actual_left, actual_right)
        """
        if not self.enabled:
            self.actual_left = target_left
            self.actual_right = target_right
            return target_left, target_right

        alpha = 1.0 - (1.0 - self.tau) ** (dt * 60)  # 帧率归一化
        self.actual_left += (target_left - self.actual_left) * alpha
        self.actual_right += (target_right - self.actual_right) * alpha
        return self.actual_left, self.actual_right

    def reset(self):
        self.actual_left = 0.0
        self.actual_right = 0.0


class VelocityPerturbationModel:
    """
    速度扰动模型。
    
    模拟地面不均匀、轮子打滑等随机扰动。
    """

    def __init__(self):
        self.enabled = False
        self.amplitude = 0.03  # 扰动幅度 (归一化速度的百分比)
        self._last_perturb_left = 0.0
        self._last_perturb_right = 0.0

    def get_perturbation(self):
        """
        生成新的随机扰动值。
        使用随机游走 (Random Walk) 模型，使扰动平滑。
        """
        if not self.enabled:
            return 0.0, 0.0

        # 随机游走: 在上一次基础上小幅度随机变化
        self._last_perturb_left += random.gauss(0, self.amplitude * 0.3)
        self._last_perturb_right += random.gauss(0, self.amplitude * 0.3)

        # 限幅
        self._last_perturb_left = max(-self.amplitude, min(self.amplitude, self._last_perturb_left))
        self._last_perturb_right = max(-self.amplitude, min(self.amplitude, self._last_perturb_right))

        # 缓慢回归零点
        self._last_perturb_left *= 0.98
        self._last_perturb_right *= 0.98

        return self._last_perturb_left, self._last_perturb_right

    def reset(self):
        self._last_perturb_left = 0.0
        self._last_perturb_right = 0.0


class WorldNoiseModel:
    """
    统一噪声管理器。
    聚合所有噪声源，提供统一接口。
    """

    def __init__(self):
        self.sensor_noise = SensorNoiseModel()
        self.control_delay = ControlDelayModel(delay_steps=2)
        self.motor_response = MotorResponseModel(tau=0.15)
        self.velocity_perturbation = VelocityPerturbationModel()

    def apply_sensor_noise(self, states, positions, track_map):
        return self.sensor_noise.apply(states, positions, track_map)

    def apply_control_delay(self, left, right):
        self.control_delay.push(left, right)
        return self.control_delay.pop()

    def apply_motor_response(self, left, right, dt):
        return self.motor_response.update(left, right, dt)

    def apply_velocity_perturbation(self):
        return self.velocity_perturbation.get_perturbation()

    def reset_all(self):
        self.control_delay.clear()
        self.motor_response.reset()
        self.velocity_perturbation.reset()

    def get_status(self):
        """获取所有噪声模块的开关状态"""
        return {
            'sensor_noise': self.sensor_noise.enabled,
            'control_delay': self.control_delay.enabled,
            'motor_response': self.motor_response.enabled,
            'velocity_perturbation': self.velocity_perturbation.enabled,
        }
