# -*- coding: utf-8 -*-
"""
observation.py - 状态空间设计

低维连续状态向量, 兼容 Gymnasium 协议。
"""

import math
import numpy as np


class ObservationBuilder:
    """
    构建归一化状态向量。

    state = [
        sensor0, sensor1, sensor2, sensor3,   # [0,1] 连续灰度
        line_error,          # [-1, 1] 归一化偏差
        line_error_rate,     # [-1, 1] 偏差变化率
        speed,               # [0, 1] 归一化速度
        angular_velocity,    # [-1, 1] 归一化角速度
        distance_from_center,# [0, 1] 到赛道中心距离
        track_curvature,     # [0, 1] 曲率
    ]
    """

    DIMENSION = 10

    def __init__(self, sensor_resolution=1023, max_speed=300.0,
                 max_angular=180.0, max_track_dist=100.0):
        self.sensor_resolution = sensor_resolution
        self.max_speed = max_speed
        self.max_angular = max_angular
        self.max_track_dist = max_track_dist

        self._prev_error = 0.0
        self._prev_time = 0.0

    def build(self, plant, analog_sensor, track, dt=0.03):
        """
        从 PlantModel 当前状态构建归一化观测向量。

        返回:
            np.ndarray: shape=(10,) float32
        """
        # 1. 传感器读数 (连续, 归一化到 [0,1])
        readings = analog_sensor.read(plant.x, plant.y, plant.angle, track)
        sensors = np.array(readings, dtype=np.float32) / self.sensor_resolution

        # 2. 行线误差 (连续, 归一化到 [-1,1])
        line_error = analog_sensor.read_position(readings) / 3.0
        line_error = max(-1.0, min(1.0, line_error))

        # 3. 误差变化率
        if self._prev_time > 0 and dt > 0:
            error_rate = (line_error - self._prev_error) / dt
            error_rate = max(-1.0, min(1.0, error_rate / 10.0))
        else:
            error_rate = 0.0
        self._prev_error = line_error
        self._prev_time += dt

        # 4. 速度
        speed = max(0.0, min(1.0, abs(plant.vx) / self.max_speed))

        # 5. 角速度
        ang_vel = max(-1.0, min(1.0, plant.va / self.max_angular))

        # 6. 到赛道中心距离
        dist = track.get_distance_to_track(plant.x, plant.y)
        norm_dist = max(0.0, min(1.0, dist / self.max_track_dist))

        # 7. 曲率 (简化: 用角速度近似)
        curvature = max(0.0, min(1.0, abs(plant.va) / self.max_angular))

        state = np.array([
            sensors[0], sensors[1], sensors[2], sensors[3],
            line_error, error_rate,
            speed, ang_vel,
            norm_dist, curvature,
        ], dtype=np.float32)

        return state

    def reset(self):
        self._prev_error = 0.0
        self._prev_time = 0.0

    @staticmethod
    def get_state_description():
        return [
            'sensor_0 (normalized gray 0-1)',
            'sensor_1 (normalized gray 0-1)',
            'sensor_2 (normalized gray 0-1)',
            'sensor_3 (normalized gray 0-1)',
            'line_error (normalized -1 to 1)',
            'line_error_rate (normalized -1 to 1)',
            'speed (normalized 0-1)',
            'angular_velocity (normalized -1 to 1)',
            'distance_from_center (normalized 0-1)',
            'track_curvature (normalized 0-1)',
        ]