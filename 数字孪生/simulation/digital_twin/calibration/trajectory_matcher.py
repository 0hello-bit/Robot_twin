# -*- coding: utf-8 -*-
"""
trajectory_matcher.py - 轨迹对齐与行为匹配 (v2)

v2 升级:
    - 新增 control-space alignment (PWM/误差/转向响应对齐)
    - 新增 state-space alignment (速度/角速度对齐)
    - 新增 composite distance metric (位置+控制+状态加权)
    - 多轨迹批量对齐支持
"""

import math
import time


# ══════════════════════════════════════════════════════════════
#  轨迹点
# ══════════════════════════════════════════════════════════════

class TrajPoint:
    __slots__ = ('t', 'x', 'y', 'angle', 'sensors', 'left_pwm',
                 'right_pwm', 'error', 'pid_output')

    def __init__(self, record):
        self.t = record.get('t', 0)
        self.x = record.get('car_x', record.get('x', 0))
        self.y = record.get('car_y', record.get('y', 0))
        self.angle = record.get('car_angle', record.get('angle', 0))
        sensors = record.get('sensors', record.get('sensor_states', [1,1,1,1]))
        self.sensors = tuple(sensors) if sensors else (1,1,1,1)
        self.left_pwm = record.get('left_pwm', 0)
        self.right_pwm = record.get('right_pwm', 0)
        self.error = record.get('error', 0)
        self.pid_output = record.get('pid_output', 0)


    def feature_vector(self):
        return (self.x, self.y, self.angle % 360,
                self.left_pwm / 999.0, self.right_pwm / 999.0)
def point_distance(a, b):
    va = a.feature_vector()
    vb = b.feature_vector()
    return math.sqrt(sum((pa - pb) ** 2 for pa, pb in zip(va, vb)))


# ══════════════════════════════════════════════════════════════
#  复合距离度量 (v2 核心)
# ══════════════════════════════════════════════════════════════

class CompositeDistance:
    """
    复合距离: 位置 + 控制 + 状态 加权。

    d = w_pos * d_position + w_ctrl * d_control + w_state * d_state
    """

    def __init__(self, w_pos=0.4, w_ctrl=0.3, w_state=0.3):
        self.w_pos = w_pos
        self.w_ctrl = w_ctrl
        self.w_state = w_state

    def __call__(self, a, b):
        # 位置距离 (归一化)
        d_pos = math.sqrt((a.x - b.x)**2 + (a.y - b.y)**2) / 500.0

        # 控制空间距离 (PWM 差异)
        d_ctrl = (abs(a.left_pwm - b.left_pwm) +
                  abs(a.right_pwm - b.right_pwm)) / (2.0 * 999.0)

        # 状态空间距离 (传感器差异)
        d_state = sum(1 for s1, s2 in zip(a.sensors, b.sensors)
                      if s1 != s2) / 4.0

        return self.w_pos * d_pos + self.w_ctrl * d_ctrl + self.w_state * d_state


# ══════════════════════════════════════════════════════════════
#  重采样
# ══════════════════════════════════════════════════════════════

def resample_trajectory(records, target_n):
    if not records or target_n < 2:
        return [TrajPoint(r) for r in records]
    n = len(records)
    if n == target_n:
        return [TrajPoint(r) for r in records]
    points = []
    for i in range(target_n):
        idx = min(int(i * (n - 1) / (target_n - 1)), n - 1)
        points.append(TrajPoint(records[idx]))
    return points


# ══════════════════════════════════════════════════════════════
#  DTW (v2: 支持复合距离)
# ══════════════════════════════════════════════════════════════

