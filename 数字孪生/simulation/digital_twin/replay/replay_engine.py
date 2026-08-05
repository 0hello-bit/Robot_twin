# -*- coding: utf-8 -*-
"""
replay_engine.py - 数据回放引擎

职责:
    1. 加载 JSON 格式的录制数据 (真实 / 仿真)
    2. 时间同步回放 (支持倍速/暂停/单步)
    3. 提供逐帧访问接口
    4. 支持同时加载真实 + 仿真数据进行对比

使用方式:
    engine = ReplayEngine()
    engine.load("data/real_test_01.json")
    
    # 在仿真器主循环中
    engine.update(dt)
    if engine.has_frame():
        frame = engine.get_frame()
        # 用 frame 驱动虚拟小车
"""

import json
import os


class ReplayFrame:
    """单帧回放数据"""
    __slots__ = ('t', 'sensors', 'left_pwm', 'right_pwm',
                 'error', 'pid_output', 'tick_ms',
                 'mode', 'lost_counter', 'battery_mv',
                 'car_x', 'car_y', 'car_angle')

    def __init__(self):
        self.t = 0.0
        self.sensors = [1, 1, 1, 1]
        self.left_pwm = 0
        self.right_pwm = 0
        self.error = 0
        self.pid_output = 0
        self.tick_ms = 0
        self.mode = 0
        self.lost_counter = 0
        self.battery_mv = 0
        self.car_x = 0.0
        self.car_y = 0.0
        self.car_angle = 0.0

    @property
    def left_normalized(self):
        return self.left_pwm / 999.0

    @property
    def right_normalized(self):
        return self.right_pwm / 999.0

    @classmethod
    def from_dict(cls, d):
        """从 dict 构造"""
        f = cls()
        f.t = d.get('t', 0.0)
        f.sensors = d.get('sensors', [1, 1, 1, 1])
        f.left_pwm = d.get('left_pwm', 0)
        f.right_pwm = d.get('right_pwm', 0)
        f.error = d.get('error', 0)
        f.pid_output = d.get('pid_output', 0)
        f.tick_ms = d.get('tick_ms', 0)
        f.mode = d.get('mode', 0)
        f.lost_counter = d.get('lost_counter', 0)
        f.battery_mv = d.get('battery_mv', 0)
        f.car_x = d.get('x', 0.0)
        f.car_y = d.get('y', 0.0)
        f.car_angle = d.get('angle', 0.0)
        return f


