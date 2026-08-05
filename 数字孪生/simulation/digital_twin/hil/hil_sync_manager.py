# -*- coding: utf-8 -*-
"""
hil_sync_manager.py - HIL 时间同步管理器

功能:
    1. 同步 STM32 tick (ms) 与 Python monotonic time (s)
    2. 自动对齐时间轴
    3. 处理 delay compensation
    4. 报告同步质量 (jitter / drift / offset)

核心原理:
    STM32 发送 tick_ms (毫秒计数器)
    Python 端收到时记录 monotonic timestamp
    通过多组 (tick_ms, monotonic) 配对
    拟合线性映射:
        sim_time = alpha * tick_ms + beta

    alpha ≈ 1.0 (时钟速率比)
    beta  = offset (绝对偏移)

后续使用:
    sync_mgr = HilSyncManager()
    sync_mgr.update(stm32_tick_ms, monotonic_now)
    sim_time = sync_mgr.to_sim_time(stm32_tick_ms)
"""

import time
import math
import threading
import collections


class HilSyncManager:
    """
    HIL 时间同步管理器。

    通过 STM32 tick_ms 与本地 monotonic timestamp 的配对,
    建立线性映射关系, 实现时间轴对齐。

    使用:
        sync = HilSyncManager()
        # 每收到一个 telemetry 帧:
        sync.update(stm32_tick_ms, time.monotonic())
        # 获取同步后的时间:
        t = sync.to_sim_time(stm32_tick_ms)
    """

    # 最少需要多少组配对才开始同步
    MIN_SAMPLES = 5
    # 最大保留样本数 (滑动窗口)
    MAX_SAMPLES = 200
    # 异常值剔除阈值 (标准差倍数)
    OUTLIER_SIGMA = 3.0
    # 同步有效期 (秒), 超过此时间无更新则认为失步
    SYNC_TIMEOUT = 5.0

    def __init__(self):
        self._lock = threading.Lock()

        # 滑动窗口: (stm32_tick_ms, monotonic_time)
        self._pairs = collections.deque(maxlen=self.MAX_SAMPLES)

        # 拟合参数: sim_time = alpha * tick_ms + beta
        self._alpha = 1.0  # 时钟速率比
        self._beta = 0.0   # 时间偏移

        # 同步状态
        self._synced = False
        self._last_update = 0.0
        self._jitter_ms = 0.0
        self._drift_ppm = 0.0
        self._offset_ms = 0.0

        # 历史 (用于诊断)
        self._residual_history = collections.deque(maxlen=50)

    def update(self, stm32_tick_ms, monotonic_time=None):
        """
        更新一组时间配对。

        参数:
            stm32_tick_ms:  STM32 发送的 tick (毫秒)
            monotonic_time: 本地 monotonic 时间 (秒), 默认 time.monotonic()
        """
        if monotonic_time is None:
            monotonic_time = time.monotonic()

        with self._lock:
            self._pairs.append((float(stm32_tick_ms), monotonic_time))
            self._last_update = monotonic_time

            if len(self._pairs) >= self.MIN_SAMPLES:
                self._fit_model()

    def _fit_model(self):
        """
        最小二乘法拟合: monotonic = alpha * tick_ms + beta

        使用剔除异常值后的鲁棒拟合。
        """
        pairs = list(self._pairs)

        # 第一轮: 初始拟合
        alpha, beta = self._least_squares(pairs)

        # 计算残差, 剔除异常值
        residuals = []
        for tick, mono in pairs:
            predicted = alpha * tick + beta
            residuals.append(mono - predicted)

        mean_r = sum(residuals) / len(residuals)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in residuals) / max(len(residuals) - 1, 1))

        # 第二轮: 剔除异常值后重新拟合
        if std_r > 1e-10:
            filtered = []
            for i, (tick, mono) in enumerate(pairs):
                if abs(residuals[i] - mean_r) < self.OUTLIER_SIGMA * std_r:
                    filtered.append((tick, mono))
            if len(filtered) >= self.MIN_SAMPLES:
                alpha, beta = self._least_squares(filtered)
                pairs = filtered

        # 更新拟合参数
        self._alpha = alpha
        self._beta = beta
        self._synced = True

        # 计算同步质量指标
        self._compute_quality(pairs)

    def _least_squares(self, pairs):
        """最小二乘法拟合 y = a*x + b"""
        n = len(pairs)
        if n < 2:
            return 1.0, 0.0

        sum_x = 0.0
        sum_y = 0.0
        sum_xy = 0.0
        sum_x2 = 0.0

        for x, y in pairs:
            sum_x += x
            sum_y += y
            sum_xy += x * y
            sum_x2 += x * x

        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-15:
            return 1.0, sum_y / n

        alpha = (n * sum_xy - sum_x * sum_y) / denom
        beta = (sum_y - alpha * sum_x) / n

        return alpha, beta

    def _compute_quality(self, pairs):
        """计算同步质量指标"""
        if len(pairs) < 2:
            return

        residuals = []
        for tick, mono in pairs:
            predicted = self._alpha * tick + self._beta
            residuals.append((mono - predicted) * 1000.0)  # 转换为 ms

        self._residual_history.extend(residuals)

        # Jitter: 残差的标准差 (ms)
        n = len(residuals)
        mean_r = sum(residuals) / n
        self._jitter_ms = math.sqrt(sum((r - mean_r) ** 2 for r in residuals) / max(n - 1, 1))

        # Offset: 平均残差 (ms)
        self._offset_ms = mean_r

        # Drift: alpha 偏离 1.0 的程度 (ppm)
        self._drift_ppm = (self._alpha - 1.0) * 1e6

    def to_sim_time(self, stm32_tick_ms):
        """
        将 STM32 tick_ms 转换为仿真时间 (秒)。

        参数:
            stm32_tick_ms: STM32 tick (毫秒)

        返回:
            float: 对齐后的仿真时间 (秒)
        """
        with self._lock:
            if not self._synced:
                # 未同步时, 直接转换单位
                return stm32_tick_ms / 1000.0
            return self._alpha * stm32_tick_ms + self._beta

    def to_stm32_tick(self, sim_time):
        """
        将仿真时间转换回 STM32 tick_ms (逆映射)。

        参数:
            sim_time: 仿真时间 (秒)

        返回:
            float: STM32 tick (毫秒)
        """
        with self._lock:
            if not self._synced:
                return sim_time * 1000.0
            if abs(self._alpha) < 1e-15:
                return 0.0
            return (sim_time - self._beta) / self._alpha

    def is_synced(self):
        """是否已同步"""
        with self._lock:
            return self._synced

    def is_alive(self):
        """同步是否仍然有效 (未超时)"""
        with self._lock:
            if not self._synced:
                return False
            return (time.monotonic() - self._last_update) < self.SYNC_TIMEOUT

    def get_quality(self):
        """
        获取同步质量报告。

        返回:
            dict: {
                'synced': bool,
                'alive': bool,
                'jitter_ms': float,
                'drift_ppm': float,
                'offset_ms': float,
                'n_samples': int,
                'alpha': float,
                'beta': float,
            }
        """
        with self._lock:
            return {
                'synced': self._synced,
                'alive': self.is_alive(),
                'jitter_ms': round(self._jitter_ms, 3),
                'drift_ppm': round(self._drift_ppm, 2),
                'offset_ms': round(self._offset_ms, 3),
                'n_samples': len(self._pairs),
                'alpha': self._alpha,
                'beta': self._beta,
            }

    def reset(self):
        """重置同步状态"""
        with self._lock:
            self._pairs.clear()
            self._alpha = 1.0
            self._beta = 0.0
            self._synced = False
            self._last_update = 0.0
            self._jitter_ms = 0.0
            self._drift_ppm = 0.0
            self._offset_ms = 0.0
            self._residual_history.clear()

    def estimate_stm32_period(self):
        """
        估算 STM32 控制周期 (ms)。

        通过相邻 tick_ms 的差值统计。
        """
        with self._lock:
            pairs = list(self._pairs)
        if len(pairs) < 3:
            return None

        tick_diffs = []
        for i in range(1, len(pairs)):
            dt = pairs[i][0] - pairs[i - 1][0]
            if 0 < dt < 1000:  # 合理范围
                tick_diffs.append(dt)

        if not tick_diffs:
            return None

        # 中位数 (抗异常值)
        tick_diffs.sort()
        mid = len(tick_diffs) // 2
        if len(tick_diffs) % 2 == 0:
            return (tick_diffs[mid - 1] + tick_diffs[mid]) / 2.0
        return tick_diffs[mid]