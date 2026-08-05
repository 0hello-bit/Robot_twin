# -*- coding: utf-8 -*-
"""
analog_sensor.py - 连续灰度传感器模型

将离散 0/1 传感器升级为连续 0~1023 灰度值。

核心原理:
    每个传感器点到黑线中心的距离 → 高斯衰减 → 灰度值

    距离=0 (在黑线上) → 值≈0 (暗/黑)
    距离→∞ (远离黑线) → 值≈1023 (亮/白)

公式:
    value = 1023 * (1 - exp(-dist^2 / (2 * sigma^2)))

其中 sigma 控制传感器的"感知宽度"。

使用方式:
    sensor = AnalogSensorArray(sigma=8.0, resolution=1023)
    readings = sensor.read(x, y, angle, track)
    # readings = [120, 350, 820, 950]

与离散模式兼容:
    readings = sensor.read(x, y, angle, track)
    discrete = sensor.to_discrete(readings, threshold=512)
    # discrete = [0, 0, 1, 1]
"""

import math
import random


class AnalogSensorArray:
    """
    连续灰度传感器阵列。

    模拟真实红外模拟传感器的行为:
    - 输出连续值 (0~resolution)
    - 值与到黑线距离呈高斯衰减关系
    - 支持噪声注入
    - 支持离散化 (兼容现有系统)

    使用:
        sensor = AnalogSensorArray()
        readings = sensor.read(x, y, angle, track)
    """

    def __init__(self, sigma=None, resolution=1023,
                 sensor_offsets=None, sensor_front=None, sensor_radius=None):
        """
        参数:
            sigma:          高斯衰减标准差 (px), 控制感知宽度
            resolution:     输出分辨率 (默认 0~1023, 与 ADC 对齐)
            sensor_offsets: 传感器横向偏移列表 (px)
            sensor_front:   传感器距车体中心的前方距离 (px)
            sensor_radius:  传感器物理半径 (px)
        """
        import config as cfg

        self.sigma = sigma if sigma is not None else 8.0
        self.resolution = resolution
        self.sensor_offsets = sensor_offsets or list(cfg.SENSOR_OFFSETS)
        self.sensor_front = sensor_front if sensor_front is not None else cfg.SENSOR_FRONT
        self.sensor_radius = sensor_radius if sensor_radius is not None else cfg.SENSOR_RADIUS

        # 噪声参数
        self.noise_enabled = False
        self.noise_std = 15.0        # 高斯噪声标准差 (ADC 单位)
        self.noise_prob = 0.03       # 脉冲噪声概率

    def read(self, x, y, angle, track):
        """
        读取 4 路连续灰度传感器。

        参数:
            x, y:    车体中心坐标
            angle:   车体朝向 (度)
            track:   TrackMap 实例

        返回:
            list[int]: 4 个灰度值, 每个 ∈ [0, resolution]
        """
        if track is None:
            return [self.resolution] * 4

        rad = math.radians(angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        readings = []
        for off in self.sensor_offsets:
            # 传感器位置 (车体坐标 → 世界坐标)
            sx = x + self.sensor_front * cos_a - off * sin_a
            sy = y + self.sensor_front * sin_a + off * cos_a

            # 到黑线中心的距离
            dist = track.get_distance_to_track(sx, sy)

            # 考虑传感器物理半径: 取半径内的平均距离
            # 简化: 使用中心点距离减去传感器半径的一半
            effective_dist = max(0.0, dist - self.sensor_radius * 0.3)

            # 高斯衰减: 距离越远, 值越亮 (越接近 resolution)
            # value = resolution * (1 - exp(-d^2 / (2*sigma^2)))
            ratio = effective_dist * effective_dist / (2.0 * self.sigma * self.sigma)
            value = self.resolution * (1.0 - math.exp(-ratio))

            # 限制范围
            value = max(0, min(self.resolution, value))

            readings.append(round(value))

        # 注入噪声
        if self.noise_enabled:
            readings = self._add_noise(readings)

        return readings

    def _add_noise(self, readings):
        """注入混合噪声 (高斯 + 脉冲)"""
        noisy = []
        for val in readings:
            v = float(val)

            # 高斯噪声 (模拟 ADC 噪声)
            v += random.gauss(0, self.noise_std)

            # 脉冲噪声 (模拟瞬时干扰)
            if random.random() < self.noise_prob:
                v = random.uniform(0, self.resolution)

            v = max(0, min(self.resolution, v))
            noisy.append(round(v))
        return noisy

    def to_discrete(self, readings, threshold=None):
        """
        将连续读数离散化为 0/1。

        参数:
            readings:  list[int] - 连续灰度值
            threshold: 阈值 (默认 resolution/2)

        返回:
            list[int]: 0=黑线, 1=白底
        """
        if threshold is None:
            threshold = self.resolution // 2
        return [0 if v < threshold else 1 for v in readings]

    def read_position(self, readings):
        """
        从连续读数计算加权位置 (替代离散 weighted sum)。

        使用灰度值的"暗度"作为权重:
            darkness = resolution - value   (越暗值越大)
            position = sum(darkness_i * weight_i) / sum(darkness_i)

        参数:
            readings: list[int] - 连续灰度值

        返回:
            float: 加权位置 (与离散模式的 position 同范围)
        """
        weights = [-3.0, -1.0, 1.0, 3.0]
        total_weight = 0.0
        weighted_sum = 0.0

        for i, val in enumerate(readings):
            # 暗度: 值越小 (越暗) 暗度越大
            darkness = max(0, self.resolution - val)
            weighted_sum += darkness * weights[i]
            total_weight += darkness

        if total_weight < 1e-6:
            return 0.0

        return weighted_sum / total_weight

    def get_sigma(self):
        return self.sigma

    def set_sigma(self, sigma):
        """调整感知宽度"""
        self.sigma = max(1.0, sigma)

    def get_info(self):
        """获取传感器配置信息"""
        return {
            'sigma': self.sigma,
            'resolution': self.resolution,
            'offsets': self.sensor_offsets,
            'front': self.sensor_front,
            'radius': self.sensor_radius,
            'noise_enabled': self.noise_enabled,
            'noise_std': self.noise_std,
        }