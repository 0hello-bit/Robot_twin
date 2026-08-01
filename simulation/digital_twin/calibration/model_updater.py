# -*- coding: utf-8 -*-
"""
model_updater.py - 稳定模型参数优化器 (v2)

v2 核心改进:
    - 参数阻尼 (EMA): θ = (1-α)*θ + α*θ_new, 防震荡
    - 梯度裁剪: |g| > threshold → clip
    - 多轨迹联合误差: batch_gradient
    - 参数历史追踪 + 版本对比
    - 收敛检测: 梯度范数 < threshold
    - 参数稳定性评分

更新公式:
    velocity = β * velocity - lr * gradient
    θ_candidate = θ + velocity
    θ = (1 - damping) * θ + damping * θ_candidate   ← EMA 阻尼
"""

import math
import copy
import inspect
import time
from calibration.trajectory_matcher import DTWMatcher, BatchDTWMatcher


class ModelUpdater:
    """
    稳定模型参数优化器 (v2)。

    关键改进:
        1. EMA 参数阻尼防止震荡
        2. 梯度裁剪防止爆炸
        3. 多轨迹联合误差
        4. 参数稳定性评估
    """

    def __init__(self, plant_model):
        self.plant = plant_model

        # 数据 (支持多轨迹)
        self.real_datasets = []    # list of list[dict]
        self.dataset_weights = []  # 每条轨迹的权重
        self.sim_callback = None
        self.sim_callback_accepts_records = False

        # 优化参数
        self.max_iterations = 20
        self.learning_rate = 0.03
        self.lr_decay = 0.97
        self.momentum = 0.7
        self.perturbation = 0.05
        self.gradient_clip = 1.0       # 梯度裁剪阈值
        self.param_damping = 0.3       # EMA 阻尼系数 (0=无更新, 1=全替换)
        self.min_improvement = 1e-5    # 最小改善阈值

        # 可校准参数
        self.calibrable_params = [
            'motor_gain', 'motor_offset', 'steering_K',
            'steering_tau', 'velocity_damping', 'angular_damping',
        ]

        # 状态
        self.history = []
        self.param_history = []
        self.converged = False

    # ── 数据管理 ──

    def set_real_data(self, records):
        """设置单条轨迹 (向后兼容)"""
        self.real_datasets = [records]
        self.dataset_weights = [1.0]

    def set_real_datasets(self, datasets, weights=None):
        """设置多条轨迹"""
        self.real_datasets = list(datasets)
        if weights is None:
            self.dataset_weights = [1.0] * len(datasets)
        else:
            self.dataset_weights = list(weights)[:len(datasets)]

    def set_sim_callback(self, callback):
        self.sim_callback = callback
        try:
            self.sim_callback_accepts_records = len(
                inspect.signature(callback).parameters) >= 2
        except (TypeError, ValueError):
            self.sim_callback_accepts_records = False

    # ── 误差计算 (v2: 多轨迹加权) ──

    def _compute_batch_error(self, params):
        """计算多轨迹加权平均误差"""
        if not self.real_datasets:
            return float('inf')

        total_error = 0.0
        total_weight = 0.0

        for i, real_data in enumerate(self.real_datasets):
            w = self.dataset_weights[i] if i < len(self.dataset_weights) else 1.0
            sim_records = self._run_sim_single(params, real_data)

            if not sim_records:
                continue

            # 使用 DTW 归一化距离
            matcher = DTWMatcher(max_warp=30)
            result = matcher.align(real_data, sim_records, target_n=100)
            dist = result.get('normalized_distance', float('inf'))

            total_error += w * dist
            total_weight += w

        return total_error / max(total_weight, 1e-10)

    def _run_sim_single(self, params, real_records):
        """用给定参数运行单条轨迹仿真"""
        if self.sim_callback:
            if self.sim_callback_accepts_records:
                return self.sim_callback(params, real_records)
            return self.sim_callback(params)
        return []

    # ── 梯度计算 (v2: 数值梯度 + 裁剪) ──

    def _compute_gradients(self, params, current_error):
        """计算数值梯度 (带裁剪)"""
        gradients = {}

        for param_name in self.calibrable_params:
            if param_name not in params:
                continue

            current_val = params[param_name]
            delta = max(abs(current_val) * self.perturbation, 1e-8)

            # 前向差分
            perturbed = dict(params)
            perturbed[param_name] = current_val + delta
            error_plus = self._compute_batch_error(perturbed)

            # 数值梯度
            if not math.isfinite(error_plus) or not math.isfinite(current_error):
                grad = 0.0
            else:
                grad = (error_plus - current_error) / delta

            # 梯度裁剪
            grad = max(-self.gradient_clip, min(self.gradient_clip, grad))

            gradients[param_name] = grad

        return gradients

    # ── 参数边界 ──

    def _get_bounds(self):
        try:
            from control_sandbox.plant_model import PARAM_BOUNDS as PB
            return PB
        except ImportError:
            return {
                'motor_gain': (0.0001, 0.005),
                'motor_offset': (-0.1, 0.1),
                'steering_K': (50, 500),
                'steering_tau': (0.001, 0.5),
                'velocity_damping': (0.5, 0.99),
                'angular_damping': (0.3, 0.99),
            }

    def _clamp_params(self, params):
        """边界约束"""
        bounds = self._get_bounds()
        result = dict(params)
        for key, val in result.items():
            if key in bounds:
                lo, hi = bounds[key]
                result[key] = max(lo, min(hi, val))
        return result

    # ── 主优化循环 (v2 核心) ──

    def calibrate(self):
        """
        执行稳定校准。

        返回:
            dict: 校准结果
        """
        if not self.real_datasets:
            return {'error': 'no real data'}
        if not self.sim_callback:
            return {'error': 'no sim callback'}

        current_params = self.plant.get_params()
        current_error = self._compute_batch_error(current_params)
        initial_error = current_error
        if not math.isfinite(initial_error):
            return {'error': 'initial calibration error is not finite'}

        velocity = {p: 0.0 for p in self.calibrable_params}
        lr = self.learning_rate
        best_error = current_error
        best_params = copy.deepcopy(current_params)
        no_improvement_count = 0
        stop_reason = 'max_iterations'

        self.history = [current_error]
        self.param_history = [copy.deepcopy(current_params)]
        self.converged = False

        for iteration in range(self.max_iterations):
            # 计算梯度
            gradients = self._compute_gradients(current_params, current_error)

            # 梯度范数 (用于收敛检测)
            grad_norm = math.sqrt(sum(g**2 for g in gradients.values()))

            if grad_norm < self.min_improvement:
                self.converged = best_error < initial_error
                stop_reason = (
                    'gradient_converged' if self.converged
                    else 'flat_gradient_without_improvement'
                )
                print("  [Calib] Stopped: {} (grad_norm={:.6f})".format(
                    stop_reason, grad_norm))
                break

            previous_params = copy.deepcopy(current_params)
            previous_error = current_error

            # 动量更新
            for param_name, grad in gradients.items():
                velocity[param_name] = (
                    self.momentum * velocity[param_name] - lr * grad)
                candidate = current_params[param_name] + velocity[param_name]

                # EMA 阻尼: 防止参数震荡
                current_params[param_name] = (
                    (1 - self.param_damping) * current_params[param_name] +
                    self.param_damping * candidate
                )

            # 边界约束
            current_params = self._clamp_params(current_params)

            # 评估新参数
            new_error = self._compute_batch_error(current_params)

            # 学习率衰减
            lr *= self.lr_decay

            # 只接受误差下降的候选参数。误差变大或无效时回滚，避免污染模型。
            if not math.isfinite(new_error) or new_error >= previous_error:
                current_params = previous_params
                current_error = previous_error
                self.plant.set_params(current_params)
                velocity = {p: 0.0 for p in self.calibrable_params}
                lr *= 0.5
                no_improvement_count += 1
                self.history.append(current_error)
                self.param_history.append(copy.deepcopy(current_params))
                print("  [Calib] iter={}: rejected error={} (current {:.4f})".format(
                    iteration + 1,
                    "{:.4f}".format(new_error) if math.isfinite(new_error) else "non-finite",
                    current_error,
                ))
                if no_improvement_count >= 3:
                    stop_reason = 'no_improving_step'
                    break
                continue

            current_error = new_error
            self.plant.set_params(current_params)
            self.history.append(current_error)
            self.param_history.append(copy.deepcopy(current_params))
            no_improvement_count = 0

            if current_error < best_error:
                best_error = current_error
                best_params = copy.deepcopy(current_params)

            # 收敛检测: 已经改善且单步改善很小。
            improvement = (previous_error - current_error) / max(abs(previous_error), 1e-10)
            if improvement < self.min_improvement and iteration > 2:
                self.converged = True
                stop_reason = 'small_positive_improvement'
                print("  [Calib] Converged: improvement={:.4f}%".format(
                    improvement * 100))
                break

            print("  [Calib] iter={}: error={:.4f} (improved {:.1f}%, grad={:.4f})".format(
                iteration + 1, current_error, improvement * 100, grad_norm))

        # 即使最后一次尝试失败，也只发布本轮找到的最佳参数。
        current_params = best_params
        current_error = best_error
        self.plant.set_params(current_params)

        # 参数稳定性评分
        stability = self._compute_param_stability()
        improved = current_error < initial_error - max(abs(initial_error), 1.0) * 1e-9

        return {
            'iterations': len(self.history) - 1,
            'final_error': round(current_error, 6),
            'initial_error': round(initial_error, 6),
            'improvement_pct': round(
                (1 - current_error / max(initial_error, 1e-10)) * 100, 1),
            'error_history': [round(e, 6) for e in self.history],
            'final_params': current_params,
            'converged': self.converged,
            'improved': improved,
            'successful': bool(improved and math.isfinite(current_error)),
            'stop_reason': stop_reason,
            'param_stability': stability,
            'n_datasets': len(self.real_datasets),
        }

    # ── 参数稳定性评估 (v2 新增) ──

    def _compute_param_stability(self):
        """
        评估参数是否稳定收敛。

        方法: 检查最后 N 次迭代中参数的变化幅度。
        """
        if len(self.param_history) < 3:
            return {'score': 0, 'detail': 'insufficient history'}

        recent = self.param_history[-5:] if len(self.param_history) >= 5 else self.param_history

        # 每个参数的变异系数
        param_stabilities = {}
        for key in recent[0]:
            values = [p[key] for p in recent]
            mean = sum(values) / len(values)
            if abs(mean) < 1e-10:
                param_stabilities[key] = 1.0
                continue
            variance = sum((v - mean)**2 for v in values) / len(values)
            cv = math.sqrt(max(0, variance)) / abs(mean)
            # cv 越小越稳定, 映射到 0~1
            param_stabilities[key] = max(0, 1.0 - min(cv * 10, 1.0))

        avg_stability = sum(param_stabilities.values()) / max(len(param_stabilities), 1)

        return {
            'score': round(avg_stability * 100, 1),
            'per_param': {k: round(v, 3) for k, v in param_stabilities.items()},
        }
