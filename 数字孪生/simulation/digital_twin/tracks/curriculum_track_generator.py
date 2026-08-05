# -*- coding: utf-8 -*-
"""
curriculum_track_generator.py - RL Robust Curriculum Track System v3

寮哄埗RL瀛︿範"鎺у埗瑙勫緥"鑰屼笉鏄?杞ㄩ亾璁板繂"銆?

Level 1: ellipse + mild curvature noise (baseline stability)
Level 2: sine wave + random phase shift + amplitude drift
Level 3: figure-8 + random crossing offset + stochastic width + optional gaps
Level 4: hybrid spline track (straight + sharp turn + spiral + sinusoidal)

鏂板鑳藉姏:
- DomainRandomization: 姣廵pisode闅忔満鍖栬禌閬撳弬鏁?
- TimeVaryingTrack: 杞ㄩ亾鍔ㄦ€佹紓绉? 闃叉璁板繂鍑犱綍
- Unseen Test Set: get_unseen_track() 鐢ㄤ簬璇勪及娉涘寲鑳藉姏

鎺ュ彛:
    gen = CurriculumTrackGenerator(seed=42)
    points = gen.get_track(level=1)          # numpy (N, 2)
    points = gen.get_unseen_track(seed=100)  # 娉涘寲娴嬭瘯璧涢亾
    start = gen.get_start_pos()
    gen.render_all_levels(save_dir="previews/")
    level, pts, start = gen.sample_curriculum()
    drift_pts = gen.apply_time_drift(points, time_val)
"""

import math
import numpy as np
import random
from scipy.interpolate import CubicSpline


DEFAULT_CANVAS = (800, 600)


class DomainRandomizer:
    """
    Domain Randomization: 姣忎釜episode闅忔満鍖栫墿鐞?璧涢亾鍙傛暟銆?
    鐢ㄤ簬闃叉RL policy杩囨嫙鍚堢壒瀹氱幆澧冦€?
    """

    def __init__(self, seed=None):
        self._rng = random.Random(seed)
        self._np_rng = np.random.RandomState(seed)

    def sample(self):
        """fixme"""
        return {
            'track_width_scale': self._rng.uniform(0.8, 1.5),
            'curvature_noise_sigma': self._rng.uniform(0.0, 0.08),
            'line_thickness_var': self._rng.uniform(0.8, 1.2),
            'sensor_noise_level': self._rng.uniform(0.0, 5.0),
            'motor_delay_ms': self._rng.uniform(0.0, 80.0),
            'friction_coeff': self._rng.uniform(0.7, 1.0),
        }


class TimeVaryingTrack:
    """
    鏃堕棿鍙樺寲璧涢亾: 璧涢亾杈圭晫闅忔椂闂村井灏忔紓绉? 闃叉policy璁板繂鍥哄畾鍑犱綍銆?
    """

    def __init__(self, points, drift_sigma=0.5, drift_freq=0.01):
        self._base_points = points.copy()
        self._drift_sigma = drift_sigma
        self._drift_freq = drift_freq

    def get_points(self, time_val):
        """fixme"""
        n = len(self._base_points)
        t = time_val * self._drift_freq
        drift_x = self._drift_sigma * np.sin(
            np.linspace(0, 2 * math.pi, n) + t)
        drift_y = self._drift_sigma * np.cos(
            np.linspace(0, 2 * math.pi, n) + t * 1.3)
        drifted = self._base_points.copy()
        drifted[:, 0] += drift_x
        drifted[:, 1] += drift_y
        return drifted


