# -*- coding: utf-8 -*-
"""
validation_trend_tracker.py - 校准趋势跟踪器

功能:
    1. 记录每轮 calibration 的关键指标
    2. 输出时间序列趋势
    3. 检测改善/退化/震荡
    4. 预测收敛趋势
"""

import json
import os
import time
import math


class TrendRecord:
    """单轮校准记录"""
    __slots__ = ('round_id', 'timestamp', 'model_error', 'dtw_distance',
                 'sensor_match_pct', 'confidence_score', 'param_stability',
                 'pid_score', 'pid_grade', 'n_datasets', 'params_snapshot')

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k, 0))

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d.get(k, 0) for k in cls.__slots__})


class ValidationTrendTracker:
    """
    校准趋势跟踪器。

    使用方式:
        tracker = ValidationTrendTracker()
        tracker.add_round(model_error=0.5, confidence=60, ...)
        trend = tracker.get_trend()
        analysis = tracker.analyze_trend()
    """

    def __init__(self, storage_dir=None):
        self.records = []
        self.storage_dir = storage_dir
        if storage_dir:
            os.makedirs(storage_dir, exist_ok=True)
            self._load()

    def _load(self):
        path = os.path.join(self.storage_dir, 'trend_history.json')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.records = [TrendRecord.from_dict(r) for r in data.get('records', [])]

    def _save(self):
        if not self.storage_dir:
            return
        path = os.path.join(self.storage_dir, 'trend_history.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'records': [r.to_dict() for r in self.records]}, f, indent=2)

    def add_round(self, **kwargs):
        """记录一轮校准"""
        round_id = len(self.records) + 1
        record = TrendRecord(round_id=round_id, timestamp=time.time(), **kwargs)
        self.records.append(record)
        self._save()
        return record

    def get_trend(self, last_n=None):
        """获取趋势数据"""
        data = self.records
        if last_n:
            data = data[-last_n:]
        return [r.to_dict() for r in data]

    def analyze_trend(self):
        """
        分析趋势。

        返回:
            dict: {
                'error_trend': 'improving'/'stable'/'oscillating'/'diverging',
                'confidence_trend': ...,
                'convergence_estimate': int or None,
                'overall_health': 'good'/'warning'/'critical',
                'details': {...},
            }
        """
        if len(self.records) < 2:
            return {'error_trend': 'insufficient_data', 'overall_health': 'unknown'}

        errors = [r.model_error for r in self.records]
        confs = [r.confidence_score for r in self.records]

        # 误差趋势
        error_trend = self._classify_trend(errors)

        # 置信度趋势
        conf_trend = self._classify_trend(confs)

        # 收敛估计
        convergence = self._estimate_convergence(errors)

        # 总体健康度
        health = 'good'
        if error_trend == 'diverging':
            health = 'critical'
        elif error_trend == 'oscillating':
            health = 'warning'
        elif error_trend == 'stable' and conf_trend == 'improving':
            health = 'good'

        return {
            'error_trend': error_trend,
            'confidence_trend': conf_trend,
            'convergence_estimate': convergence,
            'overall_health': health,
            'n_rounds': len(self.records),
            'latest_error': errors[-1],
            'best_error': min(errors),
            'latest_confidence': confs[-1],
            'error_range': round(max(errors) - min(errors), 6),
        }

    def _classify_trend(self, values):
        """分类趋势: improving / stable / oscillating / diverging"""
        if len(values) < 3:
            return 'insufficient_data'

        n = len(values)
        # 线性回归斜率
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        den = sum((i - x_mean)**2 for i in range(n))
        slope = num / max(den, 1e-10)

        # 相对斜率
        rel_slope = slope / max(abs(y_mean), 1e-10)

        # 振荡检测: 过零点次数
        diffs = [values[i] - values[i-1] for i in range(1, n)]
        sign_changes = sum(1 for i in range(1, len(diffs))
                          if diffs[i] * diffs[i-1] < 0)

        if sign_changes > len(diffs) * 0.5:
            return 'oscillating'
        elif rel_slope < -0.01:
            return 'improving'
        elif rel_slope > 0.01:
            return 'diverging'
        else:
            return 'stable'

    def _estimate_convergence(self, errors):
        """估计收敛轮数"""
        if len(errors) < 3:
            return None

        # 检查最后 3 轮是否改善 < 1%
        recent = errors[-3:]
        if all(abs(recent[i] - recent[i-1]) / max(abs(recent[i-1]), 1e-10) < 0.01
               for i in range(1, len(recent))):
            return len(self.records)  # 已收敛

        # 线性外推
        n = len(errors)
        x_mean = (n - 1) / 2.0
        y_mean = sum(errors) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(errors))
        den = sum((i - x_mean)**2 for i in range(n))
        slope = num / max(den, 1e-10)

        if abs(slope) < 1e-6:
            return None

        # 估计到达 1% 改善需要的轮数
        target = y_mean * 0.01
        rounds_needed = int((target - y_mean) / slope)
        return max(1, min(rounds_needed, 100)) if rounds_needed > 0 else None

    def get_summary(self):
        """获取摘要"""
        analysis = self.analyze_trend()
        return {
            'total_rounds': len(self.records),
            'trend': analysis,
            'latest': self.records[-1].to_dict() if self.records else None,
        }