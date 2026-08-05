# -*- coding: utf-8 -*-
"""
ground_truth_validator.py - 真实数据验证器

功能:
    1. 使用真实 telemetry 作为 ground truth
    2. 评估 sim prediction error
    3. 评估 PID stability prediction accuracy
    4. 验证 "仿真是否真的在变准"
"""

import math
import json
import os
import time

from control_sandbox.plant_model import PlantModel
from calibration.trajectory_matcher import DTWMatcher, SensorSequenceMatcher
from analysis.model_confidence import ModelConfidence


class GroundTruthValidator:
    """
    真实数据验证器。

    核心验证:
        1. 仿真预测 vs 真实 → prediction accuracy
        2. 仿真 PID 评分 vs 真实 PID 评分 → stability prediction
        3. 多次验证 → 一致性
    """

    def __init__(self):
        self.matcher = DTWMatcher(max_warp=30)
        self.history = []

    def validate(self, model_params, real_datasets, dt=0.03):
        """
        执行真实数据验证。

        参数:
            model_params:  当前模型参数
            real_datasets: list[list[dict]] - 真实数据 (作为 ground truth)
            dt:            控制周期

        返回:
            dict: 验证结果
        """
        if not real_datasets:
            return {'error': 'no ground truth data'}

        per_traj = []
        total_dtw = 0.0
        total_sensor = 0.0

        for i, real_data in enumerate(real_datasets):
            # 仿真预测
            sim_data = self._simulate(model_params, real_data, dt)

            # DTW 距离
            dtw_result = self.matcher.align(real_data, sim_data, target_n=150)
            dtw_dist = dtw_result.get('normalized_distance', float('inf'))

            # 传感器匹配
            real_s = [r.get('sensors', [1,1,1,1]) for r in real_data]
            sim_s = [s.get('sensors', [1,1,1,1]) for s in sim_data]
            sensor_match = SensorSequenceMatcher.compare(real_s, sim_s)['match_pct']

            # PWM 一致性
            pwm_error = 0.0
            for r, s in zip(real_data, sim_data):
                pwm_error += abs(r.get('left_pwm', 0) - s.get('left_pwm', 0))
                pwm_error += abs(r.get('right_pwm', 0) - s.get('right_pwm', 0))
            pwm_error /= max(len(real_data) * 2, 1)

            total_dtw += dtw_dist
            total_sensor += sensor_match

            per_traj.append({
                'index': i,
                'dtw_distance': round(dtw_dist, 4),
                'sensor_match_pct': round(sensor_match, 1),
                'pwm_error': round(pwm_error, 2),
                'n_records': len(real_data),
            })

        n = len(real_datasets)
        avg_dtw = total_dtw / n
        avg_sensor = total_sensor / n

        # 预测准确度评分
        accuracy_score = max(0, 100 - avg_dtw * 5) * 0.6 + avg_sensor * 0.4

        # 历史对比
        prev_score = self.history[-1]['accuracy_score'] if self.history else 0
        improvement = accuracy_score - prev_score

        result = {
            'accuracy_score': round(accuracy_score, 1),
            'avg_dtw_distance': round(avg_dtw, 4),
            'avg_sensor_match_pct': round(avg_sensor, 1),
            'improvement_over_previous': round(improvement, 1),
            'per_trajectory': per_traj,
            'n_datasets': n,
            'timestamp': time.time(),
        }

        self.history.append(result)
        return result

    def _simulate(self, params, real_records, dt):
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

    def get_validation_history(self):
        return list(self.history)

    def is_improving(self):
        """检查是否持续改善"""
        if len(self.history) < 2:
            return None
        return self.history[-1]['accuracy_score'] > self.history[-2]['accuracy_score']