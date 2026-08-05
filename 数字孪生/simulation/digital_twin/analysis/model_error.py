# -*- coding: utf-8 -*-
"""
model_error.py - 仿真模型误差评估

职责:
    1. 对比仿真轨迹 vs 真实轨迹
    2. 计算 RMSE / MAE / 最大误差
    3. 输出 "数字孪生可信度评分"
    4. 识别系统性偏差

评分体系:
    - 轨迹误差 RMSE (px)
    - 传感器匹配率 (%)
    - PID 误差趋势一致性
    - 转向响应一致性
    - 综合可信度评分 (0~100)
"""

import math
import json
import os
import time


class ModelErrorEvaluator:
    """
    仿真模型误差评估器。

    使用方式:
        evaluator = ModelErrorEvaluator()
        evaluator.set_real_data(real_records)
        evaluator.set_sim_data(sim_records)
        result = evaluator.evaluate()
        print(result['trust_score'])
    """

    def __init__(self):
        self.real_data = []
        self.sim_data = []
        self.result = None

    def set_real_data(self, data):
        """设置真实数据 (list[dict])"""
        self.real_data = data

    def set_sim_data(self, data):
        """设置仿真数据 (list[dict])"""
        self.sim_data = data

    def evaluate(self):
        """
        执行误差评估。

        返回:
            dict: {
                'trust_score': 综合可信度 (0~100),
                'trajectory_rmse': 轨迹 RMSE,
                'sensor_match_pct': 传感器匹配率,
                'pid_trend_corr': PID 趋势相关性,
                'turning_error': 转向误差,
                'details': 详细分析,
            }
        """
        if not self.real_data or not self.sim_data:
            return {'error': 'insufficient data'}

        # 时间对齐
        real_aligned, sim_aligned = self._time_align(
            self.real_data, self.sim_data)

        n = min(len(real_aligned), len(sim_aligned))
        if n < 5:
            return {'error': 'insufficient aligned data'}

        # 1. 轨迹误差
        trajectory_result = self._compute_trajectory_error(
            real_aligned[:n], sim_aligned[:n])

        # 2. 传感器匹配率
        sensor_result = self._compute_sensor_match(
            real_aligned[:n], sim_aligned[:n])

        # 3. PID 趋势一致性
        pid_result = self._compute_pid_trend_correlation(
            real_aligned[:n], sim_aligned[:n])

        # 4. 转向响应一致性
        turning_result = self._compute_turning_error(
            real_aligned[:n], sim_aligned[:n])

        # 5. 综合评分
        trust_score = self._compute_trust_score(
            trajectory_result, sensor_result, pid_result, turning_result)

        self.result = {
            'trust_score': round(trust_score, 1),
            'trajectory': trajectory_result,
            'sensor_match': sensor_result,
            'pid_trend': pid_result,
            'turning': turning_result,
            'n_samples': n,
            'timestamp': time.time(),
        }
        return self.result

    def _time_align(self, real, sim):
        """按时间戳对齐两组数据"""
        real_t = real[0].get('t', 0)
        sim_t = sim[0].get('t', 0)
        offset = real_t - sim_t

        sim_shifted = []
        for s in sim:
            rec = dict(s)
            rec['t'] = rec.get('t', 0) + offset
            sim_shifted.append(rec)

        return real, sim_shifted

    def _compute_trajectory_error(self, real, sim):
        """计算轨迹位置误差"""
        errors = []
        for r, s in zip(real, sim):
            rx = r.get('car_x', 0)
            ry = r.get('car_y', 0)
            sx = s.get('car_x', 0)
            sy = s.get('car_y', 0)
            err = math.sqrt((rx - sx)**2 + (ry - sy)**2)
            errors.append(err)

        if not errors:
            return {'rmse': 0, 'mae': 0, 'max': 0}

        rmse = math.sqrt(sum(e**2 for e in errors) / len(errors))
        mae = sum(errors) / len(errors)
        max_err = max(errors)

        return {
            'rmse': round(rmse, 3),
            'mae': round(mae, 3),
            'max': round(max_err, 3),
            'n_points': len(errors),
        }

    def _compute_sensor_match(self, real, sim):
        """计算传感器状态匹配率"""
        matches = 0
        total = 0

        for r, s in zip(real, sim):
            r_sensors = r.get('sensors', r.get('sensor_states', [1,1,1,1]))
            s_sensors = s.get('sensors', s.get('sensor_states', [1,1,1,1]))

            for rs, ss in zip(r_sensors, s_sensors):
                matches += (1 if rs == ss else 0)
                total += 1

        pct = matches / max(total, 1) * 100
        return {
            'match_pct': round(pct, 1),
            'matches': matches,
            'total': total,
        }

    def _compute_pid_trend_correlation(self, real, sim):
        """计算 PID 误差趋势的皮尔逊相关系数"""
        r_errors = [r.get('error', 0) for r in real]
        s_errors = [s.get('error', 0) for s in sim]

        n = len(r_errors)
        if n < 3:
            return {'correlation': 0, 'direction_match_pct': 0}

        r_mean = sum(r_errors) / n
        s_mean = sum(s_errors) / n

        cov = sum((r - r_mean) * (s - s_mean) for r, s in zip(r_errors, s_errors))
        r_var = sum((r - r_mean)**2 for r in r_errors)
        s_var = sum((s - s_mean)**2 for s in s_errors)

        denom = math.sqrt(max(r_var, 1e-10) * max(s_var, 1e-10))
        corr = cov / denom

        # 方向匹配率 (两者是否同向偏转)
        dir_match = sum(1 for r, s in zip(r_errors, s_errors)
                        if (r > 0) == (s > 0))
        dir_pct = dir_match / n * 100

        return {
            'correlation': round(corr, 4),
            'direction_match_pct': round(dir_pct, 1),
        }

    def _compute_turning_error(self, real, sim):
        """计算转向响应一致性"""
        r_angles = [r.get('car_angle', 0) for r in real]
        s_angles = [s.get('car_angle', 0) for s in sim]

        if len(r_angles) < 2:
            return {'angular_rmse': 0, 'total_rotation_error': 0}

        # 角速度误差
        r_omega = [(r_angles[i] - r_angles[i-1]) for i in range(1, len(r_angles))]
        s_omega = [(s_angles[i] - s_angles[i-1]) for i in range(1, len(s_angles))]

        n = min(len(r_omega), len(s_omega))
        omega_errors = [(r - s)**2 for r, s in zip(r_omega[:n], s_omega[:n])]
        angular_rmse = math.sqrt(sum(omega_errors) / max(len(omega_errors), 1))

        # 总旋转量误差
        r_total_rot = abs(r_angles[-1] - r_angles[0]) if len(r_angles) > 1 else 0
        s_total_rot = abs(s_angles[-1] - s_angles[0]) if len(s_angles) > 1 else 0
        total_rot_err = abs(r_total_rot - s_total_rot)

        return {
            'angular_rmse': round(angular_rmse, 3),
            'total_rotation_error': round(total_rot_err, 3),
        }

    def _compute_trust_score(self, traj, sensor, pid, turning):
        """综合可信度评分 (0~100)"""
        score = 100.0

        # 轨迹误差 (权重 40%)
        traj_penalty = min(40, traj.get('rmse', 0) * 0.5)
        score -= traj_penalty

        # 传感器匹配 (权重 25%)
        sensor_pct = sensor.get('match_pct', 0)
        sensor_penalty = min(25, (100 - sensor_pct) * 0.25)
        score -= sensor_penalty

        # PID 趋势 (权重 20%)
        corr = pid.get('correlation', 0)
        pid_penalty = min(20, max(0, (1 - corr)) * 20)
        score -= pid_penalty

        # 转向一致性 (权重 15%)
        ang_err = turning.get('angular_rmse', 0)
        turn_penalty = min(15, ang_err * 0.3)
        score -= turn_penalty

        return max(0, min(100, score))

    def save(self, filepath):
        if self.result is None:
            return
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.result, f, indent=2, ensure_ascii=False)
        print("[ModelError] Saved: {}".format(filepath))

    def load(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            self.result = json.load(f)
        return self.result