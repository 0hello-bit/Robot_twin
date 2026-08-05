#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Local WebSocket bridge for the STM32 car live WiFi telemetry panel.

The browser connects to ws://127.0.0.1:8787/live. This bridge then connects to
the ESP01S normal TCP server and decodes the existing AA 55 binary frames.
The firmware sends each frame with AT+CIPSEND; the ESP01S is not in transparent
mode.
It can also run a tightly restricted local Keil5 build/flash workflow. Tuning
parameters are written only to the selected workspace project's main.c after
validation and backup. External tracking software may publish ground-truth
poses through the same WebSocket.
"""

from __future__ import print_function

import argparse
import asyncio
import collections
import ipaddress
import json
import math
import os
import subprocess
import sys
import time
from urllib.parse import urlparse

import cv2

try:
    import websockets
except ImportError:  # pragma: no cover - startup message path
    websockets = None

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from real_world.frame_parser import (  # noqa: E402
    FrameParser,
    FRAME_TYPE_TELEMETRY,
    FRAME_TYPE_STATUS,
    FRAME_TYPE_HEALTH,
    PAYLOAD_LEN_HEALTH,
    PAYLOAD_LEN_STATUS,
    decode_status,
    decode_health,
    decode_telemetry,
)
from real_world.runtime_protocol import parse_ack, parse_status  # noqa: E402
from real_world.stream_demuxer import StreamDemuxer  # noqa: E402
from real_world.runtime_command_client import AckRegistry  # noqa: E402
from web_showcase.keil_bridge import KeilBridge  # noqa: E402
from web_showcase.camera_service import (  # noqa: E402
    CameraServiceError,
    EmbeddedPoseTracker,
    SharedCameraService,
    calibration_homography,
)
from web_showcase.product_store import ProductStore, ProductStoreError  # noqa: E402
from tracking.config_io import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    load_config,
    save_config,
)
from tracking.track_scanner import (  # noqa: E402
    DEFAULT_PREVIEW_PATH,
    DEFAULT_TRACK_MAP_PATH,
    TrackScanError,
    capture_track_map,
    extract_track_map,
    load_track_map,
    save_track_map,
)


DEFAULT_WS_HOST = "127.0.0.1"
DEFAULT_WS_PORT = 8787
DEFAULT_ESP_PORT = 8888
DEFAULT_POSE_UDP_HOST = "0.0.0.0"
DEFAULT_POSE_UDP_PORT = 8788
PROTOCOL_VERSION = 2
PRODUCT_DATA_ROOT = os.path.join(ROOT, "data", "product")
READ_SIZE = 256
RECONNECT_DELAY_S = 2.0


def now_s():
    return time.monotonic()


class QualityStats(object):
    def __init__(self, window_size=120):
        self.window_size = window_size
        self.frame_times = collections.deque(maxlen=window_size)
        self.tick_gaps = collections.deque(maxlen=window_size)
        self.total_frames = 0
        self.lost_frames = 0
        self.out_of_order = 0
        self.last_tick_ms = None

    def reset(self):
        self.frame_times.clear()
        self.tick_gaps.clear()
        self.total_frames = 0
        self.lost_frames = 0
        self.out_of_order = 0
        self.last_tick_ms = None

    def update(self, tick_ms):
        recv_time = now_s()
        self.total_frames += 1
        self.frame_times.append(recv_time)
        if self.last_tick_ms is not None:
            gap = tick_ms - self.last_tick_ms
            if 0 < gap < 10000:
                self.tick_gaps.append(gap)
                if len(self.tick_gaps) >= 6:
                    avg_gap = sum(self.tick_gaps) / float(len(self.tick_gaps))
                    if gap > max(20.0, avg_gap * 1.5):
                        self.lost_frames += max(1, int(gap / max(avg_gap, 1.0)) - 1)
            elif gap < 0:
                self.out_of_order += 1
        self.last_tick_ms = tick_ms

    def recv_rate_hz(self):
        if len(self.frame_times) < 2:
            return 0.0
        dt = self.frame_times[-1] - self.frame_times[0]
        if dt <= 0.001:
            return 0.0
        return len(self.frame_times) / dt

    def loss_rate_pct(self):
        if self.total_frames <= 0:
            return 0.0
        return self.lost_frames / float(self.total_frames) * 100.0

    def as_dict(self):
        result = {
            "total_frames": self.total_frames,
            "lost_frames": self.lost_frames,
            "out_of_order": self.out_of_order,
            "recv_rate_hz": round(self.recv_rate_hz(), 1),
            "loss_rate_pct": round(self.loss_rate_pct(), 2),
        }
        if len(self.tick_gaps) >= 3:
            result["avg_tick_period_ms"] = round(
                sum(self.tick_gaps) / float(len(self.tick_gaps)), 1
            )
        return result


class PoseUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, bridge):
        self.bridge = bridge

    def datagram_received(self, payload, address):
        if not payload or len(payload) > 2048:
            return
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        if message.get("type") not in (None, "pose"):
            return
        message["_transport"] = "udp"
        message["_source_ip"] = address[0]
        asyncio.ensure_future(self.bridge._handle_external_pose(message))


class LiveWifiBridge(object):
    # Timeout for waiting for an ACK from the STM32.
    ACK_TIMEOUT_S = 5.0

    def __init__(self):
        self.clients = set()
        self.esp_host = None
        self.esp_port = DEFAULT_ESP_PORT
        self.source = "idle"
        self.connected = False
        self.running_wifi = False
        self.running_mock = False
        self.wifi_task = None
        self.mock_task = None
        self.status_task = None
        self.parser = FrameParser()
        self.quality = QualityStats()
        # Health baseline: 0x02 健康快照最近一次（绝不广播成 car_status）
        self.last_health = None
        # Task 2 additions: reliable command send, ACK registry, stream demuxer
        self._writer = None
        self._send_lock = asyncio.Lock()
        self._ack_registry = AckRegistry()
        self._demuxer = StreamDemuxer(on_ascii_line=self._on_ascii_line)
        self.error_count = 0
        self.parse_error_count = 0
        self.disconnect_count = 0
        self.last_frame_wall_time = 0.0
        self.external_pose_count = 0
        self.external_pose_rejected = 0
        self.last_external_pose_wall_time = 0.0
        self.pose_source_state = {}
        self.last_message = "idle"
        self.start_time = now_s()
        self.keil = KeilBridge(os.path.dirname(__file__))
        self.product_store = ProductStore(PRODUCT_DATA_ROOT)
        self.camera = SharedCameraService(DEFAULT_CONFIG_PATH)
        self.camera_preview_task = None
        self.camera_pose_task = None
        self.camera_pose_tracker = EmbeddedPoseTracker()
        self.camera_pose_error = ""
        self.latest_camera_pose = None
        self.camera_validation_samples = []
        self.calibration_active = False
        self.calibration_frame = None
        self.calibration_points = []
        self.calibration_width_m = None
        self.calibration_height_m = None
        self.keil_task = None
        self.track_scan_task = None
        self.track_scan_candidate = None
        self.floor_calibration_process = None
        self.last_track_scan_message = "尚未扫描现实轨道"
        self.last_track_scan_success = None

    async def start(
        self,
        ws_host,
        ws_port,
        esp_host=None,
        esp_port=DEFAULT_ESP_PORT,
        mock=False,
        pose_udp_host=DEFAULT_POSE_UDP_HOST,
        pose_udp_port=DEFAULT_POSE_UDP_PORT,
    ):
        if websockets is None:
            raise RuntimeError("Missing dependency: pip install websockets")
        self.status_task = asyncio.ensure_future(self._status_loop())
        self.camera_preview_task = asyncio.ensure_future(
            self._camera_preview_loop()
        )
        self.camera_pose_task = asyncio.ensure_future(
            self._camera_pose_loop()
        )
        if esp_host:
            await self.connect_wifi(esp_host, esp_port)
        if mock:
            await self.start_mock()
        pose_transport = None
        if pose_udp_port:
            loop = asyncio.get_event_loop()
            pose_transport, _protocol = await loop.create_datagram_endpoint(
                lambda: PoseUdpProtocol(self),
                local_addr=(pose_udp_host, int(pose_udp_port)),
            )
            print("[LiveBridge] Pose UDP listening on %s:%d" % (pose_udp_host, pose_udp_port))
        try:
            async with websockets.serve(self._handle_client, ws_host, ws_port):
                print("[LiveBridge] WebSocket listening on ws://%s:%d/live" % (ws_host, ws_port))
                await asyncio.Future()
        finally:
            if pose_transport is not None:
                pose_transport.close()
            self.camera.stop()
            if self.camera_preview_task is not None:
                self.camera_preview_task.cancel()
            if self.camera_pose_task is not None:
                self.camera_pose_task.cancel()

    async def _handle_client(self, websocket, *args):
        """WebSocket client handler compatible with websockets 11+ and 17+.

        websockets < 17 calls handler(websocket, path).
        websockets >= 17 calls handler(websocket) — path via websocket.request.path.
        Both "/" and "/live" are accepted; anything else is rejected with 1008.
        """
        path = args[0] if args else getattr(
            getattr(websocket, "request", None), "path", "/live")
        if path not in ("/", "/live"):
            await websocket.close(code=1008, reason="Use /live")
            return
        if not self._is_local_panel_client(websocket):
            await websocket.close(code=1008, reason="Local panel only")
            return
        self.clients.add(websocket)
        await self._send(
            websocket,
            {
                "type": "hello",
                "protocol_version": PROTOCOL_VERSION,
                "status": self.status_payload(),
            },
        )
        await self._send(
            websocket,
            {
                "type": "keil_status",
                "keil": self.keil.status_payload(include_projects=True),
            },
        )
        await self._send_track_map(websocket)
        await self._send(
            websocket,
            {
                "type": "product_bootstrap",
                "protocol_version": PROTOCOL_VERSION,
                "product": self.product_store.bootstrap(),
            },
        )
        try:
            async for message in websocket:
                await self._handle_command(message, websocket)
        except Exception as exc:
            self.last_message = "client disconnected: %s" % exc
        finally:
            self.clients.discard(websocket)

    @staticmethod
    def _is_local_panel_client(websocket):
        remote = getattr(websocket, "remote_address", None)
        host = remote[0] if remote else "127.0.0.1"
        try:
            if not ipaddress.ip_address(host).is_loopback:
                return False
        except ValueError:
            return False
        headers = getattr(websocket, "request_headers", None)
        origin = headers.get("Origin") if headers is not None else None
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.hostname in ("127.0.0.1", "localhost", "::1")

    async def _handle_command(self, message, websocket=None):
        try:
            data = json.loads(message)
        except ValueError:
            return
        command = data.get("type")
        if command == "connect":
            host = (data.get("host") or "").strip()
            port = int(data.get("port") or DEFAULT_ESP_PORT)
            if host:
                await self.connect_wifi(host, port)
        elif command == "disconnect":
            await self.disconnect_wifi("manual disconnect")
        elif command == "mock":
            if data.get("enabled"):
                await self.start_mock()
            else:
                await self.stop_mock()
        elif command == "ping":
            await self.broadcast({"type": "pong", "time": time.time()})
        elif command == "pose":
            await self._handle_external_pose(data)
        elif command == "track_get":
            await self._send_track_map(websocket)
        elif command == "track_scan":
            await self._start_track_scan(websocket)
        elif command == "track_scan_confirm":
            await self._confirm_track_scan(data, websocket)
        elif command == "track_scan_cancel":
            self.track_scan_candidate = None
            self.last_track_scan_message = "已放弃本次识别结果，旧轨道保持不变"
            await self.broadcast({
                "type": "track_scan_status",
                "track_scan": self._track_status_payload(),
            })
        elif command == "track_calibrate":
            await self._send_product_error(
                websocket,
                data,
                "EXTERNAL_CALIBRATION_REMOVED",
                "外部标定窗口已停用",
                "没有启动新窗口，也没有修改旧标定",
                "请进入“视觉标定”页面，在摄像头画面中完成四点标定",
            )
        elif command == "camera_start":
            await self._start_camera(data, websocket)
        elif command == "camera_stop":
            self.calibration_active = False
            self.calibration_frame = None
            self.calibration_points = []
            self.camera.stop()
            await self._send_camera_state(websocket)
        elif command == "camera_calibration_begin":
            await self._begin_browser_calibration(data, websocket)
        elif command == "camera_calibration_point":
            await self._add_browser_calibration_point(data, websocket)
        elif command == "camera_calibration_undo":
            if self.calibration_points:
                self.calibration_points.pop()
            await self._send_camera_state(websocket)
        elif command == "camera_calibration_cancel":
            self.calibration_active = False
            self.calibration_frame = None
            self.calibration_points = []
            await self._send_camera_state(websocket)
        elif command == "camera_calibration_save":
            await self._save_browser_calibration(data, websocket)
        elif command == "camera_validation_sample":
            await self._add_camera_validation_sample(data, websocket)
        elif command == "camera_validation_reset":
            self.camera_validation_samples = []
            await self._send_camera_validation_state(websocket)
        elif command == "camera_validation_finish":
            await self._finish_camera_validation(data, websocket)
        elif command == "product_get":
            await self._send_product_result(
                websocket,
                data,
                "product_bootstrap",
                self.product_store.bootstrap(),
            )
        elif command == "product_save_profile":
            await self._run_product_action(
                websocket,
                data,
                "product_profile_saved",
                lambda: self.product_store.save_profile(data.get("profile")),
            )
        elif command == "product_save_presets":
            await self._run_product_action(
                websocket,
                data,
                "product_presets_saved",
                lambda: self.product_store.save_presets(data.get("presets")),
            )
        elif command == "product_save_workspace_state":
            await self._run_product_action(
                websocket,
                data,
                "product_workspace_state_saved",
                lambda: self.product_store.save_workspace_state(
                    data.get("workspace_state")
                ),
            )
        elif command == "product_save_session":
            await self._run_product_action(
                websocket,
                data,
                "product_session_saved",
                lambda: self.product_store.save_session(data.get("session")),
            )
        elif command == "product_get_session":
            await self._run_product_action(
                websocket,
                data,
                "product_session",
                lambda: self.product_store.load_session(data.get("session_id")),
            )
        elif command == "product_save_calibration_report":
            await self._run_product_action(
                websocket,
                data,
                "product_calibration_report_saved",
                lambda: self.product_store.save_calibration_report(
                    data.get("report")
                ),
            )
        elif command == "product_export":
            await self._send_product_result(
                websocket,
                data,
                "product_export",
                self._build_product_backup(),
            )
        elif command == "product_import":
            await self._run_product_action(
                websocket,
                data,
                "product_imported",
                lambda: self._restore_product_backup(data.get("backup")),
            )
        elif command == "keil_status":
            await self._send_keil_status(websocket, include_projects=True)
        elif command == "keil_select_project":
            try:
                payload = self.keil.select_project(data.get("project"))
                await self._send(
                    websocket,
                    {"type": "keil_status", "keil": payload},
                )
            except Exception as exc:
                await self._send_keil_error(websocket, str(exc))
        elif command == "keil_open":
            try:
                result = self.keil.open_project()
                await self._send(
                    websocket,
                    {"type": "keil_operation_result", "result": result},
                )
            except Exception as exc:
                await self._send_keil_error(websocket, str(exc))
        elif command == "keil_read_params":
            try:
                result = self.keil.read_project_parameters()
                await self._send(
                    websocket,
                    {"type": "keil_project_parameters", "result": result},
                )
            except Exception as exc:
                await self._send_keil_error(websocket, str(exc))
        elif command == "keil_set_flash_armed":
            try:
                payload = self.keil.set_flash_armed(bool(data.get("enabled")))
                await self._send(
                    websocket,
                    {"type": "keil_status", "keil": payload},
                )
            except Exception as exc:
                await self._send_keil_error(websocket, str(exc))
        elif command == "keil_build":
            await self._start_keil_operation(
                "build",
                data.get("params"),
                websocket,
            )
        elif command == "keil_prepare_flash":
            try:
                prepared = self.keil.prepare_flash()
                await self._send(
                    websocket,
                    {"type": "keil_flash_prepared", "prepared": prepared},
                )
            except Exception as exc:
                await self._send_keil_error(websocket, str(exc))
        elif command == "keil_build_flash":
            try:
                self.keil.consume_flash_token(data.get("token"))
            except Exception as exc:
                await self._send_keil_error(websocket, str(exc))
                return
            await self._start_keil_operation(
                "build_flash",
                data.get("params"),
                websocket,
            )

    def _configure_camera(self, data):
        config = load_config(DEFAULT_CONFIG_PATH)
        camera = config.get("camera") or {}
        old_camera = dict(camera)
        mode = str(data.get("camera_mode") or camera.get("mode") or "device")
        source_value = str(
            data.get(
                "camera_source",
                camera.get("stream_url")
                if mode == "stream"
                else camera.get("index", 0),
            )
        ).strip()
        if mode == "stream":
            if not source_value.lower().startswith(
                ("http://", "https://", "rtsp://")
            ):
                raise CameraServiceError(
                    "手机/平板视频地址必须以 http://、https:// 或 rtsp:// 开头"
                )
            camera["mode"] = "stream"
            camera["stream_url"] = source_value
        elif mode == "device":
            try:
                camera_index = int(source_value or 0)
            except ValueError:
                raise CameraServiceError("电脑摄像头编号必须是整数")
            if camera_index < 0 or camera_index > 16:
                raise CameraServiceError("电脑摄像头编号应在0到16之间")
            camera["mode"] = "device"
            camera["index"] = camera_index
        else:
            raise CameraServiceError("摄像头类型无效")
        config["camera"] = camera
        if old_camera != camera:
            config["floor"]["calibrated"] = False
            config["floor"]["image_points"] = []
            self.track_scan_candidate = None
        save_config(DEFAULT_CONFIG_PATH, config)
        return config

    async def _start_camera(self, data, websocket):
        try:
            self._configure_camera(data)
            loop = asyncio.get_event_loop()
            status = await loop.run_in_executor(None, self.camera.start)
            await self._send(
                websocket,
                {
                    "type": "camera_state",
                    "protocol_version": PROTOCOL_VERSION,
                    "success": True,
                    "camera": status,
                    "calibration": self._camera_calibration_payload(),
                },
            )
        except (CameraServiceError, ValueError) as exc:
            await self._send_product_error(
                websocket,
                data,
                "CAMERA_START_FAILED",
                str(exc),
                "无法预览、标定或扫描轨道",
                "检查摄像头编号、视频地址和其他占用摄像头的软件",
            )

    def _camera_calibration_payload(self):
        return {
            "active": self.calibration_active,
            "points": [
                {"x": round(point[0], 6), "y": round(point[1], 6)}
                for point in self.calibration_points
            ],
            "next_index": len(self.calibration_points),
            "ready_to_save": len(self.calibration_points) == 4,
        }

    async def _send_camera_state(self, websocket=None):
        payload = {
            "type": "camera_state",
            "protocol_version": PROTOCOL_VERSION,
            "success": True,
            "camera": self.camera.status(),
            "calibration": self._camera_calibration_payload(),
        }
        if websocket is not None:
            await self._send(websocket, payload)
        else:
            await self.broadcast(payload)

    async def _begin_browser_calibration(self, data, websocket):
        try:
            self._configure_camera(data)
            loop = asyncio.get_event_loop()
            if not self.camera.status().get("running"):
                await loop.run_in_executor(None, self.camera.start)
            frame = self.camera.snapshot()
            if frame is None:
                raise CameraServiceError("摄像头没有返回可用于标定的画面")
            width_m = float(data.get("width_m"))
            height_m = float(data.get("height_m"))
            if not (
                math.isfinite(width_m)
                and math.isfinite(height_m)
                and 0.2 <= width_m <= 20.0
                and 0.2 <= height_m <= 20.0
            ):
                raise CameraServiceError("标定区域尺寸必须在0.2到20米之间")
            self.calibration_active = True
            self.calibration_frame = frame
            self.calibration_points = []
            self.camera_validation_samples = []
            self.track_scan_candidate = None
            self.calibration_width_m = width_m
            self.calibration_height_m = height_m
            await self._send_camera_state(websocket)
        except (CameraServiceError, TypeError, ValueError) as exc:
            await self._send_product_error(
                websocket,
                data,
                "CALIBRATION_START_FAILED",
                str(exc),
                "地面标定尚未开始",
                "检查摄像头画面和标定区域实际尺寸",
            )

    async def _add_browser_calibration_point(self, data, websocket):
        if not self.calibration_active or self.calibration_frame is None:
            await self._send_product_error(
                websocket,
                data,
                "CALIBRATION_NOT_ACTIVE",
                "请先点击“开始四点标定”冻结画面",
                "本次点击未记录",
                "开始标定后依次点击四个角点",
            )
            return
        if len(self.calibration_points) >= 4:
            await self._send_product_error(
                websocket,
                data,
                "CALIBRATION_POINTS_FULL",
                "已经选择4个点",
                "本次点击未记录",
                "如需修改，请先撤销最后一点",
            )
            return
        try:
            x_value = float(data.get("x"))
            y_value = float(data.get("y"))
            if not (
                math.isfinite(x_value)
                and math.isfinite(y_value)
                and 0.0 <= x_value <= 1.0
                and 0.0 <= y_value <= 1.0
            ):
                raise ValueError
        except (TypeError, ValueError):
            await self._send_product_error(
                websocket,
                data,
                "INVALID_CALIBRATION_POINT",
                "标定点超出了摄像头画面",
                "本次点击未记录",
                "请在画面范围内重新点击",
            )
            return
        self.calibration_points.append((x_value, y_value))
        await self._send_camera_state(None)

    async def _save_browser_calibration(self, data, websocket):
        if (
            not self.calibration_active
            or self.calibration_frame is None
            or len(self.calibration_points) != 4
        ):
            await self._send_product_error(
                websocket,
                data,
                "CALIBRATION_INCOMPLETE",
                "必须按顺序选择4个地面角点",
                "旧标定保持不变",
                "依次点击原点、X端点、对角点、Z端点",
            )
            return
        try:
            image_points, homography = calibration_homography(
                self.calibration_points,
                self.calibration_frame.shape,
                self.calibration_width_m,
                self.calibration_height_m,
            )
            config = load_config(DEFAULT_CONFIG_PATH)
            floor = config["floor"]
            floor["calibrated"] = True
            floor["width"] = self.calibration_width_m
            floor["height"] = self.calibration_height_m
            floor["homography"] = homography
            floor["image_points"] = [
                [round(point[0], 3), round(point[1], 3)]
                for point in image_points
            ]
            floor["calibration_revision"] = int(
                floor.get("calibration_revision", 0)
            ) + 1
            save_config(DEFAULT_CONFIG_PATH, config)
            report = self.product_store.save_calibration_report({
                "kind": "floor_homography",
                "status": "calibrated_not_validated",
                "floor_width_m": self.calibration_width_m,
                "floor_height_m": self.calibration_height_m,
                "image_width": int(self.calibration_frame.shape[1]),
                "image_height": int(self.calibration_frame.shape[0]),
                "point_count": 4,
                "calibration_revision": floor["calibration_revision"],
                "accuracy": None,
            })
            self.calibration_active = False
            self.calibration_frame = None
            self.calibration_points = []
            self.camera_validation_samples = []
            self.latest_camera_pose = None
            self.camera_pose_tracker.reset()
            self.last_track_scan_message = (
                "地面四点标定已保存；还需完成精度验证，才能声明厘米级定位"
            )
            await self._send(
                websocket,
                {
                    "type": "camera_calibration_saved",
                    "protocol_version": PROTOCOL_VERSION,
                    "success": True,
                    "report": report,
                    "track_scan": self._track_status_payload(),
                },
            )
            await self._send_camera_state(None)
        except (CameraServiceError, ValueError) as exc:
            await self._send_product_error(
                websocket,
                data,
                "CALIBRATION_SAVE_FAILED",
                str(exc),
                "旧标定保持不变",
                "撤销可疑点后重新选择，或取消本次标定",
            )

    async def _camera_preview_loop(self):
        while True:
            try:
                if self.clients and self.camera.status().get("running"):
                    frame = (
                        self.calibration_frame.copy()
                        if self.calibration_active
                        and self.calibration_frame is not None
                        else self.camera.snapshot()
                    )
                    if frame is not None:
                        points = None
                        if self.calibration_active:
                            height, width = frame.shape[:2]
                            points = [
                                (point[0] * width, point[1] * height)
                                for point in self.calibration_points
                            ]
                        loop = asyncio.get_event_loop()
                        encoded = await loop.run_in_executor(
                            None,
                            lambda: self.camera.encode_frame(
                                frame,
                                points=points,
                            ),
                        )
                        await self.broadcast({
                            "type": "camera_frame",
                            "protocol_version": PROTOCOL_VERSION,
                            "frame": encoded,
                            "camera": self.camera.status(),
                            "calibration": self._camera_calibration_payload(),
                        })
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.camera.last_error = str(exc)
                await asyncio.sleep(0.5)

    async def _camera_pose_loop(self):
        while True:
            try:
                if self.camera.status().get("running") and not self.calibration_active:
                    config = load_config(DEFAULT_CONFIG_PATH)
                    if config.get("floor", {}).get("calibrated"):
                        frame = self.camera.snapshot()
                        if frame is not None:
                            loop = asyncio.get_event_loop()
                            pose = await loop.run_in_executor(
                                None,
                                lambda: self.camera_pose_tracker.detect(
                                    frame,
                                    config,
                                ),
                            )
                            self.camera_pose_error = ""
                            if pose is not None:
                                pose["_received_at_s"] = time.time()
                                self.latest_camera_pose = dict(pose)
                                await self._handle_external_pose(pose)
                    else:
                        self.camera_pose_tracker.reset()
                await asyncio.sleep(0.04)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.camera_pose_error = str(exc)
                await asyncio.sleep(0.5)

    @staticmethod
    def _angle_error_degrees(first, second):
        return abs((float(first) - float(second) + 180.0) % 360.0 - 180.0)

    def _camera_validation_payload(self):
        errors = [
            float(sample["error_m"])
            for sample in self.camera_validation_samples
        ]
        summary = None
        if errors:
            ordered = sorted(errors)
            p95_index = max(0, int(math.ceil(len(ordered) * 0.95)) - 1)
            yaw_errors = [
                float(sample["yaw_error_deg"])
                for sample in self.camera_validation_samples
                if sample.get("yaw_error_deg") is not None
            ]
            summary = {
                "mean_error_m": round(sum(errors) / len(errors), 6),
                "p95_error_m": round(ordered[p95_index], 6),
                "max_error_m": round(max(errors), 6),
                "yaw_error_deg": (
                    round(sum(yaw_errors) / len(yaw_errors), 4)
                    if yaw_errors
                    else None
                ),
                "passed": bool(len(errors) >= 5 and ordered[p95_index] <= 0.01),
            }
        latest_pose = None
        if self.latest_camera_pose is not None:
            latest_pose = {
                key: value
                for key, value in self.latest_camera_pose.items()
                if not key.startswith("_")
            }
            latest_pose["age_ms"] = int(
                max(
                    0.0,
                    time.time()
                    - self.latest_camera_pose.get("_received_at_s", 0.0),
                )
                * 1000
            )
        return {
            "samples": list(self.camera_validation_samples),
            "sample_count": len(self.camera_validation_samples),
            "minimum_samples": 5,
            "summary": summary,
            "latest_pose": latest_pose,
        }

    async def _send_camera_validation_state(self, websocket=None):
        payload = {
            "type": "camera_validation_state",
            "protocol_version": PROTOCOL_VERSION,
            "success": True,
            "validation": self._camera_validation_payload(),
        }
        if websocket is not None:
            await self._send(websocket, payload)
        else:
            await self.broadcast(payload)

    async def _add_camera_validation_sample(self, data, websocket):
        try:
            if self.calibration_active:
                raise CameraServiceError("请先保存或取消当前四点标定")
            config = load_config(DEFAULT_CONFIG_PATH)
            if not config.get("floor", {}).get("calibrated"):
                raise CameraServiceError("请先完成地面四点标定")
            pose = self.latest_camera_pose
            if (
                pose is None
                or time.time() - pose.get("_received_at_s", 0.0) > 1.0
            ):
                raise CameraServiceError(
                    "当前没有有效 AprilTag 位姿，请让车顶标签完整出现在画面中"
                )
            expected_x = float(data.get("expected_x"))
            expected_z = float(data.get("expected_z"))
            if not (
                math.isfinite(expected_x)
                and math.isfinite(expected_z)
                and 0.0 <= expected_x <= float(config["floor"]["width"])
                and 0.0 <= expected_z <= float(config["floor"]["height"])
            ):
                raise CameraServiceError("实测坐标超出了当前标定场地")
            expected_yaw = data.get("expected_yaw")
            yaw_error = None
            if expected_yaw not in (None, ""):
                expected_yaw = float(expected_yaw)
                if not math.isfinite(expected_yaw):
                    raise CameraServiceError("实测朝向必须是有效角度")
                yaw_error = self._angle_error_degrees(
                    pose["yaw_deg"],
                    expected_yaw,
                )
            error_m = math.hypot(
                float(pose["x"]) - expected_x,
                float(pose["z"]) - expected_z,
            )
            sample = {
                "index": len(self.camera_validation_samples) + 1,
                "expected": {
                    "x": round(expected_x, 6),
                    "z": round(expected_z, 6),
                    "yaw_deg": (
                        round(expected_yaw, 4)
                        if expected_yaw not in (None, "")
                        else None
                    ),
                },
                "observed": {
                    "x": round(float(pose["x"]), 6),
                    "z": round(float(pose["z"]), 6),
                    "yaw_deg": round(float(pose["yaw_deg"]), 4),
                    "quality": round(float(pose.get("quality", 0.0)), 3),
                },
                "error_m": round(error_m, 6),
                "yaw_error_deg": (
                    round(yaw_error, 4)
                    if yaw_error is not None
                    else None
                ),
                "captured_at_ms": int(time.time() * 1000),
            }
            self.camera_validation_samples.append(sample)
            await self._send_camera_validation_state(None)
        except (CameraServiceError, TypeError, ValueError) as exc:
            await self._send_product_error(
                websocket,
                data,
                "VALIDATION_SAMPLE_FAILED",
                str(exc),
                "本次精度样本未保存",
                "确认标签可见，并输入卷尺测得的真实坐标",
            )

    async def _finish_camera_validation(self, data, websocket):
        if len(self.camera_validation_samples) < 5:
            await self._send_product_error(
                websocket,
                data,
                "VALIDATION_INCOMPLETE",
                "定位精度验证至少需要5个不同位置",
                "当前样本保留",
                "把小车放到场地不同区域并继续采样",
            )
            return
        payload = self._camera_validation_payload()
        config = load_config(DEFAULT_CONFIG_PATH)
        revision = int(
            config.get("floor", {}).get("calibration_revision", 0)
        )
        reports = self.product_store.list_calibration_reports()
        report = next(
            (
                item
                for item in reports
                if item.get("kind") == "floor_homography"
                and int(item.get("calibration_revision", -1)) == revision
            ),
            {
                "kind": "floor_homography",
                "floor_width_m": config["floor"].get("width"),
                "floor_height_m": config["floor"].get("height"),
                "calibration_revision": revision,
            },
        )
        report["status"] = (
            "validated_passed"
            if payload["summary"]["passed"]
            else "validated_failed"
        )
        report["accuracy"] = payload["summary"]
        report["validation_samples"] = payload["samples"]
        saved = self.product_store.save_calibration_report(report)
        await self._send(
            websocket,
            {
                "type": "camera_validation_saved",
                "protocol_version": PROTOCOL_VERSION,
                "success": True,
                "report": saved,
                "validation": payload,
            },
        )
        await self.broadcast({
            "type": "product_changed",
            "protocol_version": PROTOCOL_VERSION,
            "product": self.product_store.bootstrap(),
        })

    async def _send_product_result(
        self,
        websocket,
        request,
        message_type,
        result,
    ):
        await self._send(
            websocket,
            {
                "type": message_type,
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request.get("request_id"),
                "success": True,
                "result": result,
                "product": result if message_type == "product_bootstrap" else None,
            },
        )

    def _build_product_backup(self):
        backup = self.product_store.backup()
        try:
            backup["track_map"] = load_track_map(DEFAULT_TRACK_MAP_PATH)
        except (OSError, ValueError, TrackScanError):
            backup["track_map"] = None
        return backup

    def _restore_product_backup(self, backup):
        track_map = backup.get("track_map") if isinstance(backup, dict) else None
        if track_map is not None:
            track = track_map.get("track") if isinstance(track_map, dict) else None
            points = track.get("points") if isinstance(track, dict) else None
            if (
                not isinstance(points, list)
                or len(points) < 8
                or not track.get("closed")
            ):
                raise ProductStoreError("备份中的轨道地图格式无效")
        result = self.product_store.restore_backup(backup)
        if track_map is not None:
            save_track_map(DEFAULT_TRACK_MAP_PATH, track_map)
            result["track_map_restored"] = True
        else:
            result["track_map_restored"] = False
        return result

    async def _run_product_action(
        self,
        websocket,
        request,
        message_type,
        action,
    ):
        try:
            result = action()
            await self._send_product_result(
                websocket,
                request,
                message_type,
                result,
            )
            await self.broadcast({
                "type": "product_changed",
                "protocol_version": PROTOCOL_VERSION,
                "product": self.product_store.bootstrap(),
            })
        except ProductStoreError as exc:
            await self._send_product_error(
                websocket,
                request,
                "INVALID_PRODUCT_DATA",
                str(exc),
                "数据没有保存，现有配置保持不变",
                "检查标红字段后重新提交",
            )
        except Exception as exc:
            await self._send_product_error(
                websocket,
                request,
                "PRODUCT_STORAGE_ERROR",
                "本机数据操作失败：%s" % exc,
                "本次操作未完成",
                "检查磁盘权限或从设置页导出诊断信息",
            )

    async def _send_product_error(
        self,
        websocket,
        request,
        code,
        message,
        impact,
        recovery,
    ):
        await self._send(
            websocket,
            {
                "type": "operation_error",
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request.get("request_id"),
                "success": False,
                "error": {
                    "code": code,
                    "message": message,
                    "impact": impact,
                    "recovery": recovery,
                },
            },
        )

    def _track_status_payload(self):
        if (
            self.floor_calibration_process is not None
            and self.floor_calibration_process.poll() is not None
        ):
            return_code = self.floor_calibration_process.returncode
            self.floor_calibration_process = None
            if return_code == 0:
                self.last_track_scan_message = "地面标定已保存，现在可以扫描现实轨道"
            else:
                self.last_track_scan_message = "地面标定窗口已关闭，尚未保存标定"
        calibrated = False
        floor_width_m = None
        floor_height_m = None
        camera_mode = None
        camera_source = None
        try:
            config = load_config(DEFAULT_CONFIG_PATH)
            floor = config.get("floor") or {}
            camera = config.get("camera") or {}
            calibrated = bool(floor.get("calibrated"))
            floor_width_m = floor.get("width")
            floor_height_m = floor.get("height")
            camera_mode = camera.get("mode", "device")
            camera_source = (
                camera.get("stream_url")
                if camera_mode == "stream"
                else camera.get("index", 0)
            )
        except Exception as exc:
            self.last_track_scan_message = "读取跟踪配置失败：%s" % exc
        saved_track_compatible = False
        track_summary = None
        try:
            saved_track = self._load_compatible_track_map()
            saved_track_compatible = saved_track is not None
            if saved_track is not None:
                track = saved_track.get("track") or {}
                detection = saved_track.get("detection") or {}
                track_summary = {
                    "version": saved_track.get("version"),
                    "created_at": saved_track.get("created_at"),
                    "length_m": track.get("length_m"),
                    "width_m": track.get("width_m"),
                    "point_count": len(track.get("points") or []),
                    "quality": detection.get("quality"),
                }
        except Exception:
            saved_track_compatible = False
        return {
            "busy": self.track_scan_task is not None
            and not self.track_scan_task.done(),
            "calibrating": self.floor_calibration_process is not None,
            "calibrated": calibrated,
            "floor_width_m": floor_width_m,
            "floor_height_m": floor_height_m,
            "camera_mode": camera_mode,
            "camera_source": camera_source,
            "saved": saved_track_compatible,
            "candidate_ready": self.track_scan_candidate is not None,
            "map_summary": track_summary,
            "last_success": self.last_track_scan_success,
            "message": self.last_track_scan_message,
        }

    @staticmethod
    def _load_compatible_track_map():
        track_map = load_track_map(DEFAULT_TRACK_MAP_PATH)
        if track_map is None:
            return None
        config = load_config(DEFAULT_CONFIG_PATH)
        floor = config.get("floor") or {}
        if not floor.get("calibrated"):
            return None
        current_revision = int(floor.get("calibration_revision", 0))
        map_revision = int(
            (track_map.get("floor") or {}).get("calibration_revision", 0)
        )
        if current_revision > 0 and current_revision != map_revision:
            return None
        return track_map

    async def _start_floor_calibration(self, data, websocket):
        if (
            self.floor_calibration_process is not None
            and self.floor_calibration_process.poll() is None
        ):
            await self._send(
                websocket,
                {
                    "type": "track_scan_result",
                    "success": False,
                    "message": "地面标定窗口已经打开",
                    "track_scan": self._track_status_payload(),
                },
            )
            return
        if self.track_scan_task is not None and not self.track_scan_task.done():
            await self._send(
                websocket,
                {
                    "type": "track_scan_result",
                    "success": False,
                    "message": "轨道扫描进行中，暂时不能启动标定",
                    "track_scan": self._track_status_payload(),
                },
            )
            return
        try:
            width = float(data.get("width_m"))
            height = float(data.get("height_m"))
        except (TypeError, ValueError):
            width = 0
            height = 0
        if not (0.2 <= width <= 20.0 and 0.2 <= height <= 20.0):
            await self._send(
                websocket,
                {
                    "type": "track_scan_result",
                    "success": False,
                    "message": "请填写 0.2 到 20 米之间的有效地面尺寸",
                    "track_scan": self._track_status_payload(),
                },
            )
            return
        mode = str(data.get("camera_mode") or "device")
        source_value = str(data.get("camera_source") or "").strip()
        try:
            config = load_config(DEFAULT_CONFIG_PATH)
            old_camera = dict(config.get("camera") or {})
            old_floor = dict(config.get("floor") or {})
            if mode == "stream":
                if not source_value.lower().startswith(
                    ("http://", "https://", "rtsp://")
                ):
                    raise ValueError("手机/平板视频地址必须以 http://、https:// 或 rtsp:// 开头")
                config["camera"]["mode"] = "stream"
                config["camera"]["stream_url"] = source_value
            elif mode == "device":
                camera_index = int(source_value or 0)
                if camera_index < 0 or camera_index > 16:
                    raise ValueError("电脑摄像头编号应在 0 到 16 之间")
                config["camera"]["mode"] = "device"
                config["camera"]["index"] = camera_index
            else:
                raise ValueError("摄像头类型无效")
            config["floor"]["width"] = width
            config["floor"]["height"] = height
            if (
                old_camera != config["camera"]
                or float(old_floor.get("width", 0)) != width
                or float(old_floor.get("height", 0)) != height
            ):
                config["floor"]["calibrated"] = False
                config["floor"]["image_points"] = []
            save_config(DEFAULT_CONFIG_PATH, config)
            script_path = os.path.join(
                os.path.dirname(DEFAULT_CONFIG_PATH),
                "calibrate_floor.py",
            )
            self.floor_calibration_process = subprocess.Popen(
                [
                    sys.executable,
                    script_path,
                    "--config",
                    DEFAULT_CONFIG_PATH,
                    "--width",
                    str(width),
                    "--height",
                    str(height),
                ],
                cwd=os.path.dirname(script_path),
            )
            self.last_track_scan_message = (
                "标定窗口已打开：依次点原点、X端点、对角点、Z端点，再按 S 保存"
            )
            await self.broadcast(
                {
                    "type": "track_scan_status",
                    "track_scan": self._track_status_payload(),
                }
            )
        except Exception as exc:
            self.floor_calibration_process = None
            self.last_track_scan_message = "无法启动地面标定：%s" % exc
            await self._send(
                websocket,
                {
                    "type": "track_scan_result",
                    "success": False,
                    "message": self.last_track_scan_message,
                    "track_scan": self._track_status_payload(),
                },
            )

    async def _send_track_map(self, websocket=None):
        try:
            track_map = self._load_compatible_track_map()
            payload = {
                "type": "track_map",
                "track_map": track_map,
                "track_scan": self._track_status_payload(),
            }
        except Exception as exc:
            payload = {
                "type": "track_scan_result",
                "success": False,
                "message": "读取已保存轨道失败：%s" % exc,
                "track_scan": self._track_status_payload(),
            }
        if websocket is not None:
            await self._send(websocket, payload)
        else:
            await self.broadcast(payload)

    async def _start_track_scan(self, websocket):
        if self.calibration_active:
            await self._send(
                websocket,
                {
                    "type": "track_scan_result",
                    "success": False,
                    "message": "请先保存或取消网页中的四点标定",
                    "track_scan": self._track_status_payload(),
                },
            )
            return
        if (
            self.floor_calibration_process is not None
            and self.floor_calibration_process.poll() is None
        ):
            await self._send(
                websocket,
                {
                    "type": "track_scan_result",
                    "success": False,
                    "message": "请先在标定窗口保存或关闭地面标定",
                    "track_scan": self._track_status_payload(),
                },
            )
            return
        if self.track_scan_task is not None and not self.track_scan_task.done():
            await self._send(
                websocket,
                {
                    "type": "track_scan_result",
                    "success": False,
                    "message": "轨道扫描正在进行，请稍候",
                    "track_scan": self._track_status_payload(),
                },
            )
            return
        self.last_track_scan_message = "正在读取摄像头并识别闭合轨道"
        self.last_track_scan_success = None
        self.track_scan_task = asyncio.ensure_future(self._run_track_scan())
        await self.broadcast(
            {
                "type": "track_scan_started",
                "track_scan": self._track_status_payload(),
            }
        )

    async def _run_track_scan(self):
        loop = asyncio.get_event_loop()
        try:
            if not self.camera.status().get("running"):
                await loop.run_in_executor(None, self.camera.start)
            frame = self.camera.snapshot()
            if frame is None:
                raise TrackScanError("摄像头没有返回可用于扫描的画面")

            def scan_shared_frame():
                config = load_config(DEFAULT_CONFIG_PATH)
                track_map, preview = extract_track_map(frame, config)
                return track_map, preview

            track_map, preview = await loop.run_in_executor(
                None,
                scan_shared_frame,
            )
            track = track_map.get("track") or {}
            encoded_preview = await loop.run_in_executor(
                None,
                lambda: self.camera.encode_frame(preview),
            )
            self.track_scan_candidate = {
                "track_map": track_map,
                "preview": preview,
            }
            self.last_track_scan_success = None
            self.last_track_scan_message = (
                "识别完成，等待确认：轨道长 %.2f 米，线宽 %.3f 米"
                % (
                    float(track.get("length_m", 0)),
                    float(track.get("width_m", 0)),
                )
            )
            await self.broadcast(
                {
                    "type": "track_scan_candidate",
                    "protocol_version": PROTOCOL_VERSION,
                    "track_map": track_map,
                    "preview": encoded_preview,
                    "track_scan": self._track_status_payload(),
                }
            )
        except TrackScanError as exc:
            self.last_track_scan_success = False
            self.last_track_scan_message = (
                "%s；旧轨道未修改。请移走小车和杂物，检查光照后重试"
                % exc
            )
            await self.broadcast(
                {
                    "type": "track_scan_result",
                    "success": False,
                    "message": str(exc),
                    "track_scan": self._track_status_payload(),
                }
            )
        except Exception as exc:
            self.last_track_scan_success = False
            self.last_track_scan_message = (
                "轨道扫描失败：%s；旧轨道未修改。"
                "请检查摄像头画面、标定状态和磁盘权限"
                % exc
            )
            await self.broadcast(
                {
                    "type": "track_scan_result",
                    "success": False,
                    "message": self.last_track_scan_message,
                    "track_scan": self._track_status_payload(),
                }
            )
        finally:
            self.track_scan_task = None
            await self.broadcast(
                {
                    "type": "track_scan_status",
                    "track_scan": self._track_status_payload(),
                }
            )

    async def _confirm_track_scan(self, data, websocket):
        if self.track_scan_candidate is None:
            await self._send_product_error(
                websocket,
                data,
                "TRACK_CANDIDATE_MISSING",
                "没有等待确认的轨道识别结果",
                "旧轨道保持不变",
                "先点击“扫描并预览现实轨道”",
            )
            return
        try:
            track_map = self.track_scan_candidate["track_map"]
            preview = self.track_scan_candidate["preview"]
            if not cv2.imwrite(DEFAULT_PREVIEW_PATH, preview):
                raise TrackScanError("轨道预览图保存失败")
            save_track_map(DEFAULT_TRACK_MAP_PATH, track_map)
            self.track_scan_candidate = None
            self.last_track_scan_success = True
            self.last_track_scan_message = "现实轨道已确认、保存并应用到3D场景"
            await self.broadcast({
                "type": "track_map",
                "protocol_version": PROTOCOL_VERSION,
                "track_map": track_map,
                "track_scan": self._track_status_payload(),
            })
        except (OSError, ValueError, TrackScanError) as exc:
            await self._send_product_error(
                websocket,
                data,
                "TRACK_SAVE_FAILED",
                "轨道保存失败：%s" % exc,
                "旧轨道保持不变，本次候选仍保留",
                "检查磁盘权限后再次确认",
            )

    async def _send_keil_status(self, websocket, include_projects=False):
        payload = self.keil.status_payload(include_projects=include_projects)
        if self.keil_task is not None and not self.keil_task.done():
            payload["busy"] = True
            if payload.get("phase") == "idle":
                payload["phase"] = "queued"
        message = {"type": "keil_status", "keil": payload}
        if websocket is not None:
            await self._send(websocket, message)
        else:
            await self.broadcast(message)

    async def _send_keil_error(self, websocket, message):
        reason = str(message or "Keil 操作失败")
        payload = {
            "type": "keil_operation_result",
            "result": {
                "success": False,
                "message": reason,
                "impact": "本次编译或烧录没有完成",
                "recovery": (
                    "保存并关闭 Keil5 图形界面，确认工程与下载配置后重试"
                ),
            },
        }
        if websocket is not None:
            await self._send(websocket, payload)
        else:
            await self.broadcast(payload)

    async def _start_keil_operation(self, action, params, websocket):
        if self.keil_task is not None and not self.keil_task.done():
            await self._send_keil_error(websocket, "Keil 正在执行另一项操作")
            return
        self.keil_task = asyncio.ensure_future(
            self._run_keil_operation(action, params)
        )
        await self._send_keil_status(None)

    async def _run_keil_operation(self, action, params):
        await self.broadcast({
            "type": "keil_operation_started",
            "operation": action,
        })
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self.keil.run(action, params),
            )
            await self.broadcast({
                "type": "keil_operation_result",
                "result": result,
            })
        except Exception as exc:
            await self._send_keil_error(None, str(exc))
        finally:
            self.keil_task = None
            await self._send_keil_status(None, include_projects=True)

    async def _handle_external_pose(self, data):
        received_wall_time = time.time()
        try:
            x = float(data.get("x", data.get("x_m")))
            z = float(data.get("z", data.get("z_m", data.get("y", data.get("y_m")))))
            yaw_deg = float(data.get("yaw_deg", data.get("yaw", data.get("heading_deg"))))
            timestamp_ms = float(data.get(
                "timestamp_ms",
                data.get("tick_ms", received_wall_time * 1000.0),
            ))
        except (TypeError, ValueError):
            self.external_pose_rejected += 1
            return
        if not all(math.isfinite(value) for value in (x, z, yaw_deg, timestamp_ms)):
            self.external_pose_rejected += 1
            return

        transport = data.get("_transport") or "websocket"
        source_ip = data.get("_source_ip") or ""
        default_source = "udp:%s" % source_ip if transport == "udp" else "websocket"
        source = str(data.get("source") or default_source).strip()[:64] or default_source

        sequence = None
        if data.get("sequence") is not None:
            try:
                sequence = int(data.get("sequence"))
            except (TypeError, ValueError):
                self.external_pose_rejected += 1
                return
            if sequence < 0:
                self.external_pose_rejected += 1
                return

        # UDP can duplicate or reorder packets. Reject a repeated/older sequence
        # while allowing a restarted sender after two seconds of silence.
        if transport == "udp" and sequence is not None:
            source_key = (source_ip, source)
            previous = self.pose_source_state.get(source_key)
            if (
                previous
                and received_wall_time - previous["wall_time"] < 2.0
                and sequence <= previous["sequence"]
            ):
                self.external_pose_rejected += 1
                return
            self.pose_source_state[source_key] = {
                "sequence": sequence,
                "wall_time": received_wall_time,
            }

        pose = {
            "timestamp_ms": received_wall_time * 1000.0,
            "source_timestamp_ms": timestamp_ms,
            "x": x,
            "z": z,
            "yaw_deg": yaw_deg,
            "source": source,
        }
        if sequence is not None:
            pose["sequence"] = sequence
        try:
            quality = float(data.get("quality"))
            if math.isfinite(quality):
                pose["quality"] = max(0.0, min(1.0, quality))
        except (TypeError, ValueError):
            pass
        self.external_pose_count += 1
        self.last_external_pose_wall_time = received_wall_time
        await self.broadcast({"type": "external_pose", "pose": pose})

    async def connect_wifi(self, host, port):
        await self.stop_mock()
        await self.disconnect_wifi("switch target")
        self.esp_host = host
        self.esp_port = int(port)
        self.running_wifi = True
        self.source = "wifi"
        self.last_message = "正在连接 ESP01S %s:%d" % (host, self.esp_port)
        self.quality.reset()
        self.parser = FrameParser()
        self.wifi_task = asyncio.ensure_future(self._wifi_loop())
        await self.broadcast({"type": "status", "status": self.status_payload()})

    async def disconnect_wifi(self, message):
        self.running_wifi = False
        self.connected = False
        self._fail_all_ack_futures(message)
        if self.wifi_task is not None:
            self.wifi_task.cancel()
            try:
                await self.wifi_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self.wifi_task = None
        self._writer = None
        if self.source == "wifi":
            self.source = "idle"
        message_map = {
            "switch target": "正在切换 ESP01S 目标",
            "manual disconnect": "已手动断开 ESP01S",
            "mock mode": "已切换到模拟遥测",
        }
        self.last_message = message_map.get(message, message)
        await self.broadcast({"type": "status", "status": self.status_payload()})

    async def start_mock(self):
        await self.disconnect_wifi("mock mode")
        if self.mock_task is not None:
            return
        self.source = "mock"
        self.running_mock = True
        self.connected = True
        self.quality.reset()
        self.last_message = "模拟遥测正在运行"
        self.mock_task = asyncio.ensure_future(self._mock_loop())
        await self.broadcast({"type": "status", "status": self.status_payload()})

    async def stop_mock(self):
        self.running_mock = False
        if self.mock_task is not None:
            self.mock_task.cancel()
            try:
                await self.mock_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self.mock_task = None
        if self.source == "mock":
            self.source = "idle"
            self.connected = False
            self.last_message = "模拟遥测已停止"

    # -- Task 2: ASCII line handler from StreamDemuxer ----

    def _on_ascii_line(self, line: str) -> None:
        """Called by StreamDemuxer when a complete ASCII line is received.

        Routes 'A' lines to _deliver_ack() and 'S' lines to broadcast/log.
        """
        line = line.strip()
        if not line:
            return
        if line.startswith("A,"):
            try:
                ack = parse_ack(line)
                self._deliver_ack(ack.campaign_id, ack.version, ack)
            except Exception:
                pass
        elif line.startswith("S,"):
            try:
                status = parse_status(line)
                # Broadcast to all WebSocket clients
                asyncio.ensure_future(self.broadcast({
                    "type": "status_update",
                    "status": {
                        "campaign_id": status.campaign_id,
                        "run_id": status.run_id,
                        "state": status.state,
                        "reason": status.reason,
                        "tick_ms": status.tick_ms,
                    },
                }))
            except Exception:
                pass

    # -- Task 2: Reliable runtime command send / ACK matching ----

    async def send_runtime_command(self, command: str) -> None:
        """Send an ASCII runtime command (P or R frame) to the STM32.

        Raises RuntimeError if not connected.
        Uses an asyncio lock to prevent concurrent sends.
        """
        async with self._send_lock:
            if not self.connected or self._writer is None:
                raise RuntimeError("wifi not connected")
            payload = command.encode("ascii")
            self._writer.write(payload)
            await self._writer.drain()

    async def wait_for_ack(self, campaign_id: str, version: int,
                           timeout_s: float | None = None) -> "ParameterAck | None":
        """Wait for a matching A frame from the STM32.

        The ACK must have the same campaign_id and version.
        Returns the parsed ParameterAck, or None on timeout.
        """
        from real_world.runtime_protocol import ParameterAck
        timeout = timeout_s if timeout_s is not None else self.ACK_TIMEOUT_S
        try:
            future = self._ack_registry.register(campaign_id, version)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return None

    def _deliver_ack(self, campaign_id: str, version: int, ack: "ParameterAck") -> None:
        """Deliver a received ACK to the matching waiter, if any."""
        self._ack_registry.deliver(campaign_id, version, ack)

    def _fail_all_ack_futures(self, reason: str) -> None:
        """Fail all pending ACK waiters (used on disconnect)."""
        self._ack_registry.fail_all(reason)

    async def _wifi_loop(self):
        while self.running_wifi:
            reader = None
            writer = None
            try:
                reader, writer = await asyncio.open_connection(self.esp_host, self.esp_port)
                self._writer = writer
                self.connected = True
                self.last_message = "已连接 ESP01S %s:%d" % (
                    self.esp_host,
                    self.esp_port,
                )
                await self.broadcast({"type": "status", "status": self.status_payload()})
                while self.running_wifi:
                    data = await reader.read(READ_SIZE)
                    if not data:
                        raise IOError("ESP01S closed connection")
                    # Feed each byte through StreamDemuxer.
                    # It will call _on_ascii_line for complete 'A'/'S' ASCII
                    # lines and allow AA55 binary frames to pass through.
                    for byte_val in bytearray(data):
                        self._demuxer.feed(byte_val)
                        result = self.parser.feed(byte_val)
                        if result is not None:
                            await self._process_frame(result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.connected:
                    self.disconnect_count += 1
                self.connected = False
                self._writer = None
                self._fail_all_ack_futures(str(exc))
                self.error_count += 1
                self.last_message = (
                    "ESP01S连接失败：%s；实车遥测不可用。"
                    "请检查IP、端口、电源和电脑是否在同一网络"
                    % exc
                )
                await self.broadcast({"type": "status", "status": self.status_payload()})
                await asyncio.sleep(RECONNECT_DELAY_S)
            finally:
                if writer is not None:
                    self._writer = None
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass

    async def _mock_loop(self):
        tick_ms = 0
        while self.running_mock:
            phase = tick_ms / 1000.0
            error = math.sin(phase * 2.3) * 1.6 + math.sin(phase * 0.7) * 0.4
            turn = int(error * 180 + math.cos(phase * 3.1) * 45)
            base = int(520 - min(220, abs(error) * 85))
            left = max(-650, min(650, base + turn))
            right = max(-650, min(650, base - turn))
            sensors = self._mock_sensors(error)
            packet = {
                "timestamp": round(time.time(), 3),
                "sensors": sensors,
                "left_pwm": left,
                "right_pwm": right,
                "m1": left,
                "m2": right,
                "m3": left,
                "m4": right,
                "error": round(error, 3),
                "pid_output": turn,
                "turn_pwm": turn,
                "tick_ms": tick_ms,
                "yaw": round(math.sin(phase * 0.5) * 18.0, 2),
            }
            self.last_frame_wall_time = time.time()
            self.quality.update(tick_ms)
            await self.broadcast({"type": "telemetry", "packet": packet, "status": self.status_payload()})
            tick_ms += 20
            await asyncio.sleep(0.02)

    @staticmethod
    def _mock_sensors(error):
        center = -error / 2.5
        offsets = [-0.7, -0.23, 0.23, 0.7]
        values = []
        for offset in offsets:
            response = math.exp(-((offset - center) ** 2) / (2 * 0.18 * 0.18))
            values.append(1 if response > 0.35 else 0)
        if not any(values):
            values[0 if error < 0 else 3] = 1
        return values

    async def _process_frame(self, result):
        frame_type, payload = result
        if frame_type == FRAME_TYPE_TELEMETRY:
            data = decode_telemetry(payload)
            if not data:
                self.parse_error_count += 1
                return
            self.last_frame_wall_time = time.time()
            packet = {
                "timestamp": round(time.time(), 3),
                "sensors": [data["s0"], data["s1"], data["s2"], data["s3"]],
                "left_pwm": data["m1"],
                "right_pwm": data["m2"],
                "m1": data["m1"],
                "m2": data["m2"],
                "m3": data["m3"],
                "m4": data["m4"],
                "error": round(data["error"] / 100.0, 3),
                "pid_output": data["pid_output"],
                "turn_pwm": data["pid_output"],
                "tick_ms": data["tick_ms"],
                "yaw": data.get("yaw", 0.0),
            }
            self.quality.update(packet["tick_ms"])
            await self.broadcast({"type": "telemetry", "packet": packet, "status": self.status_payload()})
        elif frame_type == FRAME_TYPE_STATUS and len(payload) == PAYLOAD_LEN_STATUS:
            data = decode_status(payload)
            if data:
                self.last_frame_wall_time = time.time()
                await self.broadcast({"type": "car_status", "packet": data, "status": self.status_payload()})
        elif frame_type == FRAME_TYPE_HEALTH and len(payload) == PAYLOAD_LEN_HEALTH:
            # 0x02 联合分流（Round 2 项 1）：106B 健康帧走 health 路径，
            # 绝不广播成 car_status。
            data = decode_health(payload)
            if data:
                self.last_health = data
                await self.broadcast({"type": "health", "packet": data, "status": self.status_payload()})
        else:
            self.parse_error_count += 1

    async def _status_loop(self):
        while True:
            await self.broadcast({"type": "status", "status": self.status_payload()})
            await asyncio.sleep(1.0)

    def status_payload(self):
        stats = self.quality.as_dict()
        keil_status = self.keil.status_payload()
        if self.keil_task is not None and not self.keil_task.done():
            keil_status["busy"] = True
            if keil_status.get("phase") == "idle":
                keil_status["phase"] = "queued"
        return {
            "protocol_version": PROTOCOL_VERSION,
            "source": self.source,
            "connected": self.connected,
            "host": self.esp_host or "",
            "port": self.esp_port,
            "message": self.last_message,
            "uptime_s": round(now_s() - self.start_time, 1),
            "error_count": self.error_count,
            "parse_error_count": self.parse_error_count,
            "disconnect_count": self.disconnect_count,
            "last_frame_wall_time": round(self.last_frame_wall_time, 3) if self.last_frame_wall_time else 0,
            "last_frame_age_ms": int((time.time() - self.last_frame_wall_time) * 1000) if self.last_frame_wall_time else None,
            "external_pose_count": self.external_pose_count,
            "external_pose_rejected": self.external_pose_rejected,
            "external_pose_age_ms": int((time.time() - self.last_external_pose_wall_time) * 1000) if self.last_external_pose_wall_time else None,
            "quality": stats,
            "keil": keil_status,
            "track_scan": self._track_status_payload(),
            "camera": dict(
                self.camera.status(),
                pose_error=self.camera_pose_error,
            ),
            "camera_validation": self._camera_validation_payload(),
        }

    async def _send(self, websocket, payload):
        await websocket.send(json.dumps(payload, separators=(",", ":")))

    async def broadcast(self, payload):
        if not self.clients:
            return
        message = json.dumps(payload, separators=(",", ":"))
        stale = []
        for client in list(self.clients):
            try:
                await client.send(message)
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)


def build_test_frame():
    payload = bytearray(24)
    payload[0:4] = bytearray([1, 0, 1, 0])
    put_i16(payload, 4, 420)
    put_i16(payload, 6, 380)
    put_i16(payload, 8, 420)
    put_i16(payload, 10, 380)
    put_i16(payload, 12, -125)
    put_i16(payload, 14, 88)
    put_u32(payload, 16, 12340)
    put_u32(payload, 20, 1234)
    checksum = FRAME_TYPE_TELEMETRY ^ 24
    for item in payload:
        checksum ^= item
    return bytearray([0xAA, 0x55, FRAME_TYPE_TELEMETRY, 24]) + payload + bytearray([checksum])


def put_i16(buf, index, value):
    value = int(value) & 0xFFFF
    buf[index] = value & 0xFF
    buf[index + 1] = (value >> 8) & 0xFF


def put_u32(buf, index, value):
    value = int(value) & 0xFFFFFFFF
    buf[index] = value & 0xFF
    buf[index + 1] = (value >> 8) & 0xFF
    buf[index + 2] = (value >> 16) & 0xFF
    buf[index + 3] = (value >> 24) & 0xFF


def run_self_test():
    parser = FrameParser()
    results = parser.feed_buffer(build_test_frame())
    if len(results) != 1:
        raise RuntimeError("self-test frame parse failed")
    frame_type, payload = results[0]
    if frame_type != FRAME_TYPE_TELEMETRY:
        raise RuntimeError("self-test frame type mismatch")
    data = decode_telemetry(payload)
    packet = {
        "sensors": [data["s0"], data["s1"], data["s2"], data["s3"]],
        "left_pwm": data["m1"],
        "right_pwm": data["m2"],
        "error": round(data["error"] / 100.0, 3),
        "turn_pwm": data["pid_output"],
        "tick_ms": data["tick_ms"],
        "yaw": data.get("yaw", 0.0),
    }
    required = ["sensors", "left_pwm", "right_pwm", "error", "turn_pwm", "tick_ms", "yaw"]
    missing = [key for key in required if key not in packet]
    if missing:
        raise RuntimeError("self-test missing fields: %s" % missing)
    print(json.dumps(packet, sort_keys=True))


def parse_args(argv):
    parser = argparse.ArgumentParser(description="STM32 live WiFi telemetry WebSocket bridge")
    parser.add_argument("--ws-host", default=DEFAULT_WS_HOST)
    parser.add_argument("--ws-port", type=int, default=DEFAULT_WS_PORT)
    parser.add_argument("--esp-host", default="")
    parser.add_argument("--esp-port", type=int, default=DEFAULT_ESP_PORT)
    parser.add_argument("--pose-udp-host", default=DEFAULT_POSE_UDP_HOST)
    parser.add_argument("--pose-udp-port", type=int, default=DEFAULT_POSE_UDP_PORT)
    parser.add_argument("--disable-pose-udp", action="store_true")
    parser.add_argument("--mock", action="store_true", help="emit mock telemetry instead of connecting to ESP01S")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        run_self_test()
        return 0
    bridge = LiveWifiBridge()
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(
            bridge.start(
                ws_host=args.ws_host,
                ws_port=args.ws_port,
                esp_host=args.esp_host or None,
                esp_port=args.esp_port,
                mock=args.mock,
                pose_udp_host=args.pose_udp_host,
                pose_udp_port=0 if args.disable_pose_udp else args.pose_udp_port,
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
