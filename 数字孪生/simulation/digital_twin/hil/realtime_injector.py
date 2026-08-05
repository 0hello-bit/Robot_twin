# -*- coding: utf-8 -*-
"""
realtime_injector.py - 实时遥测数据注入器

功能:
    1. 将真实 STM32 telemetry 实时注入仿真器
    2. 替换 plant_model 的输入 (从 simulated → real-world driven)
    3. 支持三种模式:
       - LIVE:     实时驱动 (真实 PWM → 虚拟小车)
       - REPLAY:   回放模式 (历史数据 → 虚拟小车)
       - HYBRID:   混合模式 (真实传感器 + 仿真 PWM)

核心原理:
    真实小车的 telemetry 数据:
        sensor[4], pwm_left, pwm_right, error, tick_ms

    注入到仿真器中:
        虚拟小车读取真实传感器状态
        虚拟小车使用真实 PWM 值
        仿真器只负责 "可视化" 和 "记录"

    这样:
        真实小车在地面跑
        电脑上的虚拟小车同步显示相同行为
"""

import time
import threading
import collections


class InjectionMode:
    """注入模式"""
    LIVE = 'live'           # 实时注入
    REPLAY = 'replay'       # 回放模式
    HYBRID = 'hybrid'       # 混合模式 (真实传感器 + 仿真PID)
    PASSIVE = 'passive'     # 被动监听 (只记录不注入)


