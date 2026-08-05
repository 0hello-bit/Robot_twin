# -*- coding: utf-8 -*-
import numpy as np
import math


def compute_curvature(points):
    n = len(points)
    curvatures = np.zeros(n)
    for i in range(n):
        prev_idx = (i - 1) % n
        next_idx = (i + 1) % n
        p0 = points[prev_idx]
        p1 = points[i]
        p2 = points[next_idx]
        v1 = p1 - p0
        v2 = p2 - p1
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        len1 = np.linalg.norm(v1)
        len2 = np.linalg.norm(v2)
        if len1 > 1e-6 and len2 > 1e-6:
            sin_angle = cross / (len1 * len2)
            curvatures[i] = abs(sin_angle) * 2.0 / (len1 + len2 + 1e-8)
        else:
            curvatures[i] = 0.0
    return curvatures


def compute_heading_changes(points):
    n = len(points)
    headings = np.zeros(n)
    for i in range(n):
        next_idx = (i + 1) % n
        dx = points[next_idx][0] - points[i][0]
        dy = points[next_idx][1] - points[i][1]
        headings[i] = math.atan2(dy, dx)
    changes = np.zeros(n)
    for i in range(n):
        next_idx = (i + 1) % n
        diff = headings[next_idx] - headings[i]
        while diff > math.pi:
            diff -= 2 * math.pi
        while diff < -math.pi:
            diff += 2 * math.pi
        changes[i] = abs(diff)
    return changes


def detect_crossings(points, threshold=15.0):
    n = len(points)
    crossings = []
    for i in range(n):
        for j in range(i + 10, n):
            if abs(i - j) < 5 or abs(i - j) > n - 5:
                continue
            dx = points[i][0] - points[j][0]
            dy = points[i][1] - points[j][1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < threshold:
                mid_x = (points[i][0] + points[j][0]) / 2.0
                mid_y = (points[i][1] + points[j][1]) / 2.0
                is_new = True
                for cx, cy in crossings:
                    if abs(mid_x - cx) < threshold and abs(mid_y - cy) < threshold:
                        is_new = False
                        break
                if is_new:
                    crossings.append((mid_x, mid_y))
    return crossings


def compute_track_difficulty(points):
    pts = np.array(points, dtype=float)
    n = len(pts)
    if n < 10:
        return {
            'difficulty': 0.0,
            'components': {},
            'raw_components': {},
            'curvatures': np.array([]),
            'min_turn_radius': float('inf'),
        }

    curvatures = compute_curvature(pts)
    heading_changes = compute_heading_changes(pts)
    crossings = detect_crossings(pts)

    p50_curv = float(np.percentile(curvatures, 50))
    p90_curv = float(np.percentile(curvatures, 90))
    p95_curv = float(np.percentile(curvatures, 95))
    p90_heading = float(np.percentile(heading_changes, 90))

    if p95_curv > 1e-8:
        min_turn_radius = 1.0 / p95_curv
    else:
        min_turn_radius = float('inf')

    tightness = min(p90_curv * 30.0, 1.0)
    turn_freq = min(p90_heading / (math.pi * 0.3), 1.0)
    n_crossings = len(crossings)
    crossing_score = min(n_crossings / 3.0, 1.0)

    total_length = 0.0
    for i in range(n):
        next_idx = (i + 1) % n
        dx = pts[next_idx][0] - pts[i][0]
        dy = pts[next_idx][1] - pts[i][1]
        total_length += math.sqrt(dx * dx + dy * dy)
    length_score = min(total_length / 2000.0, 1.0)

    curv_std = float(np.std(curvatures))
    variation = min(curv_std * 200.0, 1.0)

    difficulty = (
        0.15 * tightness +
        0.15 * turn_freq +
        0.35 * crossing_score +
        0.15 * length_score +
        0.20 * variation
    )
    difficulty = max(0.0, min(1.0, difficulty))

    return {
        'difficulty': round(difficulty, 4),
        'components': {
            'tightness': round(tightness, 4),
            'turn_frequency': round(turn_freq, 4),
            'crossing_complexity': round(crossing_score, 4),
            'path_length': round(length_score, 4),
            'curvature_variation': round(variation, 4),
        },
        'raw_components': {
            'p50_curvature': round(p50_curv, 6),
            'p90_curvature': round(p90_curv, 6),
            'p95_curvature': round(p95_curv, 6),
            'p90_heading_rad': round(p90_heading, 4),
            'n_crossings': n_crossings,
            'total_path_length': round(total_length, 1),
            'curvature_std': round(curv_std, 6),
            'min_turn_radius_px': round(min_turn_radius, 1),
        },
        'curvatures': curvatures,
        'min_turn_radius': round(min_turn_radius, 1),
    }


DIFFICULTY_WEIGHTS = {
    'tightness': 0.15,
    'turn_frequency': 0.15,
    'crossing_complexity': 0.35,
    'path_length': 0.15,
    'curvature_variation': 0.20,
}


def validate_difficulty_monotonicity(level_difficulties):
    levels = sorted(level_difficulties.keys())
    difficulties = [level_difficulties[l] for l in levels]
    violations = []
    for i in range(1, len(difficulties)):
        if difficulties[i] <= difficulties[i - 1]:
            violations.append({
                'from_level': levels[i - 1],
                'to_level': levels[i],
                'from_diff': difficulties[i - 1],
                'to_diff': difficulties[i],
            })
    is_monotonic = len(violations) == 0
    if not is_monotonic:
        recommendation = (
            f'Difficulty not monotonic at levels: '
            f'{[v["to_level"] for v in violations]}. '
            f'Track geometry varies significantly across levels; '
            f'monotonicity is not required for curriculum learning.'
        )
    else:
        recommendation = 'Difficulty is monotonically increasing. OK.'
    return {
        'is_monotonic': is_monotonic,
        'violations': violations,
        'recommendation': recommendation,
        'level_difficulties': level_difficulties,
    }
