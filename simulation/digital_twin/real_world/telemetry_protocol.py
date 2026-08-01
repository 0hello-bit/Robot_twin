# -*- coding: utf-8 -*-
"""
telemetry_protocol.py - STM32 ↔ Python 通信协议

设计原则:
    1. 轻量级: 基于 CSV 文本格式, STM32 端零依赖
    2. 可扩展: 预留字段, 后续可加 IMU/GPS/编码器
    3. 容错: 每帧独立, 丢帧不影响后续解析
    4. 双向: 支持 STM32→PC (遥测) 和 PC→STM32 (参数下发)

协议格式 (ASCII CSV):
    行首标识 + 逗号分隔字段 + 换行

    遥测帧 (STM32 → PC):
    T,s0,s1,s2,s3,left_pwm,right_pwm,error,pid_output,tick_ms

    示例:
    T,1,1,0,1,180,220,-1,42,12345

    状态帧 (STM32 → PC):
    S,mode,lost_counter,position,black_count,battery_mv

    参数帧 (PC → STM32):
    P,kp,ki,kd,base_speed

    控制帧 (PC → STM32):
    C,mode_override  (0=正常, 1=强制巡线, 2=停止)
"""

from dataclasses import dataclass
import time


# ── 帧类型标识 ──
FRAME_TELEMETRY = 'T'
FRAME_STATUS    = 'S'
FRAME_PARAM     = 'P'
FRAME_CONTROL   = 'C'
FRAME_ACK       = 'A'

# ── 默认参数 ──
DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT  = 0.1  # 串口读取超时 (秒)
TELEMETRY_HZ     = 50   # STM32 发送频率


class TelemetryPacket:
    """
    单帧遥测数据。
    
    字段与 STM32 端一一对应:
        s0~s3:        4 路传感器 (0=黑线, 1=白底)
        left_pwm:     左轮 PWM (0~999)
        right_pwm:    右轮 PWM (0~999)
        error:        当前偏差 (int16)
        pid_output:   PID 输出 (int16, 放大 100 倍)
        tick_ms:      MCU 运行时间 (ms)
    """
    __slots__ = ('timestamp', 's0', 's1', 's2', 's3',
                 'left_pwm', 'right_pwm', 'error', 'pid_output',
                 'tick_ms', 'yaw', 'raw_line')

    def __init__(self):
        self.timestamp = 0.0    # PC 接收时间 (time.monotonic)
        self.s0 = 1
        self.s1 = 1
        self.s2 = 1
        self.s3 = 1
        self.left_pwm = 0
        self.right_pwm = 0
        self.error = 0
        self.pid_output = 0
        self.tick_ms = 0
        self.yaw = 0.0
        self.raw_line = ""

    @property
    def sensors(self):
        return [self.s0, self.s1, self.s2, self.s3]

    @property
    def left_normalized(self):
        """左轮归一化速度 (-1 ~ +1)"""
        return self.left_pwm / 999.0

    @property
    def right_normalized(self):
        """右轮归一化速度 (-1 ~ +1)"""
        return self.right_pwm / 999.0

    def to_dict(self):
        return {
            'timestamp': round(self.timestamp, 6),
            'sensors': self.sensors,
            'left_pwm': self.left_pwm,
            'right_pwm': self.right_pwm,
            'error': self.error,
            'pid_output': self.pid_output,
            'tick_ms': self.tick_ms,
        }

    def __repr__(self):
        return ("Packet(sensors={}, L={}, R={}, err={}, pid={}, tick={})".format(
            self.sensors, self.left_pwm, self.right_pwm,
            self.error, self.pid_output, self.tick_ms))


class StatusPacket:
    """
    状态帧: 小车运行状态信息。
    """
    __slots__ = ('timestamp', 'mode', 'lost_counter',
                 'position', 'black_count', 'battery_mv', 'raw_line')

    def __init__(self):
        self.timestamp = 0.0
        self.mode = 0
        self.lost_counter = 0
        self.position = 0
        self.black_count = 0
        self.battery_mv = 0
        self.raw_line = ""

    def to_dict(self):
        return {
            'timestamp': round(self.timestamp, 6),
            'mode': self.mode,
            'lost_counter': self.lost_counter,
            'position': self.position,
            'black_count': self.black_count,
            'battery_mv': self.battery_mv,
        }


class ParamPacket:
    """
    参数帧: PC → STM32 下发 PID 参数。
    """
    __slots__ = ('kp', 'ki', 'kd', 'base_speed')

    def __init__(self, kp=0.6, ki=0.0, kd=0.15, base_speed=180):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.base_speed = base_speed

    def to_csv(self):
        return "P,{},{},{},{}\n".format(
            round(self.kp, 4), round(self.ki, 4),
            round(self.kd, 4), int(self.base_speed))


class ControlPacket:
    """
    控制帧: PC → STM32 模式覆盖。
    """
    __slots__ = ('mode_override',)

    def __init__(self, mode_override=0):
        self.mode_override = mode_override

    def to_csv(self):
        return "C,{}\n".format(self.mode_override)


# ============================================================
#  解析器
# ============================================================

