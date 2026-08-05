# -*- coding: utf-8 -*-
"""
car.py - 小车实体 (v4)
修复: 局部坐标速度 → 世界坐标速度的旋转变换。
"""

import math
import config as cfg
from simulator.physics import PhysicsEngine, MecanumKinematics


class Motor:
    def __init__(self, motor_id):
        self.id = motor_id
        self._speed = 0.0

    def set_normalized_speed(self, speed):
        self._speed = max(-1.0, min(1.0, speed))

    def set_speed(self, direction, pwm):
        pwm = max(0, min(cfg.PWM_MAX, pwm))
        self._speed = (pwm / cfg.PWM_MAX) if direction == 0 else -(pwm / cfg.PWM_MAX)

    def get_speed(self):
        return self._speed

    def stop(self):
        self._speed = 0.0


class MecanumCar:
    """
    麦轮小车 (v4)。
    
    电机编号:
        M0 = 后左 (BL)    M1 = 后右 (BR)
        M2 = 前左 (FL)    M3 = 前右 (FR)
    """

    def __init__(self, x, y, angle=0.0):
        self.x = x
        self.y = y
        self.angle = angle    # 度, 0=右, 90=下
        self.vx = 0.0         # 世界坐标 x 速度
        self.vy = 0.0         # 世界坐标 y 速度
        self.va = 0.0         # 角速度 (deg/s)

        self.motors = [Motor(i) for i in range(4)]
        self._physics = PhysicsEngine()

    def update(self, dt):
        """更新小车状态"""
        v0 = self.motors[0].get_speed()
        v1 = self.motors[1].get_speed()
        v2 = self.motors[2].get_speed()
        v3 = self.motors[3].get_speed()

        # 正运动学: 四轮速度 → 车体局部速度
        local_vx, local_vy, local_va = \
            MecanumKinematics.forward_kinematics(v0, v1, v2, v3)

        # 局部坐标 → 世界坐标旋转
        rad = math.radians(self.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        world_vx = local_vx * cos_a - local_vy * sin_a
        world_vy = local_vx * sin_a + local_vy * cos_a

        # 屏幕坐标系: kinematics 正旋转=逆时针(数学), 屏幕上需要取反
        world_va = -local_va

        # 平滑过渡 (模拟惯性)
        alpha_v = 0.3
        alpha_a = 0.4
        self.vx += (world_vx - self.vx) * alpha_v
        self.vy += (world_vy - self.vy) * alpha_v
        self.va += (world_va - self.va) * alpha_a

        # 积分
        self._physics.update(self, dt)

    def drive(self, left_speed, right_speed):
        """差速驱动: left < right → 左转"""
        self.motors[0].set_normalized_speed(left_speed)   # BL
        self.motors[1].set_normalized_speed(right_speed)  # BR
        self.motors[2].set_normalized_speed(right_speed)  # FL (swap for rotation)
        self.motors[3].set_normalized_speed(left_speed)   # FR (swap for rotation)

    def get_sensor_positions(self):
        rad = math.radians(self.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        return [(self.x + cfg.SENSOR_FRONT * cos_a - off * sin_a,
                 self.y + cfg.SENSOR_FRONT * sin_a + off * cos_a)
                for off in cfg.SENSOR_OFFSETS]

    def get_wheel_positions(self):
        rad = math.radians(self.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        hl = cfg.CAR_LENGTH / 2
        hw = cfg.CAR_WIDTH / 2
        return [(self.x + lx*cos_a - ly*sin_a,
                 self.y + lx*sin_a + ly*cos_a)
                for lx, ly in [(-hl,-hw),(-hl,hw),(hl,-hw),(hl,hw)]]

    def stop(self):
        for m in self.motors:
            m.stop()
        self.vx = self.vy = self.va = 0.0

    def reset(self, x, y, angle=0.0):
        self.x, self.y, self.angle = x, y, angle
        self.vx = self.vy = self.va = 0.0
        self.stop()