class RealtimeInjector:
    """
    实时遥测数据注入器。

    将真实 telemetry 数据注入仿真器, 驱动虚拟小车行为。

    使用:
        injector = RealtimeInjector(mode=InjectionMode.LIVE)

        # 收到 telemetry 时:
        state = injector.inject(telemetry_packet)

        # 获取注入后的小车状态:
        car_state = injector.get_car_state()
    """

    # 状态缓冲区大小
    MAX_BUFFER = 500
    # 数据超时 (秒)
    DATA_TIMEOUT = 2.0

    def __init__(self, mode=InjectionMode.LIVE):
        self._lock = threading.Lock()
        self._mode = mode

        # 标准化状态向量 (最新)
        self._current_state = {
            'timestamp': 0.0,
            'stm32_tick_ms': 0,
            'position_error': 0.0,
            'pwm_left': 180,
            'pwm_right': 180,
            'sensor': [1, 1, 1, 1],
            'velocity_estimate': 0.0,
            'mode': 'unknown',
            'lost_count': 0,
            'battery_mv': 0,
        }

        # 历史缓冲
        self._state_history = collections.deque(maxlen=self.MAX_BUFFER)

        # 统计
        self._inject_count = 0
        self._drop_count = 0
        self._start_time = time.monotonic()
        self._last_inject_time = 0.0

        # Velocity estimation (简单的差分速度估计)
        self._prev_x = 0.0
        self._prev_y = 0.0
        self._prev_time = 0.0

        # 模式特定状态
        self._hybrid_sensors = [1, 1, 1, 1]
        self._hybrid_error = 0.0

        # Replay 模式
        self._replay_buffer = []
        self._replay_index = 0

    def inject(self, telemetry_packet):
        """
        注入一个 telemetry 数据包。

        参数:
            telemetry_packet: TelemetryPacket 或 dict

        返回:
            dict: 注入后的标准化状态
        """
        with self._lock:
            state = self._parse_packet(telemetry_packet)

            if state is None:
                self._drop_count += 1
                return self._current_state

            self._current_state = state
            self._state_history.append(state.copy())
            self._inject_count += 1
            self._last_inject_time = time.monotonic()

            return state.copy()

    def _parse_packet(self, pkt):
        """将 telemetry packet 解析为标准化状态向量"""
        try:
            if hasattr(pkt, 'timestamp'):
                # TelemetryPacket 对象
                timestamp = pkt.timestamp
                s0 = getattr(pkt, 's0', 1)
                s1 = getattr(pkt, 's1', 1)
                s2 = getattr(pkt, 's2', 1)
                s3 = getattr(pkt, 's3', 1)
                pwm_l = getattr(pkt, 'left_pwm', 180)
                pwm_r = getattr(pkt, 'right_pwm', 180)
                error = getattr(pkt, 'error', 0)
                tick_ms = getattr(pkt, 'tick_ms', 0)
                pid_out = getattr(pkt, 'pid_output', 0)
            elif isinstance(pkt, dict):
                # 字典格式
                timestamp = pkt.get('timestamp', time.monotonic())
                s0 = pkt.get('s0', pkt.get('sensors', [1, 1, 1, 1])[0])
                s1 = pkt.get('s1', pkt.get('sensors', [1, 1, 1, 1])[1])
                s2 = pkt.get('s2', pkt.get('sensors', [1, 1, 1, 1])[2])
                s3 = pkt.get('s3', pkt.get('sensors', [1, 1, 1, 1])[3])
                pwm_l = pkt.get('pwm_left', pkt.get('left_pwm', 180))
                pwm_r = pkt.get('pwm_right', pkt.get('right_pwm', 180))
                error = pkt.get('error', 0)
                tick_ms = pkt.get('tick_ms', pkt.get('tick', 0))
                pid_out = pkt.get('pid_output', 0)
            else:
                return None

            # 速度估计 (基于 PWM 差值)
            vel = self._estimate_velocity(pwm_l, pwm_r)

            state = {
                'timestamp': timestamp,
                'stm32_tick_ms': tick_ms,
                'position_error': float(error),
                'pwm_left': float(pwm_l),
                'pwm_right': float(pwm_r),
                'sensor': [int(s0), int(s1), int(s2), int(s3)],
                'velocity_estimate': vel,
                'mode': 'live' if self._mode == InjectionMode.LIVE else self._mode,
                'lost_count': 0,
                'battery_mv': 0,
            }

            return state

        except Exception:
            return None

    def _estimate_velocity(self, pwm_left, pwm_right):
        """
        基于 PWM 值估计小车速度。

        简单模型: v = (pwm_left + pwm_right) / 2 - 180 (中值为停)
        """
        base = 180.0  # 中值 PWM
        v_left = pwm_left - base
        v_right = pwm_right - base
        return (v_left + v_right) / 2.0

    def get_car_state(self):
        """获取当前虚拟小车应处的状态"""
        with self._lock:
            return self._current_state.copy()

    def get_sensor_reading(self):
        """获取当前传感器读数 (用于替换仿真器的传感器)"""
        with self._lock:
            return list(self._current_state['sensor'])

    def get_motor_command(self):
        """获取当前电机命令 (用于替换仿真器的电机输入)"""
        with self._lock:
            return (self._current_state['pwm_left'],
                    self._current_state['pwm_right'])

    def get_position_error(self):
        """获取当前位置误差"""
        with self._lock:
            return self._current_state['position_error']

    def is_data_alive(self):
        """是否有新鲜数据"""
        with self._lock:
            if self._last_inject_time == 0:
                return False
            return (time.monotonic() - self._last_inject_time) < self.DATA_TIMEOUT

    def get_mode(self):
        """获取当前注入模式"""
        return self._mode

    def set_mode(self, mode):
        """切换注入模式"""
        self._mode = mode

    def get_stats(self):
        """
        获取注入统计。

        返回:
            dict: inject_count, drop_count, drop_rate, uptime, data_alive
        """
        with self._lock:
            uptime = time.monotonic() - self._start_time
            total = self._inject_count + self._drop_count
            drop_rate = self._drop_count / max(total, 1) * 100

            return {
                'inject_count': self._inject_count,
                'drop_count': self._drop_count,
                'drop_rate_pct': round(drop_rate, 2),
                'uptime_s': round(uptime, 1),
                'data_alive': self.is_data_alive(),
                'mode': self._mode,
                'buffer_size': len(self._state_history),
                'inject_rate_hz': round(self._inject_count / max(uptime, 0.01), 1),
            }

    def get_history(self, last_n=None):
        """获取注入历史"""
        with self._lock:
            if last_n:
                return list(self._state_history)[-last_n:]
            return list(self._state_history)

    # ── Replay 模式 ──

    def load_replay_data(self, data_list):
        """
        加载回放数据。

        参数:
            data_list: list of dict 或 TelemetryPacket
        """
        with self._lock:
            self._replay_buffer = []
            for pkt in data_list:
                state = self._parse_packet(pkt)
                if state:
                    self._replay_buffer.append(state)
            self._replay_index = 0

    def step_replay(self):
        """
        回放模式: 前进一步。

        返回:
            dict: 当前状态, 或 None (回放结束)
        """
        with self._lock:
            if self._replay_index >= len(self._replay_buffer):
                return None
            state = self._replay_buffer[self._replay_index]
            self._replay_index += 1
            self._current_state = state
            self._state_history.append(state.copy())
            self._inject_count += 1
            return state.copy()

    def replay_progress(self):
        """回放进度 (0~1)"""
        with self._lock:
            total = len(self._replay_buffer)
            if total == 0:
                return 0.0
            return self._replay_index / total

    def reset(self):
        """重置注入器"""
        with self._lock:
            self._current_state = {
                'timestamp': 0.0,
                'stm32_tick_ms': 0,
                'position_error': 0.0,
                'pwm_left': 180,
                'pwm_right': 180,
                'sensor': [1, 1, 1, 1],
                'velocity_estimate': 0.0,
                'mode': 'unknown',
                'lost_count': 0,
                'battery_mv': 0,
            }
            self._state_history.clear()
            self._inject_count = 0
            self._drop_count = 0
            self._start_time = time.monotonic()
            self._last_inject_time = 0.0
            self._replay_buffer.clear()
            self._replay_index = 0