class CurriculumTrackGenerator:
    """fixme"""

    LEVEL_CONFIG = {
        1: {
            'name': 'ellipse_mild',
            'n_points': (150, 200),
            'cx_range': (350, 450),
            'cy_range': (250, 350),
            'rx_range': (220, 340),
            'ry_range': (160, 260),
            'curvature_noise': 0.005,
            'width_randomization': 0.0,
        },
        2: {
            'name': 'sine_varying',
            'n_points': (200, 280),
            'length_range': (400, 600),
            'amp_range': (40, 120),
            'freq_range': (1.5, 3.0),
            'curvature_noise': 0.12,
            'width_randomization': 0.02,
            'post_smooth_noise': 0.0,
        },
        3: {
            'name': 'figure8_randomized',
            'n_points': (200, 300),
            'r_range': (90, 150),
            'curvature_noise': 0.08,
            'width_randomization': 0.03,
            'gap_prob': 0.3,
        },
        4: {
            'name': 'rounded_rectangle',
            'n_segments': (5, 8),
            'segment_length_range': (80, 200),
            'turn_radius_range': (25, 55),
            'curvature_noise': 0.06,
            'width_randomization': 0.02,
        },
    }

    def __init__(self, seed=None, canvas_size=DEFAULT_CANVAS):
        self._rng = random.Random(seed)
        self._np_rng = np.random.RandomState(seed)
        self.canvas_w, self.canvas_h = canvas_size
        self._start_pos = (400.0, 450.0, 0.0)
        self._last_points = None
        self._last_meta = {}
        self.domain_randomizer = DomainRandomizer(seed)

    def get_track(self, level, seed=None):
        """fixme"""
        if seed is not None:
            self._rng = random.Random(seed)
            self._np_rng = np.random.RandomState(seed)
        level = max(1, min(4, level))
        cfg = self.LEVEL_CONFIG[level]
        gen_map = {
            1: self._gen_level1,
            2: self._gen_level2,
            3: self._gen_level3,
            4: self._gen_level4,
        }
        points = gen_map[level](cfg)
        points = self._smooth(points, iterations=2)
        points = self._close_loop(points)
        points = self._ensure_minimum_distance(points, min_dist=3.0)
        points = self._fix_large_gaps(points, max_gap=25.0)
        points = self._validate_and_fix(points)

        # Post-smoothing noise: applied AFTER cubic spline to preserve visible jitter
        # (cubic spline acts as low-pass filter, destroying pre-smoothing noise)
        psn = cfg.get('post_smooth_noise', 0.0)
        if psn > 0 and len(points) > 10:
            noise_x = self._np_rng.normal(0, psn, len(points))
            noise_y = self._np_rng.normal(0, psn, len(points))
            points[:, 0] += noise_x
            points[:, 1] += noise_y
            # Re-validate after noise injection
            points = self._ensure_minimum_distance(points, min_dist=2.0)
            points = self._fix_large_gaps(points, max_gap=25.0)

        self._last_points = points
        self._compute_start_pos(points)
        self._compute_meta(points, level)
        return points

    def get_unseen_track(self, seed):
        """
        鐢熸垚娉涘寲娴嬭瘯璧涢亾(涓嶅弬涓庤缁?銆?
        浣跨敤涓庤缁冧笉鍚岀殑鍙傛暟绌洪棿, 娴嬭瘯policy娉涘寲鑳藉姏銆?
        """
        self._rng = random.Random(seed)
        self._np_rng = np.random.RandomState(seed)

        track_type = self._rng.choice(['sine_high_freq', 'spiral', 'hybrid_novel'])

        if track_type == 'sine_high_freq':
            points = self._gen_unseen_sine()
        elif track_type == 'spiral':
            points = self._gen_unseen_spiral()
        else:
            points = self._gen_unseen_hybrid()

        points = self._smooth(points, iterations=2)
        points = self._close_loop(points)
        points = self._ensure_minimum_distance(points, min_dist=3.0)
        points = self._fix_large_gaps(points, max_gap=25.0)
        points = self._validate_and_fix(points)
        self._last_points = points
        self._compute_start_pos(points)
        self._compute_meta(points, 0)
        return points

    def get_start_pos(self):
        return self._start_pos

    def get_track_meta(self):
        return dict(self._last_meta)

    def sample_curriculum(self):
        level = self._rng.randint(1, 4)
        points = self.get_track(level)
        return level, points, self._start_pos

    def apply_time_drift(self, points, time_val, drift_sigma=0.5):
        """fixme"""
        vt = TimeVaryingTrack(points, drift_sigma=drift_sigma)
        return vt.get_points(time_val)

    # ==================== Level Generators ====================

    def _gen_level1(self, cfg):
        """fixme"""
        n = self._rng.randint(*cfg['n_points'])
        cx = self._rng.uniform(*cfg['cx_range'])
        cy = self._rng.uniform(*cfg['cy_range'])
        rx = self._rng.uniform(*cfg['rx_range'])
        ry = self._rng.uniform(*cfg['ry_range'])

        angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
        xs = cx + rx * np.cos(angles)
        ys = cy + ry * np.sin(angles)

        noise = self._np_rng.normal(0, cfg['curvature_noise'] * rx, n)
        xs += noise
        ys += noise * 0.7

        return np.column_stack([xs, ys])

    def _gen_level2(self, cfg):
        """Level 2: trefoil / flower shape  r = R + A*sin(3*theta)"""
        n = self._rng.randint(*cfg['n_points'])
        R = self._rng.uniform(70, 100)
        A = self._rng.uniform(130, 170)

        theta = np.linspace(0, 2 * math.pi, n, endpoint=False)
        r = R + A * np.sin(3 * theta)

        cx, cy = self.canvas_w / 2, self.canvas_h / 2
        xs = cx + r * np.cos(theta)
        ys = cy + r * np.sin(theta)

        return np.column_stack([xs, ys])

    def _gen_level3(self, cfg):
        n = self._rng.randint(*cfg["n_points"])
        a = self._rng.uniform(*cfg["r_range"])
        separation = a * 2.2
        cx, cy = self.canvas_w / 2, self.canvas_h / 2
        left_cx = cx - separation / 2
        right_cx = cx + separation / 2
        loop_cy = cy
        n_half = n // 2
        t_left = np.linspace(0, 2 * math.pi, n_half, endpoint=False)
        left_x = left_cx + a * np.cos(t_left)
        left_y = loop_cy + a * np.sin(t_left)
        n_right = n - n_half
        t_right = np.linspace(0, 2 * math.pi, n_right, endpoint=False)
        right_x = right_cx + a * np.cos(t_right)
        right_y = loop_cy + a * np.sin(t_right)
        bridge_n = max(5, n // 10)
        bridge_bot_x = np.linspace(left_cx + a, right_cx - a, bridge_n)
        bridge_bot_y = np.full(bridge_n, loop_cy)
        bridge_top_x = np.linspace(right_cx - a, left_cx + a, bridge_n)
        bridge_top_y = np.full(bridge_n, loop_cy)
        all_x = np.concatenate([left_x, bridge_bot_x, right_x, bridge_top_x])
        all_y = np.concatenate([left_y, bridge_bot_y, right_y, bridge_top_y])
        return np.column_stack([all_x, all_y])

    def _gen_level4(self, cfg):
        """Level 4: rounded rectangle (4 straight sides + 4 corner arcs)"""
        rect_w = self._rng.uniform(260, 360)
        rect_h = self._rng.uniform(180, 260)
        corner_r = self._rng.uniform(40, 70)
        n_per_side = self._rng.randint(30, 50)
        n_per_corner = self._rng.randint(15, 25)
        cx, cy = self.canvas_w / 2, self.canvas_h / 2

        half_w = rect_w / 2
        half_h = rect_h / 2

        corners = [
            (cx - half_w + corner_r, cy - half_h + corner_r),
            (cx + half_w - corner_r, cy - half_h + corner_r),
            (cx + half_w - corner_r, cy + half_h - corner_r),
            (cx - half_w + corner_r, cy + half_h - corner_r),
        ]

        pts_list = []
        for i in range(4):
            cx_c, cy_c = corners[i]
            start_angle = math.pi / 2 * (i + 2)
            end_angle = start_angle + math.pi / 2
            angles = np.linspace(start_angle, end_angle, n_per_corner, endpoint=False)
            arc_x = cx_c + corner_r * np.cos(angles)
            arc_y = cy_c + corner_r * np.sin(angles)
            pts_list.append(np.column_stack([arc_x, arc_y]))

            next_i = (i + 1) % 4
            nx, ny = corners[next_i]
            side_x = np.linspace(corners[i][0], nx, n_per_side, endpoint=False)
            side_y = np.linspace(corners[i][1], ny, n_per_side, endpoint=False)
            pts_list.append(np.column_stack([side_x, side_y]))

        pts = np.vstack(pts_list)
        return pts

    # ==================== Unseen Track Generators ====================

    def _gen_unseen_sine(self):
        """fixme"""
        n = self._rng.randint(250, 350)
        freq = self._rng.uniform(4.0, 7.0)
        amp = self._rng.uniform(50, 100)
        base_radius = self._rng.uniform(150, 200)

        t = np.linspace(0, 2 * math.pi, n, endpoint=False)
        cx, cy = self.canvas_w / 2, self.canvas_h / 2
        xs = cx + base_radius * np.cos(t) + amp * np.sin(freq * t)
        ys = cy + base_radius * 0.7 * np.sin(t) + amp * 0.5 * np.cos(freq * t)

        noise = self._np_rng.normal(0, 3, n)
        xs += noise
        ys += noise
        return np.column_stack([xs, ys])

    def _gen_unseen_spiral(self):
        """Unseen: 铻烘棆璧涢亾"""
        n = self._rng.randint(200, 300)
        turns = self._rng.uniform(1.5, 2.5)
        max_r = self._rng.uniform(150, 220)
        min_r = self._rng.uniform(30, 60)

        t = np.linspace(0, turns * 2 * math.pi, n, endpoint=False)
        r_vals = min_r + (max_r - min_r) * (t / (turns * 2 * math.pi))
        cx, cy = self.canvas_w / 2, self.canvas_h / 2

        xs = cx + r_vals * np.cos(t)
        ys = cy + r_vals * np.sin(t)
        return np.column_stack([xs, ys])

    def _gen_unseen_hybrid(self):
        """Unseen: 鏂板瀷娣峰悎璧涢亾"""
        n = self._rng.randint(200, 300)
        cx, cy = self.canvas_w / 2, self.canvas_h / 2
        base_r = self._rng.uniform(120, 180)

        t = np.linspace(0, 2 * math.pi, n, endpoint=False)
        r_mod = base_r + 30 * np.sin(3 * t) + 20 * np.cos(5 * t)
        xs = cx + r_mod * np.cos(t)
        ys = cy + r_mod * np.sin(t)

        noise = self._np_rng.normal(0, 4, n)
        xs += noise
        ys += noise
        return np.column_stack([xs, ys])

    # ==================== Utility Methods ====================

    def _smooth(self, points, iterations=2):
        """Cubic spline骞虫粦"""
        if len(points) < 4:
            return points
        for _ in range(iterations):
            xs = points[:, 0]
            ys = points[:, 1]
            t_orig = np.linspace(0, 1, len(xs))
            t_fine = np.linspace(0, 1, len(xs) * 2)
            try:
                cs_x = CubicSpline(t_orig, xs, bc_type='periodic')
                cs_y = CubicSpline(t_orig, ys, bc_type='periodic')
                new_xs = cs_x(t_fine)
                new_ys = cs_y(t_fine)
                points = np.column_stack([new_xs, new_ys])
            except Exception:
                break
        return points

    def _close_loop(self, points):
        """fixme"""
        if len(points) > 2:
            dist = np.linalg.norm(points[0] - points[-1])
            if dist > 5.0:
                n_bridge = max(3, int(dist / 5))
                bridge_x = np.linspace(points[-1, 0], points[0, 0], n_bridge + 2)[1:-1]
                bridge_y = np.linspace(points[-1, 1], points[0, 1], n_bridge + 2)[1:-1]
                bridge = np.column_stack([bridge_x, bridge_y])
                points = np.vstack([points, bridge])
        return points

    def _ensure_minimum_distance(self, points, min_dist=3.0):
        """fixme"""
        if len(points) < 3:
            return points
        kept = [0]
        for i in range(1, len(points)):
            if np.linalg.norm(points[i] - points[kept[-1]]) >= min_dist:
                kept.append(i)
        return points[kept]

    def _fix_large_gaps(self, points, max_gap=25.0):
        """Insert interpolation points for gaps larger than max_gap"""
        if len(points) < 3:
            return points
        fixed = [points[0]]
        for i in range(1, len(points)):
            gap = np.linalg.norm(points[i] - points[i - 1])
            if gap > max_gap:
                n_interp = int(gap / max_gap)
                for j in range(1, n_interp + 1):
                    alpha = j / (n_interp + 1)
                    interp_pt = points[i - 1] * (1 - alpha) + points[i] * alpha
                    fixed.append(interp_pt)
            fixed.append(points[i])
        return np.array(fixed)

    def _validate_and_fix(self, points):
        """fixme"""
        if len(points) < 10:
            n = 150
            angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
            points = np.column_stack([
                400 + 150 * np.cos(angles),
                300 + 100 * np.sin(angles)])
        return points

    def _compute_start_pos(self, points):
        """计算起始位置"""
        if len(points) < 2:
            self._start_pos = (400.0, 450.0, 0.0)
            return
        start = points[0]
        nxt = points[1]
        angle = math.degrees(math.atan2(nxt[1] - start[1], nxt[0] - start[0]))
        self._start_pos = (float(start[0]), float(start[1]), angle)

    def _compute_meta(self, points, level):
        """fixme"""
        self._last_meta = {
            'level': level,
            'level_name': self.LEVEL_CONFIG.get(level, {}).get('name', 'unknown'),
            'n_points': len(points),
            'path_length': self._path_length(points),
            'avg_curvature': self._avg_curvature(points),
            'self_intersections': self._count_self_intersections(points),
            'min_turn_radius': self._min_turn_radius(points),
        }

    def _path_length(self, points):
        total = 0.0
        for i in range(1, len(points)):
            total += np.linalg.norm(points[i] - points[i - 1])
        total += np.linalg.norm(points[-1] - points[0])
        return total

    def _avg_curvature(self, points):
        n = len(points)
        if n < 3:
            return 0.0
        curvatures = []
        for i in range(n):
            p0 = points[i - 1]
            p1 = points[i]
            p2 = points[(i + 1) % n]
            v1 = p1 - p0
            v2 = p2 - p1
            cross = v1[0] * v2[1] - v1[1] * v2[0]
            len1 = np.linalg.norm(v1)
            len2 = np.linalg.norm(v2)
            if len1 > 1e-6 and len2 > 1e-6:
                curvatures.append(abs(cross) / (len1 * len2))
        return np.mean(curvatures) if curvatures else 0.0

    def _min_turn_radius(self, points):
        n = len(points)
        if n < 3:
            return float('inf')
        min_r = float('inf')
        for i in range(n):
            p0 = points[i - 1]
            p1 = points[i]
            p2 = points[(i + 1) % n]
            a = np.linalg.norm(p1 - p0)
            b = np.linalg.norm(p2 - p1)
            c = np.linalg.norm(p2 - p0)
            s = (a + b + c) / 2.0
            area_sq = max(s * (s - a) * (s - b) * (s - c), 0)
            area = math.sqrt(area_sq)
            if area > 1e-6 and c > 1e-6:
                r = (a * b * c) / (4.0 * area)
                min_r = min(min_r, r)
        return min_r if min_r < float('inf') else 0.0

    def _count_self_intersections(self, points):
        n = len(points)
        if n < 10:
            return 0
        count = 0
        step = max(1, n // 100)
        for i in range(0, n - step, step):
            a1 = points[i]
            a2 = points[min(i + step, n - 1)]
            for j in range(i + step * 3, n - step, step):
                b1 = points[j]
                b2 = points[min(j + step, n - 1)]
                if self._segments_intersect(a1, a2, b1, b2):
                    count += 1
        return count

    @staticmethod
    def _segments_intersect(p1, p2, p3, p4):
        d1x, d1y = p2[0] - p1[0], p2[1] - p1[1]
        d2x, d2y = p4[0] - p3[0], p4[1] - p3[1]
        denom = d1x * d2y - d1y * d2x
        if abs(denom) < 1e-10:
            return False
        t = ((p3[0] - p1[0]) * d2y - (p3[1] - p1[1]) * d2x) / denom
        u = ((p3[0] - p1[0]) * d1y - (p3[1] - p1[1]) * d1x) / denom
        return 0.01 < t < 0.99 and 0.01 < u < 0.99

    def _max_segment_length(self, points):
        max_len = 0.0
        for i in range(1, len(points)):
            seg_len = np.linalg.norm(points[i] - points[i - 1])
            max_len = max(max_len, seg_len)
        return max_len

    def validate(self, points):
        """fixme"""
        issues = []
        metrics = {}
        if len(points) < 10:
            issues.append('too_few_points')
        else:
            max_gap = self._max_segment_length(points)
            metrics['max_gap'] = max_gap
            if max_gap > 30:
                issues.append('large_gap')
            close_dist = np.linalg.norm(points[0] - points[-1])
            metrics['closure_error'] = close_dist
            if close_dist > 5.0:
                issues.append('not_closed')
            n_cross = self._count_self_intersections(points)
            metrics['self_intersections'] = n_cross
            min_radius = self._min_turn_radius(points)
            metrics['min_turn_radius'] = min_radius
            path_len = self._path_length(points)
            metrics['path_length'] = path_len
            if path_len < 200:
                issues.append('track_too_short')
        return {'valid': len(issues) == 0, 'issues': issues, 'metrics': metrics}

    # ==================== Rendering ====================

    def render(self, points, title=None, save_path=None):
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
        except ImportError:
            print("[TrackGen] matplotlib not available, skipping render")
            return
        fig, ax = plt.subplots(1, 1, figsize=(10, 8))
        xs = points[:, 0]
        ys = points[:, 1]
        ax.plot(xs, ys, 'b-', linewidth=2, label='Track')
        sx, sy, sa = self._start_pos
        ax.plot(sx, sy, 'ro', markersize=10, label='Start')
        arrow_len = 20
        ax.annotate('',
                    xy=(sx + arrow_len * math.cos(math.radians(sa)),
                        sy + arrow_len * math.sin(math.radians(sa))),
                    xytext=(sx, sy),
                    arrowprops=dict(arrowstyle='->', color='red', lw=2))
        dist = self._path_length(points)
        curv = self._avg_curvature(points)
        meta = self._last_meta
        n_cross = meta.get('self_intersections', 0)
        info = 'pts={} len={:.0f} curv={:.3f}'.format(len(points), dist, curv)
        if n_cross > 0:
            info += ' cross={}'.format(n_cross)
        ax.set_aspect('equal')
        ax.set_title(title or 'Curriculum Track ({})'.format(info))
        ax.legend()
        ax.grid(True, alpha=0.3)
        if save_path:
            fig.savefig(save_path, dpi=100, bbox_inches='tight')
            print("[TrackGen] Saved:", save_path)
        else:
            fig.savefig('track_preview.png', dpi=100, bbox_inches='tight')
            print("[TrackGen] Saved: track_preview.png")
        plt.close(fig)

    def render_all_levels(self, save_dir=None):
        for level in range(1, 5):
            pts = self.get_track(level, seed=level * 1000)
            meta = self.get_track_meta()
            title = 'Level {}: {} (pts={}, len={:.0f})'.format(
                level, meta['level_name'], meta['n_points'], meta['path_length'])
            path = None
            if save_dir:
                import os
                os.makedirs(save_dir, exist_ok=True)
                path = os.path.join(save_dir, 'track_level{}.png'.format(level))
            self.render(pts, title=title, save_path=path)

    def render_unseen(self, save_dir=None, n_samples=3):
        for i in range(n_samples):
            pts = self.get_unseen_track(seed=9000 + i * 111)
            meta = self.get_track_meta()
            title = 'Unseen #{}: {} (pts={}, len={:.0f})'.format(
                i + 1, meta['level_name'], meta['n_points'], meta['path_length'])
            path = None
            if save_dir:
                import os
                os.makedirs(save_dir, exist_ok=True)
                path = os.path.join(save_dir, 'unseen_track_{}.png'.format(i + 1))
            self.render(pts, title=title, save_path=path)

    def render_comparison(self, seeds=None, save_path=None):
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
        except ImportError:
            return
        if seeds is None:
            seeds = [42, 123, 456, 789]
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        colors = ['blue', 'red', 'green', 'orange']
        for idx, seed in enumerate(seeds):
            ax = axes[idx // 2][idx % 2]
            level = (idx % 4) + 1
            pts = self.get_track(level, seed=seed)
            meta = self.get_track_meta()
            ax.plot(pts[:, 0], pts[:, 1], color=colors[idx], linewidth=1.5)
            ax.plot(pts[0, 0], pts[0, 1], 'ko', markersize=6)
            ax.set_aspect('equal')
            ax.set_title('L{} seed={} len={:.0f}'.format(
                level, seed, meta['path_length']))
            ax.grid(True, alpha=0.3)
        plt.suptitle('Curriculum Track Comparison v3', fontsize=14)
        plt.tight_layout()
        if save_path:
            fig.savefig(save_path, dpi=100, bbox_inches='tight')
            print("[TrackGen] Saved comparison:", save_path)
        else:
            fig.savefig('track_comparison.png', dpi=100, bbox_inches='tight')
            plt.close(fig)