class DTWMatcher:
    def __init__(self, max_warp=50, distance_fn=None):
        self.max_warp = max_warp
        self.dist_fn = distance_fn or point_distance

    def align(self, real_records, sim_records, target_n=200):
        if not real_records or not sim_records:
            return {'error': 'empty trajectories'}

        real_pts = resample_trajectory(real_records, target_n)
        sim_pts = resample_trajectory(sim_records, target_n)
        n = len(real_pts)
        m = len(sim_pts)

        dtw = [[float('inf')] * (m + 1) for _ in range(n + 1)]
        dtw[0][0] = 0.0
        parent = [[None] * (m + 1) for _ in range(n + 1)]

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                if self.max_warp > 0 and abs(i - j) > self.max_warp:
                    continue
                d = self.dist_fn(real_pts[i-1], sim_pts[j-1])
                candidates = [
                    (dtw[i-1][j] + d, (i-1, j)),
                    (dtw[i][j-1] + d, (i, j-1)),
                    (dtw[i-1][j-1] + d, (i-1, j-1)),
                ]
                best_cost, best_parent = min(candidates, key=lambda x: x[0])
                dtw[i][j] = best_cost
                parent[i][j] = best_parent

        path = []
        i, j = n, m
        while i > 0 or j > 0:
            path.append((i-1, j-1))
            if parent[i][j] is not None:
                i, j = parent[i][j]
            else:
                break
        path.reverse()

        return {
            'dtw_distance': round(dtw[n][m], 4),
            'normalized_distance': round(dtw[n][m] / max(len(path), 1), 4),
            'alignment_path': path,
            'aligned_real': real_pts,
            'aligned_sim': sim_pts,
            'n_real': len(real_records),
            'n_sim': len(sim_records),
        }


# ══════════════════════════════════════════════════════════════
#  多轨迹批量对齐 (v2 新增)
# ══════════════════════════════════════════════════════════════

class BatchDTWMatcher:
    """
    多轨迹批量 DTW 对齐。

    计算多条轨迹的平均归一化距离。
    """

    def __init__(self, max_warp=30, distance_fn=None):
        self.matcher = DTWMatcher(max_warp=max_warp, distance_fn=distance_fn)

    def align_batch(self, real_batch, sim_batch, target_n=150, weights=None):
        """
        批量对齐。

        参数:
            real_batch: list of list[dict] - 多条真实轨迹
            sim_batch:  list of list[dict] - 多条仿真轨迹
            target_n:   每条轨迹重采样点数
            weights:    每条轨迹的权重

        返回:
            dict: avg_distance, per_trajectory, weighted_distance
        """
        n_traj = min(len(real_batch), len(sim_batch))
        if n_traj == 0:
            return {'error': 'no trajectories'}

        if weights is None:
            weights = [1.0] * n_traj
        weights = weights[:n_traj]
        w_sum = sum(weights)

        per_traj = []
        total_weighted = 0.0

        for i in range(n_traj):
            result = self.matcher.align(real_batch[i], sim_batch[i], target_n)
            dist = result.get('normalized_distance', float('inf'))
            per_traj.append({
                'index': i,
                'distance': dist,
                'weight': weights[i],
                'n_real': result.get('n_real', 0),
                'n_sim': result.get('n_sim', 0),
            })
            total_weighted += weights[i] * dist

        avg_dist = sum(p['distance'] for p in per_traj) / n_traj
        weighted_dist = total_weighted / max(w_sum, 1e-10)

        # 误差方差 (衡量一致性)
        mean_d = avg_dist
        variance = sum((p['distance'] - mean_d)**2 for p in per_traj) / n_traj

        return {
            'avg_distance': round(avg_dist, 4),
            'weighted_distance': round(weighted_dist, 4),
            'distance_variance': round(variance, 4),
            'n_trajectories': n_traj,
            'per_trajectory': per_traj,
        }


# ══════════════════════════════════════════════════════════════
#  传感器序列匹配
# ══════════════════════════════════════════════════════════════

class SensorSequenceMatcher:
    @staticmethod
    def compare(real_sensors, sim_sensors):
        n = min(len(real_sensors), len(sim_sensors))
        if n == 0:
            return {'match_pct': 0, 'n': 0}
        matches = total = hamming = 0
        for i in range(n):
            for j in range(min(len(real_sensors[i]), len(sim_sensors[i]))):
                if real_sensors[i][j] == sim_sensors[i][j]:
                    matches += 1
                total += 1
                if real_sensors[i][j] != sim_sensors[i][j]:
                    hamming += 1
        return {
            'match_pct': round(matches / max(total, 1) * 100, 1),
            'hamming_distance': hamming,
            'total_bits': total,
            'n_frames': n,
        }