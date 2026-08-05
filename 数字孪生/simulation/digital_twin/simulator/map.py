# -*- coding: utf-8 -*-
"""
map.py - 赛道地图管理
定义赛道形状，提供点到线段的距离查询。
"""

import math
import config as cfg


class TrackMap:
    """
    赛道地图。
    
    内部用折线段集合表示赛道中心线。
    检测时判断点到最近线段的距离是否 < 检测半径。
    """

    def __init__(self):
        self.segments = []     # [(x1,y1, x2,y2), ...]
        self.track_width = cfg.TRACK_WIDTH

    def add_segment(self, x1, y1, x2, y2):
        """添加一条线段"""
        self.segments.append((x1, y1, x2, y2))

    def add_polyline(self, points, close=True):
        """
        用折线点集添加赛道。
        
        参数:
            points: [(x,y), ...] 折线顶点
            close:  是否闭合 (首尾相连)
        """
        n = len(points)
        for i in range(n - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            self.add_segment(x1, y1, x2, y2)
        if close and n > 2:
            x1, y1 = points[-1]
            x2, y2 = points[0]
            self.add_segment(x1, y1, x2, y2)

    @staticmethod
    def _point_to_segment_dist(px, py, x1, y1, x2, y2):
        """
        计算点到线段的最短距离。
        
        返回:
            (distance, closest_x, closest_y)
        """
        dx = x2 - x1
        dy = y2 - y1
        len_sq = dx * dx + dy * dy
        if len_sq < 1e-10:
            # 线段退化为点
            d = math.hypot(px - x1, py - y1)
            return d, x1, y1

        # 投影参数 t ∈ [0, 1]
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / len_sq))
        cx = x1 + t * dx
        cy = y1 + t * dy
        d = math.hypot(px - cx, py - cy)
        return d, cx, cy

    def is_point_on_track(self, px, py, radius=None):
        """
        判断点是否在赛道上。
        
        参数:
            px, py:  查询点坐标
            radius: 检测半径 (默认=传感器检测半径)
        
        返回:
            bool: True 表示在黑线上
        """
        if radius is None:
            radius = cfg.SENSOR_RADIUS

        threshold = radius + self.track_width / 2.0

        for seg in self.segments:
            d, _, _ = self._point_to_segment_dist(px, py, *seg)
            if d <= threshold:
                return True
        return False

    def get_distance_to_track(self, px, py):
        """
        返回点到最近赛道线段的距离。
        用于后续 PID 计算偏差。
        """
        min_dist = float('inf')
        for seg in self.segments:
            d, _, _ = self._point_to_segment_dist(px, py, *seg)
            if d < min_dist:
                min_dist = d
        return min_dist

    @staticmethod
    def generate_oval(cx, cy, rx, ry, num_points=200):
        """
        生成椭圆形赛道。
        
        参数:
            cx, cy: 椭圆中心
            rx, ry: 半轴长
            num_points: 采样点数
        
        返回:
            [(x,y), ...] 闭合折线点集
        """
        pts = []
        for i in range(num_points):
            angle = 2 * math.pi * i / num_points
            x = cx + rx * math.cos(angle)
            y = cy + ry * math.sin(angle)
            pts.append((x, y))
        return pts

    @staticmethod
    def generate_racetrack(cx, cy, straight_len, radius, num_arc=60):
        """
        生成跑道形赛道 (两段直道 + 两段半圆)。
        """
        pts = []
        # 右半圆 (上→下)
        for i in range(num_arc):
            a = -math.pi/2 + math.pi * i / num_arc
            x = cx + straight_len/2 + radius * math.cos(a)
            y = cy + radius * math.sin(a)
            pts.append((x, y))
        # 左半圆 (下→上)
        for i in range(num_arc):
            a = math.pi/2 + math.pi * i / num_arc
            x = cx - straight_len/2 + radius * math.cos(a)
            y = cy + radius * math.sin(a)
            pts.append((x, y))
        return pts