@dataclass
class CampaignTelemetry:
    """
    Extended telemetry record for campaign-managed runs.
    Backward-compatible: old JSON without these fields loads as legacy.

    Fields:
        campaign_id: active campaign identifier
        run_id:      run within the campaign
        parameter_version: version of the parameter command that was active
        termination_reason: how the run ended (completed, line_lost, safety_stop, timeout, manual_stop)
        tick_ms:    MCU tick at record creation
        sensors:    four line sensor readings (0=black, 1=white)
        error:      current tracking error
        pid_output: PID controller output (scaled x100)
        left_pwm:   left wheel PWM
        right_pwm:  right wheel PWM
    """
    campaign_id: str = ""
    run_id: str = ""
    parameter_version: int = 0
    termination_reason: str = ""
    tick_ms: int = 0
    sensors: tuple = (1, 1, 1, 1)
    error: float = 0.0
    pid_output: float = 0.0
    left_pwm: int = 0
    right_pwm: int = 0

    @staticmethod
    def from_telemetry_packet(pkt: TelemetryPacket,
                               campaign_id: str = "",
                               run_id: str = "",
                               parameter_version: int = 0,
                               termination_reason: str = "") -> "CampaignTelemetry":
        return CampaignTelemetry(
            campaign_id=campaign_id,
            run_id=run_id,
            parameter_version=parameter_version,
            termination_reason=termination_reason,
            tick_ms=pkt.tick_ms,
            sensors=tuple(pkt.sensors),
            error=pkt.error,
            pid_output=pkt.pid_output,
            left_pwm=pkt.left_pwm,
            right_pwm=pkt.right_pwm,
        )

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "run_id": self.run_id,
            "parameter_version": self.parameter_version,
            "termination_reason": self.termination_reason,
            "tick_ms": self.tick_ms,
            "sensors": list(self.sensors),
            "error": self.error,
            "pid_output": self.pid_output,
            "left_pwm": self.left_pwm,
            "right_pwm": self.right_pwm,
        }

    @staticmethod
    def from_dict(data: dict) -> "CampaignTelemetry":
        """Load from dict, tolerating missing fields (legacy JSON)."""
        return CampaignTelemetry(
            campaign_id=data.get("campaign_id", ""),
            run_id=data.get("run_id", ""),
            parameter_version=data.get("parameter_version", 0),
            termination_reason=data.get("termination_reason", ""),
            tick_ms=data.get("tick_ms", 0),
            sensors=tuple(data.get("sensors", (1, 1, 1, 1))),
            error=data.get("error", 0.0),
            pid_output=data.get("pid_output", 0.0),
            left_pwm=data.get("left_pwm", 0),
            right_pwm=data.get("right_pwm", 0),
        )


def parse_line(line):
    """
    解析一行 CSV 数据。
    
    参数:
        line: str - 原始行 (含换行符)
    
    返回:
        (frame_type, packet) 或 None (解析失败)
    """
    line = line.strip()
    if not line:
        return None

    parts = line.split(',')
    if len(parts) < 2:
        return None

    frame_type = parts[0]

    try:
        if frame_type == FRAME_TELEMETRY:
            return _parse_telemetry(parts, line)
        elif frame_type == FRAME_STATUS:
            return _parse_status(parts, line)
        elif frame_type == FRAME_ACK:
            return (FRAME_ACK, parts[1] if len(parts) > 1 else "OK")
        else:
            return None
    except (ValueError, IndexError):
        return None


def _parse_telemetry(parts, raw_line):
    """解析遥测帧: T,s0,s1,s2,s3,left,right,error,pid,tick"""
    if len(parts) < 10:
        return None

    pkt = TelemetryPacket()
    pkt.timestamp = time.monotonic()
    pkt.s0 = int(parts[1])
    pkt.s1 = int(parts[2])
    pkt.s2 = int(parts[3])
    pkt.s3 = int(parts[4])
    pkt.left_pwm = max(0, min(999, int(parts[5])))
    pkt.right_pwm = max(0, min(999, int(parts[6])))
    pkt.error = int(parts[7])
    pkt.pid_output = int(parts[8])
    pkt.tick_ms = int(parts[9])
    pkt.raw_line = raw_line
    return (FRAME_TELEMETRY, pkt)


def _parse_status(parts, raw_line):
    """解析状态帧: S,mode,lost,pos,black,battery"""
    if len(parts) < 6:
        return None

    pkt = StatusPacket()
    pkt.timestamp = time.monotonic()
    pkt.mode = int(parts[1])
    pkt.lost_counter = int(parts[2])
    pkt.position = int(parts[3])
    pkt.black_count = int(parts[4])
    pkt.battery_mv = int(parts[5])
    pkt.raw_line = raw_line
    return (FRAME_STATUS, pkt)


def format_telemetry(s0, s1, s2, s3, left_pwm, right_pwm,
                     error, pid_output, tick_ms):
    """
    格式化遥测帧 (供 STM32 端参考)。
    
    STM32 C 代码中可直接 sprintf:
        printf("T,%d,%d,%d,%d,%d,%d,%d,%d,%d\r\n",
               s0,s1,s2,s3,left_pwm,right_pwm,error,pid_output,tick_ms);
    """
    return "T,{},{},{},{},{},{},{},{},{}\r\n".format(
        s0, s1, s2, s3, left_pwm, right_pwm, error, pid_output, tick_ms)
