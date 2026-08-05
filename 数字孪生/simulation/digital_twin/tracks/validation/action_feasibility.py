# -*- coding: utf-8 -*-
"""
action_feasibility.py - Action Feasibility Validator

Checks whether the robot can physically follow a given track
given its actuator limits.

Outputs:
    feasibility_score (0~1): 1 = fully controllable, 0 = impossible
"""

import numpy as np
import math
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config as cfg


def compute_max_steering_rate(max_speed, wheel_base):
    """
    Maximum angular velocity the robot can achieve.
    omega_max = v * 2 / wheel_base (differential drive)
    """
    return max_speed * 2.0 / wheel_base


def compute_min_achievable_radius(max_speed, max_angular_vel):
    """
    Minimum turn radius the robot can achieve.
    R_min = v / omega_max
    """
    if max_angular_vel < 1e-6:
        return float('inf')
    return max_speed / max_angular_vel


def evaluate_feasibility(track_points, max_speed=None, max_angular_vel=None,
                         wheel_base=None):
    """
    Evaluate whether the track is feasible for the robot.

    Args:
        track_points: Nx2 numpy array
        max_speed: maximum linear speed (px/s)
        max_angular_vel: maximum angular velocity (deg/s)
        wheel_base: robot wheel base (px)

    Returns:
        dict with:
            feasibility_score: 0~1
            max_curvature_demand: max curvature the track requires
            max_achievable_curvature: max curvature the robot can produce
            bottleneck_points: indices where feasibility is lowest
            details: per-segment feasibility
    """
    if max_speed is None:
        max_speed = cfg.MAX_SPEED
    if max_angular_vel is None:
        max_angular_vel = cfg.MAX_ANGULAR_VEL
    if wheel_base is None:
        wheel_base = cfg.WHEEL_BASE

    pts = np.array(track_points, dtype=float)
    n = len(pts)

    if n < 10:
        return {
            'feasibility_score': 1.0,
            'max_curvature_demand': 0.0,
            'max_achievable_curvature': 0.0,
            'bottleneck_points': [],
            'details': [],
        }

    # Compute max achievable curvature
    max_omega_rad = math.radians(max_angular_vel)
    max_achievable_curv = max_omega_rad / (max_speed + 1e-6)

    # Compute track curvatures
    from tracks.track_difficulty import compute_curvature
    curvatures = compute_curvature(pts)

    # Per-point feasibility: how much margin we have
    feasibility_per_point = np.ones(n)
    for i in range(n):
        if curvatures[i] > 1e-8:
            # Required turning rate
            required_omega = curvatures[i] * max_speed
            # Margin = how much of max capacity we use
            margin = 1.0 - min(required_omega / (max_omega_rad + 1e-6), 1.0)
            feasibility_per_point[i] = max(0.0, margin)

    # Find bottleneck points (lowest feasibility)
    sorted_indices = np.argsort(feasibility_per_point)
    bottleneck_count = max(1, n // 10)
    bottleneck_indices = sorted_indices[:bottleneck_count].tolist()

    # Overall feasibility score
    min_feasibility = np.min(feasibility_per_point)
    mean_feasibility = np.mean(feasibility_per_point)
    # Use geometric mean to penalize any single bad point heavily
    feasibility_score = min_feasibility * 0.6 + mean_feasibility * 0.4

    return {
        'feasibility_score': round(feasibility_score, 4),
        'max_curvature_demand': round(float(np.max(curvatures)), 6),
        'max_achievable_curvature': round(max_achievable_curv, 6),
        'bottleneck_points': bottleneck_indices,
        'min_point_feasibility': round(float(min_feasibility), 4),
        'mean_point_feasibility': round(float(mean_feasibility), 4),
    }


def check_all_levels(track_generator, seeds=None):
    """
    Check feasibility for all 4 curriculum levels.

    Returns:
        dict {level: feasibility_result}
    """
    if seeds is None:
        seeds = [42, 123, 456]

    results = {}
    for level in [1, 2, 3, 4]:
        scores = []
        for seed in seeds:
            pts = track_generator.get_track(level, seed=seed)
            result = evaluate_feasibility(pts)
            scores.append(result['feasibility_score'])
        results[level] = {
            'mean_feasibility': round(np.mean(scores), 4),
            'min_feasibility': round(np.min(scores), 4),
            'all_scores': [round(s, 4) for s in scores],
        }

    return results
