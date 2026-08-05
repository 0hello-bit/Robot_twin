# -*- coding: utf-8 -*-
"""
chart_panel.py - 实时曲线图面板
显示误差曲线、PID输出、左右轮PWM等时序数据。
"""

import pygame
import config as cfg


class RollingChart:
    """
    滚动折线图组件。
    在指定矩形区域内绘制实时滚动的时序数据。
    """

    def __init__(self, x, y, width, height, label="", color=(200,200,200),
                 y_min=-5.0, y_max=5.0):
        self.rect = pygame.Rect(x, y, width, height)
        self.label = label
        self.color = color
        self.y_min = y_min
        self.y_max = y_max
        self.data = []
        self.max_points = width  # 每像素一个点

        pygame.font.init()
        self.font = pygame.font.SysFont("Consolas", 11)

    def push(self, value):
        """添加一个数据点"""
        self.data.append(value)
        if len(self.data) > self.max_points:
            self.data.pop(0)

    def clear(self):
        self.data.clear()

    def set_range(self, y_min, y_max):
        self.y_min = y_min
        self.y_max = y_max

    def draw(self, surface):
        """绘制图表"""
        rx, ry, rw, rh = self.rect

        # 背景
        bg = pygame.Surface((rw, rh))
        bg.fill((15, 20, 30))
        bg.set_alpha(200)
        surface.blit(bg, (rx, ry))

        # 边框
        pygame.draw.rect(surface, (60, 60, 70), (rx, ry, rw, rh), 1)

        # 标签
        lbl = self.font.render(self.label, True, self.color)
        surface.blit(lbl, (rx + 4, ry + 2))

        # 零线
        if self.y_min < 0 < self.y_max:
            zero_y = ry + rh - int((-self.y_min) / (self.y_max - self.y_min) * rh)
            pygame.draw.line(surface, (50, 50, 60), (rx, zero_y), (rx + rw, zero_y))

        # Y 轴标签
        y_top = self.font.render(f"{self.y_max:.1f}", True, (100, 100, 110))
        y_bot = self.font.render(f"{self.y_min:.1f}", True, (100, 100, 110))
        surface.blit(y_top, (rx + rw - 30, ry + 2))
        surface.blit(y_bot, (rx + rw - 30, ry + rh - 14))

        if len(self.data) < 2:
            return

        # 绘制折线
        points = []
        data_range = self.y_max - self.y_min
        if data_range <= 0:
            data_range = 1.0

        for i, val in enumerate(self.data):
            px = rx + int(i * rw / self.max_points)
            normalized = (val - self.y_min) / data_range
            py = ry + rh - int(normalized * rh)
            py = max(ry + 1, min(ry + rh - 1, py))
            points.append((px, py))

        if len(points) >= 2:
            pygame.draw.lines(surface, self.color, False, points, 1)

        # 当前值
        if self.data:
            current = self.data[-1]
            val_text = self.font.render(f"{current:+.2f}", True, self.color)
            surface.blit(val_text, (rx + 4, ry + rh - 14))


class ChartPanel:
    """
    实时曲线图面板。
    包含多个 RollingChart 实例。
    """

    PANEL_HEIGHT = 220

    def __init__(self, x, y, width):
        chart_h = 45
        gap = 5
        colors = {
            'error': (220, 80, 80),
            'pid_out': (80, 180, 220),
            'left_pwm': (80, 200, 120),
            'right_pwm': (200, 160, 60),
        }

        self.charts = {
            'error': RollingChart(x, y, width, chart_h,
                                  "Error (position)", colors['error'], -6, 6),
            'pid_out': RollingChart(x, y + chart_h + gap, width, chart_h,
                                    "PID Output", colors['pid_out'], -1.2, 1.2),
            'left_pwm': RollingChart(x, y + 2*(chart_h + gap), width, chart_h,
                                     "Left PWM", colors['left_pwm'], -1.2, 1.2),
            'right_pwm': RollingChart(x, y + 3*(chart_h + gap), width, chart_h,
                                      "Right PWM", colors['right_pwm'], -1.2, 1.2),
        }

    def push_data(self, error, pid_output, left_speed, right_speed):
        """推入一个控制周期的数据"""
        self.charts['error'].push(error)
        self.charts['pid_out'].push(pid_output)
        self.charts['left_pwm'].push(left_speed)
        self.charts['right_pwm'].push(right_speed)

    def clear(self):
        for chart in self.charts.values():
            chart.clear()

    def draw(self, surface):
        for chart in self.charts.values():
            chart.draw(surface)
