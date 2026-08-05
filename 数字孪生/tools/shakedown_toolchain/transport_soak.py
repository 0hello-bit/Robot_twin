"""Task 4B-4 传输半场 soak 测试（纯遥测，无摄像头）。

本文件是 2026-08-02 Codex 独立审核后的**返工版**。原版缺陷（见
`transport_soak_codex_review.md` 结论 1-6）在此修复，并通过 TDD 验证
（RED→GREEN，见 `test_transport_soak_rework.py`）：

修复清单
--------
1. **混合流解析**：同一 TCP 连接里既有 AA55 二进制遥测帧、又有 ASCII `S`
   状态帧（分段/粘包/二进制 payload 含 0x0A 均处理）。原版只解析遥测，
   `S` 帧被静默丢弃。
2. **安全握手**（`--run`）：START 前必须先发送唯一标识 STOP 并收到校验
   正确、campaign/run 关联的 `S,...,STOPPED,STOP`；否则不得 START。
   START 后必须收到关联 `S,...,RUNNING,START`；否则立即 STOP 清理并判
   FAIL。结束 `sendall(STOP)` 不算完成，必须收到关联 `STOPPED/STOP` 才判
   安全 PASS；超时醒目提示用户切断电机电源。
3. **原始证据**：保存实际 TX/RX 原始字节（`raw_io.json`）、墙钟/单调时间
   与解析结果；不只保存遥测对象。
4. **门禁拆分**：`transport_cadence` 与 `main_loop_nonblocking` 独立判定。
   blocking 样本不足（tick_gap==20ms 帧对 <20）时 nonblocking 必须返回
   `INSUFFICIENT_EVIDENCE`，不得被整体 PASS 掩盖。
5. **时长安全**：`--run` 默认 30s 短时上限；更长必须显式 `--long-run` 授权
   + 醒目风险提示；没有 MCU 命令心跳，长时运行不宣称无人值守安全。

门禁结论
--------
- `transport_cadence`：PASS/FAIL/INSUFFICIENT_EVIDENCE（帧数不足）。
- `main_loop_nonblocking`：PASS/FAIL/INSUFFICIENT_EVIDENCE（20ms 帧对不足）。
- `command_safety_handshake`：PASS/FAIL/N/A（passive）。

退出码契约：0=全部 PASS；2=任一 FAIL（门禁阻塞）；3=无 FAIL 但存在
INSUFFICIENT_EVIDENCE（数据不足，不算 PASS）。

⚠️ 运行会连接真实 ESP01S（TCP 8888）并读取遥测，需用户当次授权。`--run`
   驱动电机（架空轮 + 用户在场 + 赛道净空 + 轮子可立即断电）。STOPPED/
   运动抑制态固件**不发遥测**（2026-08-02 实测确认）。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_WORKSPACE_ROOT / "simulation" / "digital_twin"))

from real_world.frame_parser import (  # noqa: E402
    FRAME_TYPE_TELEMETRY,
    FRAME_TYPE_HEALTH,
    PAYLOAD_LEN_HEALTH,
    FrameParser,
    decode_telemetry,
    decode_health,
)
from real_world.runtime_protocol import (  # noqa: E402
    RunCommand,
    frame,
    parse_status,
)
from v1_twin.v1_twin_capture import resolve_run_output_dir  # noqa: E402
from v1_twin.v1_twin_sync import ClockSync  # noqa: E402

TELEMETRY_PERIOD_MS = 20          # 固件 TELEMETRY_INTERVAL_MS（设计值）
TICK_MODULUS = 1 << 32            # uint32
WRAP_GAP_MAX_MS = 60_000
BATCH_THRESHOLD_NS = 10_000_000
MAX_IDLE_GAP_S = 5.0              # runbook 阶段 C: 未断流超过 5s
CONTINUITY_GAP_THRESHOLD_S = 5.0  # Task 10 门禁拆分：TRANSPORT_CONTINUITY 初值
                                  # （来源：既有 runbook 阶段 C “未断流超过 5s”）
BLOCKING_RATIO_GATE = 3.0         # 期望 ~1.0~2.0；旧同步阻塞 ~6.5
FIRST_FRAME_TIMEOUT_S = 30.0

# -- 返工新增约束 -------------------------------------------------
DEFAULT_RUN_DURATION_S = 30.0      # --run 短时上限（任务要求 30s）
DEFAULT_PASSIVE_DURATION_S = 300.0  # passive 无电机风险，可长
LONG_RUN_THRESHOLD_S = 30.0        # 超过即需 --long-run 显式授权
MIN_FRAMES_FOR_CADENCE = 20        # cadence 判定最少帧数
MIN_BLOCKING_PAIRS = 20            # 主循环无阻塞判定最少 20ms 帧对数
HANDSHAKE_TIMEOUT_DEFAULTS = {
    "initial_status_s": 5.0,
    "confirm_s": 10.0,
    "stop_confirm_s": 10.0,
}
OUTPUT_FILENAMES = ("raw_telemetry.json", "raw_io.json", "transport_report.json",
                    "raw_health.json")

# Health baseline: 心跳周期（RUNNING 态 200ms）。
HEARTBEAT_PERIOD_S = 0.2

# 规范运行模式值（2026-08-03 假被动回归）：内部控制分支只使用这些规范值，
# 绝不用面向显示的文本做分支依据；显示文本仅在报告/打印时经 RUN_MODE_DISPLAY
# 转换。旧版把 'passive(no commands)' 当作 run_mode 传入导致被动模式误入运行
# 分支、实际发送 STOP/START/心跳。
RUN_MODE_RUN = "run"
RUN_MODE_PASSIVE = "passive"
RUN_MODE_DISPLAY = {
    RUN_MODE_RUN: "run-mode(START/STOP)",
    RUN_MODE_PASSIVE: "passive(no commands)",
}


def make_run_id() -> str:
    t = time.localtime()
    return "soak_{0:04d}{1:02d}{2:02d}_{3:02d}{4:02d}{5:02d}".format(
        t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


def auto_run_id() -> str:
    """命令 run_id 自动生成：soak{epoch_s:08x}（12 字符，[A-Za-z0-9-]≤16 合规，
    唯一到秒）。与 make_run_id()（输出目录名）分离（Task 10）。"""
    return "soak{0:08x}".format(int(time.time()))


def resolve_cmd_run_id(args):
    """--cmd-run-id 显式覆盖；否则用 auto_run_id()。"""
    if args.cmd_run_id:
        return args.cmd_run_id
    return auto_run_id()


class HeartbeatCommand(object):
    """MCU 命令心跳：H,campaign,run_id,<cs>\\n（复用既有 XOR 校验和算法）。"""

    def __init__(self, campaign, run_id):
        self.campaign = campaign
        self.run_id = run_id

    def encode(self) -> str:
        return frame("H,{0},{1}".format(self.campaign, self.run_id))


def tick_gap(prev_tick: int, tick: int):
    """相对上一帧的 tick 间隔，区分 uint32 回绕与真实倒退。"""
    diff = tick - prev_tick
    if diff < 0:
        adjusted = diff + TICK_MODULUS
        if adjusted <= WRAP_GAP_MAX_MS:
            return adjusted, False
        return diff, True
    return diff, False


def percentile(sorted_vals, q):
    if not sorted_vals:
        return None
    idx = max(0, int(q * len(sorted_vals)) - 1)
    return float(sorted_vals[idx])


# ════════════════════════════════════════════════════════════════
# #1 混合流解析：AA55 二进制 + ASCII 行（分段/粘包/二进制内换行）
# ════════════════════════════════════════════════════════════════

class _BusyAwareFrameParser(FrameParser):
    """暴露『是否在二进制帧内』状态，供混合解析分流。"""

    @property
    def busy(self) -> bool:
        return self._state != FrameParser.S_IDLE


class MixedStreamParser(object):
    """把一个 TCP 字节流拆成 AA55 二进制帧与 ASCII 行。

    回调：
      - on_telemetry(payload_bytes)：每解析出一帧遥测二进制帧调用。
      - on_line(text)：每解析出一个完整 ASCII 行（含换行）调用。

    二进制 payload 中的 0x0A/0xAA 等字节不会污染 ASCII 行缓冲（用 FrameParser
    的『帧内』状态门控），分段与粘包自然成立。
    """

    def __init__(self, on_telemetry=None, on_line=None, on_health=None):
        self._fp = _BusyAwareFrameParser()
        self._ascii = bytearray()
        self._on_telemetry = on_telemetry
        self._on_line = on_line
        self._on_health = on_health

    def feed(self, byte: int) -> None:
        if self._fp.busy:
            self._feed_binary(byte)
            return
        if byte == 0xAA:
            # 疑似二进制帧头；交给状态机判定，进入 busy 则整帧走二进制。
            self._feed_binary(byte)
            return
        if byte == 0x0A:
            self._ascii.append(byte)
            line = self._ascii.decode("ascii", errors="replace")
            self._ascii.clear()
            if self._on_line is None:
                return
            if line.startswith("S,"):
                self._on_line(line)
                return
            # ESP AT 回声噪声可能与 S 帧拆段合并进同一行（真实抓包：
            # 'AT+CIPSEND=0,3S,soak,...'）。从行内最后一个 'S,' 起提取。
            idx = line.rfind("S,")
            if idx >= 0:
                self._on_line(line[idx:])
        elif byte == 0x0D:
            pass  # CR 忽略
        elif 0x20 <= byte <= 0x7E:
            self._ascii.append(byte)
        else:
            self._ascii.clear()   # 帧间不可打印噪声：清掉半行

    def _feed_binary(self, byte: int) -> None:
        res = self._fp.feed(byte)
        if res is None:
            return
        ftype, payload = res
        if ftype == FRAME_TYPE_TELEMETRY and self._on_telemetry is not None:
            self._on_telemetry(payload)
        elif ftype == FRAME_TYPE_HEALTH and len(payload) == PAYLOAD_LEN_HEALTH \
                and self._on_health is not None:
            self._on_health(payload)

    def reset(self) -> None:
        self._fp.reset()
        self._ascii.clear()


# ════════════════════════════════════════════════════════════════
# #5 原始 TX/RX 字节 trace（墙钟 + 单调时间 + 解析结果）
# ════════════════════════════════════════════════════════════════

class RawIoLogger(object):
    """记录每次 sendall/recv 的原始字节与时间戳，落盘 raw_io.json。"""

    def __init__(self, out_dir=None):
        self._out_dir = out_dir
        self._events = []

    def _now(self):
        wall = time.time()
        mono = time.monotonic()
        wall_iso = time.strftime("%Y-%m-%dT%H:%M:%S",
                                 time.localtime(wall))
        return mono, wall_iso

    def log_send(self, data: bytes) -> None:
        mono, wall_iso = self._now()
        self._events.append({
            "dir": "TX", "monotonic_s": round(mono, 6), "wall_iso": wall_iso,
            "n_bytes": len(data), "bytes_hex": data.hex()})

    def log_recv(self, data: bytes, note=None) -> None:
        mono, wall_iso = self._now()
        ev = {"dir": "RX", "monotonic_s": round(mono, 6),
              "wall_iso": wall_iso, "n_bytes": len(data),
              "bytes_hex": data.hex()}
        if note:
            ev["note"] = note
        self._events.append(ev)

    def events(self):
        return list(self._events)

    def write(self):
        payload = {
            "n_send": sum(1 for e in self._events if e["dir"] == "TX"),
            "n_recv": sum(1 for e in self._events if e["dir"] == "RX"),
            "events": self._events,
        }
        if self._out_dir:
            with open(os.path.join(self._out_dir, "raw_io.json"), "w",
                      encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        return payload


# ════════════════════════════════════════════════════════════════
# 传输抽象（真机 socket / 脚本化离线）
# ════════════════════════════════════════════════════════════════

class SocketTransport(object):
    """真实 TCP 传输。recv 契约：
      - 返回 bytes（可为空 b''）→ 继续等待
      - 返回 None → EOF（连接关闭）
    """

    def __init__(self, host, port, recv_timeout=0.1):
        self.host = host
        self.port = port
        self.recv_timeout = recv_timeout
        self._sock = None

    def connect(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect((self.host, self.port))
        s.settimeout(self.recv_timeout)
        self._sock = s

    def send(self, data: bytes) -> None:
        if self._sock is None:
            raise OSError("not connected")
        self._sock.sendall(data)

    def recv(self, max_bytes: int):
        if self._sock is None:
            return None
        try:
            data = self._sock.recv(max_bytes)
        except socket.timeout:
            return b""
        if not data:
            return None
        return data

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class _ScriptedTransport(object):
    """离线回放：按脚本逐块返回 RX；记录 TX；脚本耗尽=EOF。"""

    def __init__(self, rx_chunks=()):
        self.rx_chunks = list(rx_chunks)
        self.tx = bytearray()

    def send(self, data):
        self.tx.extend(data)

    def recv(self, _n):
        if self.rx_chunks:
            return bytes(self.rx_chunks.pop(0))
        return None

    def close(self):
        pass


# ════════════════════════════════════════════════════════════════
# 会话上下文 + 读取线程
# ════════════════════════════════════════════════════════════════

class _SessionCtx(object):
    def __init__(self, transport, rx_log):
        self.transport = transport
        self.rx_log = rx_log
        self.frames = []
        self.health_frames = []   # 0x02 健康快照（Task 9）
        self.frames_lock = threading.Lock()
        self.statuses = []        # 待消费（握手消费队列）
        self.all_statuses = []    # 全量日志（落盘用）
        self.parse_errors = []
        self.cv = threading.Condition()
        self.stop = threading.Event()
        self.reader_err = None
        self._mixed = MixedStreamParser(
            on_telemetry=self._on_telemetry, on_line=self._on_line,
            on_health=self._on_health)

    def _on_telemetry(self, payload):
        d = decode_telemetry(payload)
        if not d:
            return
        pc_ns = time.monotonic_ns()
        frame = {
            "tick_ms": int(d["tick_ms"]),
            "pc_recv_ns": pc_ns,
            "s0": int(d["s0"]), "s1": int(d["s1"]),
            "s2": int(d["s2"]), "s3": int(d["s3"]),
            "m1": int(d["m1"]), "m2": int(d["m2"]),
            "m3": int(d["m3"]), "m4": int(d["m4"]),
            "error": int(d["error"]),
            "pid_output": int(d["pid_output"]),
            "yaw_rad": round(float(d.get("yaw", 0.0)), 6),
        }
        with self.frames_lock:
            self.frames.append(frame)

    def _on_health(self, payload):
        d = decode_health(payload)
        if not d:
            return
        pc_ns = time.monotonic_ns()
        record = {"frame_ts_s": round(time.time(), 6), "pc_recv_ns": pc_ns}
        for key, value in d.items():
            record[key] = int(value)
        with self.frames_lock:
            self.health_frames.append(record)

    def _on_line(self, line):
        st = None
        if line.startswith("S,"):
            try:
                st = parse_status(line)
            except Exception as exc:  # noqa: BLE001 - 坏帧记录，不致命
                with self.cv:
                    self.parse_errors.append({"line": line,
                                              "error": repr(exc)})
        if st is not None:
            with self.cv:
                self.statuses.append(st)
                self.all_statuses.append(st)
                self.cv.notify_all()

    def reader_loop(self):
        while not self.stop.is_set():
            try:
                data = self.transport.recv(4096)
            except Exception as exc:  # noqa: BLE001 - reader must not die silently
                with self.cv:
                    self.reader_err = repr(exc)
                    self.cv.notify_all()
                break
            if data is None:
                break
            if not data:
                continue
            self.rx_log.log_recv(data)
            for b in data:
                self._mixed.feed(b)


def _status_dict(st):
    return {"campaign": st.campaign_id, "run_id": st.run_id,
            "state": st.state, "reason": st.reason, "tick_ms": st.tick_ms}


def wait_for_status(ctx, predicate, timeout_s):
    """从状态队列中消费满足 *predicate* 的 S 帧；未命中则丢弃陈旧帧。

    返回 (RunStatus 或 None, 是否确认)。
    """
    deadline = time.monotonic() + timeout_s
    with ctx.cv:
        while True:
            # Task 10: reader 线程异常（如 recv 抛错）→ 立即向握手抛错，
            # 触发 run_handshake 的 finally-STOP 兜底。
            if ctx.reader_err:
                raise RuntimeError(
                    "transport reader error: {0}".format(ctx.reader_err))
            i = 0
            while i < len(ctx.statuses):
                st = ctx.statuses[i]
                if predicate(st):
                    del ctx.statuses[i]
                    return st, True
                i += 1
            if ctx.statuses:
                del ctx.statuses[:]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, False
            ctx.cv.wait(remaining)


def peek_first_status(ctx, timeout_s):
    """窥视队列首个 S 帧（不消费），用于记录初始权威状态。"""
    deadline = time.monotonic() + timeout_s
    with ctx.cv:
        while True:
            if ctx.statuses:
                return ctx.statuses[0], True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, False
            ctx.cv.wait(remaining)


def status_matches(st, campaign, run_id, state, reason) -> bool:
    return (st.campaign_id == campaign and st.run_id == run_id
            and st.state == state and st.reason == reason)


def _collect(ctx, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.05)


def _finalize(ctx, out):
    with ctx.frames_lock:
        frames = list(ctx.frames)
        health_frames = list(ctx.health_frames)
    out["telemetry"] = {"n": len(frames), "frames": frames}
    out["health_raw"] = health_frames
    out["health"] = compute_health_summary(health_frames)
    with ctx.cv:
        out["statuses"] = [_status_dict(s) for s in ctx.all_statuses]
        out["parse_errors"] = list(ctx.parse_errors)
    events = ctx.rx_log.events()
    out["raw"] = {
        "n_rx_events": sum(1 for e in events if e["dir"] == "RX"),
        "n_tx_events": sum(1 for e in events if e["dir"] == "TX"),
        "n_rx_bytes": sum(e["n_bytes"] for e in events if e["dir"] == "RX"),
        "n_tx_bytes": sum(e["n_bytes"] for e in events if e["dir"] == "TX"),
    }
    out["cut_power_warning"] = bool(out.get("cut_power_warning", False))
    return out


# ════════════════════════════════════════════════════════════════
# #2/#3/#4 安全握手状态机
# ════════════════════════════════════════════════════════════════

def _send(ctx, data):
    ctx.transport.send(data)
    ctx.rx_log.log_send(data)


def _heartbeat_loop(ctx, campaign, run_id, stop_event):
    """RUNNING 确认后每 0.2s 发一条 H 命令心跳，直到 stop_event 置位。
    final STOP 前由 run_handshake 置位停止（Task 9）。"""
    cmd = HeartbeatCommand(campaign, run_id).encode().encode("ascii")
    while not stop_event.is_set():
        try:
            _send(ctx, cmd)
        except OSError:
            break
        stop_event.wait(HEARTBEAT_PERIOD_S)


def _final_stop(ctx, out, campaign, run_id, timeouts):
    stop_cmd = RunCommand(campaign, run_id, "STOP").encode().encode("ascii")
    send_ok, send_err = True, None
    try:
        _send(ctx, stop_cmd)
    except OSError as exc:
        send_ok, send_err = False, repr(exc)
    st = None
    ok = False
    try:
        st, ok = wait_for_status(
            ctx, lambda s: status_matches(s, campaign, run_id, "STOPPED", "STOP"),
            timeouts.get("stop_confirm_s", HANDSHAKE_TIMEOUT_DEFAULTS["stop_confirm_s"]))
    except Exception:  # noqa: BLE001 - STOP not confirmed (e.g. reader error)
        ok = False
    out["stop"] = {
        "attempted": True, "cmd_sent": send_ok, "send_error": send_err,
        "confirmed": ok, "status": _status_dict(st) if st else None,
        "cmd_hex": stop_cmd.hex()}
    if not send_ok or not ok:
        out["cut_power_warning"] = True


def run_handshake(transport, campaign, run_id, timeouts,
                  collect_s=0.0, rx_log=None):
    """--run 安全握手：pre-STOP → START/RUNNING → collect → final STOP。"""
    if rx_log is None:
        rx_log = RawIoLogger(None)
    ctx = _SessionCtx(transport, rx_log)
    out = {"run_mode": RUN_MODE_RUN, "cut_power_warning": False,
           "aborted_before_collect": False,
           "window_start_ns": None}
    thr = threading.Thread(target=ctx.reader_loop, daemon=True)
    thr.start()
    started_send = False      # START 已发送
    stop_attempted = False    # 已尝试过 final STOP
    try:
        # 1. 初始权威状态（窥视不消费，避免吞掉 pre-STOP 的响应）
        init_st, _ = peek_first_status(
            ctx, timeouts.get("initial_status_s",
                              HANDSHAKE_TIMEOUT_DEFAULTS["initial_status_s"]))
        out["initial_status"] = _status_dict(init_st) if init_st else None

        # 2. pre-START STOP：唯一标识 STOP，确认关联 STOPPED/STOP 前不得 START
        pre_stop_cmd = RunCommand(campaign, run_id, "STOP").encode().encode("ascii")
        _send(ctx, pre_stop_cmd)
        st, ok = wait_for_status(
            ctx, lambda s: status_matches(s, campaign, run_id, "STOPPED", "STOP"),
            timeouts.get("stop_confirm_s",
                         HANDSHAKE_TIMEOUT_DEFAULTS["stop_confirm_s"]))
        out["pre_stop"] = {"cmd_sent": True, "confirmed": ok,
                           "status": _status_dict(st) if st else None,
                           "cmd_hex": pre_stop_cmd.hex()}
        if not ok:
            out["cut_power_warning"] = True
            out["aborted_before_collect"] = True
            # START 从未发送：显式记录，避免被误读为已进入运动允许态
            out["start"] = {"cmd_sent": False, "confirmed": False,
                            "status": None, "cmd_hex": None}
            return _finalize(ctx, out)

        # 3. START + RUNNING 确认；未确认立即 STOP 清理并判 FAIL
        start_cmd = RunCommand(campaign, run_id, "START").encode().encode("ascii")
        _send(ctx, start_cmd)
        started_send = True
        out["start"] = {"cmd_sent": True, "confirmed": False,
                        "status": None, "cmd_hex": start_cmd.hex()}
        st2, ok2 = wait_for_status(
            ctx, lambda s: status_matches(s, campaign, run_id, "RUNNING", "START"),
            timeouts.get("confirm_s", HANDSHAKE_TIMEOUT_DEFAULTS["confirm_s"]))
        out["start"] = {"cmd_sent": True, "confirmed": ok2,
                        "status": _status_dict(st2) if st2 else None,
                        "cmd_hex": start_cmd.hex()}
        if not ok2:
            out["aborted_before_collect"] = True
            _final_stop(ctx, out, campaign, run_id, timeouts)
            stop_attempted = True
            return _finalize(ctx, out)

        # 采集窗口起点 = RUNNING 确认时刻（Task 10 窗口排除）
        out["window_start_ns"] = time.monotonic_ns()

        # 4. RUNNING 确认后启动 200ms 命令心跳；采集；final STOP 前停止。
        heartbeat_stop = threading.Event()
        hb_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(ctx, campaign, run_id, heartbeat_stop))
        hb_thread.daemon = True
        hb_thread.start()
        if collect_s > 0:
            _collect(ctx, collect_s)
        heartbeat_stop.set()
        hb_thread.join(timeout=1.0)

        # 5. final STOP + STOPPED 确认（sendall 不算完成）
        _final_stop(ctx, out, campaign, run_id, timeouts)
        stop_attempted = True
        return _finalize(ctx, out)
    except KeyboardInterrupt:
        out["unexpected_exception"] = "KeyboardInterrupt"
        if started_send and not stop_attempted:
            _final_stop(ctx, out, campaign, run_id, timeouts)
        return _finalize(ctx, out)
    except Exception as exc:  # noqa: BLE001 - 兜底记录并 best-effort STOP
        out["unexpected_exception"] = repr(exc)
        if started_send and not stop_attempted:
            _final_stop(ctx, out, campaign, run_id, timeouts)
        return _finalize(ctx, out)
    finally:
        ctx.stop.set()
        thr.join(timeout=2.0)
        transport.close()


def capture_scripted_session(blob, campaign, run_id, timeouts, collect_s=0.1):
    """离线回放路径（测试用）：把一段脚本化字节流喂给完整握手。"""
    return run_handshake(_ScriptedTransport([blob]), campaign, run_id,
                         timeouts, collect_s=collect_s, rx_log=RawIoLogger(None))


def capture_session(transport, duration_s, run_mode, campaign, cmd_run_id,
                    timeouts, out_dir=None):
    """主采集入口。返回 (out, rx_log)。

    - run-mode（RUN_MODE_RUN）：完整安全握手 + 采集。
    - passive（RUN_MODE_PASSIVE）：不发送任何命令（STOPPED 态固件不发遥测）。

    run_mode 必须是规范值（RUN_MODE_RUN / RUN_MODE_PASSIVE）；任何其它值——
    包括旧版把显示文本 'passive(no commands)' 当模式传入——一律抛 ValueError，
    绝不静默落入运行分支（2026-08-03 假被动回归）。
    """
    rx_log = RawIoLogger(out_dir)
    if run_mode == RUN_MODE_PASSIVE:
        ctx = _SessionCtx(transport, rx_log)
        thr = threading.Thread(target=ctx.reader_loop, daemon=True)
        thr.start()
        try:
            _collect(ctx, duration_s)
        finally:
            ctx.stop.set()
            thr.join(timeout=2.0)
            transport.close()
        out = {"run_mode": RUN_MODE_PASSIVE, "cut_power_warning": False}
        out = _finalize(ctx, out)
        out["handshake"] = {"verdict": "N/A"}
        return out, rx_log
    if run_mode != RUN_MODE_RUN:
        raise ValueError(
            "run_mode must be a canonical value ({0!r} or {1!r}); got {2!r}. "
            "Display text is not a valid control value.".format(
                RUN_MODE_RUN, RUN_MODE_PASSIVE, run_mode))
    out = run_handshake(transport, campaign, cmd_run_id, timeouts,
                        collect_s=duration_s, rx_log=rx_log)
    out["handshake"] = {"verdict": eval_handshake_gate(out)}
    return out, rx_log


def eval_handshake_gate(out):
    """安全握手门禁。passive=N/A；任一确认缺失=FAIL。"""
    if out.get("run_mode") != RUN_MODE_RUN:
        return "N/A"
    for key in ("pre_stop", "start", "stop"):
        if out.get(key, {}).get("confirmed") is not True:
            return "FAIL"
    return "PASS"


# ════════════════════════════════════════════════════════════════
# 指标 + #6 拆分门禁
# ════════════════════════════════════════════════════════════════

def compute_metrics_from_gaps(tick_gaps, wall_gaps_ms, n_frames, backward=0,
                              max_wall_gap_s=None, clock_fit=None,
                              duration_s=0.0):
    """从帧间间隔列表计算传输指标（不修改帧）。"""
    if n_frames < 2:
        return {
            "n_frames": n_frames,
            "delivery_rate_hz": None,
            "expected_frames_50hz": None,
            "delivery_ratio": None,
            "tick_gap_ms": None, "wall_gap_ms": None,
            "blocking_ratio_periodic": {
                "n_pairs": 0, "median": None, "p95": None,
                "expected_range": "1.0..2.0"},
            "backward_tick_events": backward,
            "max_wall_gap_s": max_wall_gap_s,
            "batch": None,
            "clock_fit": clock_fit,
        }
    tick_sorted = sorted(tick_gaps)
    wall_sorted = sorted(wall_gaps_ms)
    periodic_ratios = [
        wg / TELEMETRY_PERIOD_MS
        for tg, wg in zip(tick_gaps, wall_gaps_ms)
        if tg == TELEMETRY_PERIOD_MS]
    ratio_sorted = sorted(periodic_ratios)
    expected = (max(1.0, duration_s * 1000.0 / TELEMETRY_PERIOD_MS)
                if duration_s > 0 else None)
    return {
        "n_frames": n_frames,
        "delivery_rate_hz": round(n_frames / duration_s, 2) if duration_s > 0 else None,
        "expected_frames_50hz": int(round(expected)) if expected is not None else None,
        "delivery_ratio": round(n_frames / expected, 4) if expected is not None else None,
        "tick_gap_ms": {
            "min": percentile(tick_sorted, 0.0),
            "p50": percentile(tick_sorted, 0.5),
            "p95": percentile(tick_sorted, 0.95),
            "p99": percentile(tick_sorted, 0.99),
            "max": percentile(tick_sorted, 1.0),
        },
        "wall_gap_ms": {
            "min": percentile(wall_sorted, 0.0),
            "p50": percentile(wall_sorted, 0.5),
            "p95": percentile(wall_sorted, 0.95),
            "p99": percentile(wall_sorted, 0.99),
            "max": percentile(wall_sorted, 1.0),
        },
        "blocking_ratio_periodic": {
            "n_pairs": len(periodic_ratios),
            "median": percentile(ratio_sorted, 0.5),
            "p95": percentile(ratio_sorted, 0.95),
            "expected_range": "1.0..2.0",
        },
        "backward_tick_events": backward,
        "max_wall_gap_s": (round(max_wall_gap_s, 3)
                           if max_wall_gap_s is not None else None),
        "batch": None,
        "clock_fit": clock_fit,
    }


def compute_metrics(frames, duration_s, window_start_ns=None):
    """从帧列表计算传输指标（批量投递 + ClockSync 拟合诊断）。

    Task 10 窗口排除：采集窗口 = [window_start_ns, window_start_ns + duration)。
    窗口外帧（START 前 INIT/STOPPED、final STOP 握手期）一律排除。
    """
    if window_start_ns is not None:
        end_ns = window_start_ns + int(max(0.0, duration_s) * 1e9)
        frames = [f for f in frames
                  if window_start_ns <= f["pc_recv_ns"] < end_ns]
    n = len(frames)
    if n < 2:
        return compute_metrics_from_gaps([], [], n, 0, None, None, duration_s)

    tick_gaps = []
    wall_gaps_ms = []
    backward = 0
    big_gap_s = 0.0
    for i in range(1, n):
        tg, is_back = tick_gap(frames[i - 1]["tick_ms"], frames[i]["tick_ms"])
        wg_ms = (frames[i]["pc_recv_ns"] - frames[i - 1]["pc_recv_ns"]) / 1e6
        if is_back:
            backward += 1
            continue
        tick_gaps.append(float(tg))
        wall_gaps_ms.append(wg_ms)
        if wg_ms / 1000.0 > big_gap_s:
            big_gap_s = wg_ms / 1000.0

    clock = ClockSync()
    for f in frames:
        clock.add_sample(f["tick_ms"], f["pc_recv_ns"])
    clock_fit = None
    if len(clock._unwrapped) >= 2:
        try:
            clock.fit_batched()
            a, b = clock.params()
            res = clock.fit_residuals()
            clock_fit = {
                "a_ns_per_ms": round(a, 3),
                "b_ns": round(b, 0),
                "n_samples": len(frames),
                "fit": "fit_batched",
                "residual_rms_ns": round(res["rms_ns"], 0),
                "residual_max_ns": round(res["max_ns"], 0),
            }
        except Exception:  # noqa: BLE001 - 诊断项失败不致命
            clock_fit = None

    m = compute_metrics_from_gaps(tick_gaps, wall_gaps_ms, n, backward,
                                  big_gap_s, clock_fit, duration_s)

    batches = []
    cur = [frames[0]]
    for i in range(1, n):
        if frames[i]["pc_recv_ns"] - frames[i - 1]["pc_recv_ns"] < BATCH_THRESHOLD_NS:
            cur.append(frames[i])
        else:
            batches.append(cur)
            cur = [frames[i]]
    batches.append(cur)
    multi = [len(b) for b in batches if len(b) > 1]
    in_batch = sum(len(b) - 1 for b in batches)
    m["batch"] = {
        "batch_threshold_ns": BATCH_THRESHOLD_NS,
        "n_batches": len(batches),
        "n_multi_frame_batches": len(multi),
        "max_batch_size": max((len(b) for b in batches), default=1),
        "frames_in_batch_extra": in_batch,
    }
    # Task 10 DELIVERY_CADENCE: >300ms 缺口密度（墙钟间隔超过 300ms 的比例）。
    if wall_gaps_ms:
        m["gap_density_gt_300ms"] = round(
            sum(1 for wg in wall_gaps_ms if wg > 300.0) / len(wall_gaps_ms), 4)
    else:
        m["gap_density_gt_300ms"] = None
    return m


def compute_health_summary(health_frames):
    """0x02 健康摘要（Task 9；Round 2 item 2 / Round 3 item 4）。

    0x02 投递率（多跳归因）：PC 实收帧数 / 三跳分母（Δhealth_generated 尝试、
    Δhealth_started 进入 CIPSEND、Δhealth_ok ESP 回 SEND OK）；期望窗口秒数以
    首末帧 snapshot_tick_ms 模差估计。断流窗口内 0x02 同链路可能不可达，PC 侧
    仅能定位缺失区间，不宣称逐秒连续观测。

    0x02 事务延迟：health_last_duration_ms 的可观测去重 last-duration 样本及
    完整性标志——仅当相邻 0x02 的 Δ(health_ok+health_failed)==1 时计一个新样本；
    delta=0 不重复计样；delta>1 置 duration_samples_incomplete=true 且只保留
    latest。不构成完整事务延迟分布。
    """
    n = len(health_frames)
    if n == 0:
        return {
            "n_frames_pc": 0,
            "delivery_multi_hop": None,
            "tx_duration_samples": [],
            "tx_duration_latest": None,
            "duration_samples_incomplete": False,
            "note": "no 0x02 frames received",
        }
    first = health_frames[0]
    last = health_frames[-1]

    tick_span_ms = (last["snapshot_tick_ms"] - first["snapshot_tick_ms"]) \
        & 0xFFFFFFFF
    expected_s = tick_span_ms / 1000.0

    def delta16(key):
        return (last[key] - first[key]) & 0xFFFF

    dgen = delta16("health_generated")
    dstarted = delta16("health_started")
    dok = delta16("health_ok")
    delivery = {
        "pc_received": n,
        "expected_window_s": round(expected_s, 3),
        "hop_attempt_delta": dgen,
        "hop_cipsend_start_delta": dstarted,
        "hop_esp_send_ok_delta": dok,
        "delivery_ratio_generated": (round(n / dgen, 4) if dgen else None),
        "delivery_ratio_started": (round(n / dstarted, 4) if dstarted else None),
        "delivery_ratio_ok": (round(n / dok, 4) if dok else None),
    }

    samples = []
    incomplete = False
    latest = None
    prev = None
    for f in health_frames:
        if prev is not None:
            delta = ((f["health_ok"] + f["health_failed"]) -
                     (prev["health_ok"] + prev["health_failed"])) & 0xFFFF
            if delta == 1:
                samples.append(f["health_last_duration_ms"])
            elif delta > 1:
                incomplete = True
        latest = f["health_last_duration_ms"]
        prev = f
    if incomplete and latest is not None:
        samples = [latest]   # 只保留 latest，不声称完整分布

    return {
        "n_frames_pc": n,
        "delivery_multi_hop": delivery,
        "tx_duration_samples": samples,
        "tx_duration_latest": latest,
        "duration_samples_incomplete": incomplete,
        "note": "observable deduped last-duration samples; NOT a complete "
                "distribution (Round 3 item 4)",
    }


def eval_gates_split(metrics):
    """拆分为两个独立结论：#6 blocking 样本不足→INSUFFICIENT_EVIDENCE。

    返回 {transport_cadence: {verdict, reasons},
          main_loop_nonblocking: {verdict, reasons}}。
    """
    n = metrics["n_frames"]
    cadence_reasons = []
    if n < MIN_FRAMES_FOR_CADENCE:
        cadence = "INSUFFICIENT_EVIDENCE"
        cadence_reasons.append("n_frames={0}<{1}".format(n, MIN_FRAMES_FOR_CADENCE))
    else:
        if metrics["backward_tick_events"] > 0:
            cadence_reasons.append("backward_tick_events={0}".format(
                metrics["backward_tick_events"]))
        mg = metrics.get("max_wall_gap_s")
        if mg is not None and mg > MAX_IDLE_GAP_S:
            cadence_reasons.append("max_wall_gap_s={0:.1f}>={1:.0f}s".format(
                mg, MAX_IDLE_GAP_S))
        cadence = "FAIL" if cadence_reasons else "PASS"

    ratio = metrics.get("blocking_ratio_periodic") or {}
    npairs = ratio.get("n_pairs") or 0
    nb_reasons = []
    if npairs < MIN_BLOCKING_PAIRS:
        nb = "INSUFFICIENT_EVIDENCE"
        nb_reasons.append("blocking_pairs={0}<{1}".format(npairs, MIN_BLOCKING_PAIRS))
    elif ratio.get("median") is not None and ratio["median"] >= BLOCKING_RATIO_GATE:
        nb = "FAIL"
        nb_reasons.append("blocking_ratio_median={0:.2f}>={1:.1f}".format(
            ratio["median"], BLOCKING_RATIO_GATE))
    else:
        nb = "PASS"
        nb_reasons.append("blocking_pairs={0} median={1}".format(
            npairs, ratio.get("median")))
    # ── Task 10 门禁拆分（health baseline）────────────────────────────
    # TRANSPORT_CONTINUITY：max_wall_gap_s ≤ CONTINUITY_GAP_THRESHOLD_S。
    # DELIVERY_CADENCE：p50/p95/p99/max + >300ms 缺口密度。
    # 本批次只登记基线（BASELINE_REGISTERED，非 PASS/FAIL）；阈值必须在基线
    # 收集 ≥3 次运行且来源可溯后才可固化为 Gate 参数（设计 §13-3），不得凭空设阈。
    mg = metrics.get("max_wall_gap_s")
    continuity_reasons = []
    if mg is None:
        continuity_reasons.append("max_wall_gap_s unknown (insufficient frames)")
    elif mg <= CONTINUITY_GAP_THRESHOLD_S:
        continuity_reasons.append(
            "max_wall_gap_s={0:.1f}s <= provisional threshold {1:.0f}s".format(
                mg, CONTINUITY_GAP_THRESHOLD_S))
    else:
        continuity_reasons.append(
            "max_wall_gap_s={0:.1f}s > provisional threshold {1:.0f}s".format(
                mg, CONTINUITY_GAP_THRESHOLD_S))
    continuity_reasons.append(
        "BASELINE_REGISTERED: not a frozen 4B-4 sync gate")

    tg = metrics.get("tick_gap_ms") or {}
    wg = metrics.get("wall_gap_ms") or {}
    cadence_reasons = [
        "tick p50/p95/p99/max = {0}/{1}/{2}/{3}".format(
            tg.get("p50"), tg.get("p95"), tg.get("p99"), tg.get("max")),
        "wall p50/p95/p99/max = {0}/{1}/{2}/{3}".format(
            wg.get("p50"), wg.get("p95"), wg.get("p99"), wg.get("max")),
    ]
    gap_density = metrics.get("gap_density_gt_300ms")
    if gap_density is not None:
        cadence_reasons.append(">300ms wall-gap density = {0}".format(gap_density))
    cadence_reasons.append(
        "BASELINE_REGISTERED: threshold registered from health-baseline "
        "re-test distribution; not frozen without source (>=3 runs)")

    return {
        "transport_cadence": {"verdict": cadence, "reasons": cadence_reasons},
        "main_loop_nonblocking": {"verdict": nb, "reasons": nb_reasons},
        "TRANSPORT_CONTINUITY": {
            "verdict": "BASELINE_REGISTERED", "reasons": continuity_reasons},
        "DELIVERY_CADENCE": {
            "verdict": "BASELINE_REGISTERED", "reasons": cadence_reasons},
    }


def exit_code_for(verdicts, run_mode=None):
    """0=全 PASS；2=任一 FAIL；3=无 FAIL 但存在 INSUFFICIENT_EVIDENCE。"""
    all_v = [v["verdict"] for v in verdicts.values()]
    if any(v == "FAIL" for v in all_v):
        return 2
    if any(v == "INSUFFICIENT_EVIDENCE" for v in all_v):
        return 3
    return 0


# ════════════════════════════════════════════════════════════════
# #7 时长上限与显式长时授权
# ════════════════════════════════════════════════════════════════

def build_arg_parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.110.236")
    ap.add_argument("--port", type=int, default=8888)
    ap.add_argument("--duration", type=float, default=None,
                    help="soak 秒数；--run 默认 {0:.0f}s，passive 默认 {1:.0f}s；"
                         "--run 超过 {0:.0f}s 必须加 --long-run".format(
                             DEFAULT_RUN_DURATION_S, DEFAULT_PASSIVE_DURATION_S))
    ap.add_argument("--run", action="store_true",
                    help="发送 R,...,START 使小车进入运动允许态（架空轮 + 用户在场授权）；"
                         "安全握手通过后自动 STOP")
    ap.add_argument("--long-run", action="store_true",
                    help="显式授权长时运行（--run 且 --duration>{0:.0f} 必需）；"
                         "有醒目风险提示，非无人值守安全".format(LONG_RUN_THRESHOLD_S))
    ap.add_argument("--campaign", default="soak")
    ap.add_argument("--cmd-run-id", default=None,
                    help="R 命令 run_id：仅字母/数字/连字符，<=16 字符；"
                         "缺省自动生成 soak{epoch_s:08x}（12 字符，唯一到秒）")
    ap.add_argument("--reconnects", type=int, default=0,
                    help="额外断连/重连轮数（runbook 阶段 C 建议 3）")
    ap.add_argument("--reconnect-wait", type=float, default=5.0)
    ap.add_argument("--reconnect-duration", type=float, default=30.0)
    ap.add_argument("--out", default=".")
    return ap


def resolve_duration(args):
    if args.duration is not None:
        return float(args.duration)
    return DEFAULT_RUN_DURATION_S if args.run else DEFAULT_PASSIVE_DURATION_S


def validate_run_duration(run_mode, duration_s, long_run):
    """--run 时长超过短时上限而无 --long-run → 拒绝（配置错误，非静默放行）。"""
    if run_mode and duration_s > LONG_RUN_THRESHOLD_S and not long_run:
        return (False,
                "run-mode duration {0:.0f}s exceeds short-run cap {1:.0f}s; "
                "add --long-run to explicitly authorize a longer soak "
                "(NOT unattended-safe: this tool sends no MCU command "
                "heartbeat)".format(duration_s, LONG_RUN_THRESHOLD_S))
    return (True, "")


def long_run_warning_text():
    return (
        "\n" + "=" * 72 +
        "\n!!! 长时运行授权已开启（--long-run）—— 有明确风险，需你全程在场！！！\n"
        "   - 运行期间无人值守不安全：本工具不发 MCU 命令心跳，无法自动确认小车状态。\n"
        "   - 必须满足：轮子架空 / 周围净空 / 用户在场可立即断电。\n"
        "   - 如 START 后 RUNNING 未确认或 STOP 未确认，请立即切断电机电源。\n"
        "   - 本次运行只用于 cadence 稳定性与安全握手验证，不用于证明主循环无阻塞。\n"
        + "=" * 72)


# ════════════════════════════════════════════════════════════════
# 断连/重连隔离（保留原能力）
# ════════════════════════════════════════════════════════════════

def passive_capture(host, port, duration_s, timeouts):
    transport = SocketTransport(host, port)
    try:
        transport.connect()
    except OSError as exc:
        return [], False, repr(exc)
    out, _rx = capture_session(transport, duration_s, RUN_MODE_PASSIVE, "", "",
                               timeouts, out_dir=None)
    return out["telemetry"]["frames"], True, None


def reconnect_check(host, port, n_cycles, wait_s, duration_s,
                    last_tick_before, timeouts):
    out = {}
    for i in range(1, n_cycles + 1):
        time.sleep(wait_s)
        frames, ok, err = passive_capture(host, port, duration_s, timeouts)
        leak = 0
        if ok and frames:
            base = frames[0]["pc_recv_ns"]
            for f in frames:
                if f["pc_recv_ns"] - base < 2_000_000_000 and \
                        f["tick_ms"] < last_tick_before:
                    leak += 1
        out[i] = {
            "resumed": bool(frames),
            "n_frames": len(frames),
            "leak_suspects": leak,
            "ok": ok,
            "error": err,
        }
        if frames:
            last_tick_before = frames[-1]["tick_ms"]
    return out


# ════════════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════════════

def main():
    ap = build_arg_parser()
    args = ap.parse_args()

    if args.run and args.reconnects > 0:
        print("警告: --run 结束后小车回到 STOPPED（运动抑制），--reconnects "
              "在此态无遥测可判；已跳过重连检查")
        args.reconnects = 0

    duration = resolve_duration(args)
    ok, dur_err = validate_run_duration(args.run, duration, args.long_run)
    if not ok:
        print("ERROR: {0}".format(dur_err))
        return 1
    if args.run and args.long_run:
        print(long_run_warning_text())

    dir_run_id = make_run_id()
    cmd_run_id = resolve_cmd_run_id(args)   # 命令 run_id（唯一，与目录名分离）
    out_dir = resolve_run_output_dir(args.out, dir_run_id, OUTPUT_FILENAMES)
    print("dir_run_id:", dir_run_id, "->", out_dir)
    print("cmd_run_id:", cmd_run_id)

    timeouts = dict(HANDSHAKE_TIMEOUT_DEFAULTS)
    transport = SocketTransport(args.host, args.port)
    try:
        transport.connect()
    except OSError as exc:
        print("ERROR: connect failed: {0}".format(exc))
        return 1

    # 规范模式值（内部控制只用规范值；显示文本仅在报告时经 RUN_MODE_DISPLAY 转换）
    run_mode = RUN_MODE_RUN if args.run else RUN_MODE_PASSIVE
    out, rx_log = capture_session(
        transport, duration, run_mode,
        args.campaign, cmd_run_id, timeouts, out_dir)

    # -- 指标与门禁 -------------------------------------------------
    # Task 10 窗口排除：采集窗口 = [RUNNING 确认, +duration)
    frames = out["telemetry"]["frames"]
    metrics = compute_metrics(frames, duration,
                              window_start_ns=out.get("window_start_ns"))
    verdicts = eval_gates_split(metrics)
    handshake_verdict = eval_handshake_gate(out)
    verdicts["command_safety_handshake"] = {
        "verdict": handshake_verdict,
        "reasons": _handshake_reasons(out, args.run)}
    code = exit_code_for(verdicts)

    print("== 传输 soak 结果 ==")
    print("帧数: {}  cadence: {}/{}  主循环无阻塞: {}  握手: {}".format(
        metrics["n_frames"],
        verdicts["transport_cadence"]["verdict"],
        metrics["tick_gap_ms"]["p50"] if metrics["tick_gap_ms"] else "n/a",
        verdicts["main_loop_nonblocking"]["verdict"],
        handshake_verdict))
    tg = metrics["tick_gap_ms"] or {}
    wg = metrics["wall_gap_ms"] or {}
    print("tick 间隔(ms) p50/p95/max: {}/{}/{}".format(
        tg.get("p50"), tg.get("p95"), tg.get("max")))
    print("墙钟间隔(ms) p50/p95/max: {}/{}/{}".format(
        wg.get("p50"), wg.get("p95"), wg.get("max")))
    print("tick 倒退事件: {}  最大墙钟断流: {} s (门限 {}s)".format(
        metrics["backward_tick_events"], metrics["max_wall_gap_s"],
        MAX_IDLE_GAP_S))
    print("VERDICT cadence: {}  {}".format(
        verdicts["transport_cadence"]["verdict"],
        "; ".join(verdicts["transport_cadence"]["reasons"])))
    print("VERDICT nonblocking: {}  {}".format(
        verdicts["main_loop_nonblocking"]["verdict"],
        "; ".join(verdicts["main_loop_nonblocking"]["reasons"])))
    print("VERDICT handshake: {}  {}".format(
        handshake_verdict, "; ".join(verdicts["command_safety_handshake"]["reasons"])))
    if args.run:
        print("pre_stop:", out.get("pre_stop"))
        print("start:", out.get("start"))
        print("stop:", out.get("stop"))
        print("initial_status:", out.get("initial_status"))
    if out.get("cut_power_warning"):
        print("\n!!! {0} !!!\n".format(CUT_POWER_WARNING_TEXT))

    reconnects = {}
    if args.reconnects > 0:
        print("== 断连/重连隔离 ({} 轮) ==".format(args.reconnects))
        last_tick = frames[-1]["tick_ms"] if frames else 0
        reconnects = reconnect_check(
            args.host, args.port, args.reconnects,
            args.reconnect_wait, args.reconnect_duration, last_tick, timeouts)
        for i, rec in sorted(reconnects.items()):
            print("  轮 {}: 恢复={} 帧数={} 泄漏可疑={} ok={}".format(
                i, rec["resumed"], rec["n_frames"],
                rec["leak_suspects"], rec["ok"]))
            if rec.get("error"):
                print("    error: {}".format(rec["error"]))
    reconnect_ok = True
    if args.reconnects > 0:
        for rec in reconnects.values():
            if not rec["resumed"] or rec["leak_suspects"] > 0:
                reconnect_ok = False
    if not reconnect_ok:
        verdicts["transport_cadence"]["verdict"] = "FAIL"
        verdicts["transport_cadence"]["reasons"].append(
            "reconnect leak or no-resume")
        code = exit_code_for(verdicts)

    report = {
        "task": "4B-4 transport soak",
        "host": args.host, "port": args.port,
        "dir_run_id": dir_run_id,
        "cmd_run_id": cmd_run_id,
        "run_mode": RUN_MODE_DISPLAY[run_mode],
        "duration_s": duration,
        "long_run_authorized": bool(args.long_run),
        "verdicts": verdicts,
        "exit_code": code,
        "handshake": {
            "initial_status": out.get("initial_status"),
            "pre_stop": out.get("pre_stop"),
            "start": out.get("start"),
            "stop": out.get("stop"),
            "cut_power_warning": out.get("cut_power_warning"),
        },
        "statuses": out.get("statuses"),
        "parse_errors": out.get("parse_errors"),
        "raw_io": out.get("raw"),
        "health": out.get("health"),
        "reconnects": reconnects,
        "metrics": metrics,
        "caveats": [
            "health-baseline: this run registers a new baseline (0x02 health "
            "frames + 200ms command heartbeat + 1s lease). 0x01 frame rate / "
            "0x02 delivery (health_* multi-hop attribution) / 0x02 transaction "
            "latency (health_last_duration_ms deduped samples) / dropout "
            "distribution are recorded separately and must NOT be compared "
            "directly to historical 60s/300s soak.",
            "firmware does not stream telemetry while motion-inhibited "
            "(STOPPED); telemetry requires R,...,START. Verified on real car "
            "2026-08-02.",
            "black-box observation: no logic analyzer, cannot prove UART "
            "shift-register residue absent.",
            "telemetry is latest-wins droppable; delivery_ratio <1 expected.",
            "main_loop_nonblocking requires >=20 tick_gap==20ms pairs; a "
            "~100ms cadence provides none -> INSUFFICIENT_EVIDENCE, NOT PASS. "
            "ClockSync slope a~1e6 only proves tick/wall rate agreement, not "
            "main-loop non-blocking.",
            "full 4B-4 sync Gate (coverage>=95%, p95<=33.3ms) still requires "
            "camera; this is the telemetry half only.",
            "long-run (--long-run) is NOT unattended-safe: this tool sends no "
            "MCU command heartbeat.",
        ],
    }
    rx_log.write()
    with open(os.path.join(out_dir, "raw_telemetry.json"), "w",
              encoding="utf-8") as f:
        json.dump(frames, f, ensure_ascii=False)
    with open(os.path.join(out_dir, "raw_health.json"), "w",
              encoding="utf-8") as f:
        json.dump(out.get("health_raw", []), f, ensure_ascii=False)
    with open(os.path.join(out_dir, "transport_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("report:", os.path.join(out_dir, "transport_report.json"))
    print("raw_io:", os.path.join(out_dir, "raw_io.json"))
    print("raw_health:", os.path.join(out_dir, "raw_health.json"))
    return code


CUT_POWER_WARNING_TEXT = (
    "未确认小车进入 STOPPED。若本会话发送过 START/运动指令，请立即切断电机电源！")


def _handshake_reasons(out, is_run):
    if not is_run:
        return ["passive: no commands sent"]
    if eval_handshake_gate(out) == "PASS":
        return ["pre-STOP confirmed, RUNNING confirmed, final STOPPED confirmed"]
    reasons = []
    if not out.get("pre_stop", {}).get("confirmed"):
        reasons.append("pre-START STOP not confirmed")
    if not out.get("start", {}).get("confirmed"):
        reasons.append("RUNNING/START not confirmed after START")
    if not out.get("stop", {}).get("confirmed"):
        reasons.append("final STOPPED/STOP not confirmed")
    if out.get("cut_power_warning"):
        reasons.append("CUT POWER warning raised")
    return reasons


if __name__ == "__main__":
    raise SystemExit(main())
