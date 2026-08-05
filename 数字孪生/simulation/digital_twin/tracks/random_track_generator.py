# -*- coding: utf-8 -*-
"""
random_track_generator.py - 随机赛道生成器

支持多种赛道类型, 避免 RL 过拟合。
"""

import math
import random


class TrackGenerator:
    """
    赛道生成器。

    支持: oval, figure8, s_curve, cross, random_combo

    使用:
        gen = TrackGenerator(seed=42)
        points = gen.generate('oval')
        track.add_polyline(points)
    """

    def __init__(self, seed=None):
        self._rng = random.Random(seed)

    def generate(self, track_type, **kwargs):
        """
        生成赛道点集。

        返回:
            list of (x, y)
        """
        generators = {
            'oval': self._oval,
            'figure8': self._figure8,
            's_curve': self._s_curve,
            'cross': self._cross,
            'random_oval': self._random_oval,
            'random_combo': self._random_combo,
        }
        gen_fn = generators.get(track_type, self._oval)
        return gen_fn(**kwargs)

    def _oval(self, cx=400, cy=300, rx=200, ry=150, n=200):
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        return pts

    def _figure8(self, cx=400, cy=300, r=120, n=160):
        """8 字赛道"""
        pts = []
        half = n // 2
        for i in range(half):
            a = 2 * math.pi * i / half
            pts.append((cx - r + r * math.cos(a), cy + r * math.sin(a)))
        for i in range(half):
            a = 2 * math.pi * i / half
            pts.append((cx + r + r * math.cos(a + math.pi), cy + r * math.sin(a + math.pi)))
        return pts

    def _s_curve(self, cx=400, cy=300, length=500, amplitude=100, n=120):
        """S 弯赛道"""
        pts = []
        for i in range(n):
            t = i / (n - 1)
            x = cx - length / 2 + length * t
            y = cy + amplitude * math.sin(2 * math.pi * t)
            pts.append((x, y))
        return pts

    def _cross(self, cx=400, cy=300, size=200, n_per_arm=30):
        """十字赛道"""
        pts = []
        half = size / 2
        # 上臂
        for i in range(n_per_arm):
            pts.append((cx, cy - half + size * i / n_per_arm))
        # 右臂
        for i in range(n_per_arm):
            pts.append((cx - half + size * i / n_per_arm, cy))
        # 下臂 (反向)
        for i in range(n_per_arm):
            pts.append((cx, cy + half - size * i / n_per_arm))
        # 左臂 (反向)
        for i in range(n_per_arm):
            pts.append((cx + half - size * i / n_per_arm, cy))
        return pts

    def _random_oval(self):
        """随机参数椭圆"""
        cx = self._rng.uniform(300, 500)
        cy = self._rng.uniform(200, 400)
        rx = self._rng.uniform(100, 250)
        ry = self._rng.uniform(60, 150)
        return self._oval(cx, cy, rx, ry)

    def _random_combo(self):
        """随机组合赛道"""
        types = ['oval', 'figure8', 's_curve']
        t = self._rng.choice(types)
        return self.generate(t)

    @staticmethod
    def get_track_types():
        return ['oval', 'figure8', 's_curve', 'cross', 'random_oval', 'random_combo']