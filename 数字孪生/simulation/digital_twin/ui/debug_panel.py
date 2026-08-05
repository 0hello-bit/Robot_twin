# -*- coding: utf-8 -*-
"""
debug_panel.py - 调试信息面板 (v3)
新增: HIL 蓝牙连接状态显示
"""

import pygame
import config as cfg


class DebugPanel:
    """右侧调试面板"""

    PANEL_WIDTH = 320

    def __init__(self, screen):
        self.screen = screen
        self.panel_x = cfg.SCREEN_WIDTH - self.PANEL_WIDTH

        pygame.font.init()
        self.font = pygame.font.SysFont("Consolas", 13)
        self.font_bold = pygame.font.SysFont("Consolas", 15, bold=True)
        self.font_title = pygame.font.SysFont("Arial", 18, bold=True)
        self.font_small = pygame.font.SysFont("Consolas", 11)

    def draw(self, car, sensor_array, controller, mode_name, fps,
             timer=None, noise=None, recording=False,
             serial_bridge=None, real_data=None):
        """绘制完整的调试面板"""
        x0 = self.panel_x
        pw = self.PANEL_WIDTH

        bg = pygame.Surface((pw, cfg.SCREEN_HEIGHT))
        bg.fill(cfg.COLOR_HUD_BG)
        bg.set_alpha(230)
        self.screen.blit(bg, (x0, 0))

        y = 8

        # 标题
        self._text("STM32 Digital Twin v3", self.font_title,
                   cfg.COLOR_CYAN, x0 + 10, y); y += 26

        # 录制指示
        if recording:
            pygame.draw.circle(self.screen, cfg.COLOR_RED, (x0 + pw - 20, y - 8), 6)
            self._text("REC", self.font_bold, cfg.COLOR_RED, x0 + pw - 50, y - 16)

        pygame.draw.line(self.screen, cfg.COLOR_GRAY,
                         (x0 + 10, y), (x0 + pw - 10, y), 1); y += 8

        # 模式 + FPS
        mc = cfg.COLOR_YELLOW if mode_name == "AUTO" else cfg.COLOR_GREEN
        if mode_name == "HIL":
            mc = cfg.COLOR_CYAN
        self._text(f"Mode: {mode_name}", self.font_bold, mc, x0 + 10, y); y += 20

        fps_color = cfg.COLOR_GREEN if fps > 45 else cfg.COLOR_YELLOW if fps > 30 else cfg.COLOR_RED
        self._text(f"FPS: {fps:.0f}", self.font, fps_color, x0 + 10, y)

        # 控制周期
        if timer:
            ctrl_color = cfg.COLOR_GREEN if timer.actual_hz >= timer.control_hz * 0.9 else cfg.COLOR_RED
            self._text(f"Ctrl: {timer.actual_hz:.0f}/{timer.control_hz:.0f}Hz",
                       self.font, ctrl_color, x0 + 140, y)
            self._text(f"#{timer.get_tick_count()}", self.font, cfg.COLOR_GRAY, x0 + 270, y)
        y += 22

        # ── HIL 蓝牙连接状态 (新增) ──
        if mode_name == "HIL":
            self._draw_hil_status(x0, y, serial_bridge, real_data)
            y += 80

        pygame.draw.line(self.screen, cfg.COLOR_GRAY,
                         (x0 + 10, y), (x0 + pw - 10, y), 1); y += 6

        # ── 小车状态 ──
        self._text("CAR", self.font_bold, cfg.COLOR_CYAN, x0 + 10, y); y += 18
        speed = (car.vx**2 + car.vy**2)**0.5
        self._text(f"({car.x:.0f},{car.y:.0f}) A={car.angle:.0f} V={speed:.0f}",
                   self.font, cfg.COLOR_HUD_TEXT, x0 + 10, y); y += 18

        # ── 传感器 ──
        self._text("SENSORS", self.font_bold, cfg.COLOR_CYAN, x0 + 10, y); y += 18

        # HIL 模式下显示真实传感器数据
        if mode_name == "HIL" and real_data:
            states = real_data.sensors
            src = "(REAL)"
        else:
            states = sensor_array.get_raw()
            src = ""

        for i, s in enumerate(states):
            color = cfg.COLOR_SENSOR_ON if s == 0 else cfg.COLOR_SENSOR_OFF
            pygame.draw.circle(self.screen, color, (x0 + 18, y + 6), 5)
            lbl = f"S{i}={'BLK' if s==0 else 'wht'}"
            self._text(lbl, self.font, cfg.COLOR_HUD_TEXT, x0 + 28, y)
            y += 16

        if src:
            self._text(src, self.font_small, cfg.COLOR_CYAN, x0 + 10, y); y += 14

        self._text(f"Pos={controller.position:.1f} Bcnt={controller.black_count}",
                   self.font, cfg.COLOR_HUD_TEXT, x0 + 10, y); y += 20

        # ── PID ──
        self._text("PID", self.font_bold, cfg.COLOR_CYAN, x0 + 10, y); y += 18
        if hasattr(controller, 'pid') and controller.pid is not None:
            kp, ki, kd = controller.pid.get_gains()
            self._text(f"Kp:{kp:.3f}", self.font, cfg.COLOR_YELLOW, x0 + 10, y)
            self._slider(x0 + 80, y + 2, 190, kp / 2.0, cfg.COLOR_YELLOW)
            y += 17
            self._text(f"Ki:{ki:.3f}", self.font, cfg.COLOR_GREEN, x0 + 10, y)
            self._slider(x0 + 80, y + 2, 190, ki / 1.0, cfg.COLOR_GREEN)
            y += 17
            self._text(f"Kd:{kd:.3f}", self.font, cfg.COLOR_ORANGE, x0 + 10, y)
            self._slider(x0 + 80, y + 2, 190, kd / 1.0, cfg.COLOR_ORANGE)
            y += 17
            pid_out = getattr(controller, 'pid_output', 0)
            pos = getattr(controller, 'position', 0)
            self._text(f"Out:{pid_out:+.3f}  Err:{pos:+.1f}",
                       self.font, cfg.COLOR_HUD_TEXT, x0 + 10, y); y += 20
        else:
            self._text("STM32 Faithful Mode", self.font, cfg.COLOR_HUD_TEXT, x0 + 10, y)
            y += 20

        # ── 电机 ──
        self._text("MOTORS", self.font_bold, cfg.COLOR_CYAN, x0 + 10, y); y += 18

        if mode_name == "HIL" and real_data:
            # HIL 模式显示真实 PWM
            lp = real_data.left_pwm
            rp = real_data.right_pwm
            self._text(f"L:{lp:+4d}", self.font, cfg.COLOR_HUD_TEXT, x0 + 10, y)
            self._motor_bar(x0 + 70, y + 2, 190, lp / 999.0, cfg.COLOR_GREEN)
            y += 17
            self._text(f"R:{rp:+4d}", self.font, cfg.COLOR_HUD_TEXT, x0 + 10, y)
            self._motor_bar(x0 + 70, y + 2, 190, rp / 999.0, cfg.COLOR_BLUE)
            y += 17
            # PID 输出
            if real_data.pid_output:
                self._text(f"PID:{real_data.pid_output:+d}",
                           self.font_small, cfg.COLOR_YELLOW, x0 + 10, y)
                y += 14
        else:
            left, right = controller.motor_cmd
            self._text(f"L:{left:+.2f}", self.font, cfg.COLOR_HUD_TEXT, x0 + 10, y)
            self._motor_bar(x0 + 70, y + 2, 190, left, cfg.COLOR_GREEN)
            y += 17
            self._text(f"R:{right:+.2f}", self.font, cfg.COLOR_HUD_TEXT, x0 + 10, y)
            self._motor_bar(x0 + 70, y + 2, 190, right, cfg.COLOR_BLUE)
            y += 17
        y += 5

        # ── 噪声状态 ──
        if noise:
            self._text("NOISE", self.font_bold, cfg.COLOR_CYAN, x0 + 10, y); y += 18
            status = noise.get_status()
            for name, enabled in status.items():
                color = cfg.COLOR_GREEN if enabled else cfg.COLOR_GRAY
                mark = "[ON]" if enabled else "[--]"
                short = name.replace('_', ' ')[:18]
                self._text(f"{mark} {short}", self.font_small, color, x0 + 10, y)
                y += 14
            y += 6

        # ── 帮助 ──
        pygame.draw.line(self.screen, cfg.COLOR_GRAY,
                         (x0 + 10, y), (x0 + pw - 10, y), 1); y += 6
        helps = [
            "SPACE=Mode  R=Reset  T=Trail",
            "N=Toggle noise  C=Charts",
            "1/2/3/4=Ctrl Hz (10/20/50/100)",
            "F5=Record  F6=Score  F7=Compare",
            "Mouse drag=PID sliders  ESC=Quit",
        ]
        for h in helps:
            self._text(h, self.font_small, cfg.COLOR_GRAY, x0 + 10, y)
            y += 13

    def _draw_hil_status(self, x0, y, serial_bridge, real_data):
        """绘制 HIL 蓝牙连接状态"""
        # 标题
        self._text("HIL BLUETOOTH", self.font_bold, cfg.COLOR_CYAN, x0 + 10, y)
        y += 20

        if serial_bridge and serial_bridge.is_connected():
            # 已连接
            stats = serial_bridge.get_stats()
            conn_type = "BT" if stats.get('bluetooth') else "USB"
            port = stats.get('port', '?')
            baud = stats.get('baudrate', '?')
            hz = stats.get('actual_hz', 0)
            frames = stats.get('frame_count', 0)
            errors = stats.get('error_count', 0)

            # 连接状态灯
            pygame.draw.circle(self.screen, cfg.COLOR_GREEN, (x0 + 18, y + 6), 6)
            self._text(f"CONNECTED ({conn_type})", self.font,
                       cfg.COLOR_GREEN, x0 + 28, y)
            y += 16

            self._text(f"{port} @{baud} baud",
                       self.font_small, cfg.COLOR_HUD_TEXT, x0 + 10, y)
            y += 14

            hz_color = cfg.COLOR_GREEN if hz > 10 else cfg.COLOR_YELLOW
            self._text(f"RX: {hz:.0f}Hz  #{frames}  err:{errors}",
                       self.font_small, hz_color, x0 + 10, y)
            y += 14

            if real_data:
                tick = getattr(real_data, 'tick_ms', 0)
                self._text(f"MCU tick: {tick}",
                           self.font_small, cfg.COLOR_HUD_TEXT, x0 + 10, y)
                y += 14
        else:
            # 未连接
            pygame.draw.circle(self.screen, cfg.COLOR_GRAY, (x0 + 18, y + 6), 6)
            self._text("DISCONNECTED", self.font, cfg.COLOR_GRAY, x0 + 28, y)
            y += 16

            self._text("按 H 连接蓝牙串口",
                       self.font_small, cfg.COLOR_GRAY, x0 + 10, y)
            y += 14

    def handle_click(self, mx, my, controller):
        if mx < self.panel_x:
            return False
        if not hasattr(controller, 'pid') or controller.pid is None:
            return False
        kp, ki, kd = controller.pid.get_gains()
        slider_x = self.panel_x + 80
        slider_w = 190
        if slider_x <= mx <= slider_x + slider_w:
            ratio = (mx - slider_x) / slider_w
            base_y = 185
            if abs(my - base_y) < 10:
                controller.set_pid_gains(kp=ratio * 2.0); return True
            elif abs(my - base_y - 17) < 10:
                controller.set_pid_gains(ki=ratio * 1.0); return True
            elif abs(my - base_y - 34) < 10:
                controller.set_pid_gains(kd=ratio * 1.0); return True
        return False

    def _text(self, text, font, color, x, y):
        self.screen.blit(font.render(text, True, color), (x, y))

    def _slider(self, x, y, width, ratio, color):
        ratio = max(0, min(1, ratio))
        pygame.draw.rect(self.screen, (50, 50, 60), (x, y, width, 5))
        pygame.draw.rect(self.screen, color, (x, y, int(width * ratio), 5))
        pygame.draw.circle(self.screen, cfg.COLOR_WHITE, (x + int(width * ratio), y + 2), 4)

    def _motor_bar(self, x, y, width, value, color):
        half = width // 2
        pygame.draw.rect(self.screen, (50, 50, 60), (x, y, width, 7))
        pygame.draw.line(self.screen, cfg.COLOR_GRAY, (x + half, y), (x + half, y + 7))
        bar_w = int(abs(value) * half)
        if value >= 0:
            pygame.draw.rect(self.screen, color, (x + half, y, bar_w, 7))
        else:
            pygame.draw.rect(self.screen, color, (x + half - bar_w, y, bar_w, 7))

