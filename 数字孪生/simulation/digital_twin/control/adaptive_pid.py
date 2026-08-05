# -*- coding: utf-8 -*-
"""
adaptive_pid.py - 轻量自适应 PID 扩展层

核心思路:
    不重写 PID 公式, 只对 Kp/Ki/Kd 做"微调修正"。

    - error 大  → 增大 Kp (加速响应)
    - error 小且稳定 → 增大 Ki (消除稳态误差)
    - error 变化快 → 增大 Kd (抑制震荡)

所有修正通过 EMA 平滑, 防止参数突变。

使用方式:
    adapter = AdaptivePID(kp=0.6, ki=0.0, kd=0.15)
    kp, ki, kd = adapter.update(error, error_derivative, dt)
    pid.set_gains(kp, ki, kd)
    output = pid.compute(error, dt)
"""


class AdaptivePID:
    """
    轻量自适应 PID 参数调整器。

    不替代 PID, 只对参数做 EMA 平滑微调。

    使用:
        apid = AdaptivePID(kp=0.6, ki=0.0, kd=0.15)
        # 每个控制周期:
        kp, ki, kd = apid.update(error, error_derivative, dt)
    """

    # ── 默认参数范围 (硬限幅) ──
    DEFAULT_KP_RANGE = (0.05, 5.0)
    DEFAULT_KI_RANGE = (0.0, 2.0)
    DEFAULT_KD_RANGE = (0.0, 2.0)

    # ── EMA 平滑系数 (越小越平滑) ──
    DEFAULT_ALPHA_KP = 0.01
    DEFAULT_ALPHA_KI = 0.005
    DEFAULT_ALPHA_KD = 0.008

    # ── 误差阈值 ──
    LARGE_ERROR = 3.0       # 认为"误差大"的阈值
    SMALL_ERROR = 0.3       # 认为"误差小"的阈值
    HIGH_DERIVATIVE = 2.0   # 认为"变化快"的阈值

    def __init__(self, kp, ki, kd,
                 kp_range=None, ki_range=None, kd_range=None,
                 alpha_kp=None, alpha_ki=None, alpha_kd=None,
                 enabled=True):
        """
        参数:
            kp, ki, kd:   初始 PID 参数 (基准值)
            *_range:       参数允许范围 (min, max)
            alpha_*:       EMA 平滑系数 (0~1, 越小越平滑)
            enabled:       是否启用自适应
        """
        # 基准参数 (用户设定的初始值, 不变)
        self.base_kp = float(kp)
        self.base_ki = float(ki)
        self.base_kd = float(kd)

        # 当前自适应值
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)

        # 参数范围
        self.kp_range = kp_range or self.DEFAULT_KP_RANGE
        self.ki_range = ki_range or self.DEFAULT_KI_RANGE
        self.kd_range = kd_range or self.DEFAULT_KD_RANGE

        # EMA 系数
        self.alpha_kp = alpha_kp if alpha_kp is not None else self.DEFAULT_ALPHA_KP
        self.alpha_ki = alpha_ki if alpha_ki is not None else self.DEFAULT_ALPHA_KI
        self.alpha_kd = alpha_kd if alpha_kd is not None else self.DEFAULT_ALPHA_KD

        # 启用开关
        self.enabled = enabled

        # 内部状态 (用于 EMA)
        self._raw_kp = float(kp)
        self._raw_ki = float(ki)
        self._raw_kd = float(kd)

        # 稳态误差检测
        self._error_history = []
        self._history_max = 50
        self._steady_state_error = 0.0

    def update(self, error, error_derivative, dt):
        """
        计算自适应 PID 参数。

        参数:
            error:              当前误差
            error_derivative:   误差变化率 (de/dt)
            dt:                 时间步长 (s)

        返回:
            tuple: (kp, ki, kd) — 调整后的参数
        """
        if not self.enabled:
            return self.base_kp, self.base_ki, self.base_kd

        abs_error = abs(error)
        abs_deriv = abs(error_derivative)

        # ── 1. Kp 自适应 ──
        # 误差大 → 增大 Kp (加速响应)
        # 误差小 → 减小 Kp (避免过冲)
        kp_delta = 0.0
        if abs_error > self.LARGE_ERROR:
            scale = min((abs_error - self.LARGE_ERROR) / self.LARGE_ERROR, 1.0)
            kp_delta = self.base_kp * 0.3 * scale
        elif abs_error < self.SMALL_ERROR:
            kp_delta = -self.base_kp * 0.1

        self._raw_kp = self.base_kp + kp_delta
        self.kp = self._clamp(self._ema(self.kp, self._raw_kp, self.alpha_kp),
                              self.kp_range)

        # ── 2. Ki 自适应 ──
        # 稳态误差持续存在 → 增大 Ki (消除静差)
        # 误差大 → 减小 Ki (防止积分饱和)
        self._update_steady_state(abs_error)
        ki_delta = 0.0
        if self._steady_state_error > self.SMALL_ERROR and abs_error < self.LARGE_ERROR:
            scale = min(self._steady_state_error / self.LARGE_ERROR, 1.0)
            ki_delta = self.base_ki * 0.5 * scale if self.base_ki > 0 else 0.01 * scale
        elif abs_error > self.LARGE_ERROR:
            ki_delta = -self.base_ki * 0.2

        self._raw_ki = self.base_ki + ki_delta
        self.ki = self._clamp(self._ema(self.ki, self._raw_ki, self.alpha_ki),
                              self.ki_range)

        # ── 3. Kd 自适应 ──
        # 误差变化快 → 增大 Kd (抑制震荡)
        # 误差变化慢 → 减小 Kd (减少噪声放大)
        kd_delta = 0.0
        if abs_deriv > self.HIGH_DERIVATIVE:
            scale = min((abs_deriv - self.HIGH_DERIVATIVE) / self.HIGH_DERIVATIVE, 1.0)
            kd_delta = self.base_kd * 0.4 * scale
        elif abs_deriv < 0.5:
            kd_delta = -self.base_kd * 0.1

        self._raw_kd = self.base_kd + kd_delta
        self.kd = self._clamp(self._ema(self.kd, self._raw_kd, self.alpha_kd),
                              self.kd_range)

        return self.kp, self.ki, self.kd

    def _ema(self, current, target, alpha):
        """指数移动平均"""
        return current + alpha * (target - current)

    def _clamp(self, value, value_range):
        """将值限制在范围内"""
        return max(value_range[0], min(value_range[1], value))

    def _update_steady_state(self, abs_error):
        """更新稳态误差估计"""
        self._error_history.append(abs_error)
        if len(self._error_history) > self._history_max:
            self._error_history.pop(0)

        if len(self._error_history) >= 10:
            recent = self._error_history[-10:]
            self._steady_state_error = sum(recent) / len(recent)

    def get_gains(self):
        """获取当前自适应后的 PID 参数"""
        return self.kp, self.ki, self.kd

    def get_base_gains(self):
        """获取基准 PID 参数"""
        return self.base_kp, self.base_ki, self.base_kd

    def get_deviation(self):
        """获取当前参数相对于基准的偏离度"""
        def safe_pct(current, base):
            if abs(base) < 1e-10:
                # 基准为 0 时, 用绝对值衡量偏离
                return round(min(abs(current) * 100, 100.0), 2)
            return round(abs(current - base) / abs(base) * 100, 2)

        return {
            'kp_deviation_pct': safe_pct(self.kp, self.base_kp),
            'ki_deviation_pct': safe_pct(self.ki, self.base_ki),
            'kd_deviation_pct': safe_pct(self.kd, self.base_kd),
            'steady_state_error': round(self._steady_state_error, 4),
        }

    def reset(self):
        """重置到基准参数"""
        self.kp = self.base_kp
        self.ki = self.base_ki
        self.kd = self.base_kd
        self._raw_kp = self.base_kp
        self._raw_ki = self.base_ki
        self._raw_kd = self.base_kd
        self._error_history.clear()
        self._steady_state_error = 0.0

    def set_enabled(self, enabled):
        """启用/禁用自适应"""
        self.enabled = enabled
        if not enabled:
            self.reset()

    def set_base_gains(self, kp, ki, kd):
        """更新基准参数 (例如用户手动调参后)"""
        self.base_kp = float(kp)
        self.base_ki = float(ki)
        self.base_kd = float(kd)