class ReplayEngine:
    """
    回放引擎。
    
    支持:
        - 加载 JSON 数据文件
        - 变速播放 (0.1x ~ 10x)
        - 暂停/恢复
        - 单步前进
        - 循环播放
        - 同时加载两组数据对比
    """

    def __init__(self):
        self.frames = []           # 回放帧列表
        self.metadata = {}         # 文件元数据
        self.metrics = {}          # 指标

        # 播放状态
        self._playhead = 0.0       # 当前播放时间 (s)
        self._frame_idx = 0        # 当前帧索引
        self._speed = 1.0          # 播放倍速
        self._paused = False
        self._loop = False
        self._finished = False

        # 对比数据
        self.compare_frames = []
        self.compare_metadata = {}

        # 回调
        self._on_frame_callbacks = []

    # ── 数据加载 ──

    def load(self, filepath):
        """
        加载 JSON 数据文件。
        
        兼容 ExperimentLogger 和 RealDataLogger 的输出格式。
        
        返回:
            bool: 是否成功加载
        """
        if not os.path.exists(filepath):
            print("[ReplayEngine] 文件不存在: {}".format(filepath))
            return False

        with open(filepath, 'r', encoding='utf-8') as f:
            result = json.load(f)

        self.metadata = {
            'name': result.get('name', 'unknown'),
            'source': result.get('source', 'simulation'),
            'params': result.get('params', {}),
        }
        self.metrics = result.get('metrics', {})

        raw_data = result.get('data', [])
        self.frames = [ReplayFrame.from_dict(d) for d in raw_data]

        self._playhead = 0.0
        self._frame_idx = 0
        self._finished = False

        print("[ReplayEngine] 已加载: {} ({} 帧, {:.1f}s)".format(
            filepath, len(self.frames),
            self.frames[-1].t if self.frames else 0))
        return True

    def load_compare(self, filepath):
        """加载对比数据集"""
        if not os.path.exists(filepath):
            return False
        with open(filepath, 'r', encoding='utf-8') as f:
            result = json.load(f)
        self.compare_metadata = result.get('metadata', result.get('name', ''))
        raw = result.get('data', [])
        self.compare_frames = [ReplayFrame.from_dict(d) for d in raw]
        print("[ReplayEngine] 对比数据: {} ({} 帧)".format(
            filepath, len(self.compare_frames)))
        return True

    def clear(self):
        """清空所有数据"""
        self.frames.clear()
        self.compare_frames.clear()
        self._playhead = 0.0
        self._frame_idx = 0
        self._finished = False

    # ── 播放控制 ──

    def update(self, dt):
        """
        推进播放时间。
        
        参数:
            dt: 自上一帧以来的真实时间 (s)
        
        返回:
            bool: 是否有新帧可读
        """
        if self._paused or self._finished or not self.frames:
            return False

        self._playhead += dt * self._speed

        # 检查是否到达新帧
        new_frame = False
        while (self._frame_idx < len(self.frames) and
               self.frames[self._frame_idx].t <= self._playhead):
            self._frame_idx += 1
            new_frame = True

        # 检查是否播放完毕
        if self._frame_idx >= len(self.frames):
            if self._loop:
                self._playhead = 0.0
                self._frame_idx = 0
                self._finished = False
            else:
                self._finished = True

        return new_frame

    def get_frame(self):
        """获取当前帧"""
        if self._frame_idx > 0 and self._frame_idx <= len(self.frames):
            return self.frames[self._frame_idx - 1]
        return None

    def get_frame_at_index(self, idx):
        """按索引获取帧"""
        if 0 <= idx < len(self.frames):
            return self.frames[idx]
        return None

    def get_compare_frame(self):
        """获取对比数据集的当前帧"""
        if not self.compare_frames:
            return None
        # 找到最接近当前时间的帧
        target_t = self._playhead
        best_idx = 0
        for i, f in enumerate(self.compare_frames):
            if f.t <= target_t:
                best_idx = i
            else:
                break
        return self.compare_frames[best_idx]

    def step(self):
        """单步前进一帧"""
        if self._frame_idx < len(self.frames):
            self._frame_idx += 1
            self._playhead = self.frames[self._frame_idx - 1].t
            return self.frames[self._frame_idx - 1]
        return None

    def seek(self, time_s):
        """跳转到指定时间"""
        self._playhead = max(0, time_s)
        self._frame_idx = 0
        for i, f in enumerate(self.frames):
            if f.t >= self._playhead:
                self._frame_idx = i
                break
        else:
            self._frame_idx = len(self.frames)
        self._finished = False

    def set_speed(self, speed):
        """设置播放倍速 (0.1 ~ 10.0)"""
        self._speed = max(0.1, min(10.0, speed))

    def set_loop(self, loop):
        """设置循环播放"""
        self._loop = loop

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def toggle_pause(self):
        self._paused = not self._paused

    def reset(self):
        """重置到开头"""
        self._playhead = 0.0
        self._frame_idx = 0
        self._finished = False

    # ── 状态查询 ──

    def is_paused(self):
        return self._paused

    def is_finished(self):
        return self._finished

    def is_empty(self):
        return len(self.frames) == 0

    def get_progress(self):
        """获取播放进度 (0.0 ~ 1.0)"""
        if not self.frames:
            return 0.0
        total_t = self.frames[-1].t
        return min(1.0, self._playhead / max(total_t, 0.001))

    def get_current_time(self):
        return self._playhead

    def get_total_time(self):
        if self.frames:
            return self.frames[-1].t
        return 0.0

    def get_speed(self):
        return self._speed

    def get_info(self):
        """获取回放状态摘要"""
        return {
            'name': self.metadata.get('name', ''),
            'source': self.metadata.get('source', ''),
            'total_frames': len(self.frames),
            'current_idx': self._frame_idx,
            'progress': round(self.get_progress() * 100, 1),
            'time': round(self._playhead, 2),
            'total_time': round(self.get_total_time(), 2),
            'speed': self._speed,
            'paused': self._paused,
            'finished': self._finished,
            'has_compare': len(self.compare_frames) > 0,
        }
