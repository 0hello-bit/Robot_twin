# -*- coding: utf-8 -*-
"""
run_demo.py - STM32 移植代码独立验证

运行方式:
    cd digital_twin
    python examples/stm32_port/run_demo.py

功能:
    1. 启动仿真器
    2. 使用移植的 STM32 巡线代码作为控制器
    3. 验证: 移植代码能否正常驱动小车巡线
"""

import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pygame
import config as cfg
from simulator.car import MecanumCar
from simulator.sensor import SensorArray
from simulator.map import TrackMap
from simulator.renderer import Renderer
from simulator.timing import ControlTickTimer
from virtual_hw.device_bus import VirtualDeviceBus
from stm32_compat.hal_stubs import init as hal_init
from stm32_compat.bus_bridge import BusBridge
from examples.stm32_port.line_follow_stm32 import STM32LineFollowController
from control.state_machine import StateMachine, SimMode
from ui.debug_panel import DebugPanel
from ui.chart_panel import ChartPanel


class STM32DemoSimulator:
    """STM32 移植代码验证仿真器"""

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode(
            (cfg.SCREEN_WIDTH, cfg.SCREEN_HEIGHT))
        pygame.display.set_caption("STM32 移植验证 - 数字孪生仿真器")
        self.clock = pygame.time.Clock()
        self.running = True
        self.fps = cfg.FPS

        # ── 赛道 ──
        self.track = TrackMap()
        self.track_cx = (cfg.SCREEN_WIDTH - DebugPanel.PANEL_WIDTH) / 2
        self.track_cy = cfg.SCREEN_HEIGHT / 2
        oval_rx, oval_ry = 350, 220
        pts = TrackMap.generate_oval(self.track_cx, self.track_cy,
                                     oval_rx, oval_ry, 200)
        self.track.add_polyline(pts, close=True)

        # ── 小车 ──
        self.start_pos = (self.track_cx, self.track_cy + oval_ry, 0.0)
        self.car = MecanumCar(*self.start_pos)

        # ── 传感器 ──
        self.sensor_array = SensorArray()

        # ── 虚拟硬件层 ──
        self.bus = VirtualDeviceBus()
        hal_init(self.bus)

        # ── 桥接器 ──
        self.bridge = BusBridge(self.bus, self.car, self.sensor_array, self.track)

        # ── STM32 控制器 ──
        self.stm32_controller = STM32LineFollowController()
        self.stm32_controller.begin()

        # ── 状态机 ──
        self.state_machine = StateMachine()

        # ── 时序系统 ──
        self.timer = ControlTickTimer(50)

        # ── 渲染 ──
        self.renderer = Renderer(self.screen)
        self.debug_panel = DebugPanel(self.screen)
        chart_x = 10
        chart_y = cfg.SCREEN_HEIGHT - ChartPanel.PANEL_HEIGHT - 5
        chart_w = self.track_cx - 20
        self.chart_panel = ChartPanel(chart_x, chart_y, chart_w)

        # ── UI ──
        self.info_text = ""
        self.info_timer = 0.0
        self.show_charts = True

        print("=" * 55)
        print("  STM32 移植验证仿真器")
        print("  使用移植的 main.c 巡线逻辑")
        print("=" * 55)
        print("  SPACE = 暂停/恢复  R = 复位  ESC = 退出")
        print("  C = 曲线开关  T = 清轨迹")
        print("=" * 55)

    def run(self):
        while self.running:
            dt = self.clock.tick(cfg.FPS) / 1000.0
            self.fps = self.clock.get_fps()

            self._handle_events()

            if not self.state_machine.is_paused():
                ticks = self.timer.feed(dt)
                for _ in range(ticks):
                    self._control_tick(self.timer.get_control_dt())

            if cfg.SHOW_TRAIL:
                self.renderer.add_trail_point(self.car.x, self.car.y)

            self._render()

            if self.info_timer > 0:
                self.info_timer -= dt
                if self.info_timer <= 0:
                    self.info_text = ""

        pygame.quit()

    def _control_tick(self, dt):
        """单个控制周期: STM32 兼容模式"""
        # 1. 推送传感器到总线
        self.bridge.push_sensors()

        # 2. 运行 STM32 控制逻辑
        self.stm32_controller.run_one_tick()

        # 3. 获取差速指令并应用
        left, right = self.stm32_controller.get_motor_command()
        self.car.drive(left, right)
        self.car.update(dt)

        # 4. 图表
        if self.show_charts:
            diag = self.stm32_controller.get_diagnostic()
            self.chart_panel.push_data(
                diag['error'], 0.0, left, right)

    def _render(self):
        self.renderer.clear()
        self.renderer.draw_track(self.track)

        if cfg.SHOW_TRAIL:
            self.renderer.draw_trail()

        self.renderer.draw_car(self.car)
        self.renderer.draw_sensors(self.sensor_array)

        wrapper = self._make_controller_wrapper()
        self.debug_panel.draw(
            self.car, self.sensor_array, wrapper,
            "STM32", self.fps,
            timer=self.timer
        )

        if self.show_charts:
            self.chart_panel.draw(self.screen)

        self._draw_hud()
        pygame.display.flip()

    def _make_controller_wrapper(self):
        diag = self.stm32_controller.get_diagnostic()
        class Wrapper:
            pass
        w = Wrapper()
        w.position = diag['position']
        w.black_count = diag['black_count']
        w.pid_output = 0.0
        w.motor_cmd = diag['motor_output']
        class PIDWrapper:
            def get_gains(self):
                return (0.0, 0.0, 0.0)
            output = 0.0
        w.pid = PIDWrapper()
        w.set_pid_gains = lambda **kw: None
        return w

    def _draw_hud(self):
        font = pygame.font.SysFont("Consolas", 14)

        mode = "RUNNING" if not self.state_machine.is_paused() else "PAUSED"
        color = cfg.COLOR_GREEN if not self.state_machine.is_paused() else cfg.COLOR_YELLOW
        text = font.render("Mode: " + mode, True, color)
        self.screen.blit(text, (10, 10))

        ctrl_text = font.render(
            "Controller: STM32 Port (main.c)", True, cfg.COLOR_CYAN)
        self.screen.blit(ctrl_text, (10, 28))

        diag = self.stm32_controller.get_diagnostic()
        sr = diag['sensor_reading']
        for i, s in enumerate(sr):
            c = cfg.COLOR_SENSOR_ON if s == 0 else cfg.COLOR_SENSOR_OFF
            pygame.draw.circle(self.screen, c, (120 + i * 25, 17), 6)
            lbl = font.render("S%d" % i, True, cfg.COLOR_BLACK)
            self.screen.blit(lbl, (114 + i * 25, 26))

        if self.info_text:
            info_font = pygame.font.SysFont("Consolas", 20, bold=True)
            text = info_font.render(self.info_text, True, cfg.COLOR_WHITE)
            rect = text.get_rect(center=(self.track_cx, 50))
            bg = pygame.Surface((rect.width + 20, rect.height + 10))
            bg.fill((0, 0, 0))
            bg.set_alpha(180)
            self.screen.blit(bg, (rect.x - 10, rect.y - 5))
            self.screen.blit(text, rect)

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._on_key_down(event.key)

    def _on_key_down(self, key):
        if key == pygame.K_ESCAPE:
            self.running = False

        elif key == pygame.K_SPACE:
            self.state_machine.toggle_pause()
            if self.state_machine.is_paused():
                self.car.stop()
            self._show_info(
                "PAUSED" if self.state_machine.is_paused() else "RUNNING")

        elif key == pygame.K_r:
            self.car.reset(*self.start_pos)
            self.stm32_controller.reset()
            self.stm32_controller.begin()
            self.timer.reset()
            self.renderer.clear_trail()
            self.chart_panel.clear()
            self._show_info("Reset")

        elif key == pygame.K_t:
            self.renderer.clear_trail()
            self._show_info("Trail cleared")

        elif key == pygame.K_c:
            self.show_charts = not self.show_charts
            self._show_info("Charts: " + ("ON" if self.show_charts else "OFF"))

        elif key == pygame.K_1:
            self.timer.set_hz(10)
            self._show_info("Control Hz: 10")
        elif key == pygame.K_2:
            self.timer.set_hz(20)
            self._show_info("Control Hz: 20")
        elif key == pygame.K_3:
            self.timer.set_hz(50)
            self._show_info("Control Hz: 50")
        elif key == pygame.K_4:
            self.timer.set_hz(100)
            self._show_info("Control Hz: 100")

    def _show_info(self, text, duration=2.0):
        self.info_text = text
        self.info_timer = duration


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(os.path.join('..', '..'))
    sim = STM32DemoSimulator()
    sim.run()
