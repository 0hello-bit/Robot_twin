"""wifi_bridge.py - ESP01S WiFi 桥接器

替代 HC-06 蓝牙，通过 ESP01S WiFi TCP 接收 STM32 遥测数据。

接线:
    ESP01S        STM32
    TXD      ->   PA10 (USART1_RX)
    RXD      <-   PA9  (USART1_TX)
    VCC      ->   3.3V
    GND      ->   GND
    CH_PD(EN) ->  3.3V (通过 10K 电阻)

使用方式:
    bridge = WifiBridge()
    bridge.connect("192.168.1.100", 8888)  # ESP01S IP 和端口
    bridge.start()

    while True:
        pkt = bridge.get_latest()
        if pkt:
            print(pkt.s0, pkt.s1, pkt.s2, pkt.s3)
"""
import os
import sys
import time
import json
import socket
import struct
import threading
import collections

# Frame parser from existing serial bridge
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from real_world.frame_parser import (
    FrameParser, FRAME_TYPE_TELEMETRY, FRAME_TYPE_STATUS, FRAME_TYPE_HEALTH,
    FRAME_TYPE_ACK, PAYLOAD_LEN_HEALTH, PAYLOAD_LEN_STATUS,
    decode_telemetry, decode_status, decode_health, decode_ack,
)
from real_world.telemetry_protocol import (
    TelemetryPacket, StatusPacket,
    FRAME_TELEMETRY, FRAME_STATUS,
)


class ConnectionQuality:
    """连接质量跟踪器 (复用 serial_bridge 逻辑)"""
    def __init__(self, window_size=100):
        self._window_size = window_size
        self._tick_gaps = collections.deque(maxlen=window_size)
        self._frame_times = collections.deque(maxlen=window_size)
        self.total_frames = 0
        self.lost_frames = 0
        self.out_of_order = 0
        self._last_tick_ms = None

    def update(self, tick_ms, recv_time=None):
        if recv_time is None:
            recv_time = time.monotonic()
        self.total_frames += 1
        self._frame_times.append(recv_time)
        if self._last_tick_ms is not None:
            gap = tick_ms - self._last_tick_ms
            if 0 < gap < 10000:
                self._tick_gaps.append(gap)
            if len(self._tick_gaps) >= 3:
                avg_gap = sum(self._tick_gaps) / len(self._tick_gaps)
                if gap > avg_gap * 1.5 and gap > 20:
                    self.lost_frames += max(1, int(gap / max(avg_gap, 1)) - 1)
            if tick_ms < self._last_tick_ms:
                self.out_of_order += 1
        self._last_tick_ms = tick_ms

    def get_loss_rate(self):
        if self.total_frames == 0:
            return 0.0
        return self.lost_frames / self.total_frames * 100

    def get_recv_rate_hz(self):
        if len(self._frame_times) < 2:
            return 0.0
        dt = self._frame_times[-1] - self._frame_times[0]
        if dt < 0.001:
            return 0.0
        return len(self._frame_times) / dt

    def get_stats(self):
        r = {
            "total_frames": self.total_frames,
            "lost_frames": self.lost_frames,
            "loss_rate_pct": round(self.get_loss_rate(), 2),
            "recv_rate_hz": round(self.get_recv_rate_hz(), 1),
        }
        if len(self._tick_gaps) >= 3:
            r["avg_tick_period_ms"] = round(sum(self._tick_gaps) / len(self._tick_gaps), 1)
        return r


