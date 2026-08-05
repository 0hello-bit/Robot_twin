# -*- coding: utf-8 -*-
"""
plant_model.py - 小车物理系统模型 (v2)

v2 新增:
    - get_params() / set_params() / export_params() / import_params()
    - 参数边界约束 (防止非物理值)
    - 增量参数更新 (在线校准)
    - 参数历史记录 (版本化)
"""

import math
import random
import os
import json
import copy
import time

import config as cfg


# ══════════════════════════════════════════════════════════════
#  参数约束
# ══════════════════════════════════════════════════════════════

PARAM_BOUNDS = {
    'motor_gain':           (0.0001, 0.005),
    'motor_offset':         (-0.1, 0.1),
    'motor_nonlinear':      (-1e-8, 1e-6),
    'steering_K':           (50.0, 500.0),
    'steering_tau':         (0.001, 0.5),
    'velocity_damping':     (0.5, 0.99),
    'angular_damping':      (0.3, 0.99),
    'sensor_noise_prob':    (0.0, 0.15),
    'motor_noise_std':      (0.0, 0.1),
    'position_noise_std':   (0.0, 5.0),
}


class PlantModel:
    """
    小车物理系统模型 (v2 可学习版本)。

    参数可导出/导入/更新, 支持在线校准。
    """

    def __init__(self, model_dir=None):
        self.x = 0.0
        self.y = 0.0
        self.angle = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.va = 0.0

        self.motor_gain = 1.0 / 999.0
        self.motor_offset = 0.0
        self.motor_nonlinear = 0.0

        self.steering_K = 180.0
        self.steering_tau = 0.05
        self.steering_delay_steps = 0

        self.velocity_damping = cfg.VELOCITY_DAMPING
        self.angular_damping = cfg.ANGULAR_DAMPING

        self.noise_enabled = False
        self.sensor_noise_prob = 0.03
        self.motor_noise_std = 0.02
        self.position_noise_std = 0.5

        self.sensor_offsets = list(cfg.SENSOR_OFFSETS)
        self.sensor_front = cfg.SENSOR_FRONT
        self.sensor_radius = cfg.SENSOR_RADIUS

        self.track = None

        self._delay_buffer = []
        self._delay_max = 3
        self._smooth_left = 0.0
        self._smooth_right = 0.0

        # v2: 参数历史
        self._param_history = []
        self._version = 0

        if model_dir:
            self.load_calibration(model_dir)

    # ══════════════════════════════════════════════════════════════
    #  v2: 参数管理接口
    # ══════════════════════════════════════════════════════════════

    def get_params(self):
        """导出当前可校准参数 (dict)"""
        return {
            'motor_gain': self.motor_gain,
            'motor_offset': self.motor_offset,
            'motor_nonlinear': self.motor_nonlinear,
            'steering_K': self.steering_K,
            'steering_tau': self.steering_tau,
            'velocity_damping': self.velocity_damping,
            'angular_damping': self.angular_damping,
            'sensor_noise_prob': self.sensor_noise_prob,
            'motor_noise_std': self.motor_noise_std,
            'position_noise_std': self.position_noise_std,
        }

    def set_params(self, params):
        """设置参数 (带边界约束)"""
        for key, val in params.items():
            if key in PARAM_BOUNDS:
                lo, hi = PARAM_BOUNDS[key]
                val = max(lo, min(hi, val))
            if hasattr(self, key):
                setattr(self, key, val)

    def export_params(self):
        """导出完整参数快照"""
        self._version += 1
        snapshot = {
            'version': self._version,
            'timestamp': time.time(),
            'params': self.get_params(),
        }
        self._param_history.append(copy.deepcopy(snapshot))
        return snapshot

    def import_params(self, snapshot):
        """从快照恢复参数"""
        if isinstance(snapshot, dict) and 'params' in snapshot:
            self.set_params(snapshot['params'])
        elif isinstance(snapshot, dict):
            self.set_params(snapshot)

    def get_param_history(self):
        return list(self._param_history)

    def load_calibration(self, model_dir):
        motor_path = os.path.join(model_dir, 'motor_model.json')
        if os.path.exists(motor_path):
            with open(motor_path, 'r') as f:
                data = json.load(f)
            result = data.get('fit_result', data)
            mt = result.get('model', 'linear')
            if mt == 'linear':
                self.motor_gain = result.get('a', 1.0/999)
                self.motor_offset = result.get('b', 0)
            elif mt == 'quadratic':
                self.motor_gain = result.get('b', 1.0/999)
                self.motor_offset = result.get('c', 0)
                self.motor_nonlinear = result.get('a', 0)

        steer_path = os.path.join(model_dir, 'steering_model.json')
        if os.path.exists(steer_path):
            with open(steer_path, 'r') as f:
                data = json.load(f)
            self.steering_K = data.get('K', 180)
            self.steering_tau = data.get('tau', 50) / 1000.0

        lat_path = os.path.join(model_dir, 'latency_model.json')
        if os.path.exists(lat_path):
            with open(lat_path, 'r') as f:
                data = json.load(f)
            total_ms = data.get('total_latency_ms', 30)
            self._delay_max = max(1, int(total_ms / 30))

    def save_params(self, filepath):
        snapshot = self.export_params()
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2)

    # ══════════════════════════════════════════════════════════════
    #  核心仿真逻辑 (与 v1 相同)
    # ══════════════════════════════════════════════════════════════

    def reset(self, x=0.0, y=0.0, angle=0.0):
        self.x = x
        self.y = y
        self.angle = angle
        self.vx = self.vy = self.va = 0.0
        self._smooth_left = 0.0
        self._smooth_right = 0.0
        self._delay_buffer.clear()

    def pwm_to_velocity(self, pwm):
        pwm = max(0, min(999, pwm))
        v = (self.motor_gain * pwm + self.motor_offset +
             self.motor_nonlinear * pwm * pwm)
        return max(0.0, min(1.0, v))

    def step(self, left_pwm, right_pwm, dt=0.03):
        lp = left_pwm
        rp = right_pwm
        if self.noise_enabled:
            lp = max(0, min(999, lp + random.gauss(0, self.motor_noise_std * 999)))
            rp = max(0, min(999, rp + random.gauss(0, self.motor_noise_std * 999)))

        v_left = self.pwm_to_velocity(lp)
        v_right = self.pwm_to_velocity(rp)

        alpha = dt / (self.steering_tau + dt) if self.steering_tau > 0 else 1.0
        self._smooth_left += (v_left - self._smooth_left) * alpha
        self._smooth_right += (v_right - self._smooth_right) * alpha

        delta = self._smooth_left - self._smooth_right
        omega_target = delta * self.steering_K
        self.va += (omega_target - self.va) * alpha

        avg_v = (self._smooth_left + self._smooth_right) / 2.0
        target_vx = avg_v * cfg.MAX_SPEED
        self.vx += (target_vx - self.vx) * alpha

        rad = math.radians(self.angle)
        self.x += self.vx * math.cos(rad) * dt
        self.y += self.vx * math.sin(rad) * dt
        self.angle += self.va * dt
        self.angle %= 360.0

        if self.noise_enabled:
            self.x += random.gauss(0, self.position_noise_std)
            self.y += random.gauss(0, self.position_noise_std)

        return self.read_sensors()

    def read_sensors(self):
        if self.track is None:
            return [1, 1, 1, 1]
        rad = math.radians(self.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        sensors = []
        for off in self.sensor_offsets:
            sx = self.x + self.sensor_front * cos_a - off * sin_a
            sy = self.y + self.sensor_front * sin_a + off * cos_a
            on_line = self.track.is_point_on_track(sx, sy, self.sensor_radius)
            val = 0 if on_line else 1
            if self.noise_enabled and random.random() < self.sensor_noise_prob:
                val = 1 - val
            sensors.append(val)
        return sensors

    def set_track(self, track):
        self.track = track

    def get_state_dict(self):
        return {
            'x': round(self.x, 2),
            'y': round(self.y, 2),
            'angle': round(self.angle, 2),
            'vx': round(self.vx, 2),
            'va': round(self.va, 2),
        }