# -*- coding: utf-8 -*-
"""
pwm_speed_identification.py - PWM → 速度系统辨识

职责:
    1. 从真实 telemetry 数据中提取 PWM-速度对应关系
    2. 拟合线性/多项式/分段模型
    3. 输出可直接写入 config.py 的参数

数据来源:
    - HIL 录制的真实遥测数据
    - Replay 回放数据
    - 手动标注的步进响应数据

拟合模型:
    1. 线性:     v = a * PWM + b
    2. 二次:     v = a * PWM² + b * PWM + c
    3. 分段线性: 查表 + 插值

注意:
    无编码器时, 速度从传感器模式变化率推断
    有编码器时, 直接使用编码器读数
"""

import json
import math
import os
import time


# ══════════════════════════════════════════════════════════════
#  数据结构
# ══════════════════════════════════════════════════════════════

class MotorSample:
    """单个电机采样点: PWM输入 → 速度输出"""
    __slots__ = ('timestamp', 'pwm', 'velocity', 'direction')

    def __init__(self, timestamp, pwm, velocity, direction=1):
        """
        参数:
            timestamp: 采样时间 (s)
            pwm:       PWM 输入 (0~999)
            velocity:  实际速度 (px/s 或 归一化)
            direction: 1=正转, -1=反转
        """
        self.timestamp = timestamp
        self.pwm = abs(pwm)
        self.velocity = abs(velocity)
        self.direction = direction


# ══════════════════════════════════════════════════════════════
#  速度推断 (无编码器方案)
# ══════════════════════════════════════════════════════════════

def infer_velocity_from_telemetry(records, dt=0.03):
    """
    从遥测记录推断速度。

    方法: 使用 PWM 值的加权平均作为速度代理。
    在无编码器的情况下, PWM 与速度近似线性相关。

    对于更精确的速度推断, 需要编码器数据。

    参数:
        records: list[dict] - HIL 录制数据
        dt:      控制周期 (s)

    返回:
        list[MotorSample]
    """
    samples = []
    for i, rec in enumerate(records):
        t = rec.get('t', i * dt)
        sensors = rec.get('sensors', [1, 1, 1, 1])

        # 从传感器模式推断运动方向
        # S0=最左, S3=最右
        # 如果 S0/S1 检测到线 → 车偏右 → 在左转
        # 如果 S2/S3 检测到线 → 车偏左 → 在右转

        # PWM 值作为速度代理 (在没有编码器时最直接)
        left_pwm = rec.get('left_pwm', 0)
        right_pwm = rec.get('right_pwm', 0)

        # 左轮速度代理
        samples.append(MotorSample(t, left_pwm, left_pwm / 999.0, 1))
        # 右轮速度代理
        samples.append(MotorSample(t, right_pwm, right_pwm / 999.0, 1))

    return samples


def infer_velocity_from_encoder(records, encoder_cpr, wheel_radius, dt=0.03):
    """
    从编码器数据推断真实速度 (高精度方案)。

    参数:
        records:      list[dict] - 包含 encoder_count 字段的数据
        encoder_cpr:  编码器每转脉冲数
        wheel_radius: 轮子半径 (mm)
        dt:           采样周期 (s)

    返回:
        list[MotorSample]
    """
    samples = []
    prev_left = 0
    prev_right = 0

    for i, rec in enumerate(records):
        t = rec.get('t', i * dt)
        enc_left = rec.get('encoder_left', 0)
        enc_right = rec.get('encoder_right', 0)

        # 编码器差分 → 角速度 → 线速度
        d_left = enc_left - prev_left
        d_right = enc_right - prev_right
        prev_left = enc_left
        prev_right = enc_right

        # RPM = (delta / CPR) * (60 / dt)
        rpm_left = (d_left / encoder_cpr) * (60.0 / dt)
        rpm_right = (d_right / encoder_cpr) * (60.0 / dt)

        # 线速度 = RPM * 2π * R / 60
        vel_left = abs(rpm_left * 2 * math.pi * wheel_radius / 60.0)
        vel_right = abs(rpm_right * 2 * math.pi * wheel_radius / 60.0)

        left_pwm = rec.get('left_pwm', 0)
        right_pwm = rec.get('right_pwm', 0)

        samples.append(MotorSample(t, left_pwm, vel_left,
                                    1 if d_left >= 0 else -1))
        samples.append(MotorSample(t, right_pwm, vel_right,
                                    1 if d_right >= 0 else -1))

    return samples


# ══════════════════════════════════════════════════════════════
#  曲线拟合
# ══════════════════════════════════════════════════════════════

