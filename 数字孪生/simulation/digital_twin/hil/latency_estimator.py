# -*- coding: utf-8 -*-
"""
latency_estimator.py - 延迟估计器

功能:
    1. 估计蓝牙传输延迟
    2. 估计控制周期延迟
    3. 估计传感器响应延迟
    4. 使用 cross-correlation 估算系统总延迟
    5. 输出延迟分布 (mean / jitter / max)

方法:
    输入信号:  PWM command sequence (来自 controller)
    输出信号:  observed PWM / sensor sequence (来自 telemetry)

    cross-correlation(r[tau]) = sum(x[t] * y[t+tau])

    峰值对应的 tau 即为系统延迟

后续使用:
    estimator = LatencyEstimator()
    estimator.feed_input(pwm_left, pwm_right, tick_ms)
    estimator.feed_output(obs_left, obs_right, tick_ms)
    latency = estimator.estimate()
"""

import math
import time
import threading
import collections


class LatencyEstimator:
    """
    延迟估计器。

    通过 cross-correlation 分析输入 (PWM command) 与输出 (observed response)
    之间的时间延迟。

    使用:
        est = LatencyEstimator()
        # 每个控制周期:
        est.feed_input(pwm_l, pwm_r, tick_ms)
        est.feed_output(obs_l, obs_r, tick_ms)
        # 查询延迟:
        result = est.estimate()
        print(result['total_latency_ms'])
    """

    MAX_HISTORY = 500
    MIN_SAMPLES = 20
    MAX_DELAY_MS = 200  # 最大搜索延迟 (ms)
    RESOLUTION_MS = 1   # 延迟分辨率 (ms)

    def __init__(self):
        self._lock = threading.Lock()

        # 输入/输出历史 (tick_ms, value)
        self._input_left = collections.deque(maxlen=self.MAX_HISTORY)
        self._input_right = collections.deque(maxlen=self.MAX_HISTORY)
        self._output_left = collections.deque(maxlen=self.MAX_HISTORY)
        self._output_right = collections.deque(maxlen=self.MAX_HISTORY)

        # 缓存估计结果
        self._cached_latency = None
        self._cache_time = 0.0
        self._cache_validity = 1.0  # 缓存有效期 (秒)

        # 历史估计
        self._history = collections.deque(maxlen=50)

    def feed_input(self, pwm_left, pwm_right, tick_ms):
        """
        记录控制输入 (来自 controller 的 PWM 命令)。
        """
        with self._lock:
            self._input_left.append((float(tick_ms), float(pwm_left)))
            self._input_right.append((float(tick_ms), float(pwm_right)))

    def feed_output(self, obs_left, obs_right, tick_ms):
        """
        记录观测输出 (来自 telemetry 的实际 PWM/速度)。
        """
        with self._lock:
            self._output_left.append((float(tick_ms), float(obs_left)))
            self._output_right.append((float(tick_ms), float(obs_right)))

    def estimate(self):
        """
        估计系统延迟。

        返回:
            dict: {
                'total_latency_ms': float,
                'jitter_ms': float,
                'max_latency_ms': float,
                'confidence': float 0~1,
                'method': str,
            }
        """
        now = time.monotonic()

        # 使用缓存
        if (self._cached_latency is not None and
                (now - self._cache_time) < self._cache_validity):
            return self._cached_latency

        with self._lock:
            # 需要足够数据
            n_input = len(self._input_left)
            n_output = len(self._output_left)

            if n_input < self.MIN_SAMPLES or n_output < self.MIN_SAMPLES:
                result = {
                    'total_latency_ms': 0.0,
                    'jitter_ms': 0.0,
                    'max_latency_ms': 0.0,
                    'confidence': 0.0,
                    'method': 'insufficient_data',
                }
                return result

            # 提取信号序列
            in_l = list(self._input_left)
            in_r = list(self._input_right)
            out_l = list(self._output_left)
            out_r = list(self._output_right)

        # 对左轮和右轮分别计算延迟
        lat_l = self._cross_correlate(in_l, out_l)
        lat_r = self._cross_correlate(in_r, out_r)

        # 综合延迟 (取平均)
        if lat_l is not None and lat_r is not None:
            total = (lat_l['delay_ms'] + lat_r['delay_ms']) / 2.0
            jitter = max(lat_l['jitter_ms'], lat_r['jitter_ms'])
            max_lat = max(lat_l['max_delay_ms'], lat_r['max_delay_ms'])
            confidence = (lat_l['confidence'] + lat_r['confidence']) / 2.0
        elif lat_l is not None:
            total = lat_l['delay_ms']
            jitter = lat_l['jitter_ms']
            max_lat = lat_l['max_delay_ms']
            confidence = lat_l['confidence']
        elif lat_r is not None:
            total = lat_r['delay_ms']
            jitter = lat_r['jitter_ms']
            max_lat = lat_r['max_delay_ms']
            confidence = lat_r['confidence']
        else:
            total = 0.0
            jitter = 0.0
            max_lat = 0.0
            confidence = 0.0

        result = {
            'total_latency_ms': round(total, 2),
            'jitter_ms': round(jitter, 2),
            'max_latency_ms': round(max_lat, 2),
            'confidence': round(confidence, 3),
            'method': 'cross_correlation',
            'left_latency': round(lat_l['delay_ms'], 2) if lat_l else None,
            'right_latency': round(lat_r['delay_ms'], 2) if lat_r else None,
        }

        self._cached_latency = result
        self._cache_time = now
        self._history.append(result)

        return result

    def _cross_correlate(self, input_seq, output_seq):
        """
        对两个信号序列做 cross-correlation, 找到最佳延迟。

        参数:
            input_seq:  list of (tick_ms, value)
            output_seq: list of (tick_ms, value)

        返回:
            dict: {'delay_ms', 'jitter_ms', 'max_delay_ms', 'confidence'}
            或 None (数据不足)
        """
        if len(input_seq) < self.MIN_SAMPLES or len(output_seq) < self.MIN_SAMPLES:
            return None

        # 重采样到统一时间网格
        all_ticks = set()
        for tick, _ in input_seq:
            all_ticks.add(round(tick / self.RESOLUTION_MS) * self.RESOLUTION_MS)
        for tick, _ in output_seq:
            all_ticks.add(round(tick / self.RESOLUTION_MS) * self.RESOLUTION_MS)

        if len(all_ticks) < self.MIN_SAMPLES:
            return None

        sorted_ticks = sorted(all_ticks)
        tick_to_idx = {t: i for i, t in enumerate(sorted_ticks)}

        # 构建等间隔信号
        n = len(sorted_ticks)
        input_signal = [0.0] * n
        output_signal = [0.0] * n

        for tick, val in input_seq:
            idx = tick_to_idx.get(round(tick / self.RESOLUTION_MS) * self.RESOLUTION_MS)
            if idx is not None:
                input_signal[idx] = val

        for tick, val in output_seq:
            idx = tick_to_idx.get(round(tick / self.RESOLUTION_MS) * self.RESOLUTION_MS)
            if idx is not None:
                output_signal[idx] = val

        # 去均值
        in_mean = sum(input_signal) / n
        out_mean = sum(output_signal) / n
        input_signal = [v - in_mean for v in input_signal]
        output_signal = [v - out_mean for v in output_signal]

        # 计算能量
        in_energy = sum(v * v for v in input_signal)
        out_energy = sum(v * v for v in output_signal)
        if in_energy < 1e-10 or out_energy < 1e-10:
            return None

        # Cross-correlation: 在不同延迟下求相关系数
        max_lag = min(int(self.MAX_DELAY_MS / self.RESOLUTION_MS), n // 2)
        best_corr = -1.0
        best_lag = 0
        corr_values = []

        for lag in range(0, max_lag + 1):
            corr = 0.0
            count = 0
            for i in range(n - lag):
                corr += input_signal[i] * output_signal[i + lag]
                count += 1

            if count > 0:
                corr /= count
                norm = math.sqrt(in_energy / n * out_energy / n)
                if norm > 1e-10:
                    corr /= norm

            corr_values.append((lag * self.RESOLUTION_MS, corr))

            if corr > best_corr:
                best_corr = corr
                best_lag = lag

        # 抖动估计: 用 top-3 峰值的 spread
        corr_values.sort(key=lambda x: -x[1])
        top_delays = [c[0] for c in corr_values[:3]]
        jitter = max(top_delays) - min(top_delays) if len(top_delays) >= 2 else 0.0

        confidence = max(0.0, min(1.0, best_corr))

        return {
            'delay_ms': best_lag * self.RESOLUTION_MS,
            'jitter_ms': jitter,
            'max_delay_ms': best_lag * self.RESOLUTION_MS + jitter,
            'confidence': confidence,
        }

    def get_history(self):
        """获取延迟估计历史"""
        with self._lock:
            return list(self._history)

    def reset(self):
        """重置所有数据"""
        with self._lock:
            self._input_left.clear()
            self._input_right.clear()
            self._output_left.clear()
            self._output_right.clear()
            self._cached_latency = None
            self._cache_time = 0.0
            self._history.clear()