# -*- coding: utf-8 -*-
"""
ab_test_runner.py - A/B 模型对比测试

功能:
    1. 同一组 PID, 在不同模型上测试
    2. 同一组真实数据, 对比不同模型的预测精度
    3. 输出: 哪个模型更接近真实系统
"""

import json
import os
import time

from control_sandbox.plant_model import PlantModel
from calibration.trajectory_matcher import DTWMatcher, BatchDTWMatcher
from analysis.model_confidence import ModelConfidence


class ABTestRunner:
    """
    A/B 模型对比测试器。

    使用方式:
        runner = ABTestRunner()
        result = runner.run(model_a_params, model_b_params, real_data)
        print(result['winner'])
    """

    def __init__(self):
        self.matcher = DTWMatcher(max_warp=30)
        self.batch_matcher = BatchDTWMatcher(max_warp=30)

    def run(self, params_a, params_b, real_datasets, dt=0.03, weights=None):
        """
        执行 A/B 测试。

        参数:
            params_a:      模型 A 参数
            params_b:      模型 B 参数
            real_datasets: list[list[dict]] - 真实数据
            dt:            控制周期
            weights:       每条轨迹权重

        返回:
            dict: {
                'winner': 'A' or 'B' or 'tie',
                'model_a': {...},
                'model_b': {...},
                'per_trajectory': [...],
            }
        """
        if weights is None:
            weights = [1.0] * len(real_datasets)

        per_traj = []
        total_score_a = 0.0
        total_score_b = 0.0

        for i, real_data in enumerate(real_datasets):
            w = weights[i] if i < len(weights) else 1.0

            # 模型 A 仿真
            sim_a = self._simulate(params_a, real_data, dt)
            # 模型 B 仿真
            sim_b = self._simulate(params_b, real_data, dt)

            # DTW 误差
            dtw_a = self.matcher.align(real_data, sim_a, target_n=150)
            dtw_b = self.matcher.align(real_data, sim_b, target_n=150)

            err_a = dtw_a.get('normalized_distance', float('inf'))
            err_b = dtw_b.get('normalized_distance', float('inf'))

            # 传感器匹配
            real_s = [r.get('sensors', [1,1,1,1]) for r in real_data]
            sen_a = [s.get('sensors', [1,1,1,1]) for s in sim_a]
            sen_b = [s.get('sensors', [1,1,1,1]) for s in sim_b]

            from calibration.trajectory_matcher import SensorSequenceMatcher
            sm_a = SensorSequenceMatcher.compare(real_s, sen_a)['match_pct']
            sm_b = SensorSequenceMatcher.compare(real_s, sen_b)['match_pct']

            # 综合得分 (误差越低越好, 传感器匹配越高越好)
            score_a = w * (100 - min(err_a * 10, 100)) * 0.6 + w * sm_a * 0.4
            score_b = w * (100 - min(err_b * 10, 100)) * 0.6 + w * sm_b * 0.4

            total_score_a += score_a
            total_score_b += score_b

            per_traj.append({
                'index': i,
                'dtw_a': round(err_a, 4),
                'dtw_b': round(err_b, 4),
                'sensor_a': sm_a,
                'sensor_b': sm_b,
                'score_a': round(score_a, 2),
                'score_b': round(score_b, 2),
                'winner': 'A' if err_a < err_b else 'B' if err_b < err_a else 'tie',
            })

        # 总判定
        if total_score_a > total_score_b * 1.05:
            winner = 'A'
        elif total_score_b > total_score_a * 1.05:
            winner = 'B'
        else:
            winner = 'tie'

        return {
            'winner': winner,
            'model_a': {
                'total_score': round(total_score_a, 2),
                'avg_dtw': round(sum(p['dtw_a'] for p in per_traj) / len(per_traj), 4),
                'avg_sensor': round(sum(p['sensor_a'] for p in per_traj) / len(per_traj), 1),
            },
            'model_b': {
                'total_score': round(total_score_b, 2),
                'avg_dtw': round(sum(p['dtw_b'] for p in per_traj) / len(per_traj), 4),
                'avg_sensor': round(sum(p['sensor_b'] for p in per_traj) / len(per_traj), 1),
            },
            'per_trajectory': per_traj,
            'n_datasets': len(real_datasets),
            'margin': round(abs(total_score_a - total_score_b) /
                           max(total_score_a + total_score_b, 1e-10) * 100, 1),
        }

    def _simulate(self, params, real_records, dt):
        """用给定参数运行仿真"""
        plant = PlantModel()
        plant.set_params(params)
        traj = []
        for rec in real_records:
            sensors = plant.step(rec.get('left_pwm', 180), rec.get('right_pwm', 180), dt)
            state = plant.get_state_dict()
            state['t'] = rec.get('t', 0)
            state['sensors'] = sensors
            state['left_pwm'] = rec.get('left_pwm', 0)
            state['right_pwm'] = rec.get('right_pwm', 0)
            traj.append(state)
        return traj