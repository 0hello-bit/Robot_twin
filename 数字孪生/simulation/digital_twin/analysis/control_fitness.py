# -*- coding: utf-8 -*-
"""
control_fitness.py - 控制参数适应度评估

职责:
    1. 评估 PID 参数的控制效果
    2. 输出稳定性评分 (0~100)
    3. 输出可用性等级 (A/B/C/D)
    4. 识别: 稳定 / 振荡 / 丢线 / 发散

评估维度:
    1. 稳定性: 误差方差 / 震荡频率
    2. 跟踪性: 平均误差 / 最大误差
    3. 丢线率: 传感器全白的比例
    4. 收敛性: 是否能回到线上
    5. 平滑性: 转向变化率

等级定义:
    A: 稳定可用 (score >= 80)
    B: 轻微振荡 (60 <= score < 80)
    C: 不稳定但可修 (40 <= score < 60)
    D: 不可用 / 发散 (score < 40)
"""

import math


class ControlFitness:
    """
    控制参数适应度评估器。

    使用方式:
        fitness = ControlFitness()
        result = fitness.evaluate(trajectory, sensors, motors)
        print(result['grade'], result['score'])
    """

    def evaluate(self, trajectory, sensor_history, motor_history):
        """
        评估控制效果。

        参数:
            trajectory:     list[dict] - 每步状态
            sensor_history: list[list] - 传感器历史
            motor_history:  list[tuple] - 电机输出历史

        返回:
            dict: {
                'score': 0~100,
                'grade': 'A'/'B'/'C'/'D',
                'metrics': {...},
                'diagnosis': [...],
            }
        """
        if not trajectory or len(trajectory) < 10:
            return self._empty_result()

        n = len(trajectory)

        # ── 1. 丢线率 ──
        lost_count = sum(1 for s in sensor_history if all(v == 1 for v in s))
        lost_pct = lost_count / n * 100

        # ── 2. 传感器中心偏差 ──
        errors = []
        for sensors in sensor_history:
            s0, s1, s2, s3 = sensors
            pos = 0
            if s0 == 0: pos += -3
            if s1 == 0: pos += -1
            if s2 == 0: pos += +1
            if s3 == 0: pos += +3
            errors.append(pos)

        avg_error = sum(abs(e) for e in errors) / max(len(errors), 1)
        max_error = max(abs(e) for e in errors) if errors else 0

        # ── 3. 震荡检测 ──
        zero_crossings = 0
        for i in range(1, len(errors)):
            if errors[i-1] * errors[i] < 0:
                zero_crossings += 1
        osc_freq = zero_crossings / max(n, 1) * 2

        # ── 4. 误差方差 (稳定性) ──
        if len(errors) > 1:
            err_mean = sum(errors) / len(errors)
            err_var = sum((e - err_mean)**2 for e in errors) / len(errors)
        else:
            err_var = 0

        # ── 5. 转向平滑性 ──
        turn_changes = 0
        for i in range(1, len(motor_history)):
            dl = abs(motor_history[i][0] - motor_history[i-1][0])
            dr = abs(motor_history[i][1] - motor_history[i-1][1])
            if dl + dr > 100:
                turn_changes += 1
        smoothness = 1.0 - turn_changes / max(n, 1)

        # ── 6. 收敛性 ──
        # 检查最后 20% 的误差是否比前 20% 小
        quarter = max(1, n // 5)
        early_err = sum(abs(e) for e in errors[:quarter]) / quarter
        late_err = sum(abs(e) for e in errors[-quarter:]) / quarter
        converging = late_err < early_err

        # ── 7. 发散检测 ──
        # 如果后半段平均误差 > 前半段 2 倍 → 发散
        half = n // 2
        first_half_err = sum(abs(e) for e in errors[:half]) / max(half, 1)
        second_half_err = sum(abs(e) for e in errors[half:]) / max(n - half, 1)
        diverging = second_half_err > first_half_err * 2.0

        # ── 综合评分 ──
        score = 100.0

        # 丢线惩罚 (权重 35%)
        score -= min(35, lost_pct * 1.5)

        # 平均误差惩罚 (权重 25%)
        score -= min(25, avg_error * 5)

        # 震荡惩罚 (权重 15%)
        score -= min(15, osc_freq * 15)

        # 方差惩罚 (权重 10%)
        score -= min(10, err_var * 0.5)

        # 平滑性奖励 (权重 10%)
        score -= min(10, (1 - smoothness) * 10)

        # 发散惩罚 (权重 5%)
        if diverging:
            score -= 30

        score = max(0, min(100, score))

        # ── 等级判定 ──
        if score >= 80:
            grade = 'A'
        elif score >= 60:
            grade = 'B'
        elif score >= 40:
            grade = 'C'
        else:
            grade = 'D'

        # ── 诊断 ──
        diagnosis = []
        if lost_pct > 5:
            diagnosis.append("HIGH_LOSS: 丢线率 {:.1f}%".format(lost_pct))
        if osc_freq > 0.3:
            diagnosis.append("OSCILLATION: 震荡频率 {:.2f}".format(osc_freq))
        if diverging:
            diagnosis.append("DIVERGING: 后半段误差增大")
        if not converging:
            diagnosis.append("NOT_CONVERGING: 未收敛")
        if avg_error > 3:
            diagnosis.append("HIGH_ERROR: 平均偏差过大")
        if max_error > 6:
            diagnosis.append("EXTREME_ERROR: 最大偏差过大")
        if smoothness < 0.5:
            diagnosis.append("ROUGH: 转向不平滑")
        if not diagnosis:
            diagnosis.append("HEALTHY: 控制正常")

        return {
            'score': round(score, 1),
            'grade': grade,
            'metrics': {
                'lost_pct': round(lost_pct, 1),
                'avg_error': round(avg_error, 3),
                'max_error': max_error,
                'osc_freq': round(osc_freq, 3),
                'err_var': round(err_var, 3),
                'smoothness': round(smoothness, 3),
                'converging': converging,
                'diverging': diverging,
                'zero_crossings': zero_crossings,
            },
            'diagnosis': diagnosis,
        }

    def evaluate_sim_real(self, real_records, sim_records, real_sensors=None, sim_sensors=None):
        """
        评估仿真与真实的一致性。

        参数:
            real_records: 真实轨迹
            sim_records:  仿真轨迹
            real_sensors: 真实传感器序列
            sim_sensors:  仿真传感器序列

        返回:
            dict: sim-real 一致性评分
        """
        if not real_records or not sim_records:
            return {'error': 'insufficient data'}

        n = min(len(real_records), len(sim_records))

        # 轨迹误差
        traj_errors = []
        for i in range(n):
            rx = real_records[i].get('car_x', real_records[i].get('x', 0))
            ry = real_records[i].get('car_y', real_records[i].get('y', 0))
            sx = sim_records[i].get('car_x', sim_records[i].get('x', 0))
            sy = sim_records[i].get('car_y', sim_records[i].get('y', 0))
            traj_errors.append(((rx-sx)**2 + (ry-sy)**2)**0.5)

        avg_traj_err = sum(traj_errors) / max(len(traj_errors), 1)
        max_traj_err = max(traj_errors) if traj_errors else 0

        # 传感器匹配
        sensor_match = 0
        sensor_total = 0
        if real_sensors and sim_sensors:
            for i in range(min(len(real_sensors), len(sim_sensors))):
                for j in range(min(len(real_sensors[i]), len(sim_sensors[i]))):
                    if real_sensors[i][j] == sim_sensors[i][j]:
                        sensor_match += 1
                    sensor_total += 1

        sensor_pct = sensor_match / max(sensor_total, 1) * 100

        # 一致性评分
        score = 100.0
        score -= min(40, avg_traj_err * 2)
        score -= min(20, max_traj_err * 0.5)
        score -= min(25, (100 - sensor_pct) * 0.25)
        score = max(0, min(100, score))

        return {
            'consistency_score': round(score, 1),
            'avg_trajectory_error': round(avg_traj_err, 3),
            'max_trajectory_error': round(max_traj_err, 3),
            'sensor_match_pct': round(sensor_pct, 1),
            'n_samples': n,
        }

    def _empty_result(self):
        return {
            'score': 0,
            'grade': 'D',
            'metrics': {},
            'diagnosis': ['INSUFFICIENT_DATA'],
        }