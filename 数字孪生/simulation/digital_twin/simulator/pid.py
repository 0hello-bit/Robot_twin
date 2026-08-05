# -*- coding: utf-8 -*-
"""
pid.py - PID 控制器
通用 PID 控制器实现，支持积分抗饱和、微分滤波。
"""

import config as cfg


class PIDController:
    """
    增量式 PID 控制器。
    
    与真实 STM32 代码中的 PID 结构一致，
    方便后续直接替换为嵌入式算法。
    """

    def __init__(self, kp=None, ki=None, kd=None,
                 output_min=None, output_max=None):
        """
        参数:
            kp, ki, kd: PID 增益
            output_min, output_max: 输出限幅
        """
        self.kp = kp if kp is not None else cfg.DEFAULT_KP
        self.ki = ki if ki is not None else cfg.DEFAULT_KI
        self.kd = kd if kd is not None else cfg.DEFAULT_KD

        self.output_min = output_min if output_min is not None else cfg.PID_OUTPUT_MIN
        self.output_max = output_max if output_max is not None else cfg.PID_OUTPUT_MAX

        # 内部状态
        self._integral = 0.0
        self._prev_error = 0.0
        self._first_run = True

        # 输出 (方便 UI 读取)
        self.output = 0.0
        self.error = 0.0
        self.p_term = 0.0
        self.i_term = 0.0
        self.d_term = 0.0

    def reset(self):
        """重置控制器状态"""
        self._integral = 0.0
        self._prev_error = 0.0
        self._first_run = True
        self.output = 0.0
        self.error = 0.0
        self.p_term = self.i_term = self.d_term = 0.0

    def compute(self, error, dt):
        """
        计算 PID 输出。
        
        参数:
            error: 误差值 (设定值 - 反馈值)
            dt:    时间步长 (s)
        
        返回:
            float: PID 输出 (已限幅)
        """
        if dt <= 0:
            return self.output

        # P
        self.p_term = self.kp * error

        # I (梯形积分)
        self._integral += error * dt
        self.i_term = self.ki * self._integral

        # D
        if self._first_run:
            self.d_term = 0.0
            self._first_run = False
        else:
            derivative = (error - self._prev_error) / dt
            self.d_term = self.kd * derivative

        self._prev_error = error
        self.error = error

        # 求和 + 限幅
        raw = self.p_term + self.i_term + self.d_term
        self.output = max(self.output_min, min(self.output_max, raw))

        # 积分抗饱和
        if self.output != raw:
            # 输出饱和时停止积分累积
            self._integral -= error * dt  # 回退本次积分

        return self.output

    def set_gains(self, kp=None, ki=None, kd=None):
        """动态调整 PID 参数"""
        if kp is not None:
            self.kp = kp
        if ki is not None:
            self.ki = ki
        if kd is not None:
            self.kd = kd

    def get_gains(self):
        """获取当前 PID 参数"""
        return self.kp, self.ki, self.kd