class CurveFitter:
    """
    PWM → 速度曲线拟合器。

    支持:
        1. 线性模型:      v = a * PWM + b
        2. 二次多项式:    v = a * PWM² + b * PWM + c
        3. 分段线性:      查表插值
    """

    def __init__(self):
        self.samples = []
        self.fit_result = None

    def add_samples(self, samples):
        """添加采样数据"""
        self.samples.extend(samples)

    def clear(self):
        self.samples = []
        self.fit_result = None

    def fit_linear(self):
        """
        线性拟合: v = a * PWM + b

        使用最小二乘法。
        返回: dict {a, b, r_squared, rmse}
        """
        n = len(self.samples)
        if n < 2:
            return {'error': 'insufficient data', 'n_samples': n}

        xs = [s.pwm for s in self.samples]
        ys = [s.velocity for s in self.samples]

        # 最小二乘
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xx = sum(x * x for x in xs)
        sum_xy = sum(x * y for x, y in zip(xs, ys))

        denom = n * sum_xx - sum_x * sum_x
        if abs(denom) < 1e-10:
            return {'error': 'singular matrix', 'n_samples': n}

        a = (n * sum_xy - sum_x * sum_y) / denom
        b = (sum_y - a * sum_x) / n

        # R² 和 RMSE
        y_mean = sum_y / n
        ss_res = sum((y - (a * x + b))**2 for x, y in zip(xs, ys))
        ss_tot = sum((y - y_mean)**2 for y in ys)
        r_squared = 1 - ss_res / max(ss_tot, 1e-10)
        rmse = math.sqrt(ss_res / n)

        result = {
            'model': 'linear',
            'a': a, 'b': b,
            'r_squared': round(r_squared, 4),
            'rmse': round(rmse, 6),
            'n_samples': n,
        }
        self.fit_result = result
        return result

    def fit_quadratic(self):
        """
        二次拟合: v = a * PWM² + b * PWM + c

        使用最小二乘法 (正规方程)。
        返回: dict {a, b, c, r_squared, rmse}
        """
        n = len(self.samples)
        if n < 3:
            return {'error': 'insufficient data', 'n_samples': n}

        xs = [s.pwm for s in self.samples]
        ys = [s.velocity for s in self.samples]

        # 构建正规方程: [Σx⁴ Σx³ Σx²] [a]   [Σx²y]
        #                [Σx³ Σx² Σx ] [b] = [Σxy ]
        #                [Σx² Σx  n  ] [c]   [Σy  ]
        Sx2 = sum(x*x for x in xs)
        Sx3 = sum(x*x*x for x in xs)
        Sx4 = sum(x**4 for x in xs)
        Sy = sum(ys)
        Sxy = sum(x*y for x, y in zip(xs, ys))
        Sx2y = sum(x*x*y for x, y in zip(xs, ys))

        # 3x3 求解 (Cramer's rule)
        A = [[Sx4, Sx3, Sx2],
             [Sx3, Sx2, Sx2 if False else sum(xs)],
             [Sx2, sum(xs), n]]
        B = [Sx2y, Sxy, Sy]

        det = _det3(A)
        if abs(det) < 1e-10:
            return {'error': 'singular matrix', 'n_samples': n}

        a = _solve_cramer(A, B, 0, det)
        b = _solve_cramer(A, B, 1, det)
        c = _solve_cramer(A, B, 2, det)

        y_mean = Sy / n
        ss_res = sum((y - (a*x*x + b*x + c))**2 for x, y in zip(xs, ys))
        ss_tot = sum((y - y_mean)**2 for y in ys)
        r_squared = 1 - ss_res / max(ss_tot, 1e-10)
        rmse = math.sqrt(ss_res / n)

        result = {
            'model': 'quadratic',
            'a': a, 'b': b, 'c': c,
            'r_squared': round(r_squared, 4),
            'rmse': round(rmse, 6),
            'n_samples': n,
        }
        self.fit_result = result
        return result

    def fit_piecewise_linear(self, n_segments=5):
        """
        分段线性拟合 (查表 + 插值)。

        将 PWM 范围 [0, 999] 分成 n_segments 段,
        每段内线性拟合。

        返回: dict {breakpoints, slopes, intercepts, rmse}
        """
        n = len(self.samples)
        if n < n_segments * 2:
            return {'error': 'insufficient data', 'n_segments': n_segments}

        # 按 PWM 排序
        sorted_samples = sorted(self.samples, key=lambda s: s.pwm)

        # 等分断点
        pmin = sorted_samples[0].pwm
        pmax = sorted_samples[-1].pwm
        step = (pmax - pmin) / n_segments

        breakpoints = [pmin + i * step for i in range(n_segments + 1)]
        slopes = []
        intercepts = []
        segment_rmses = []

        for seg in range(n_segments):
            lo = breakpoints[seg]
            hi = breakpoints[seg + 1]
            seg_samples = [s for s in sorted_samples if lo <= s.pwm <= hi]

            if len(seg_samples) < 2:
                slopes.append(0)
                intercepts.append(0)
                segment_rmses.append(0)
                continue

            xs = [s.pwm for s in seg_samples]
            ys = [s.velocity for s in seg_samples]
            n_seg = len(seg_samples)

            sum_x = sum(xs)
            sum_y = sum(ys)
            sum_xx = sum(x*x for x in xs)
            sum_xy = sum(x*y for x, y in zip(xs, ys))

            denom = n_seg * sum_xx - sum_x * sum_x
            if abs(denom) < 1e-10:
                slopes.append(0)
                intercepts.append(sum_y / n_seg)
                segment_rmses.append(0)
                continue

            a = (n_seg * sum_xy - sum_x * sum_y) / denom
            b = (sum_y - a * sum_x) / n_seg

            slopes.append(a)
            intercepts.append(b)

            ss_res = sum((y - (a*x + b))**2 for x, y in zip(xs, ys))
            segment_rmses.append(math.sqrt(ss_res / n_seg))

        result = {
            'model': 'piecewise_linear',
            'n_segments': n_segments,
            'breakpoints': [round(bp, 1) for bp in breakpoints],
            'slopes': [round(s, 8) for s in slopes],
            'intercepts': [round(ic, 6) for ic in intercepts],
            'segment_rmses': [round(r, 6) for r in segment_rmses],
            'n_samples': n,
        }
        self.fit_result = result
        return result

    def predict(self, pwm):
        """用拟合模型预测速度"""
        if self.fit_result is None:
            return 0.0

        model = self.fit_result.get('model', 'linear')

        if model == 'linear':
            a = self.fit_result['a']
            b = self.fit_result['b']
            return max(0, a * pwm + b)

        elif model == 'quadratic':
            a = self.fit_result['a']
            b = self.fit_result['b']
            c = self.fit_result['c']
            return max(0, a * pwm * pwm + b * pwm + c)

        elif model == 'piecewise_linear':
            bps = self.fit_result['breakpoints']
            slopes = self.fit_result['slopes']
            intercepts = self.fit_result['intercepts']

            for i in range(len(bps) - 1):
                if bps[i] <= pwm <= bps[i+1]:
                    return max(0, slopes[i] * pwm + intercepts[i])

            return max(0, slopes[-1] * pwm + intercepts[-1])

        return 0.0

    def to_config_dict(self):
        """导出为 config.py 格式的字典"""
        if self.fit_result is None:
            return {}

        model = self.fit_result.get('model', 'linear')
        result = {
            'motor_model_type': model,
        }

        if model == 'linear':
            result['motor_a'] = self.fit_result['a']
            result['motor_b'] = self.fit_result['b']
        elif model == 'quadratic':
            result['motor_a'] = self.fit_result['a']
            result['motor_b'] = self.fit_result['b']
            result['motor_c'] = self.fit_result['c']
        elif model == 'piecewise_linear':
            result['motor.breakpoints'] = self.fit_result['breakpoints']
            result['motor.slopes'] = self.fit_result['slopes']
            result['motor.intercepts'] = self.fit_result['intercepts']

        result['motor_r_squared'] = self.fit_result.get('r_squared', 0)
        result['motor_rmse'] = self.fit_result.get('rmse', 0)

        return result

    def save(self, filepath):
        """保存拟合结果为 JSON"""
        data = {
            'fit_result': self.fit_result,
            'n_samples': len(self.samples),
            'timestamp': time.time(),
        }
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("[PWM-ID] Saved: {}".format(filepath))

    def load(self, filepath):
        """加载拟合结果"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.fit_result = data.get('fit_result')
        return self.fit_result


# ══════════════════════════════════════════════════════════════
#  3x3 行列式求解 (最小依赖)
# ══════════════════════════════════════════════════════════════

def _det3(m):
    """计算 3x3 矩阵行列式"""
    return (m[0][0] * (m[1][1]*m[2][2] - m[1][2]*m[2][1])
          - m[0][1] * (m[1][0]*m[2][2] - m[1][2]*m[2][0])
          + m[0][2] * (m[1][0]*m[2][1] - m[1][1]*m[2][0]))

def _solve_cramer(A, B, col, det):
    """Cramer 法则求解第 col 个变量"""
    M = [row[:] for row in A]
    for i in range(3):
        M[i][col] = B[i]
    return _det3(M) / det