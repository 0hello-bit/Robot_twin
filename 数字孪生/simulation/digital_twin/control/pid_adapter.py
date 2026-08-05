# -*- coding: utf-8 -*-
"""
pid_adapter.py - PID 适配器 (包装层)

作用:
    包装现有 PID controller, 在每个控制周期前
    自动调用 AdaptivePID 微调参数。

    不修改原有 PID 代码, 只做"参数注入"。

使用方式:
    from simulator.pid import PIDController
    from control.pid_adapter import PIDAdapter

    base_pid = PIDController(kp=0.6, ki=0.0, kd=0.15)
    adapter = PIDAdapter(base_pid)

    # 每个控制周期:
    output = adapter.step(error, dt)
"""

from control.adaptive_pid import AdaptivePID


class PIDAdapter:
    """
    PID 适配器 — 在不修改原有 PID 的前提下增加自适应能力。

    使用:
        adapter = PIDAdapter(base_pid)
        output = adapter.step(error, dt)
    """

    def __init__(self, pid_controller,
                 alpha_kp=None, alpha_ki=None, alpha_kd=None,
                 kp_range=None, ki_range=None, kd_range=None,
                 enabled=True):
        """
        参数:
            pid_controller:  现有 PIDController 实例
            alpha_*:         自适应 EMA 系数 (可选, None=默认)
            *_range:         参数范围限制 (可选)
            enabled:         是否启用自适应
        """
        self.pid = pid_controller

        # 保存 PID 原始增益 (用于 disabled 时恢复)
        kp, ki, kd = pid_controller.get_gains()
        self._saved_kp = kp
        self._saved_ki = ki
        self._saved_kd = kd

        # 创建自适应核心
        self._adaptive = AdaptivePID(
            kp=kp, ki=ki, kd=kd,
            kp_range=kp_range, ki_range=ki_range, kd_range=kd_range,
            alpha_kp=alpha_kp, alpha_ki=alpha_ki, alpha_kd=alpha_kd,
            enabled=enabled,
        )

        # 内部状态
        self._prev_error = None
        self._step_count = 0

    def step(self, error, dt):
        """
        执行一步自适应 PID 控制。

        参数:
            error:  当前误差
            dt:     时间步长 (s)

        返回:
            float: PID 输出 (与 pid.compute() 返回值一致)
        """
        # 计算 error derivative
        if self._prev_error is not None and dt > 0:
            error_derivative = (error - self._prev_error) / dt
        else:
            error_derivative = 0.0

        self._prev_error = error

        # 自适应更新参数
        if self._adaptive.enabled:
            kp, ki, kd = self._adaptive.update(error, error_derivative, dt)
            self.pid.set_gains(kp, ki, kd)
        else:
            # 确保 disabled 时 PID 保持原始参数
            self.pid.set_gains(self._saved_kp, self._saved_ki, self._saved_kd)

        # 正常 PID 计算
        output = self.pid.compute(error, dt)
        self._step_count += 1

        return output

    def reset(self):
        """重置适配器和 PID"""
        self.pid.set_gains(self._saved_kp, self._saved_ki, self._saved_kd)
        self.pid.reset()
        self._adaptive.reset()
        self._prev_error = None
        self._step_count = 0

    def get_gains(self):
        """获取当前自适应后的 PID 参数"""
        return self.pid.get_gains()

    def get_base_gains(self):
        """获取基准 PID 参数"""
        return self._adaptive.get_base_gains()

    def get_deviation(self):
        """获取参数偏离度"""
        return self._adaptive.get_deviation()

    def get_step_count(self):
        """获取已执行步数"""
        return self._step_count

    def set_enabled(self, enabled):
        """启用/禁用自适应"""
        self._adaptive.set_enabled(enabled)

    def is_enabled(self):
        """是否启用自适应"""
        return self._adaptive.enabled

    def set_base_gains(self, kp, ki, kd):
        """更新基准参数"""
        self._adaptive.set_base_gains(kp, ki, kd)
        self._saved_kp = kp
        self._saved_ki = ki
        self._saved_kd = kd