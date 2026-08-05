# -*- coding: utf-8 -*-
"""
logger.py - PID 实验数据记录器
记录控制周期的完整状态快照，支持回放、对比、评分。
"""

import time
import json
import os
from collections import deque


class ControlSnapshot:
    """单个控制周期的数据快照"""
    __slots__ = ('t', 'error', 'pid_p', 'pid_i', 'pid_d', 'pid_output',
                 'left_speed', 'right_speed', 'sensor_states',
                 'car_x', 'car_y', 'car_angle', 'black_count')

    def __init__(self):
        self.t = 0.0
        self.error = 0.0
        self.pid_p = 0.0
        self.pid_i = 0.0
        self.pid_d = 0.0
        self.pid_output = 0.0
        self.left_speed = 0.0
        self.right_speed = 0.0
        self.sensor_states = [1, 1, 1, 1]
        self.car_x = 0.0
        self.car_y = 0.0
        self.car_angle = 0.0
        self.black_count = 0


class ExperimentLogger:
    """
    PID 实验记录器。
    
    功能:
        1. 实时记录每个控制周期的完整状态
        2. 计算稳定性评分指标
        3. 支持导出为 JSON
        4. 支持多组实验对比
    """

    def __init__(self, max_history=5000):
        self.max_history = max_history
        self.history = deque(maxlen=max_history)
        self.recording = False
        self.experiment_name = ""
        self.start_time = 0.0

    def start_recording(self, name=None):
        """开始录制"""
        self.history.clear()
        self.recording = True
        self.start_time = time.monotonic()
        self.experiment_name = name or f"exp_{int(self.start_time)}"

    def stop_recording(self):
        """停止录制"""
        self.recording = False

    def record(self, snapshot):
        """记录一个控制周期"""
        if self.recording:
            self.history.append(snapshot)

    def get_recent(self, n=200):
        """获取最近 n 个数据点"""
        data = list(self.history)
        return data[-n:] if len(data) > n else data

    def get_all(self):
        return list(self.history)

    # ── 稳定性评分指标 ──

    def compute_metrics(self):
        """
        计算稳定性评分。
        
        返回:
            dict: {
                'avg_error': 平均绝对误差,
                'max_error': 最大绝对误差,
                'rms_error': 均方根误差,
                'overshoot_pct': 超调百分比,
                'oscillation_freq': 震荡频率 (Hz),
                'settling_time': 收敛时间 (s),
                'track_loss_pct': 丢线百分比,
                'score': 综合评分 (0~100, 越高越好),
            }
        """
        if len(self.history) < 10:
            return self._empty_metrics()

        data = list(self.history)
        errors = [abs(s.error) for s in data]
        raw_errors = [s.error for s in data]

        avg_error = sum(errors) / len(errors)
        max_error = max(errors)
        rms_error = (sum(e**2 for e in raw_errors) / len(raw_errors)) ** 0.5

        # 丢线比例
        track_loss = sum(1 for s in data if s.black_count == 0)
        track_loss_pct = track_loss / len(data) * 100

        # 超调: 误差超过平均值 2 倍的比例
        overshoot_count = sum(1 for e in errors if e > avg_error * 2)
        overshoot_pct = overshoot_count / len(data) * 100

        # 震荡频率: 过零点计数
        zero_crossings = 0
        for i in range(1, len(raw_errors)):
            if raw_errors[i-1] * raw_errors[i] < 0:
                zero_crossings += 1
        duration = data[-1].t - data[0].t if len(data) > 1 else 1.0
        oscillation_freq = zero_crossings / (2.0 * max(duration, 0.001))

        # 收敛时间: 首次进入 ±1 并保持 10 个周期
        settling_time = duration  # 默认未收敛
        window = 10
        threshold = 1.0
        for i in range(len(raw_errors) - window):
            segment = raw_errors[i:i+window]
            if all(abs(e) < threshold for e in segment):
                settling_time = data[i].t - data[0].t
                break

        # 综合评分 (加权)
        score = 100.0
        score -= min(40, avg_error * 8)           # 平均误差惩罚
        score -= min(20, max_error * 2)           # 最大误差惩罚
        score -= min(15, track_loss_pct * 1.5)    # 丢线惩罚
        score -= min(10, overshoot_pct * 0.5)     # 超调惩罚
        score -= min(10, oscillation_freq * 2)    # 震荡惩罚
        score = max(0, min(100, score))

        return {
            'avg_error': round(avg_error, 3),
            'max_error': round(max_error, 3),
            'rms_error': round(rms_error, 3),
            'overshoot_pct': round(overshoot_pct, 1),
            'oscillation_freq': round(oscillation_freq, 2),
            'settling_time': round(settling_time, 3),
            'track_loss_pct': round(track_loss_pct, 1),
            'score': round(score, 1),
            'data_points': len(data),
            'duration': round(duration, 3),
        }

    def _empty_metrics(self):
        return {k: 0.0 for k in ['avg_error', 'max_error', 'rms_error',
                                   'overshoot_pct', 'oscillation_freq',
                                   'settling_time', 'track_loss_pct', 'score',
                                   'data_points', 'duration']}

    def export_json(self, filepath):
        """导出实验数据为 JSON"""
        data = []
        for s in self.history:
            data.append({
                't': s.t, 'error': s.error,
                'pid_p': s.pid_p, 'pid_i': s.pid_i, 'pid_d': s.pid_d,
                'pid_output': s.pid_output,
                'left': s.left_speed, 'right': s.right_speed,
                'sensors': s.sensor_states,
                'x': s.car_x, 'y': s.car_y, 'angle': s.car_angle,
                'black_count': s.black_count,
            })
        result = {
            'name': self.experiment_name,
            'params': {},
            'metrics': self.compute_metrics(),
            'data': data,
        }
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        return filepath


class ExperimentComparison:
    """
    多组实验对比。
    """

    def __init__(self):
        self.experiments = []  # [(name, metrics, color), ...]

    def add(self, name, metrics, color=None):
        self.experiments.append((name, metrics, color))

    def clear(self):
        self.experiments.clear()

    def get_summary(self):
        """获取对比摘要"""
        if not self.experiments:
            return "No experiments to compare."
        lines = ["=== PID Experiment Comparison ==="]
        for name, m, _ in self.experiments:
            lines.append(f"\n[{name}]")
            lines.append(f"  Score: {m['score']:.1f}/100")
            lines.append(f"  Avg Error: {m['avg_error']:.3f}")
            lines.append(f"  Max Error: {m['max_error']:.3f}")
            lines.append(f"  Track Loss: {m['track_loss_pct']:.1f}%")
            lines.append(f"  Oscillation: {m['oscillation_freq']:.2f} Hz")
            lines.append(f"  Settling: {m['settling_time']:.3f}s")
        return "\n".join(lines)
