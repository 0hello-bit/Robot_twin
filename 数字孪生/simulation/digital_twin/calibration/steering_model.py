# -*- coding: utf-8 -*-
"""
steering_model.py - 转向动力学建模

职责:
    1. 建模 左右轮差速 → 角速度 ω 的传递函数
    2. 识别响应延迟 delay
    3. 识别时间常数 τ (惯性)
    4. 识别超调因子 overshoot

物理模型:
    一阶惯性 + 纯延迟:

    ω(t) = K * (1 - e^(-(t-td)/τ)) * u(t-td)

    其中:
        K:  增益 (PWM差 → 角速度)
        td: 纯延迟 (ms)
        τ:  时间常数 (ms)
        u:  输入 (PWM_L - PWM_R)

识别方法:
    1. 阶跃响应法: 施加阶跃输入, 拟合响应曲线
    2. 互相关法:   input/output 互相关, 识别延迟
    3. 最小二乘:   直接拟合参数

输入数据格式:
    records[i] = {
        't': timestamp_ms,
        'left_pwm': int,
        'right_pwm': int,
        'omega': float (角速度 deg/s, 从传感器变化推断)
    }
"""

import json
import math
import os
import time


class SteeringModel:
    """
    转向动力学模型。

    传递函数:
        ω(s) = K * e^(-td*s) / (τ*s + 1) * ΔPWM(s)

    参数:
        K:        增益 (deg/s per PWM unit)
        td:       纯延迟 (ms)
        tau:      时间常数 (ms)
        overshoot: 超调因子 (0=无超调)
    """

    def __init__(self):
        self.K = 0.0          # 增益
        self.td = 0.0         # 延迟 (ms)
        self.tau = 50.0       # 时间常数 (ms)
        self.overshoot = 0.0  # 超调因子
        self.offset = 0.0     # 零偏

        # 拟合结果
        self.fit_quality = 0.0
        self.n_samples = 0
        self.rmse = 0.0

    def predict(self, delta_pwm, t, dt=0.03):
        """
        预测角速度。

        使用一阶惯性 + 延迟模型。

        参数:
            delta_pwm: PWM 差值 (left - right), 归一化到 [-1, 1]
            t:         当前时间 (s)
            dt:        时间步长 (s)

        返回:
            omega: 角速度 (deg/s)
        """
        if dt <= 0:
            return 0.0

        # 延迟补偿: 使用 t - td 时刻的输入
        t_delayed = t - self.td / 1000.0
        if t_delayed < 0:
            return 0.0

        # 一阶惯性响应
        tau_s = self.tau / 1000.0
        if tau_s < 1e-6:
            # 无惯性: 直接响应
            omega = self.K * delta_pwm + self.offset
        else:
            alpha = dt / (tau_s + dt)
            target = self.K * delta_pwm + self.offset
            omega = target * (1 - (1 - alpha) ** (t_delayed / max(dt, 1e-6)))

        # 超调
        if self.overshoot > 0 and abs(delta_pwm) > 0.1:
            omega *= (1.0 + self.overshoot * 0.1)

        return omega

    def fit_from_step_response(self, records, dt_ms=30):
        """
        从阶跃响应数据拟合参数。

        方法:
            1. 检测阶跃起始点
            2. 从响应曲线拟合 K, τ, td

        参数:
            records: list[dict] - 包含 t, left_pwm, right_pwm, omega
            dt_ms:   控制周期 (ms)

        返回:
            dict: 拟合结果
        """
        if len(records) < 10:
            return {'error': 'insufficient data'}

        # 提取数据
        ts = [r['t'] for r in records]
        delta_pwms = [r.get('left_pwm', 0) - r.get('right_pwm', 0)
                      for r in records]
        omegas = [r.get('omega', 0) for r in records]

        # 检测阶跃: PWM 差值从 ~0 跳变到非零
        step_idx = None
        threshold = 50  # PWM 差值阈值
        for i in range(1, len(delta_pwms)):
            if abs(delta_pwms[i]) > threshold and abs(delta_pwms[i-1]) < threshold * 0.3:
                step_idx = i
                break

        if step_idx is None:
            # 没有明显阶跃, 使用全数据最小二乘拟合
            return self._fit_full_data(ts, delta_pwms, omegas, dt_ms)

        # 阶跃响应分析
        step_input = delta_pwms[step_idx]
        step_response = omegas[step_idx:]

        if len(step_response) < 5:
            return {'error': 'step response too short'}

        # 稳态值 (最后 20% 的平均)
        tail = max(1, len(step_response) // 5)
        steady_state = sum(step_response[-tail:]) / tail

        # 增益 K = 稳态输出 / 阶跃输入
        self.K = steady_state / max(abs(step_input), 1)

        # 时间常数 τ: 响应达到 63.2% 稳态值的时间
        target_63 = 0.632 * steady_state
        self.tau = dt_ms * 5  # 默认值
        for i, omega in enumerate(step_response):
            if abs(omega) >= abs(target_63):
                self.tau = i * dt_ms
                break

        # 延迟 td: 响应开始变化的时间
        self.td = 0
        for i, omega in enumerate(step_response):
            if abs(omega) > abs(steady_state) * 0.05:
                self.td = i * dt_ms
                break

        # 超调
        peak = max(abs(o) for o in step_response) if step_response else 0
        if abs(steady_state) > 0.1:
            self.overshoot = max(0, (peak / abs(steady_state)) - 1.0)
        else:
            self.overshoot = 0.0

        # 计算 RMSE
        self.rmse = self._compute_rmse(ts, delta_pwms, omegas, dt_ms)
        self.n_samples = len(records)
        self.fit_quality = max(0, 1.0 - self.rmse / max(abs(steady_state), 1))

        return {
            'K': round(self.K, 6),
            'td_ms': round(self.td, 1),
            'tau_ms': round(self.tau, 1),
            'overshoot': round(self.overshoot, 4),
            'steady_state': round(steady_state, 4),
            'rmse': round(self.rmse, 6),
            'fit_quality': round(self.fit_quality, 4),
            'n_samples': self.n_samples,
        }

    def _fit_full_data(self, ts, delta_pwms, omegas, dt_ms):
        """全数据最小二乘拟合 (无明显阶跃时)"""
        # 简化: 假设线性关系 ω = K * ΔPWM
        sum_dp = sum(abs(d) for d in delta_pwms)
        sum_om = sum(abs(o) for o in omegas)
        if sum_dp > 0:
            self.K = sum_om / sum_dp
        else:
            self.K = 0

        self.td = dt_ms  # 默认 1 周期延迟
        self.tau = dt_ms * 3
        self.overshoot = 0

        self.rmse = self._compute_rmse(ts, delta_pwms, omegas, dt_ms)
        self.n_samples = len(ts)

        return {
            'K': round(self.K, 6),
            'td_ms': round(self.td, 1),
            'tau_ms': round(self.tau, 1),
            'overshoot': 0,
            'rmse': round(self.rmse, 6),
            'n_samples': self.n_samples,
        }

    def _compute_rmse(self, ts, delta_pwms, omegas, dt_ms):
        """计算模型预测与实际的 RMSE"""
        if len(ts) < 2:
            return 0.0

        dt_s = dt_ms / 1000.0
        errors = []
        for i in range(len(ts)):
            pred = self.predict(delta_pwms[i] / 999.0, ts[i] / 1000.0, dt_s)
            errors.append((pred - omegas[i]) ** 2)

        return math.sqrt(sum(errors) / len(errors))

    def save(self, filepath):
        data = {
            'K': self.K, 'td': self.td, 'tau': self.tau,
            'overshoot': self.overshoot, 'offset': self.offset,
            'rmse': self.rmse, 'fit_quality': self.fit_quality,
            'n_samples': self.n_samples,
            'timestamp': time.time(),
        }
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print("[Steering] Saved: {}".format(filepath))

    def load(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.K = data.get('K', 0)
        self.td = data.get('td', 0)
        self.tau = data.get('tau', 50)
        self.overshoot = data.get('overshoot', 0)
        self.offset = data.get('offset', 0)
        self.rmse = data.get('rmse', 0)
        self.fit_quality = data.get('fit_quality', 0)
        return data