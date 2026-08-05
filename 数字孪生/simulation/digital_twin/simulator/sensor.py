# -*- coding: utf-8 -*-
"""
sensor.py - 红外巡线传感器模拟
模拟 TCRT5000 红外传感器阵列，检测地面黑线。
v2: 新增 set_raw / get_processed 支持 HIL 真实数据注入
"""

import config as cfg


class IRSensor:
    """单个红外传感器"""

    def __init__(self, sensor_id, x=0, y=0):
        self.id = sensor_id
        self.x = x              # 世界坐标 x
        self.y = y              # 世界坐标 y
        self.state = 0          # 0=检测到黑线, 1=白底
        self.detect_radius = cfg.SENSOR_RADIUS
        self.noise_prob = 0.0   # 噪声概率 (后续扩展)

    def update(self, world):
        """
        根据当前世界状态更新传感器读数。

        参数:
            world: TrackMap 对象，提供线段查询

        返回:
            int: 0=黑线, 1=白底
        """
        on_line = world.is_point_on_track(self.x, self.y, self.detect_radius)
        self.state = 0 if on_line else 1
        return self.state


class SensorArray:
    """
    四路红外传感器阵列。

    排列方式与真实小车一致:
        S0(PB1) = 最左
        S1(PB0) = 左中
        S2(PB4) = 右中
        S3(PB5) = 最右
    """

    def __init__(self):
        self.sensors = [IRSensor(i) for i in range(cfg.NUM_SENSORS)]
        self._external_override = [0, 0, 0, 0]  # HIL 外部注入值
        self._use_external = False

    def update_positions(self, car):
        """
        根据小车当前位姿更新所有传感器的世界坐标。

        参数:
            car: MecanumCar 对象
        """
        positions = car.get_sensor_positions()
        for sensor, (wx, wy) in zip(self.sensors, positions):
            sensor.x = wx
            sensor.y = wy

    def read(self, world):
        """
        读取所有传感器状态。

        参数:
            world: TrackMap 对象

        返回:
            list[int]: [S0, S1, S2, S3]，0=黑线, 1=白底
        """
        if self._use_external:
            return list(self._external_override)
        return [s.update(world) for s in self.sensors]

    def get_raw(self):
        """获取原始状态列表"""
        if self._use_external:
            return list(self._external_override)
        return [s.state for s in self.sensors]

    def get_processed(self):
        """
        获取处理后的传感器状态 (用于控制器输入)。
        与 get_raw 相同，但预留后续滤波/去噪接口。
        """
        return self.get_raw()

    def set_raw(self, index, value):
        """
        直接设置传感器状态 (HIL 模式用)。

        参数:
            index: 传感器编号 (0~3)
            value: 0=黑线, 1=白底
        """
        if 0 <= index < cfg.NUM_SENSORS:
            self._external_override[index] = value
            self._use_external = True

    def set_all_raw(self, values):
        """
        批量设置所有传感器状态 (HIL 模式用)。

        参数:
            values: [S0, S1, S2, S3]
        """
        for i, v in enumerate(values[:cfg.NUM_SENSORS]):
            self._external_override[i] = v
        self._use_external = True

    def clear_override(self):
        """清除外部注入，恢复仿真模式"""
        self._use_external = False

    def get_positions(self):
        """获取所有传感器的世界坐标"""
        return [(s.x, s.y) for s in self.sensors]