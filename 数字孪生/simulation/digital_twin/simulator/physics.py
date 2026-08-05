# -*- coding: utf-8 -*-
"""
physics.py - 麦轮运动学引擎 (v2)

v2 改进:
    1. 支持从 calibration 数据动态加载模型参数
    2. PWM → 速度使用拟合曲线 (非线性)
    3. 转向响应带延迟 + 惯性
    4. 摩擦模型可配置
    5. 保留 v1 默认参数 (无 calibration 时向后兼容)

模型来源:
    calibration/system_id/pwm_speed_identification.py → motor_model.json
    calibration/steering_model.py → steering_model.json
    calibration/latency_model.py → latency_model.json

使用方式:
    # v1 默认模式 (向后兼容)
    kin = MecanumKinematics()

    # v2 加载校准模型
    kin = MecanumKinematics.from_calibration('calibration/models/')
"""

import math
import json
import os
import config as cfg


class MotorModel:
    """
    PWM → 速度映射模型。

    支持:
        - 线性:      v = a * PWM + b
        - 二次:      v = a * PWM² + b * PWM + c
        - 分段线性:  查表插值
    """

    def __init__(self):
        self.model_type = 'linear'
        self.a = 1.0 / cfg.PWM_MAX   # 默认线性: v = PWM/999
        self.b = 0.0
        self.c = 0.0
        self.breakpoints = []
        self.slopes = []
        self.intercepts = []

    def predict(self, pwm):
        """PWM (0~999) → 归一化速度 (0~1)"""
        pwm = max(0, min(cfg.PWM_MAX, pwm))

        if self.model_type == 'linear':
            return max(0, min(1.0, self.a * pwm + self.b))

        elif self.model_type == 'quadratic':
            return max(0, min(1.0, self.a * pwm * pwm + self.b * pwm + self.c))

        elif self.model_type == 'piecewise_linear':
            for i in range(len(self.breakpoints) - 1):
                if self.breakpoints[i] <= pwm <= self.breakpoints[i+1]:
                    return max(0, min(1.0, self.slopes[i] * pwm + self.intercepts[i]))
            if self.slopes:
                return max(0, min(1.0, self.slopes[-1] * pwm + self.intercepts[-1]))
            return pwm / cfg.PWM_MAX

        return pwm / cfg.PWM_MAX

    def load(self, filepath):
        """从 JSON 加载拟合参数"""
        if not os.path.exists(filepath):
            return False
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        result = data.get('fit_result', data)
        self.model_type = result.get('model', 'linear')
        self.a = result.get('a', 1.0 / cfg.PWM_MAX)
        self.b = result.get('b', 0)
        self.c = result.get('c', 0)
        self.breakpoints = result.get('breakpoints', [])
        self.slopes = result.get('slopes', [])
        self.intercepts = result.get('intercepts', [])
        return True


class SteeringDynamics:
    """
    转向动力学模型。

    一阶惯性 + 纯延迟:
        ω(t) = K * ΔPWM * (1 - e^(-(t-td)/τ))
    """

    def __init__(self):
        self.K = 180.0       # 增益 (deg/s per normalized PWM diff)
        self.td = 0.0        # 延迟 (s)
        self.tau = 0.05      # 时间常数 (s)
        self.omega = 0.0     # 当前角速度 (内部状态)

    def update(self, delta_normalized, dt):
        """
        更新角速度。

        参数:
            delta_normalized: 左右轮速度差 (归一化, -1~1)
            dt: 时间步长 (s)

        返回:
            omega: 当前角速度 (deg/s)
        """
        target = self.K * delta_normalized

        if self.tau < 1e-6:
            self.omega = target
        else:
            alpha = dt / (self.tau + dt)
            self.omega += (target - self.omega) * alpha

        return self.omega

    def load(self, filepath):
        if not os.path.exists(filepath):
            return False
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.K = data.get('K', 180.0)
        self.td = data.get('td', 0) / 1000.0  # ms → s
        self.tau = data.get('tau', 50) / 1000.0
        return True


