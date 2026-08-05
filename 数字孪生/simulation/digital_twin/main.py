# -*- coding: utf-8 -*-
"""
main.py - STM32 数字孪生仿真器主入口 (v6)
支持: ESP01S WiFi HIL 实时遥测模式
"""

import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame

import config as cfg
from simulator.car import MecanumCar
from simulator.sensor import SensorArray
from simulator.map import TrackMap
from simulator.renderer import Renderer
from simulator.timing import ControlTickTimer
from simulator.noise_model import WorldNoiseModel
from control.base_controller import LineFollowController, ControllerOutput
from control.state_machine import StateMachine, SimMode
from control.stm32_faithful_controller import STM32FaithfulController
from analysis.logger import ExperimentLogger, ControlSnapshot, ExperimentComparison
from ui.debug_panel import DebugPanel
from ui.chart_panel import ChartPanel
from virtual_hw.device_bus import VirtualDeviceBus
from stm32_compat.hal_stubs import init as hal_init
from stm32_compat.bus_bridge import BusBridge
from examples.stm32_port.line_follow_stm32 import STM32LineFollowController
from real_world.wifi_bridge import WifiBridge
from real_world.data_logger import RealDataLogger
from replay.replay_engine import ReplayEngine
from replay.replay_compare import ReplayComparison
from tracks.real_world_mapper import load_track, map_real_track


