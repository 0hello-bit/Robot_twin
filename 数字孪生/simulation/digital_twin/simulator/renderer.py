# -*- coding: utf-8 -*-
"""
renderer.py - Pygame 渲染引擎
负责所有视觉元素的绘制: 赛道、小车、传感器、轨迹、HUD。
"""

import math
import pygame
import config as cfg


class Renderer:
    """Pygame 渲染器"""

    def __init__(self, screen):
        """
        参数:
            screen: pygame.display Surface
        """
        self.screen = screen
        self.trail_points = []  # 小车轨迹点

        # 字体
        pygame.font.init()
        self.font_small = pygame.font.SysFont("Consolas", 14)
        self.font_medium = pygame.font.SysFont("Consolas", 18)
        self.font_large = pygame.font.SysFont("Consolas", 24, bold=True)
        self.font_title = pygame.font.SysFont("Arial", 28, bold=True)

    def clear(self):
        """清屏"""
        self.screen.fill(cfg.BACKGROUND_COLOR)

    def draw_track(self, track_map):
        """绘制赛道"""
        for seg in track_map.segments:
            x1, y1, x2, y2 = seg
            # 浅色边缘 (先画)
            pygame.draw.line(self.screen, (80, 80, 80),
                             (int(x1), int(y1)), (int(x2), int(y2)),
                             cfg.TRACK_WIDTH + 4)
            # 黑线主体 (后画，叠在边缘上面)
            pygame.draw.line(self.screen, cfg.TRACK_COLOR,
                             (int(x1), int(y1)), (int(x2), int(y2)),
                             cfg.TRACK_WIDTH)
    def draw_car(self, car):
        """绘制小车"""
        rad = math.radians(car.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        hl = cfg.CAR_LENGTH / 2
        hw = cfg.CAR_WIDTH / 2

        # 车身四角 (车体坐标 → 世界坐标)
        corners_body = [
            (-hl, -hw), (-hl, hw), (hl, hw), (hl, -hw)
        ]
        world_corners = [
            (int(car.x + lx*cos_a - ly*sin_a),
             int(car.y + lx*sin_a + ly*cos_a))
            for lx, ly in corners_body
        ]

        # 底板 (深色)
        pygame.draw.polygon(self.screen, (30, 30, 40), world_corners)
        pygame.draw.polygon(self.screen, cfg.COLOR_CAR_OUTLINE, world_corners, 2)

        # 车头标记 (三角形)
        tip_x = car.x + hl * cos_a
        tip_y = car.y + hl * sin_a
        left_x  = car.x + (hl - 10) * cos_a - hw * 0.6 * sin_a
        left_y  = car.y + (hl - 10) * sin_a + hw * 0.6 * cos_a
        right_x = car.x + (hl - 10) * cos_a + hw * 0.6 * sin_a
        right_y = car.y + (hl - 10) * sin_a - hw * 0.6 * cos_a
        pygame.draw.polygon(self.screen, cfg.COLOR_CYAN,
            [(int(tip_x), int(tip_y)),
             (int(left_x), int(left_y)),
             (int(right_x), int(right_y))])

        # 四个轮子
        wheel_positions = car.get_wheel_positions()
        for wx, wy in wheel_positions:
            pygame.draw.circle(self.screen, cfg.COLOR_DARK_GRAY,
                               (int(wx), int(wy)), cfg.WHEEL_RADIUS)
            pygame.draw.circle(self.screen, (100, 100, 100),
                               (int(wx), int(wy)), cfg.WHEEL_RADIUS, 1)

        # 方向线 (从中心到车头)
        center_x = car.x
        center_y = car.y
        pygame.draw.line(self.screen, cfg.COLOR_YELLOW,
                         (int(center_x), int(center_y)),
                         (int(tip_x), int(tip_y)), 2)

    def draw_sensors(self, sensor_array):
        """绘制传感器状态"""
        positions = sensor_array.get_positions()
        for i, (px, py) in enumerate(positions):
            state = sensor_array.sensors[i].state
            color = cfg.COLOR_SENSOR_ON if state == 0 else cfg.COLOR_SENSOR_OFF
            # 传感器圆点
            pygame.draw.circle(self.screen, color, (int(px), int(py)), 5)
            pygame.draw.circle(self.screen, cfg.COLOR_BLACK, (int(px), int(py)), 5, 1)
            # 标号
            label = self.font_small.render(f"S{i}", True, cfg.COLOR_BLACK)
            self.screen.blit(label, (int(px) - 6, int(py) - 18))

    def draw_trail(self):
        """绘制运动轨迹"""
        if len(self.trail_points) < 2:
            return
        for i in range(1, len(self.trail_points)):
            alpha = i / len(self.trail_points)
            r = int(cfg.COLOR_TRAIL[0] * alpha)
            g = int(cfg.COLOR_TRAIL[1] * alpha)
            b = int(cfg.COLOR_TRAIL[2] * alpha)
            color = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
            p1 = self.trail_points[i - 1]
            p2 = self.trail_points[i]
            pygame.draw.line(self.screen, color,
                             (int(p1[0]), int(p1[1])),
                             (int(p2[0]), int(p2[1])), 2)

    def add_trail_point(self, x, y):
        """添加轨迹点"""
        self.trail_points.append((x, y))
        if len(self.trail_points) > cfg.TRAIL_MAX_POINTS:
            self.trail_points.pop(0)

    def clear_trail(self):
        """清除轨迹"""
        self.trail_points.clear()