class WifiBridge:
    """ESP01S WiFi-TCP 桥接器"""

    RECONNECT_DELAY = 2.0
    MAX_RECONNECT_ATTEMPTS = 0  # 0 = 无限重试
    SOCKET_TIMEOUT = 5.0

    def __init__(self, reconnect=True):
        self._host = None
        self._port = None
        self._sock = None
        self._connected = False
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._reconnect = reconnect

        # 帧解析器
        self._parser = FrameParser()
        self._buffer = collections.deque(maxlen=100)
        self._latest_telemetry = None
        self._latest_status = None
        # Health baseline: 0x02 健康快照最近一次（绝不广播成 car_status）
        self._latest_health = None

        # 统计
        self._frame_count = 0
        self._error_count = 0
        self._quality = ConnectionQuality()
        self._start_time = 0.0

        # 回调
        self._callbacks = {}

    def connect(self, host, port=8888):
        """设置 ESP01S 的 IP 和端口"""
        self._host = host
        self._port = port

    def start(self):
        """启动连接线程"""
        if self._running:
            return
        self._running = True
        self._start_time = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[WifiBridge] Connecting to {self._host}:{self._port}...")

    def stop(self):
        """停止连接"""
        self._running = False
        self.disconnect()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        print("[WifiBridge] Stopped")

    def disconnect(self):
        """断开当前连接"""
        with self._lock:
            self._connected = False
            if self._sock:
                try:
                    self._sock.close()
                except:
                    pass
                self._sock = None
        print("[WifiBridge] Disconnected")

    def is_connected(self):
        return self._connected

    def send(self, data):
        """发送数据到 ESP01S（如 PID 参数调整）"""
        with self._lock:
            if self._sock and self._connected:
                try:
                    self._sock.sendall(data)
                    return True
                except:
                    self._connected = False
        return False

    def get_latest(self):
        """获取最新遥测包"""
        with self._lock:
            return self._latest_telemetry

    def get_latest_status(self):
        """获取最新状态包"""
        with self._lock:
            return self._latest_status

    def get_latest_health(self):
        """获取最新 0x02 健康快照（dict），未收到则为 None。"""
        with self._lock:
            return self._latest_health

    def get_stats(self):
        """获取连接统计"""
        s = {
            "connected": self._connected,
            "host": self._host,
            "port": self._port,
            "frame_count": self._frame_count,
            "error_count": self._error_count,
            "uptime_s": round(time.monotonic() - self._start_time, 1) if self._start_time else 0,
        }
        q = self._quality.get_stats()
        s.update({
            "connection_quality": q,
        })
        return s

    def on(self, frame_type, callback):
        """注册回调"""
        if frame_type not in self._callbacks:
            self._callbacks[frame_type] = []
        self._callbacks[frame_type].append(callback)

    def _run(self):
        """主循环：连接 + 读取"""
        attempt = 0
        while self._running:
            if not self._host or not self._port:
                time.sleep(1)
                continue

            if not self._connect_socket():
                if not self._reconnect:
                    break
                attempt += 1
                if 0 < self.MAX_RECONNECT_ATTEMPTS < attempt:
                    print("[WifiBridge] Max reconnects reached")
                    break
                time.sleep(self.RECONNECT_DELAY)
                continue

            attempt = 0
            self._read_loop()

    def _connect_socket(self):
        """建立 TCP 连接"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.SOCKET_TIMEOUT)
            sock.connect((self._host, self._port))
            sock.settimeout(0.1)  # 非阻塞读取

            self._sock = sock
            self._connected = True
            self._parser = FrameParser()
            print(f"[WifiBridge] Connected to {self._host}:{self._port}")
            return True
        except socket.timeout:
            print(f"[WifiBridge] Connection timeout to {self._host}:{self._port}")
        except ConnectionRefusedError:
            print(f"[WifiBridge] Connection refused - ESP01S not ready?")
        except Exception as e:
            print(f"[WifiBridge] Connection failed: {e}")
        return False

    def _read_loop(self):
        """读取 TCP 数据流"""
        while self._running and self._connected:
            try:
                data = self._sock.recv(256)
                if not data:
                    print("[WifiBridge] Connection closed by ESP01S")
                    self._connected = False
                    break
                for byte_val in data:
                    result = self._parser.feed(byte_val)
                    if result is not None:
                        self._process_binary_frame(result)
            except socket.timeout:
                continue
            except OSError:
                self._connected = False
                break
            except Exception as e:
                self._error_count += 1
                time.sleep(0.01)

    def _process_binary_frame(self, result):
        """处理解析完成的数据帧。

        0x02 联合分流（Round 2 项 1，设计 §8.2）：
          (0x02, len==7)   -> decode_status（旧 STATUS，保留 car_status）
          (0x02, len==106) -> decode_health（health 路径，绝不 car_status）
          (0x02, 其它 len) -> 判坏丢弃，绝不广播成 car_status
        """
        frame_type, payload = result
        try:
            print("[WiFi] Frame type=0x%02x len=%d" % (frame_type, len(payload)))
            if frame_type == FRAME_TYPE_TELEMETRY:
                data = decode_telemetry(payload)
                if data:
                    pkt = TelemetryPacket()
                    pkt.timestamp = time.monotonic()
                    pkt.s0 = data["s0"]
                    pkt.s1 = data["s1"]
                    pkt.s2 = data["s2"]
                    pkt.s3 = data["s3"]
                    pkt.left_pwm = data["m1"]
                    pkt.right_pwm = data["m2"]
                    pkt.error = data["error"]
                    pkt.pid_output = data["pid_output"]
                    pkt.tick_ms = data["tick_ms"]
                    pkt.yaw = data.get("yaw", 0.0)
                    self._quality.update(data["tick_ms"], pkt.timestamp)
                    self._on_packet(FRAME_TELEMETRY, pkt)

            elif frame_type == FRAME_TYPE_STATUS and \
                    len(payload) == PAYLOAD_LEN_STATUS:
                data = decode_status(payload)
                if data:
                    pkt = StatusPacket()
                    pkt.timestamp = time.monotonic()
                    pkt.mode = data["mode"]
                    pkt.lost_counter = data["lost"]
                    pkt.position = data["position"]
                    pkt.black_count = data["black"]
                    pkt.battery_mv = data["battery"]
                    self._on_packet(FRAME_STATUS, pkt)

            elif frame_type == FRAME_TYPE_HEALTH and \
                    len(payload) == PAYLOAD_LEN_HEALTH:
                data = decode_health(payload)
                if data:
                    self._on_health_packet(data)

            elif frame_type in (FRAME_TYPE_STATUS, FRAME_TYPE_HEALTH):
                # (0x02, 其它 len)：判坏丢弃，绝不广播成 car_status
                self._error_count += 1

        except Exception:
            self._error_count += 1

    def _on_health_packet(self, data):
        """0x02 健康快照：存最近一次 + 触发 health 回调（独立于 status 槽）。"""
        with self._lock:
            self._latest_health = data
        for cb in self._callbacks.get(FRAME_TYPE_HEALTH, []):
            try:
                cb(data)
            except Exception:
                pass

    def _on_packet(self, frame_type, packet):
        """收到数据包的统一处理"""
        with self._lock:
            self._buffer.append(packet)
            self._frame_count += 1
            if frame_type == FRAME_TELEMETRY:
                self._latest_telemetry = packet
            elif frame_type == FRAME_STATUS:
                self._latest_status = packet

        for cb in self._callbacks.get(frame_type, []):
            try:
                cb(packet)
            except:
                pass
