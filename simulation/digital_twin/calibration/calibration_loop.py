# -*- coding: utf-8 -*-
"""
calibration_loop.py - Real-to-Sim 校准闭环 (v2)

v2 升级:
    - 支持多轨迹联合校准 (batch calibration)
    - 加权误差优化
    - 防止单轨迹过拟合
    - 模型版本管理
"""

import json
import os
import time
import copy

from control_sandbox.plant_model import PlantModel
from calibration.trajectory_matcher import DTWMatcher, BatchDTWMatcher, SensorSequenceMatcher
from calibration.model_updater import ModelUpdater


class CalibrationLoop:
    """
    Real-to-Sim 校准闭环 (v2)。

    支持:
        - 单轨迹校准 (向后兼容)
        - 多轨迹联合校准 (防过拟合)
        - 模型版本管理
    """

    def __init__(self, model_dir=None):
        self.model_dir = model_dir
        self.plant = PlantModel(model_dir)
        self.updater = ModelUpdater(self.plant)
        self.matcher = DTWMatcher(max_warp=30)
        self.batch_matcher = BatchDTWMatcher(max_warp=30)

        self.history = []
        self.model_versions = []

    # ── 单轨迹校准 (向后兼容) ──

    def calibrate(self, real_records, max_iterations=15, dt=0.03):
        """单轨迹校准"""
        if not real_records:
            return {'error': 'no real data'}

        print("[CalLoop] Single-trajectory calibration: {} records".format(
            len(real_records)))

        initial_params = self.plant.get_params()

        self.updater.set_real_data(real_records)
        self.updater.max_iterations = max_iterations
        self.updater.set_sim_callback(
            lambda params, records: self._run_simulation(params, records, dt))

        result = self.updater.calibrate()

        if result.get('successful'):
            self._save_version(result)

        result['initial_params'] = initial_params
        self.history = self.updater.history
        return result

    # ── v2: 多轨迹联合校准 ──

    def calibrate_batch(self, real_datasets, max_iterations=20, dt=0.03,
                        weights=None):
        """
        多轨迹联合校准。

        参数:
            real_datasets: list of list[dict] - 多条真实轨迹
            max_iterations: 最大迭代次数
            dt: 控制周期
            weights: 每条轨迹的权重 (默认等权)

        返回:
            dict: 校准结果
        """
        if not real_datasets:
            return {'error': 'no datasets'}

        n_traj = len(real_datasets)
        total_records = sum(len(d) for d in real_datasets)
        print("[CalLoop] Batch calibration: {} trajectories, {} total records".format(
            n_traj, total_records))

        initial_params = self.plant.get_params()

        # 设置多轨迹数据
        self.updater.set_real_datasets(real_datasets, weights)
        self.updater.max_iterations = max_iterations
        self.updater.set_sim_callback(
            lambda params, records: self._run_simulation(params, records, dt))

        result = self.updater.calibrate()

        if result.get('successful'):
            self._save_version(result)

        # 批量验证
        batch_verify = self._verify_batch(result.get('final_params', initial_params),
                                          real_datasets, dt)
        result['batch_verification'] = batch_verify
        result['initial_params'] = initial_params
        result['n_datasets'] = n_traj

        return result

    def _batch_sim_callback(self, params, datasets, dt):
        """多轨迹仿真回调: 对每条轨迹运行仿真, 返回合并结果"""
        all_sim = []
        for real_data in datasets:
            sim = self._run_simulation(params, real_data, dt)
            all_sim.append(sim)
        return all_sim  # ModelUpdater 会分别计算每条的误差

    def _verify_batch(self, params, datasets, dt):
        """批量验证: 计算每条轨迹的误差"""
        per_traj = []
        for i, real_data in enumerate(datasets):
            sim_data = self._run_simulation(params, real_data, dt)
            dtw_result = self.matcher.align(real_data, sim_data, target_n=150)

            real_sensors = [r.get('sensors', [1,1,1,1]) for r in real_data]
            sim_sensors = [s.get('sensors', [1,1,1,1]) for s in sim_data]
            sensor_match = SensorSequenceMatcher.compare(real_sensors, sim_sensors)

            per_traj.append({
                'index': i,
                'dtw_distance': dtw_result.get('normalized_distance', float('inf')),
                'sensor_match_pct': sensor_match['match_pct'],
                'n_records': len(real_data),
            })

        avg_dtw = sum(p['dtw_distance'] for p in per_traj) / max(len(per_traj), 1)
        avg_sensor = sum(p['sensor_match_pct'] for p in per_traj) / max(len(per_traj), 1)

        return {
            'avg_dtw_distance': round(avg_dtw, 4),
            'avg_sensor_match_pct': round(avg_sensor, 1),
            'per_trajectory': per_traj,
            'error_variance': round(
                sum((p['dtw_distance'] - avg_dtw)**2 for p in per_traj) /
                max(len(per_traj), 1), 4),
        }

    # ── 仿真运行 ──

    def _run_simulation(self, params, real_records, dt):
        plant = PlantModel()
        plant.set_params(params)
        trajectory = []
        for rec in real_records:
            left_pwm = rec.get('left_pwm', 180)
            right_pwm = rec.get('right_pwm', 180)
            sensors = plant.step(left_pwm, right_pwm, dt)
            state = plant.get_state_dict()
            state['t'] = rec.get('t', 0)
            state['sensors'] = sensors
            state['left_pwm'] = left_pwm
            state['right_pwm'] = right_pwm
            trajectory.append(state)
        return trajectory

    # ── 验证 ──

    def verify(self, real_records, dt=0.03):
        sim_records = self._run_simulation(
            self.plant.get_params(), real_records, dt)
        dtw_result = self.matcher.align(real_records, sim_records, target_n=200)
        real_sensors = [r.get('sensors', [1,1,1,1]) for r in real_records]
        sim_sensors = [s.get('sensors', [1,1,1,1]) for s in sim_records]
        sensor_match = SensorSequenceMatcher.compare(real_sensors, sim_sensors)
        return {
            'dtw_distance': dtw_result.get('dtw_distance', float('inf')),
            'normalized_distance': dtw_result.get('normalized_distance', float('inf')),
            'sensor_match_pct': sensor_match['match_pct'],
            'n_real': len(real_records),
            'n_sim': len(sim_records),
        }

    # ── 模型版本管理 ──

    def _save_version(self, result):
        version = {
            'params': result.get('final_params', {}),
            'error': result.get('final_error', 0),
            'timestamp': time.time(),
            'iterations': result.get('iterations', 0),
        }
        self.model_versions.append(version)

        if self.model_dir:
            path = os.path.join(self.model_dir, 'calibrated_model.json')
            self.plant.save_params(path)

    def get_versions(self):
        return list(self.model_versions)

    def get_params(self):
        return self.plant.get_params()