class DigitalTwinSimulator:
    """数字孪生仿真器主类 (v6)"""

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode(
            (cfg.SCREEN_WIDTH, cfg.SCREEN_HEIGHT))
        pygame.display.set_caption(cfg.WINDOW_TITLE)
        self.clock = pygame.time.Clock()
        self.running = True
        self.fps = cfg.FPS

        # -- 赛道 --
        self.track = TrackMap()
        self.track_cx = (cfg.SCREEN_WIDTH - DebugPanel.PANEL_WIDTH) / 2
        self.track_cy = cfg.SCREEN_HEIGHT / 2
        oval_rx, oval_ry = 350, 220
        pts = TrackMap.generate_oval(self.track_cx, self.track_cy,
                                     oval_rx, oval_ry, 200)
        self.track.add_polyline(pts, close=True)

        # -- 小车 --
        self.start_pos = (self.track_cx, self.track_cy + oval_ry, 0.0)
        self.car = MecanumCar(*self.start_pos)

        # ── 传感器 ──
        self.sensor_array = SensorArray()

        # ── STM32 忠实移植控制器 ──
        self.controller = STM32FaithfulController()
        self.controller_output = ControllerOutput()

        # ── STM32 兼容控制器 ──
        self.bus = VirtualDeviceBus()
        hal_init(self.bus)
        self.bridge = BusBridge(self.bus, self.car, self.sensor_array, self.track)
        self.stm32_controller = STM32LineFollowController()
        self.stm32_controller.begin()

        self.state_machine = StateMachine()
        self.state_machine.switch_to(SimMode.LINE_FOLLOW)

        # ── 时序系统 ──
        self.timer = ControlTickTimer(cfg.DEFAULT_CONTROL_HZ)

        # ── 噪声模型 ──
        self.noise = WorldNoiseModel()
        self.noise.sensor_noise.enabled = cfg.NOISE_SENSOR_ENABLED
        self.noise.control_delay.enabled = cfg.NOISE_CONTROL_DELAY_ENABLED
        self.noise.control_delay.set_delay(cfg.NOISE_CONTROL_DELAY_STEPS)
        self.noise.motor_response.enabled = cfg.NOISE_MOTOR_RESPONSE_ENABLED
        self.noise.motor_response.tau = cfg.NOISE_MOTOR_RESPONSE_TAU
        self.noise.velocity_perturbation.enabled = cfg.NOISE_VELOCITY_PERTURB_ENABLED
        self.noise.velocity_perturbation.amplitude = cfg.NOISE_VELOCITY_PERTURB_AMP

        # ── 实验记录 ──
        self.logger = ExperimentLogger()
        self.comparison = ExperimentComparison()

        # ── 真实世界数据采集 (ESP01S WiFi) ──
        self.wifi_bridge = WifiBridge()
        self.real_data_logger = RealDataLogger()
        self.real_telemetry = None  # 最新真实遥测数据

        # ── 回放系统 ──
        self.replay_engine = ReplayEngine()

        # ── 渲染 ──
        self.renderer = Renderer(self.screen)
        self.debug_panel = DebugPanel(self.screen)
        chart_x = 10
        chart_y = cfg.SCREEN_HEIGHT - ChartPanel.PANEL_HEIGHT - 5
        chart_w = self.track_cx - 20
        self.chart_panel = ChartPanel(chart_x, chart_y, chart_w)

        # ── 手动模式 ──
        self.manual_speed = 0.3

        # -- 画线模式 --
        self.drawing_mode = False
        self.drawing_points = []

        # -- 赛道录制 / 绘制 --
        self.record_trail = []      # 录制中: 实时实际轨迹
        self.record_raw = []        # 录制中: 原始遥测(供精确重建/标定)
        self.record_x = 0.0
        self.record_y = 0.0
        self.record_angle = 0.0
        self.record_active = False
        self.actual_trail = []      # 停止后保留: 实际小车轨迹(橙虚线)
        self.reference_line = []    # 重建并可修正的参考赛道线(实线)
        self.edit_mode = False      # 参考线拖点编辑模式
        self.edit_points = []       # 可拖动的控制点
        self.drag_idx = -1

        # ── UI 状态 ──
        self.show_charts = True
        self.info_text = ""
        self.info_timer = 0.0

        print("=" * 55)
        print("  STM32 数字孪生仿真器 v6")
        print("  SPACE=模式  R=复位  T=轨迹  N=噪声")
        print("  C=曲线  F5=录制  F6=评分  F7=对比")
        print("  1-4=控制Hz  ESC=退出")
        print("  模式: PID / STM32 / HIL / Replay / 手动 / 暂停")
        print("  HIL: Y=连接WiFi  U=断开  K=录制")
        print("  D=画线  M=录制赛道  5-8=预设赛道  F8=真实赛道  L=回放")
        print("=" * 55)

    def run(self):
        """主循环"""
        while self.running:
            self._handle_events()
            self._update()
            self._render()
            self.clock.tick(self.fps)
        pygame.quit()

    # ── 事件处理 ──

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._on_key_down(event.key)
            elif event.type == pygame.KEYUP:
                self._on_key_up(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._on_mouse_down(event.pos, event.button)
            elif event.type == pygame.MOUSEBUTTONUP:
                self._on_mouse_up(event.pos)
            elif event.type == pygame.MOUSEMOTION:
                self._on_mouse_motion(event.pos)

    def _on_key_down(self, key):
        if key == pygame.K_ESCAPE:
            self.running = False
        elif key == pygame.K_SPACE:
            self.state_machine.cycle_mode()
            self._show_info("Mode: " + self.state_machine.mode.name)
            self._reset_for_mode()
        elif key == pygame.K_r:
            self.car.reset(*self.start_pos)
            self.controller.reset()
            self.stm32_controller.reset()
            self.stm32_controller.begin()
            self.bridge.stop_all()
            self.noise.reset_all()
            self.timer.reset()
            self.renderer.clear_trail()
            self._show_info("Reset")
        elif key == pygame.K_t:
            cfg.SHOW_TRAIL = not cfg.SHOW_TRAIL
            if not cfg.SHOW_TRAIL:
                self.renderer.clear_trail()
        elif key == pygame.K_n:
            self._toggle_all_noise()
        elif key == pygame.K_c:
            self.show_charts = not self.show_charts
        elif key == pygame.K_1:
            self.timer.set_control_hz(10)
            self._show_info("Control: 10 Hz")
        elif key == pygame.K_2:
            self.timer.set_control_hz(20)
            self._show_info("Control: 20 Hz")
        elif key == pygame.K_3:
            self.timer.set_control_hz(50)
            self._show_info("Control: 50 Hz")
        elif key == pygame.K_4:
            self.timer.set_control_hz(100)
            self._show_info("Control: 100 Hz")
        elif key == pygame.K_F5:
            self._toggle_recording()
        elif key == pygame.K_F6:
            self._compute_score()
        elif key == pygame.K_F7:
            self._run_comparison()
        elif key == pygame.K_k:
            self._hil_toggle_record()
        elif key == pygame.K_y:
            self._wifi_connect()
        elif key == pygame.K_u:
            self._wifi_disconnect()
        elif key == pygame.K_m:
            self._toggle_track_record()
        elif key == pygame.K_d:
            if not self.state_machine.is_manual():
                self._toggle_draw_mode()
        elif key == pygame.K_5:
            self._load_preset_track(1)
            self._show_info("Track: Oval")
        elif key == pygame.K_6:
            self._load_preset_track(2)
            self._show_info("Track: Sine Wave")
        elif key == pygame.K_7:
            self._load_preset_track(3)
            self._show_info("Track: Figure-8")
        elif key == pygame.K_8:
            self._load_preset_track(4)
            self._show_info("Track: Rounded Rect")
        elif key == pygame.K_F8:
            self._load_real_track()
        elif key == pygame.K_l:
            self._replay_load()

    def _on_key_up(self, key):
        if self.state_machine.is_manual():
            self._manual_key(key, up=True)

    def _manual_key(self, key, up=False):
        spd = self.manual_speed
        if key == pygame.K_w:
            self.car.drive(spd, spd) if not up else self.car.stop()
        elif key == pygame.K_s:
            self.car.drive(-spd, -spd) if not up else self.car.stop()
        elif key == pygame.K_a:
            self.car.drive(-spd, spd) if not up else self.car.stop()
        elif key == pygame.K_m:
            self._toggle_track_record()
        elif key == pygame.K_d:
            self.car.drive(spd, -spd) if not up else self.car.stop()

    def _on_mouse_down(self, pos, button=1):
        mx, my = pos
        if self.edit_mode and button == 1 and self.edit_points and mx < self.debug_panel.panel_x:
            # 选中最近的控制点开始拖动 (半径 18px 内)
            best, bd = -1, 18 ** 2
            for i, (px, py) in enumerate(self.edit_points):
                d = (px - mx) ** 2 + (py - my) ** 2
                if d < bd:
                    bd, best = d, i
            self.drag_idx = best
            return
        if self.drawing_mode and mx < self.debug_panel.panel_x:
            if button == 1:
                self.drawing_points.append([mx, my])
                self._show_info("Point %d: (%d, %d)" % (len(self.drawing_points), mx, my))
            elif button == 3 and self.drawing_points:
                self.drawing_points.pop()
                self._show_info("Undo, %d points left" % len(self.drawing_points))
        else:
            self.debug_panel.handle_click(mx, my, self.controller)

    def _on_mouse_up(self, pos):
        if self.edit_mode and self.drag_idx >= 0:
            self._apply_edit_points()
            self.drag_idx = -1

    def _on_mouse_motion(self, pos):
        if self.edit_mode and self.drag_idx >= 0:
            self.edit_points[self.drag_idx] = [float(pos[0]), float(pos[1])]

    # ── HIL ──

    def _hil_disconnect(self):
        self._wifi_disconnect()

    def _hil_toggle_record(self):
        if self.real_data_logger.recording:
            stats = self.real_data_logger.stop()
            self._show_info("Real data recording STOPPED: %s" % str(stats))
        else:
            self.real_data_logger.start()
            self._show_info("Real data recording STARTED")

    # ── 更新 ──


    # ---- WiFi HIL 连接 ----

    def _wifi_connect(self, host=None, port=None):
        if self.wifi_bridge.is_connected():
            self._show_info("WiFi already connected")
            return
        if port is None:
            port = cfg.WIFI_TCP_PORT

        if host is None:
            host = self._wifi_auto_scan(port)

        if host is None:
            self._show_info("WiFi scan: no ESP01S found")
            return

        self.wifi_bridge.connect(host, port)
        self.wifi_bridge.start()
        self.state_machine.switch_to(SimMode.REALTIME_HIL)
        self._show_info("WiFi connecting: %s:%d" % (host, port))

    def _wifi_auto_scan(self, port=8888, timeout=0.5):
        import socket
        import struct
        # Get local IP to determine subnet
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            self._show_info("WiFi scan: cannot detect local IP")
            return None

        subnet = ".".join(local_ip.split(".")[:3]) + "."
        print("[WiFi] Scanning subnet %s0/24 for port %d..." % (subnet, port))

        found_ip = None
        for i in range(1, 255):
            ip = subnet + str(i)
            if ip == local_ip:
                continue
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.1)
                s.connect((ip, port))
                s.close()
                print("[WiFi] Found ESP01S at %s:%d" % (ip, port))
                found_ip = ip
                break
            except (socket.timeout, ConnectionRefusedError, OSError):
                pass
            except Exception:
                pass

        if found_ip:
            self._show_info("ESP01S found: %s" % found_ip)
        else:
            self._show_info("No device on port %d in subnet %s" % (port, subnet))
        return found_ip

    def _update_track_record(self, telemetry):
        """IMU + PWM dead reckoning for real-time track drawing"""
        import math
        if telemetry is None:
            return

        # Get motor PWM values
        if hasattr(telemetry, 'left_pwm'):
            lp = telemetry.left_pwm / 999.0
            rp = telemetry.right_pwm / 999.0
        else:
            lp = telemetry.get('left_normalized', 0)
            rp = telemetry.get('right_normalized', 0)

        # Always use gyro yaw (absolute angle from MPU6050)
        if hasattr(telemetry, 'yaw'):
            self.record_angle = telemetry.yaw
        else:
            # Fallback: estimate rotation from PWM difference
            angular = (rp - lp) * 5.0
            dt = 1.0 / 20.0
            self.record_angle += angular * dt * 100

        forward = (lp + rp) * 0.5

        dt = 1.0 / 20.0
        speed = forward * 200  # scale to pixels/s
        self.record_x += speed * math.cos(math.radians(self.record_angle)) * dt
        self.record_y += speed * math.sin(math.radians(self.record_angle)) * dt
        self.record_trail.append((self.record_x, self.record_y))

        # 同时存原始遥测, 供停止时精确重建/标定
        self.record_raw.append({
            't': len(self.record_raw) / 50.0,
            'yaw': getattr(telemetry, 'yaw', self.record_angle),
            'left_pwm': getattr(telemetry, 'left_pwm', 0),
            'right_pwm': getattr(telemetry, 'right_pwm', 0),
            'error': getattr(telemetry, 'error', 0),
        })

    def _wifi_disconnect(self):
        self.wifi_bridge.stop()
        self.real_telemetry = None
        self._show_info("WiFi disconnected")

    def _update(self):
        dt = cfg.PHYSICS_DT
        if self.state_machine.is_paused():
            return

        if self.state_machine.is_hil():
            self._update_hil()
            return

        if self.state_machine.is_track_record():
            if self.wifi_bridge.is_connected():
                # 真车录制: 用 WiFi 遥测做航迹推算
                telemetry = self.wifi_bridge.get_latest()
                if telemetry is not None:
                    self._update_track_record(telemetry)
                self.car.update(cfg.PHYSICS_DT)
            else:
                # 仿真演示: 仿真车在当前赛道自主巡线, 记录其真实轨迹作数据源
                if self.timer.tick():
                    self._update_line_follow()
                self.car.update(cfg.PHYSICS_DT)
                self._record_sim_point()
            return

        if self.state_machine.is_replay():
            frame = self.replay_engine.step()
            if frame is not None and self.real_telemetry is not None:
                pass
            return

        if self.timer.tick():
            if self.noise.control_delay.enabled:
                pass  # control delay is handled in timing

            if self.state_machine.is_autonomous() or self.state_machine.is_real_world():
                self._update_line_follow()
            elif self.state_machine.is_stm32_compat():
                self._update_stm32_compat()

        self.car.update(dt)

    def _update_hil(self):
        telemetry = self.wifi_bridge.get_latest()
        if telemetry is not None:
            self.real_telemetry = telemetry
            if self.real_data_logger.recording:
                self.real_data_logger.on_telemetry(telemetry)
            # Handle both TelemetryPacket objects and dicts
            if hasattr(telemetry, "s0"):
                sensors_raw = [telemetry.s0, telemetry.s1, telemetry.s2, telemetry.s3]
                lp = getattr(telemetry, "left_pwm", 0)
                rp = getattr(telemetry, "right_pwm", 0)
                left = lp / 999.0
                right = rp / 999.0
            else:
                sensors_raw = [telemetry.get("s0", 1), telemetry.get("s1", 1),
                           telemetry.get("s2", 1), telemetry.get("s3", 1)]
                left = telemetry.get("left_normalized", 0)
                right = telemetry.get("right_normalized", 0)
            for i, val in enumerate(sensors_raw):
                self.sensor_array.set_raw(i, val)
            self.car.drive(left, right)
        self.car.update(cfg.PHYSICS_DT)
        self.renderer.add_trail_point(self.car.x, self.car.y)

    def _update_line_follow(self):
        self.sensor_array.clear_override()
        self.sensor_array.update_positions(self.car)
        self.sensor_array.read(self.track)        # 真正检测赛道线 (此前缺失:传感器读数从未刷新)
        sensors = self.sensor_array.get_processed()
        self.controller.update(sensors, cfg.PHYSICS_DT)
        left, right = self.controller.motor_cmd
        self.car.drive(left, right)

    def _update_stm32_compat(self):
        self.bridge.push_sensors()
        self.stm32_controller.run_one_tick()
        left, right = self.stm32_controller.get_motor_command()
        self.car.drive(left, right)
    def _reset_for_mode(self):
        self.car.reset(*self.start_pos)
        self.controller.reset()
        self.stm32_controller.reset()
        self.stm32_controller.begin()
        self.bridge.stop_all()
        self.timer.reset()
        self.renderer.clear_trail()
        self.chart_panel.clear()
        self.real_telemetry = None

    # ── 渲染 ──

    def _render(self):
        self.screen.fill(cfg.BACKGROUND_COLOR)
        self.renderer.draw_track(self.track)

        # 赛道录制轨迹 (虚线 = 真实小车走过的路径)
        if self.state_machine.is_track_record() and len(self.record_trail) > 1:
            import pygame as pg
            dash_len = 10
            gap_len = 6
            ox = self.track_cx - self.record_trail[0][0]
            oy = self.track_cy - self.record_trail[0][1]
            count = 0
            drawing = True
            for i in range(1, len(self.record_trail)):
                sx1 = int(self.record_trail[i-1][0] + ox)
                sy1 = int(self.record_trail[i-1][1] + oy)
                sx2 = int(self.record_trail[i][0] + ox)
                sy2 = int(self.record_trail[i][1] + oy)
                if drawing:
                    pg.draw.line(self.screen, cfg.COLOR_TRAJECTORY, (sx1, sy1), (sx2, sy2), 2)
                count += 1
                if drawing and count >= dash_len:
                    drawing = False
                    count = 0
                elif not drawing and count >= gap_len:
                    drawing = True
                    count = 0
            # Current position dot
            last = self.record_trail[-1]
            dx = int(last[0] + ox)
            dy = int(last[1] + oy)
            pg.draw.circle(self.screen, cfg.COLOR_TRAJECTORY_DOT, (dx, dy), 6)

        # 编辑模式: 实际轨迹(橙虚线) + 参考线(track已画为实线) + 控制点(绿)
        if self.edit_mode and self.actual_trail:
            import pygame as pg
            apts = [(int(x), int(y)) for x, y in self.actual_trail]
            for i in range(1, len(apts)):
                if i % 16 < 10:   # 虚线
                    pg.draw.line(self.screen, cfg.COLOR_TRAJECTORY, apts[i-1], apts[i], 2)
            for i, (px, py) in enumerate(self.edit_points):
                col = cfg.COLOR_RED if i == self.drag_idx else cfg.COLOR_GREEN
                pg.draw.circle(self.screen, col, (int(px), int(py)), 5)

        # 轨迹
        if cfg.SHOW_TRAIL:
            self.renderer.draw_trail()

        # 小车
        self.renderer.draw_car(self.car)
        self.renderer.draw_sensors(self.sensor_array)

        # 模式名称
        mode_names = {
            SimMode.LINE_FOLLOW: "AUTO (PID)",
            SimMode.STM32_COMPAT: "AUTO (STM32)",
            SimMode.MANUAL: "MANUAL",
            SimMode.REALTIME_HIL: "HIL",
            SimMode.REPLAY: "REPLAY",
              SimMode.REAL_WORLD: "REAL TRACK",
            SimMode.TRACK_RECORD: "RECORD",
            SimMode.PAUSED: "PAUSED",
        }
        mode_name = mode_names.get(self.state_machine.mode, "?")

        # 调试面板 (v6: 传递蓝牙和真实数据)
        self.debug_panel.draw(
            self.car, self.sensor_array, self.controller,
            mode_name, self.fps,
            timer=self.timer,
            noise=self.noise,
            recording=self.logger.recording,
            serial_bridge=None,
            real_data=self.real_telemetry,
        )

        # 曲线面板
        if self.show_charts and not self.state_machine.is_paused():
            self.chart_panel.push_data(
                error=getattr(self.controller, 'position', 0),
                pid_output=getattr(self.controller, 'pid_output', 0),
                left_speed=getattr(self.controller, 'motor_cmd', (0,0))[0],
                right_speed=getattr(self.controller, 'motor_cmd', (0,0))[1],
            )
            self.chart_panel.draw(self.screen)

        # 信息文字
        if self.info_timer > 0:
            self.info_timer -= cfg.PHYSICS_DT
            font = pygame.font.SysFont("Arial", 20, bold=True)
            txt = font.render(self.info_text, True, cfg.COLOR_WHITE)
            bg = pygame.Surface((txt.get_width() + 20, txt.get_height() + 10))
            bg.fill((20, 20, 30))
            bg.set_alpha(200)
            cx = (cfg.SCREEN_WIDTH - DebugPanel.PANEL_WIDTH) // 2
            self.screen.blit(bg, (cx - bg.get_width() // 2, 10))
            self.screen.blit(txt, (cx - txt.get_width() // 2, 15))

        pygame.display.flip()

    # ── 原有功能 ──

    def _toggle_all_noise(self):
        status = self.noise.get_status()
        any_on = any(status.values())
        new_state = not any_on
        self.noise.sensor_noise.enabled = new_state
        self.noise.control_delay.enabled = new_state
        self.noise.motor_response.enabled = new_state
        self.noise.velocity_perturbation.enabled = new_state

    def _toggle_recording(self):
        if self.logger.recording:
            self.logger.stop_recording()
            n = len(self.logger.history)
            self._show_info("Recording STOPPED (%d samples)" % n)
        else:
            mode = self.state_machine.mode.name
            self.logger.start_recording(mode)
            self.car.reset(*self.start_pos)
            self.controller.reset()
            self.stm32_controller.reset()
            self.stm32_controller.begin()
            self.bridge.stop_all()
            self.noise.reset_all()
            self.timer.reset()
            self.renderer.clear_trail()
            self._show_info("Recording STARTED: " + mode)

    def _compute_score(self):
        metrics = self.logger.compute_metrics()
        self.comparison.add(self.logger.experiment_name, metrics)
        score = metrics['score']
        self._show_info(
            "Score: %.1f/100 | Avg Err: %.2f | Loss: %.1f%%" % (
                score, metrics['avg_error'], metrics['track_loss_pct']), 4.0)
        print(self.comparison.get_summary())

    def _run_comparison(self):
        if len(self.comparison.experiments) < 2:
            self._show_info("Need 2+ recorded experiments to compare")
            return
        print(self.comparison.get_summary())
        self._show_info(
            "Comparison: %d experiments (see console)" % len(self.comparison.experiments), 4.0)

    # ── Replay ──

    def _replay_load(self):
        data_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'data')
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
        json_files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
        if not json_files:
            self._show_info("No replay data in data/ folder")
            return
        latest = sorted(json_files)[-1]
        filepath = os.path.join(data_dir, latest)
        ok = self.replay_engine.load(filepath)
        if ok:
            self.state_machine.switch_to(SimMode.REPLAY)
            self.car.reset(*self.start_pos)
            self.renderer.clear_trail()
            self.chart_panel.clear()
            self._show_info("Replay: " + latest)
        else:
            self._show_info("Replay: Failed to load")


    def _load_real_track(self):
        data_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'tracks')
        npy_path = os.path.join(data_dir, 'real_reconstructed_track.npy')
        if not os.path.exists(npy_path):
            self._show_info('No real track found: run real_world_mapper first')
            return
        track_data = load_track(npy_path)
        smoothed = track_data.get('smoothed', track_data.get('track_points'))
        if smoothed is None or len(smoothed) < 3:
            self._show_info('Track data invalid')
            return
        cx = smoothed[:, 0].mean()
        cy = smoothed[:, 1].mean()
        offset_x = self.track_cx - cx
        offset_y = self.track_cy - cy
        centered = smoothed.copy()
        centered[:, 0] += offset_x
        centered[:, 1] += offset_y
        self.track = TrackMap()
        self.track.add_polyline(centered.tolist(), close=True)
        self.start_pos = (centered[0, 0], centered[0, 1], 0.0)
        self.car.reset(*self.start_pos)
        self.controller.reset()
        meta = track_data.get('metadata', {})
        length = meta.get('track_length', 0)
        self._show_info('REAL WORLD track loaded: %.0f px' % length)
        self.state_machine.switch_to(SimMode.REAL_WORLD)

    # ---- 赛道录制模式 ----

    def _toggle_track_record(self):
        if self.state_machine.is_track_record():
            # 停止录制 -> 自动重建参考赛道线
            self.record_active = False
            self.state_machine.switch_to(SimMode.LINE_FOLLOW)
            if len(self.record_trail) >= 10:
                self._build_reference_from_record()
            else:
                self._show_info("Recorded too few points (need 10+)")
        else:
            # 开始录制
            self.record_trail = []
            self.record_raw = []
            self.record_x = self.record_y = self.record_angle = 0.0
            self.actual_trail = []
            self.reference_line = []
            self.edit_mode = False
            self.edit_points = []
            self.record_active = True
            self.renderer.clear_trail()
            if self.wifi_bridge.is_connected():
                # 真车录制: 清空背景(现实赛道在现实中)
                self.track = TrackMap()
                self._show_info("REC (real car): drive on track, press M to finish")
            else:
                # 仿真演示: 保留当前赛道, 仿真车自主巡线作数据源
                self.car.reset(*self.start_pos)
                self.controller.reset()
                self._show_info("REC (sim demo): sim car laps track, press M to finish")
            self.state_machine.switch_to(SimMode.TRACK_RECORD)

    def _record_sim_point(self):
        """仿真演示录制: 记录仿真车真实位置 + 合成遥测。"""
        self.record_trail.append((self.car.x, self.car.y))
        l, r = getattr(self.controller, 'motor_cmd', (0.0, 0.0))
        self.record_raw.append({
            't': len(self.record_raw) / 50.0,
            'yaw': self.car.angle,
            'left_pwm': l * 650.0,
            'right_pwm': r * 650.0,
            'error': getattr(self.controller, 'position', 0.0),
        })

    def _build_reference_from_record(self):
        """从录制轨迹自动重建参考赛道线, 保存, 进入拖点编辑。"""
        import os
        import numpy as np
        from tracks.real_world_mapper import smooth_trajectory, resample_track, export_track, reconstruct_from_records
        # 真车: 用原始遥测(yaw+PWM)精确重建; 仿真演示: 直接用记录的真实位置
        if self.wifi_bridge.is_connected() and len(self.record_raw) >= 10:
            actual = reconstruct_from_records(self.record_raw, use_gyro=True)
        else:
            actual = np.array(self.record_trail, dtype=float)
        if len(actual) < 4:
            self._show_info("Recorded data invalid")
            return
        # 居中 + 自适应缩放到屏幕(真车航迹推算尺度不定, 统一缩放避免画出屏幕/过小)
        actual = actual - actual.mean(axis=0)
        span = max(float(np.ptp(actual[:, 0])), float(np.ptp(actual[:, 1])), 1e-6)
        actual = actual * (460.0 / span)
        actual[:, 0] += self.track_cx
        actual[:, 1] += self.track_cy
        # 自动平滑成参考线
        try:
            ref = smooth_trajectory(resample_track(actual, 300), method='bspline')
        except Exception:
            ref = actual
        self.actual_trail = [(float(p[0]), float(p[1])) for p in actual]
        self.reference_line = [[float(p[0]), float(p[1])] for p in ref]
        # 设为赛道
        self.track = TrackMap()
        self.track.add_polyline(self.reference_line, close=True)
        self.start_pos = (self.reference_line[0][0], self.reference_line[0][1], 0.0)
        self.car.reset(*self.start_pos)
        self.controller.reset()
        # 降采样控制点(供拖动微调)
        step = max(1, len(self.reference_line) // 24)
        self.edit_points = [list(self.reference_line[i])
                            for i in range(0, len(self.reference_line), step)]
        self.edit_mode = True
        # 保存
        try:
            os.makedirs('tracks', exist_ok=True)
            path = os.path.join('tracks', 'recorded_track.npy')
            export_track(np.array(self.edit_points, dtype=float), path,
                         smoothed=np.array(self.reference_line, dtype=float))
            self._show_info("Rebuilt & saved: %s (green=ref, orange=actual)" % path)
        except Exception as e:
            self._show_info("Rebuilt (save failed: %s)" % str(e)[:40])

    def _apply_edit_points(self):
        """拖动控制点后, 重新平滑生成参考线并更新赛道。"""
        import numpy as np
        from tracks.real_world_mapper import smooth_trajectory, resample_track
        if len(self.edit_points) < 4:
            return
        pts = np.array(self.edit_points, dtype=float)
        try:
            ref = smooth_trajectory(resample_track(pts, 300), method='bspline')
        except Exception:
            ref = pts
        self.reference_line = [[float(p[0]), float(p[1])] for p in ref]
        self.track = TrackMap()
        self.track.add_polyline(self.reference_line, close=True)

    # ---- 画线模式 ----

    def _toggle_draw_mode(self):
        if self.drawing_mode:
            if len(self.drawing_points) >= 3:
                self.track = TrackMap()
                self.track.add_polyline(self.drawing_points, close=True)
                self.start_pos = (self.drawing_points[0][0],
                                  self.drawing_points[0][1], 0.0)
                self.car.reset(*self.start_pos)
                self.controller.reset()
                self.renderer.clear_trail()
                self._show_info("Track drawn: %d points" % len(self.drawing_points))
            else:
                self._show_info("Need 3+ points to make a track")
            self.drawing_mode = False
            self.drawing_points = []
        else:
            self.drawing_mode = True
            self.drawing_points = []
            self._show_info("DRAW MODE: Left=Add, Right=Undo, D=Finish")

    def _load_preset_track(self, level):
        from tracks.curriculum_track_generator import CurriculumTrackGenerator
        import numpy as np
        gen = CurriculumTrackGenerator(seed=42)
        pts = gen.get_track(level=level)
        # Center the track on screen
        cx = pts[:, 0].mean()
        cy = pts[:, 1].mean()
        offset_x = self.track_cx - cx
        offset_y = self.track_cy - cy
        pts_list = [[float(p[0]) + offset_x, float(p[1]) + offset_y] for p in pts]
        self.track = TrackMap()
        self.track.add_polyline(pts_list, close=True)
        self.start_pos = (pts_list[0][0], pts_list[0][1], 0.0)
        self.car.reset(*self.start_pos)
        self.controller.reset()
        self.renderer.clear_trail()

    def _show_info(self, text, duration=2.0):
        self.info_text = text
        self.info_timer = duration


if __name__ == "__main__":
    DigitalTwinSimulator().run()




