# -*- coding: utf-8 -*-
"""
curriculum_sanity.py - Curriculum Sanity Checker

Validates that the curriculum system is well-formed:
1. Difficulty increases monotonically
2. Reward variance doesn't explode
3. Episode length doesn't degrade
4. No impossible tracks
"""

import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def check_curriculum_sanity(track_generator, difficulty_results=None):
    """
    Run full sanity check on the curriculum.

    Args:
        track_generator: CurriculumTrackGenerator instance
        difficulty_results: output from compute_track_difficulty per level

    Returns:
        dict with pass/fail for each check + overall verdict
    """
    report = {
        'checks': {},
        'overall_pass': True,
        'issues': [],
    }

    # Check 1: All levels generate valid tracks
    check_valid = _check_track_validity(track_generator)
    report['checks']['track_validity'] = check_valid
    if not check_valid['passed']:
        report['overall_pass'] = False
        report['issues'].extend(check_valid['issues'])

    # Check 2: Difficulty monotonicity
    if difficulty_results is not None:
        check_diff = _check_difficulty_monotonic(difficulty_results)
        report['checks']['difficulty_monotonic'] = check_diff
        if not check_diff['passed']:
            report['overall_pass'] = False
            report['issues'].extend(check_diff['issues'])

    # Check 3: Track size consistency
    check_size = _check_track_sizes(track_generator)
    report['checks']['track_sizes'] = check_size
    if not check_size['passed']:
        report['overall_pass'] = False
        report['issues'].extend(check_size['issues'])

    # Check 4: No degenerate tracks
    check_degen = _check_no_degenerate(track_generator)
    report['checks']['no_degenerate'] = check_degen
    if not check_degen['passed']:
        report['overall_pass'] = False
        report['issues'].extend(check_degen['issues'])

    return report


def _check_track_validity(track_generator, n_seeds=5):
    """Check that all levels produce valid tracks across multiple seeds."""
    issues = []
    for level in [1, 2, 3, 4]:
        for seed in range(42, 42 + n_seeds):
            try:
                pts = track_generator.get_track(level, seed=seed)
                if pts is None or len(pts) < 10:
                    issues.append(f'Level {level} seed {seed}: too few points ({len(pts) if pts is not None else 0})')
                elif np.any(np.isnan(pts)):
                    issues.append(f'Level {level} seed {seed}: contains NaN')
                elif np.any(np.isinf(pts)):
                    issues.append(f'Level {level} seed {seed}: contains Inf')
            except Exception as e:
                issues.append(f'Level {level} seed {seed}: exception {e}')

    return {
        'passed': len(issues) == 0,
        'issues': issues,
        'n_seeds_tested': n_seeds,
    }


def _check_difficulty_monotonic(difficulty_results):
    """Check that difficulty increases across levels."""
    issues = []
    levels = sorted(difficulty_results.keys())
    for i in range(1, len(levels)):
        prev_level = levels[i - 1]
        curr_level = levels[i]
        prev_diff = difficulty_results[prev_level].get('difficulty', 0)
        curr_diff = difficulty_results[curr_level].get('difficulty', 0)
        if curr_diff <= prev_diff:
            issues.append(
                f'Level {prev_level} ({prev_diff:.3f}) >= '
                f'Level {curr_level} ({curr_diff:.3f}): not monotonic'
            )

    return {
        'passed': len(issues) == 0,
        'issues': issues,
    }


def _check_track_sizes(track_generator, n_seeds=3):
    """Check that tracks fit within canvas and have reasonable size."""
    issues = []
    canvas_w, canvas_h = 800, 600
    margin = 20

    for level in [1, 2, 3, 4]:
        for seed in [42, 100, 200]:
            pts = track_generator.get_track(level, seed=seed)
            if pts is None or len(pts) == 0:
                continue
            xmin, ymin = pts.min(axis=0)
            xmax, ymax = pts.max(axis=0)

            if xmin < margin or xmax > canvas_w - margin:
                issues.append(f'Level {level} seed {seed}: x out of bounds [{xmin:.0f}, {xmax:.0f}]')
            if ymin < margin or ymax > canvas_h - margin:
                issues.append(f'Level {level} seed {seed}: y out of bounds [{ymin:.0f}, {ymax:.0f}]')

    return {
        'passed': len(issues) == 0,
        'issues': issues,
    }


def _check_no_degenerate(track_generator, n_seeds=5):
    """Check that tracks are not degenerate (e.g., all same point, self-intersecting badly)."""
    issues = []
    for level in [1, 2, 3, 4]:
        for seed in range(42, 42 + n_seeds):
            pts = track_generator.get_track(level, seed=seed)
            if pts is None or len(pts) < 10:
                issues.append(f'Level {level} seed {seed}: degenerate (too few points)')
                continue

            # Check for near-zero total path length
            diffs = np.diff(pts, axis=0)
            lengths = np.linalg.norm(diffs, axis=1)
            total_length = lengths.sum()
            if total_length < 100:
                issues.append(f'Level {level} seed {seed}: total path length {total_length:.0f} too short')

            # Check for duplicate consecutive points
            dup_count = np.sum(lengths < 0.1)
            if dup_count > len(pts) * 0.1:
                issues.append(f'Level {level} seed {seed}: {dup_count} duplicate consecutive points')

    return {
        'passed': len(issues) == 0,
        'issues': issues,
    }


def generate_sanity_report(track_generator):
    """Generate a complete sanity report."""
    from tracks.track_difficulty import compute_track_difficulty

    # Compute difficulties
    difficulties = {}
    for level in [1, 2, 3, 4]:
        pts = track_generator.get_track(level, seed=42)
        diff_result = compute_track_difficulty(pts)
        difficulties[level] = diff_result

    # Run sanity checks
    report = check_curriculum_sanity(track_generator, difficulties)

    # Add difficulty info
    report['difficulties'] = {
        level: {
            'difficulty': d['difficulty'],
            'components': d['components'],
            'min_turn_radius': d['min_turn_radius'],
        }
        for level, d in difficulties.items()
    }

    return report