class MecanumKinematics:
    """
    麦轮运动学求解器 (v2)。

    v2: 支持从 calibration 数据加载非线性模型。
    """

    def __init__(self):
        self.motor_model = MotorModel()
        self.steering = SteeringDynamics()

    @classmethod
    def from_calibration(cls, model_dir):
        """
        从校准目录加载模型。

        参数:
            model_dir: 模型文件目录 (如 'calibration/models/')

        返回:
            MecanumKinematics 实例
        """
        kin = cls()
        kin.motor_model.load(os.path.join(model_dir, 'motor_model.json'))
        kin.steering.load(os.path.join(model_dir, 'steering_model.json'))
        return kin

    @staticmethod
    def forward_kinematics(v0, v1, v2, v3):
        """正运动学: 四轮速度 → 车体速度 (v1 兼容)"""
        n = 4.0
        fwd = (v0 + v1 + v2 + v3) / n
        lat = (-v0 + v1 - v2 + v3) / n
        rot = (-v0 + v1 + v2 - v3) / n
        omega = rot * cfg.MAX_ANGULAR_VEL
        return fwd * cfg.MAX_SPEED, lat * cfg.MAX_SPEED, omega

    @staticmethod
    def inverse_kinematics(vx, vy, omega):
        """逆运动学: 车体速度 → 四轮速度 (v1 兼容)"""
        v0 = vx - vy - omega
        v1 = vx + vy + omega
        v2 = vx - vy + omega
        v3 = vx + vy - omega
        max_val = max(abs(v0), abs(v1), abs(v2), abs(v3), 1.0)
        return v0/max_val, v1/max_val, v2/max_val, v3/max_val

    def forward_kinematics_v2(self, raw_motor_speeds):
        """
        v2 正运动学: 原始电机速度 → 车体速度。

        使用 MotorModel 将 PWM 映射为实际速度,
        使用 SteeringDynamics 计算带惯性的角速度。

        参数:
            raw_motor_speeds: (s0, s1, s2, s3) 归一化电机命令

        返回:
            (vx, vy, omega)
        """
        v0, v1, v2, v3 = raw_motor_speeds

        # 非线性 PWM → 速度映射
        actual_v0 = self.motor_model.predict(abs(v0) * cfg.PWM_MAX)
        actual_v1 = self.motor_model.predict(abs(v1) * cfg.PWM_MAX)
        actual_v2 = self.motor_model.predict(abs(v2) * cfg.PWM_MAX)
        actual_v3 = self.motor_model.predict(abs(v3) * cfg.PWM_MAX)

        # 恢复符号
        if v0 < 0: actual_v0 = -actual_v0
        if v1 < 0: actual_v1 = -actual_v1
        if v2 < 0: actual_v2 = -actual_v2
        if v3 < 0: actual_v3 = -actual_v3

        # 正运动学
        n = 4.0
        fwd = (actual_v0 + actual_v1 + actual_v2 + actual_v3) / n
        lat = (-actual_v0 + actual_v1 - actual_v2 + actual_v3) / n
        rot = (-actual_v0 + actual_v1 + actual_v2 - actual_v3) / n

        return fwd * cfg.MAX_SPEED, lat * cfg.MAX_SPEED, rot * cfg.MAX_ANGULAR_VEL


class PhysicsEngine:
    """
    物理引擎 (v2): 支持校准模型的动态参数。
    """

    def __init__(self, kinematics=None):
        self.velocity_damping = cfg.VELOCITY_DAMPING
        self.angular_damping = cfg.ANGULAR_DAMPING
        self.kinematics = kinematics or MecanumKinematics()

    def update(self, car, dt):
        """更新小车状态"""
        car.vx *= self.velocity_damping
        car.vy *= self.velocity_damping
        car.va *= self.angular_damping

        car.x += car.vx * dt
        car.y += car.vy * dt

        car.angle += car.va * dt
        car.angle %= 360.0

    def apply_motor_command(self, car, motor_speeds):
        """将电机命令转换为速度 (v1 兼容)"""
        v0, v1, v2, v3 = motor_speeds
        vx, vy, omega = MecanumKinematics.forward_kinematics(v0, v1, v2, v3)
        car.vx = vx
        car.vy = vy
        car.va = omega

    def apply_motor_command_v2(self, car, motor_speeds, dt):
        """
        v2: 使用校准模型的电机命令。

        参数:
            car: 小车对象
            motor_speeds: 四轮归一化速度
            dt: 时间步长
        """
        vx, vy, omega = self.kinematics.forward_kinematics_v2(motor_speeds)

        # 使用转向动力学
        left_avg = (motor_speeds[0] + motor_speeds[3]) / 2.0
        right_avg = (motor_speeds[1] + motor_speeds[2]) / 2.0
        delta = left_avg - right_avg
        omega_calibrated = self.kinematics.steering.update(delta, dt)

        # 平滑过渡 (惯性)
        alpha_v = 0.3
        alpha_a = 0.4
        car.vx += (vx - car.vx) * alpha_v
        car.vy += (vy - car.vy) * alpha_v
        car.va += (omega_calibrated - car.va) * alpha_a