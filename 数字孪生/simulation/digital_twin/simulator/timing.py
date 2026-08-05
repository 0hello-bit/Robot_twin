# -*- coding: utf-8 -*-
"""
timing.py - 控制周期时序管理
模拟 STM32 定时器中断的固定周期控制。
解耦控制线程与渲染线程。
"""

import time
import config as cfg


class ControlTickTimer:
    """
    控制周期定时器。
    
    模拟 STM32 TIM 中断:
    - 固定周期触发 (如 10ms / 20ms / 50ms)
    - 与渲染帧率解耦
    - 支持动态调整周期
    """

    def __init__(self, control_hz=None):
        """
        参数:
            control_hz: 控制频率 (Hz), 默认使用 config 中的值
        """
        self.control_hz = control_hz or cfg.CONTROLLER_HZ
        self.control_dt = 1.0 / self.control_hz
        self._accumulator = 0.0
        self._tick_count = 0
        self._last_real_time = time.monotonic()

        # 性能监控
        self.actual_hz = 0.0
        self._hz_counter = 0
        self._hz_timer = time.monotonic()

    def reset(self):
        """重置定时器"""
        self._accumulator = 0.0
        self._tick_count = 0
        self._last_real_time = time.monotonic()
        self._hz_counter = 0
        self._hz_timer = time.monotonic()

    def feed(self, real_dt):
        """
        喂入真实时间增量，返回是否触发控制周期。
        
        参数:
            real_dt: 自上一帧以来的真实时间 (s)
        
        返回:
            int: 本帧触发的控制周期次数 (0, 1, 2, ...)
        """
        self._accumulator += real_dt
        ticks = 0

        while self._accumulator >= self.control_dt:
            self._accumulator -= self.control_dt
            self._tick_count += 1
            ticks += 1

        # 计算实际频率
        self._hz_counter += ticks
        now = time.monotonic()
        elapsed = now - self._hz_timer
        if elapsed >= 1.0:
            self.actual_hz = self._hz_counter / elapsed
            self._hz_counter = 0
            self._hz_timer = now

        return ticks

    def set_hz(self, hz):
        """动态调整控制频率"""
        self.control_hz = max(1, min(1000, hz))
        self.control_dt = 1.0 / self.control_hz

    def set_control_hz(self, hz):
        """Alias for set_hz (compatibility with main.py)"""
        self.set_hz(hz)

    def tick(self):
        """Check if a control tick should fire (uses wall clock).
        Returns True if enough time has passed for a new tick."""
        now = time.monotonic()
        real_dt = now - self._last_real_time
        self._last_real_time = now
        ticks = self.feed(real_dt)
        return ticks > 0

    def should_tick(self):
        """Same as tick() - returns True if control should run."""
        return self.tick()

    def get_tick_count(self):
        return self._tick_count

    def get_control_dt(self):
        return self.control_dt


class SimulationClock:
    """
    仿真时钟。
    提供统一的时间管理，支持暂停、变速。
    """

    def __init__(self):
        self.sim_time = 0.0       # 仿真累计时间
        self.timeScale = 1.0      # 时间倍率 (1.0=实时, 2.0=两倍速)
        self.paused = False
        self.frame_count = 0

    def advance(self, dt):
        """推进仿真时钟"""
        if not self.paused:
            self.sim_time += dt * self.timeScale
            self.frame_count += 1

    def get_time(self):
        return self.sim_time

    def reset(self):
        self.sim_time = 0.0
        self.frame_count = 0

