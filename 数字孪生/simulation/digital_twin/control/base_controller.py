# -*- coding: utf-8 -*-
"""
base_controller.py - 标准化控制器接口
所有控制器（仿真/PID/未来STM32）必须实现此接口。
确保仿真控制器、真实STM32代码、虚拟小车可以互换。
"""

from abc import ABC, abstractmethod


class ControllerOutput:
    """
    控制器输出统一结构。
    
    与真实 STM32 Motor.c 的 Motor1_SetSpeed(direction, pwm) 对齐。
    """
    __slots__ = ('left_speed', 'right_speed', 'raw_pid',
                 'sensor_reading', 'error', 'metadata')

    def __init__(self):
        self.left_speed = 0.0     # 左轮归一化速度 (-1 ~ +1)
        self.right_speed = 0.0    # 右轮归一化速度 (-1 ~ +1)
        self.raw_pid = 0.0        # PID 原始输出 (未分配到轮子)
        self.sensor_reading = []  # 本轮传感器读数 [S0..S3]
        self.error = 0.0          # 本轮误差值
        self.metadata = {}        # 扩展字段 (延迟/噪声等)


class BaseController(ABC):
    """
    控制器抽象基类。
    
    所有控制器必须实现:
        - update(sensor_input, dt) -> ControllerOutput
        - reset()
    
    设计目标:
        1. Python 仿真控制器和 STM32 真实代码使用同一接口
        2. 可以在运行时热替换控制器
        3. 输出结构统一，方便日志记录和对比
    """

    @abstractmethod
    def update(self, sensor_input, dt):
        """
        执行一步控制计算。
        
        参数:
            sensor_input: list[int] - 传感器状态 [S0, S1, S2, S3]
                          0=检测到黑线, 1=白底
            dt: float - 时间步长 (s)
        
        返回:
            ControllerOutput: 统一控制输出
        """
        pass

    @abstractmethod
    def reset(self):
        """重置控制器内部状态"""
        pass

    def get_name(self):
        """控制器名称 (用于日志/显示)"""
        return self.__class__.__name__

    def get_params(self):
        """获取当前参数 (用于日志记录)"""
        return {}


class LineFollowController(BaseController):
    """
    巡线控制器的标准实现。
    
    封装原有 LineFollower 的逻辑，同时实现 BaseController 接口。
    """

    WEIGHTS = [-3.0, -1.0, 1.0, 3.0]

    def __init__(self, kp=0.6, ki=0.0, kd=0.15, base_speed=200):
        from simulator.pid import PIDController
        self.pid = PIDController(kp=kp, ki=ki, kd=kd)
        self.base_speed = base_speed
        self.enabled = True

        # 诊断
        self.position = 0.0
        self.black_count = 0
        self.pid_output = 0.0
        self.motor_cmd = (0.0, 0.0)

    def update(self, sensor_input, dt):
        if not self.enabled:
            return ControllerOutput()

        position = 0.0
        black_count = 0
        for i, state in enumerate(sensor_input):
            if state == 0:
                position += self.WEIGHTS[i]
                black_count += 1

        self.position = position
        self.black_count = black_count

        out = ControllerOutput()
        out.sensor_reading = list(sensor_input)
        out.error = position

        if black_count == 4:
            self.pid.reset()
            base = self.base_speed / 999.0
            out.left_speed = base
            out.right_speed = base
        elif black_count == 0:
            self.pid.reset()
            base = self.base_speed * 0.5 / 999.0
            out.left_speed = base
            out.right_speed = base
        else:
            self.pid_output = self.pid.compute(position, dt)
            self.pid_output = max(-1.0, min(1.0, self.pid_output))
            out.raw_pid = self.pid_output
            base = self.base_speed / 999.0
            out.left_speed = max(-1.0, min(1.0, base + self.pid_output * 0.5))
            out.right_speed = max(-1.0, min(1.0, base - self.pid_output * 0.5))

        self.motor_cmd = (out.left_speed, out.right_speed)
        return out

    def reset(self):
        self.pid.reset()
        self.position = 0.0
        self.black_count = 0
        self.pid_output = 0.0
        self.motor_cmd = (0.0, 0.0)

    def get_name(self):
        kp, ki, kd = self.pid.get_gains()
        return f"PID(Kp={kp:.2f},Ki={ki:.2f},Kd={kd:.2f})"

    def get_params(self):
        kp, ki, kd = self.pid.get_gains()
        return {'kp': kp, 'ki': ki, 'kd': kd,
                'base_speed': self.base_speed}
