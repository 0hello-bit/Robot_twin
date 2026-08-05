# -*- coding: utf-8 -*-
"""
model_confidence.py - 模型置信度评估

职责:
    1. 评估 plant_model 的可信度
    2. 多维度指标: 误差方差 / 参数稳定性 / 预测一致性
    3. 输出 confidence_score ∈ [0, 100]

置信度维度:
    1. 多轨迹误差一致性 (30%): 不同轨迹误差是否接近
    2. 参数稳定性 (25%): 参数是否收敛不震荡
    3. 预测一致性 (25%): 重复仿真结果是否一致
    4. 传感器匹配 (20%): 仿真传感器与真实是否一致
"""

import math


class ModelConfidence:
    """
    模型置信度评估器。

    使用方式:
        conf = ModelConfidence()
        score = conf.evaluate(
            batch_errors=[0.5, 0.6, 0.4],
            param_stability=0.9,
            prediction_variance=0.02,
            sensor_match_pct=85.0,
        )
    """

    def evaluate(self, batch_errors=None, param_stability=1.0,
                 prediction_variance=0.0, sensor_match_pct=100.0,
                 n_datasets=1):
        """
        计算模型置信度。

        参数:
            batch_errors:         list[float] - 各轨迹的 DTW 距离
            param_stability:      float 0~1 - 参数稳定性
            prediction_variance:  float - 重复预测的方差
            sensor_match_pct:     float 0~100 - 传感器匹配率
            n_datasets:           int - 数据集数量

        返回:
            dict: {
                'confidence_score': 0~100,
                'grade': 'HIGH'/'MEDIUM'/'LOW'/'UNRELIABLE',
                'dimensions': {...},
                'recommendations': [...],
            }
        """
        dims = {}
        recs = []

        # ── 1. 多轨迹误差一致性 (30%) ──
        if batch_errors and len(batch_errors) >= 2:
            mean_err = sum(batch_errors) / len(batch_errors)
            variance = sum((e - mean_err)**2 for e in batch_errors) / len(batch_errors)
            cv = math.sqrt(max(0, variance)) / max(abs(mean_err), 1e-10)
            consistency = max(0, 1.0 - min(cv, 2.0) / 2.0)
            dims['multi_traj_consistency'] = round(consistency * 100, 1)

            if consistency < 0.5:
                recs.append("HIGH_VARIANCE: 不同轨迹误差差异大, 需要更多数据")
        elif batch_errors:
            dims['multi_traj_consistency'] = 50.0  # 单轨迹, 中等置信
            recs.append("SINGLE_TRAJ: 仅单条轨迹, 建议增加数据")
        else:
            dims['multi_traj_consistency'] = 0.0

        # ── 2. 参数稳定性 (25%) ──
        dims['param_stability'] = round(param_stability * 100, 1)
        if param_stability < 0.5:
            recs.append("UNSTABLE_PARAMS: 参数未稳定收敛")

        # ── 3. 预测一致性 (25%) ──
        pred_consistency = max(0, 1.0 - min(prediction_variance, 1.0))
        dims['prediction_consistency'] = round(pred_consistency * 100, 1)
        if prediction_variance > 0.1:
            recs.append("HIGH_VARIANCE: 重复预测结果不一致")

        # ── 4. 传感器匹配 (20%) ──
        dims['sensor_match'] = round(sensor_match_pct, 1)
        if sensor_match_pct < 60:
            recs.append("LOW_SENSOR_MATCH: 传感器行为差异大")

        # ── 综合评分 ──
        weights = {
            'multi_traj_consistency': 0.30,
            'param_stability': 0.25,
            'prediction_consistency': 0.25,
            'sensor_match': 0.20,
        }

        score = sum(dims.get(k, 0) * w for k, w in weights.items())

        # 数据量奖励
        if n_datasets >= 3:
            score = min(100, score * 1.05)
        elif n_datasets >= 5:
            score = min(100, score * 1.10)

        score = max(0, min(100, score))

        # 等级
        if score >= 80:
            grade = 'HIGH'
        elif score >= 60:
            grade = 'MEDIUM'
        elif score >= 40:
            grade = 'LOW'
        else:
            grade = 'UNRELIABLE'

        if not recs:
            recs.append("MODEL_OK: 模型可信度良好")

        return {
            'confidence_score': round(score, 1),
            'grade': grade,
            'dimensions': dims,
            'n_datasets': n_datasets,
            'recommendations': recs,
        }