# -*- coding: utf-8 -*-
"""
device_bus.py - 虚拟硬件总线
连接 STM32 兼容层与仿真器核心。
所有虚拟硬件通过此总线读写真实仿真状态。
"""

import threading


class VirtualDeviceBus:
    """
    虚拟硬件总线。
    
    设计原则:
        - 所有硬件设备通过此总线注册和访问
        - 提供线程安全的读写
        - 模拟真实 MCU 的外设地址空间
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sensors = [0, 0, 0, 0]    # 传感器 GPIO 状态
        self._pwm = [0, 0, 0, 0]        # PWM 占空比 (0~999)
        self._motor_dir = [0, 0, 0, 0]  # 电机方向 (0=Forward, 1=Backward)
        self._delay_ms_value = 0         # 最近一次 delay 调用值
        self._tick_ms = 0                # MCU tick 计数 (ms)
        self._callbacks = {}             # 事件回调

    # ── 传感器 GPIO ──

    def set_sensor_state(self, sensor_id, value):
        """设置传感器状态 (由仿真器调用)"""
        with self._lock:
            self._sensors[sensor_id] = value

    def set_all_sensors(self, states):
        """批量设置传感器"""
        with self._lock:
            self._sensors = list(states)

    def get_sensor_state(self, pin_name):
        """
        读取传感器 GPIO 状态 (由 STM32 代码调用)。
        返回: 0 或 1
        """
        pin_map = {
            'PB1': 0,  # Sensor0
            'PB0': 1,  # Sensor1
            'PB4': 2,  # Sensor2
            'PB5': 3,  # Sensor3
        }
        idx = pin_map.get(pin_name, 0)
        with self._lock:
            return self._sensors[idx]

    # ── PWM 电机控制 ──

    def set_motor(self, motor_id, direction, speed):
        """
        设置电机 PWM (由 STM32 代码调用)。
        
        参数:
            motor_id:  0~3
            direction: 0=Forward通道, 1=Backward通道
            speed:     0~999
        """
        with self._lock:
            self._motor_dir[motor_id] = direction
            self._pwm[motor_id] = min(999, max(0, speed))

    def get_motor_state(self, motor_id):
        """获取电机当前状态 (direction, speed)"""
        with self._lock:
            return self._motor_dir[motor_id], self._pwm[motor_id]

    def get_all_motors(self):
        """获取所有电机状态"""
        with self._lock:
            return [(self._motor_dir[i], self._pwm[i]) for i in range(4)]

    def stop_all_motors(self):
        """急停所有电机"""
        with self._lock:
            self._pwm = [0, 0, 0, 0]

    # ── 延时模拟 ──

    def delay_ms(self, ms):
        """
        模拟 Delay_ms。
        在仿真中不真正阻塞，而是记录延迟值。
        实际时间推进由仿真器的时钟控制。
        """
        self._delay_ms_value = ms

    def get_delay_value(self):
        return self._delay_ms_value

    # ── MCU Tick ──

    def get_tick_ms(self):
        """获取 MCU 运行时间 (ms)"""
        return self._tick_ms

    def advance_tick(self, dt_ms):
        """推进 MCU 时钟"""
        self._tick_ms += dt_ms

    # ── 寄存器兼容 (极简) ──

    def set_register(self, reg_name, value):
        """极简寄存器写入 (用于模拟 RCC/GPIO_Init 等)"""
        pass  # 仿真中忽略寄存器操作

    def get_register(self, reg_name):
        return 0

    # ── 状态导出 ──

    def get_status(self):
        """导出总线完整状态"""
        with self._lock:
            return {
                'sensors': list(self._sensors),
                'motors': [(self._motor_dir[i], self._pwm[i]) for i in range(4)],
                'delay_ms': self._delay_ms_value,
                'tick_ms': self._tick_ms,
            }
