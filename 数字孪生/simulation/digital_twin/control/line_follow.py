# -*- coding: utf-8 -*-
"""
line_follow.py - 巡线控制逻辑
基于 PID 的巡线算法，将传感器读数转换为电机控制信号。
"""

import config as cfg
from simulator.pid import PIDController


class LineFollower:
    """
    巡线控制器。
    
    逻辑流程:
        1. 读取 4 路传感器状态
        2. 计算偏差 (error)
        3. PID 计算输出
        4. 将输出转换为电机 PWM
    
    与真实 STM32 代码结构对应:
        sensor_read → position_calc → pid_compute → motor_set
    """

    # 传感器位置权重 (与真实代码一致)
    # S0=-3, S1=-1, S2=+1, S3=+3
    WEIGHTS = [-3.0, -1.0, 1.0, 3.0]

    def __init__(self):
        self.pid = PIDController()
        self.base_speed = int(cfg.PWM_MAX * 0.2)  # 基础前进速度
        self.enabled = True

        # 诊断信息 (供 UI 显示)
        self.position = 0.0       # 加权偏差
        self.black_count = 0      # 检测到黑线的传感器数
        self.pid_output = 0.0     # PID 输出
        self.motor_cmd = (0, 0)   # (left_pwm, right_pwm)

    def compute_error(self, sensor_states):
        """
        从传感器状态计算加权偏差。
        
        参数:
            sensor_states: [S0, S1, S2, S3]，0=黑线, 1=白底
        
        返回:
            (position, black_count)
        """
        position = 0.0
        black_count = 0
        for i, state in enumerate(sensor_states):
            if state == 0:  # 检测到黑线
                position += self.WEIGHTS[i]
                black_count += 1
        return position, black_count

    def update(self, sensor_states, dt):
        """
        执行一步巡线控制。
        
        参数:
            sensor_states: [S0, S1, S2, S3]
            dt: 时间步长 (s)
        
        返回:
            (left_speed, right_speed) 归一化速度 (-1 ~ 1)
        """
        if not self.enabled:
            return 0.0, 0.0

        position, black_count = self.compute_error(sensor_states)
        self.position = position
        self.black_count = black_count

        # 全黑 (交叉路口) 或全白 (丢线) 的特殊处理
        if black_count == 4:
            # 交叉路口: 直行
            self.pid.reset()
            left = self.base_speed / cfg.PWM_MAX
            right = self.base_speed / cfg.PWM_MAX
        elif black_count == 0:
            # 丢线: 以较低速度直行 (尝试找回)
            self.pid.reset()
            left = self.base_speed * 0.5 / cfg.PWM_MAX
            right = self.base_speed * 0.5 / cfg.PWM_MAX
        else:
            # 正常巡线: PID 控制
            # error < 0 表示偏左 → 需要右转 → 左轮加速
            self.pid_output = self.pid.compute(position, dt)
            self.pid_output = max(-1.0, min(1.0, self.pid_output))

            # 差速分配
            base = self.base_speed / cfg.PWM_MAX
            left  = base + self.pid_output * 0.5
            right = base - self.pid_output * 0.5

            # 限幅
            left  = max(-1.0, min(1.0, left))
            right = max(-1.0, min(1.0, right))

        self.motor_cmd = (left, right)
        return left, right

    def set_pid_gains(self, kp=None, ki=None, kd=None):
        """动态调整 PID 参数"""
        self.pid.set_gains(kp, ki, kd)

    def set_base_speed(self, speed_pwm):
        """设置基础前进速度 (PWM)"""
        self.base_speed = max(0, min(cfg.PWM_MAX, speed_pwm))

    def toggle(self):
        """开关巡线"""
        self.enabled = not self.enabled
        if not self.enabled:
            self.pid.reset()
