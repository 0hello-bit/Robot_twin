# -*- coding: utf-8 -*-
"""
sim_replay_calibrator.py - 回放校准器

功能:
    1. 加载真实 replay 数据
    2. 用真实传感器序列 + PWM 序列驱动仿真
    3. 自动调整 plant_model 参数
    4. 输出校准报告

与 calibration_loop 的区别:
    - 本模块专注于"回放校准": 用真实输入驱动仿真
    - calibration_loop 是通用校准框架
    - 本模块提供更详细的回放分析
"""

import json
import math
import os
import time

from calibration.calibration_loop import CalibrationLoop
from calibration.trajectory_matcher import (
    DTWMatcher, SensorSequenceMatcher)


class SimReplayCalibrator:
    """
    回放校准器。

    使用方式:
        calibrator = SimReplayCalibrator(model_dir='calibration/models/')
        calibrator.load_replay('data/hil_session.json')
        result = calibrator.calibrate()
        calibrator.save_report('data/calibration_report.json')
    """

    def __init__(self, model_dir=None):
        self.model_dir = model_dir
        self.loop = CalibrationLoop(model_dir)
        self.replay_data = []
        self.calibration_result = None
        self.verification_result = None
        self.post_verification_result = None

    def load_replay(self, filepath):
        """加载 replay 数据"""
        with open(filepath, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        if isinstance(raw, list):
            self.replay_data = raw
        elif isinstance(raw, dict):
            self.replay_data = raw.get('data', [])

        print("[ReplayCal] Loaded {} records from {}".format(
            len(self.replay_data), filepath))

    def load_replay_direct(self, records):
        self.replay_data = records

    def calibrate(self, max_iterations=15, dt=0.03):
        """执行回放校准"""
        if not self.replay_data:
            return {'error': 'no replay data'}

        print("[ReplayCal] Starting calibration ...")

        # 校准前验证
        self.verification_result = self.loop.verify(self.replay_data, dt)
        pre_error = self.verification_result['dtw_distance']
        pre_sensor = self.verification_result['sensor_match_pct']
        print("[ReplayCal] Pre-calibration: DTW={:.4f}, Sensor={:.1f}%".format(
            pre_error, pre_sensor))

        # 执行校准
        self.calibration_result = self.loop.calibrate(
            self.replay_data, max_iterations, dt)

        # 校准后验证
        self.post_verification_result = self.loop.verify(self.replay_data, dt)
        post_error = self.post_verification_result['dtw_distance']
        post_sensor = self.post_verification_result['sensor_match_pct']
        print("[ReplayCal] Post-calibration: DTW={:.4f}, Sensor={:.1f}%".format(
            post_error, post_sensor))

        # 改善率
        improvement = (1 - post_error / max(pre_error, 1e-10)) * 100

        return {
            'pre_calibration': self.verification_result,
            'post_calibration': self.post_verification_result,
            'improvement_pct': round(improvement, 1),
            'calibration': self.calibration_result,
        }

    def compare_params(self):
        """对比校准前后的参数"""
        if not self.calibration_result:
            return None

        initial = self.calibration_result.get('initial_params', {})
        final = self.calibration_result.get('final_params', {})

        comparison = {}
        for key in final:
            v0 = initial.get(key, 0)
            v1 = final.get(key, 0)
            if abs(v0) > 1e-10:
                change_pct = (v1 - v0) / abs(v0) * 100
            else:
                change_pct = 0 if abs(v1) < 1e-10 else None
            comparison[key] = {
                'initial': round(v0, 6),
                'final': round(v1, 6),
                'change_pct': round(change_pct, 1) if change_pct is not None else None,
                'change_absolute': round(v1 - v0, 6),
            }
        return comparison

    @staticmethod
    def _json_safe(value):
        """Convert non-finite floats to null so reports are strict JSON."""
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {key: SimReplayCalibrator._json_safe(item)
                    for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [SimReplayCalibrator._json_safe(item) for item in value]
        return value

    def save_report(self, filepath):
        """保存校准报告"""
        report = {
            'schema_version': 2,
            'calibration_result': self.calibration_result,
            'verification_before': self.verification_result,
            'verification_after': self.post_verification_result,
            'param_comparison': self.compare_params(),
            'n_records': len(self.replay_data),
            'timestamp': time.time(),
        }

        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self._json_safe(report), f, indent=2, ensure_ascii=False,
                      allow_nan=False)
        print("[ReplayCal] Report saved: {}".format(filepath))

    def print_summary(self):
        """打印校准摘要"""
        if not self.calibration_result:
            print("No calibration result")
            return

        r = self.calibration_result
        print("\n" + "=" * 55)
        print("  Replay Calibration Report")
        print("=" * 55)

        if self.verification_result:
            print("  Pre:  DTW={:.4f}, Sensor={:.1f}%".format(
                self.verification_result['dtw_distance'],
                self.verification_result['sensor_match_pct']))

        post = self.post_verification_result or {}
        if post:
            print("  Post: DTW={:.4f}, Sensor={:.1f}%".format(
                post.get('dtw_distance', 0),
                post.get('sensor_match_pct', 0)))

        print("  Iterations: {}".format(r.get('iterations', 0)))
        print("  Improvement: {:.1f}%".format(
            r.get('improvement_pct', 0)))
        print("  Converged: {}".format(r.get('converged', False)))

        comp = self.compare_params()
        if comp:
            print("\n  Parameter Changes:")
            for key, vals in comp.items():
                if vals['change_pct'] is None:
                    change_text = "absolute {:+.6f}".format(vals['change_absolute'])
                else:
                    change_text = "{:+.1f}%".format(vals['change_pct'])
                print("    {}: {:.6f} -> {:.6f} ({})".format(
                    key, vals['initial'], vals['final'], change_text))

        print("=" * 55)
