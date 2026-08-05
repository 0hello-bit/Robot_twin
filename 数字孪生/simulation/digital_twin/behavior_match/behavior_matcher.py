# -*- coding: utf-8 -*-
"""
behavior_matcher.py - 行为一致性对比工具

输入: 仿真运行日志 + STM32 运行日志
输出:
  - error 曲线对比 (RMSE / MAE / 趋势相关性)
  - PWM 输出对比
  - 传感器响应对比
  - 状态切换对比
  - 巡线偏差统计
  - 综合 match_score (0~100)
"""

import numpy as np
from behavior_match.log_protocol import LOG_HEADER


class BehaviorMatcher:
    """
    行为一致性对比器。

    将两份日志逐 tick 对齐, 输出量化对比结果。
    """

    def __init__(self):
        self._sim_log = []
        self._real_log = []

    def load(self, sim_log, real_log):
        self._sim_log = sim_log
        self._real_log = real_log

    def compare(self):
        n = min(len(self._sim_log), len(self._real_log))
        if n == 0:
            return self._empty_result()

        sim_err = np.array([e['error'] for e in self._sim_log[:n]], dtype=float)
        real_err = np.array([e['error'] for e in self._real_log[:n]], dtype=float)
        sim_lp = np.array([e['pwm_left'] for e in self._sim_log[:n]], dtype=float)
        real_lp = np.array([e['pwm_left'] for e in self._real_log[:n]], dtype=float)
        sim_rp = np.array([e['pwm_right'] for e in self._sim_log[:n]], dtype=float)
        real_rp = np.array([e['pwm_right'] for e in self._real_log[:n]], dtype=float)

        err_diff = sim_err - real_err
        error_mae = float(np.mean(np.abs(err_diff)))
        error_rmse = float(np.sqrt(np.mean(err_diff ** 2)))
        error_corr = self._safe_corr(sim_err, real_err)

        pwm_l_diff = sim_lp - real_lp
        pwm_r_diff = sim_rp - real_rp
        pwm_mae = float((np.mean(np.abs(pwm_l_diff)) + np.mean(np.abs(pwm_r_diff))) / 2.0)
        pwm_rmse = float(np.sqrt(np.mean(pwm_l_diff**2 + pwm_r_diff**2) / 2.0))

        sim_sensors = np.array([
            [e['s0'], e['s1'], e['s2'], e['s3']] for e in self._sim_log[:n]
        ], dtype=int)
        real_sensors = np.array([
            [e['s0'], e['s1'], e['s2'], e['s3']] for e in self._real_log[:n]
        ], dtype=int)
        sensor_match = float(np.mean(sim_sensors == real_sensors))

        sim_states = [e['state'] for e in self._sim_log[:n]]
        real_states = [e['state'] for e in self._real_log[:n]]
        state_match = float(sum(a == b for a, b in zip(sim_states, real_states)) / n)

        sim_lost = sum(1 for e in self._sim_log[:n] if e['state'] == 'lost')
        real_lost = sum(1 for e in self._real_log[:n] if e['state'] == 'lost')
        lost_diff = abs(sim_lost - real_lost)
        lost_ratio = lost_diff / max(n, 1)

        score = self._compute_score(
            error_mae, error_corr, pwm_mae, sensor_match,
            state_match, lost_ratio)

        return {
            'match_score': round(score, 1),
            'ticks_compared': n,
            'error': {
                'mae': round(error_mae, 3),
                'rmse': round(error_rmse, 3),
                'correlation': round(error_corr, 4),
            },
            'pwm': {
                'mae': round(pwm_mae, 1),
                'rmse': round(pwm_rmse, 1),
            },
            'sensor_match_rate': round(sensor_match, 4),
            'state_match_rate': round(state_match, 4),
            'lost_line': {
                'sim': sim_lost,
                'real': real_lost,
                'diff': lost_diff,
            },
            'error_curve_diff': err_diff.tolist()[:50],
        }

    def _compute_score(self, error_mae, error_corr, pwm_mae,
                       sensor_match, state_match, lost_ratio):
        err_score = max(0, 100 - error_mae * 10)
        corr_score = max(0, error_corr * 100)
        pwm_score = max(0, 100 - pwm_mae * 0.5)
        sensor_score = sensor_match * 100
        state_score = state_match * 100
        lost_score = max(0, 100 - lost_ratio * 200)

        score = (err_score * 0.25 + corr_score * 0.15 + pwm_score * 0.20 +
                 sensor_score * 0.15 + state_score * 0.15 + lost_score * 0.10)
        return max(0.0, min(100.0, score))

    @staticmethod
    def _safe_corr(a, b):
        if len(a) < 2:
            return 0.0
        if np.std(a) < 1e-8 or np.std(b) < 1e-8:
            return 1.0 if np.all(a == b) else 0.0
        return float(np.corrcoef(a, b)[0, 1])

    def _empty_result(self):
        return {
            'match_score': 0.0,
            'ticks_compared': 0,
            'error': {'mae': 0, 'rmse': 0, 'correlation': 0},
            'pwm': {'mae': 0, 'rmse': 0},
            'sensor_match_rate': 0,
            'state_match_rate': 0,
            'lost_line': {'sim': 0, 'real': 0, 'diff': 0},
            'error_curve_diff': [],
        }
