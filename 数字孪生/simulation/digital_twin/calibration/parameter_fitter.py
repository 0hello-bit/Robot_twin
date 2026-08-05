# -*- coding: utf-8 -*-
"""
parameter_fitter.py - 仿真参数自动拟合

职责:
    1. 根据真实数据与仿真数据的差异
    2. 自动计算仿真参数修正量
    3. 输出优化后的 config 参数

算法:
    使用梯度下降 + 网格搜索混合方法:
    1. 对每个待拟合参数施加小扰动
    2. 重新运行仿真, 计算误差
    3. 沿梯度方向更新参数
    4. 重复直到收敛

待拟合参数:
    - MOTOR_RESPONSE_TAU: 电机响应时间常数
    - VELOCITY_DAMPING: 速度衰减系数
    - ANGULAR_DAMPING: 角速度衰减系数
    - CONTROL_DELAY_STEPS: 控制延迟步数
    - SENSOR_RADIUS: 传感器检测半径
"""

import math
import copy


class ParameterFitter:
    """
    仿真参数拟合器。
    
    使用方式:
        fitter = ParameterFitter()
        fitter.set_real_data(real_records)
        fitter.set_sim_callback(sim_run_function)
        result = fitter.fit()
        print(result)
    """

    # 默认参数范围
    DEFAULT_BOUNDS = {
        'velocity_damping': (0.5, 0.99),
        'angular_damping': (0.3, 0.99),
        'motor_tau': (0.01, 0.5),
        'sensor_radius': (2.0, 12.0),
        'control_delay': (0, 5),
    }

    def __init__(self):
        self.real_data = []
        self.sim_callback = None  # callable(params) -> sim_records
        self.bounds = dict(self.DEFAULT_BOUNDS)
        self.max_iterations = 20
        self.learning_rate = 0.1
        self.convergence_threshold = 0.01

        # 结果
        self.best_params = {}
        self.best_score = float('inf')
        self.history = []  # (iteration, score, params)

    def set_real_data(self, data):
        """
        设置真实数据。
        
        参数:
            data: list[dict] - 与 DataLogger/ExperimentLogger 格式兼容
        """
        self.real_data = data

    def set_sim_callback(self, callback):
        """
        设置仿真运行回调。
        
        回调签名:
            callback(params: dict) -> list[dict]
            
        其中 params 包含待拟合参数,
        返回的 list[dict] 格式与 real_data 相同。
        """
        self.sim_callback = callback

    def set_bounds(self, bounds):
        """设置参数搜索范围"""
        self.bounds.update(bounds)

    def fit(self):
        """
        执行参数拟合。
        
        返回:
            dict: {
                'best_params': 最优参数,
                'best_score': 最优评分 (越小越好),
                'iterations': 迭代次数,
                'history': [(iter, score, params), ...],
                'converged': 是否收敛,
            }
        """
        if not self.real_data:
            return {'error': '未设置真实数据'}
        if self.sim_callback is None:
            return {'error': '未设置仿真回调'}

        # 初始参数
        current_params = {
            'velocity_damping': 0.85,
            'angular_damping': 0.80,
            'motor_tau': 0.15,
            'sensor_radius': 6.0,
            'control_delay': 2,
        }

        # 评估初始参数
        self.best_score = self._evaluate(current_params)
        self.best_params = dict(current_params)
        self.history = [(0, self.best_score, dict(current_params))]

        converged = False
        for iteration in range(1, self.max_iterations + 1):
            # 对每个参数计算数值梯度
            gradients = {}
            for param_name in current_params:
                if param_name not in self.bounds:
                    continue

                lo, hi = self.bounds[param_name]
                current_val = current_params[param_name]
                delta = max(0.01, (hi - lo) * 0.05)  # 5% 步长

                # 前向扰动
                params_plus = dict(current_params)
                params_plus[param_name] = min(hi, current_val + delta)
                score_plus = self._evaluate(params_plus)

                # 后向扰动
                params_minus = dict(current_params)
                params_minus[param_name] = max(lo, current_val - delta)
                score_minus = self._evaluate(params_minus)

                # 数值梯度
                gradients[param_name] = (score_plus - score_minus) / (2 * delta)

            # 梯度下降更新
            for param_name, grad in gradients.items():
                lo, hi = self.bounds[param_name]
                step = -self.learning_rate * grad
                new_val = current_params[param_name] + step
                current_params[param_name] = max(lo, min(hi, new_val))

            # 评估新参数
            score = self._evaluate(current_params)
            self.history.append((iteration, score, dict(current_params)))

            if score < self.best_score:
                self.best_score = score
                self.best_params = dict(current_params)

            # 收敛检查
            if iteration > 2:
                prev_score = self.history[-2][1]
                if abs(prev_score - score) < self.convergence_threshold:
                    converged = True
                    break

        return {
            'best_params': self.best_params,
            'best_score': round(self.best_score, 4),
            'iterations': len(self.history) - 1,
            'history': [(i, round(s, 4)) for i, s, _ in self.history],
            'converged': converged,
        }

    def _evaluate(self, params):
        """
        评估参数集的拟合度。
        
        运行仿真并计算与真实数据的差异。
        
        返回:
            float: 误差分数 (越小越好)
        """
        try:
            sim_data = self.sim_callback(params)
        except Exception:
            return float('inf')

        if not sim_data:
            return float('inf')

        return self._compute_error(self.real_data, sim_data)

    @staticmethod
    def _compute_error(real, sim):
        """
        计算两组数据的误差。
        
        使用:
            - 传感器匹配度 (权重最高)
            - PWM 差异
            - 误差趋势差异
        """
        n = min(len(real), len(sim))
        if n == 0:
            return float('inf')

        sensor_errors = 0
        pwm_errors = 0
        error_trend_errors = 0

        for i in range(n):
            r = real[i]
            s = sim[i]

            # 传感器匹配
            r_sensors = r.get('sensors', [1,1,1,1])
            s_sensors = s.get('sensors', [1,1,1,1])
            for j in range(min(4, len(r_sensors), len(s_sensors))):
                if r_sensors[j] != s_sensors[j]:
                    sensor_errors += 1

            # PWM 差异 (归一化)
            r_left = r.get('left_pwm', 0) / 999.0
            s_left = s.get('left_pwm', 0) / 999.0
            r_right = r.get('right_pwm', 0) / 999.0
            s_right = s.get('right_pwm', 0) / 999.0
            pwm_errors += abs(r_left - s_left) + abs(r_right - s_right)

            # 误差趋势
            r_err = r.get('error', 0)
            s_err = s.get('error', 0)
            error_trend_errors += (r_err - s_err) ** 2

        total = n * 4  # 归一化基数
        score = (
            (sensor_errors / total) * 10.0 +     # 传感器匹配 (权重最大)
            (pwm_errors / n) * 5.0 +              # PWM 差异
            math.sqrt(error_trend_errors / n)     # 误差趋势
        )
        return score

    def get_best_config(self):
        """
        生成推荐的 config.py 更新内容。
        
        返回:
            str: 可直接粘贴到 config.py 的配置代码
        """
        if not self.best_params:
            return "# 尚未执行拟合"

        lines = [
            "# ============================================================",
            "#  自动拟合参数 (由 ParameterFitter 生成)",
            "#  拟合评分: {:.4f}".format(self.best_score),
            "# ============================================================",
            "",
        ]

        p = self.best_params
        if 'velocity_damping' in p:
            lines.append("VELOCITY_DAMPING = {:.4f}".format(p['velocity_damping']))
        if 'angular_damping' in p:
            lines.append("ANGULAR_DAMPING  = {:.4f}".format(p['angular_damping']))
        if 'motor_tau' in p:
            lines.append("NOISE_MOTOR_RESPONSE_TAU = {:.4f}".format(p['motor_tau']))
        if 'sensor_radius' in p:
            lines.append("SENSOR_RADIUS = {:.1f}".format(p['sensor_radius']))
        if 'control_delay' in p:
            lines.append("NOISE_CONTROL_DELAY_STEPS = {}".format(int(p['control_delay'])))

        return "\n".join(lines)
