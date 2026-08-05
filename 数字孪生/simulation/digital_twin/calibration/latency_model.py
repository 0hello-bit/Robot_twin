# -*- coding: utf-8 -*-
"""
latency_model.py - 系统延迟建模

职责:
    1. 识别蓝牙传输延迟
    2. 识别 STM32 控制周期延迟
    3. 识别电机响应延迟
    4. 使用互相关法估算总延迟

方法:
    互相关 (Cross-correlation):
        R_xy(τ) = Σ x(t) * y(t+τ)

        峰值位置即为最优延迟估计

    阶跃响应法:
        从 PWM 跳变到速度开始变化的时间 = 总延迟

输出:
    total_latency_ms: 总延迟 (ms)
    jitter_ms:        延迟抖动标准差 (ms)
    breakdown:        各部分延迟分解
"""

import json
import math
import os
import time


class LatencyModel:
    """
    系统延迟模型。

    总延迟 = 蓝牙延迟 + 控制周期延迟 + 电机响应延迟
    """

    def __init__(self):
        self.total_latency_ms = 30.0    # 默认: 1 个控制周期
        self.jitter_ms = 5.0            # 抖动标准差
        self.bluetooth_ms = 10.0        # 蓝牙传输延迟
        self.control_cycle_ms = 30.0    # STM32 控制周期
        self.motor_response_ms = 10.0   # 电机响应延迟

        self.confidence = 0.0
        self.n_samples = 0

    def identify_from_correlation(self, input_signal, output_signal, dt_ms=30):
        """
        使用互相关法识别延迟。

        参数:
            input_signal:  输入信号序列 (PWM 值)
            output_signal: 输出信号序列 (速度/角速度)
            dt_ms:         采样周期 (ms)

        返回:
            dict: 延迟识别结果
        """
        n = min(len(input_signal), len(output_signal))
        if n < 10:
            return {'error': 'insufficient data'}

        # 去均值
        in_mean = sum(input_signal[:n]) / n
        out_mean = sum(output_signal[:n]) / n

        in_centered = [x - in_mean for x in input_signal[:n]]
        out_centered = [x - out_mean for x in output_signal[:n]]

        # 互相关 (只计算正延迟部分)
        max_lag = min(n // 2, 50)  # 最多搜索 50 个采样周期
        correlations = []

        for lag in range(max_lag):
            corr = 0.0
            count = 0
            for i in range(n - lag):
                corr += in_centered[i] * out_centered[i + lag]
                count += 1
            if count > 0:
                corr /= count
            correlations.append(corr)

        # 找峰值
        if not correlations:
            return {'error': 'correlation failed'}

        max_corr = max(abs(c) for c in correlations)
        if max_corr < 1e-10:
            return {'error': 'no correlation found'}

        peak_lag = 0
        peak_val = 0
        for i, c in enumerate(correlations):
            if abs(c) > abs(peak_val):
                peak_val = c
                peak_lag = i

        self.total_latency_ms = peak_lag * dt_ms
        self.control_cycle_ms = dt_ms

        # 估算抖动: 峰值附近的半峰宽
        half_max = abs(peak_val) * 0.5
        left = peak_lag
        right = peak_lag
        for i in range(peak_lag, -1, -1):
            if abs(correlations[i]) < half_max:
                left = i
                break
        for i in range(peak_lag, len(correlations)):
            if abs(correlations[i]) < half_max:
                right = i
                break
        self.jitter_ms = (right - left) * dt_ms / 2.0

        # 置信度
        self.confidence = abs(peak_val) / max(max_corr, 1e-10)
        self.n_samples = n

        return {
            'total_latency_ms': round(self.total_latency_ms, 1),
            'jitter_ms': round(self.jitter_ms, 1),
            'control_cycle_ms': self.control_cycle_ms,
            'peak_lag_samples': peak_lag,
            'correlation_strength': round(abs(peak_val), 6),
            'confidence': round(self.confidence, 4),
            'n_samples': n,
        }

    def identify_from_step_response(self, input_signal, output_signal, dt_ms=30):
        """
        从阶跃响应识别延迟。

        方法: 检测输入跳变点, 测量输出开始变化的时间。

        参数:
            input_signal:  PWM 序列
            output_signal: 速度序列
            dt_ms:         采样周期

        返回:
            dict
        """
        n = min(len(input_signal), len(output_signal))
        if n < 10:
            return {'error': 'insufficient data'}

        # 检测输入跳变
        threshold = max(abs(max(input_signal) - min(input_signal)) * 0.3, 10)
        delays = []

        for i in range(1, n):
            if abs(input_signal[i] - input_signal[i-1]) > threshold:
                # 检测输出响应
                input_level = input_signal[i]
                for j in range(i, min(i + 30, n)):
                    # 输出变化超过输入变化的 5% 视为响应
                    if abs(output_signal[j] - output_signal[i-1]) > \
                       abs(input_level - input_signal[i-1]) * 0.05:
                        delays.append((j - i) * dt_ms)
                        break

        if not delays:
            return {'error': 'no step response detected'}

        avg_delay = sum(delays) / len(delays)
        variance = sum((d - avg_delay)**2 for d in delays) / len(delays)

        self.total_latency_ms = avg_delay
        self.jitter_ms = math.sqrt(variance)
        self.motor_response_ms = max(0, avg_delay - self.control_cycle_ms)

        return {
            'total_latency_ms': round(avg_delay, 1),
            'jitter_ms': round(math.sqrt(variance), 1),
            'n_steps_detected': len(delays),
            'individual_delays_ms': [round(d, 1) for d in delays[:10]],
        }

    def get_total_latency_ms(self):
        return self.total_latency_ms

    def get_jitter_ms(self):
        return self.jitter_ms

    def save(self, filepath):
        data = {
            'total_latency_ms': self.total_latency_ms,
            'jitter_ms': self.jitter_ms,
            'bluetooth_ms': self.bluetooth_ms,
            'control_cycle_ms': self.control_cycle_ms,
            'motor_response_ms': self.motor_response_ms,
            'confidence': self.confidence,
            'n_samples': self.n_samples,
            'timestamp': time.time(),
        }
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print("[Latency] Saved: {}".format(filepath))

    def load(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.total_latency_ms = data.get('total_latency_ms', 30)
        self.jitter_ms = data.get('jitter_ms', 5)
        self.bluetooth_ms = data.get('bluetooth_ms', 10)
        self.control_cycle_ms = data.get('control_cycle_ms', 30)
        self.motor_response_ms = data.get('motor_response_ms', 10)
        self.confidence = data.get('confidence', 0)
        return data