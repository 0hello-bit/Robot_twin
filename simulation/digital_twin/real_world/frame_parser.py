# -*- coding: utf-8 -*-
"""
frame_parser.py - 二进制帧字节流解析器 (状态机)

功能:
    1. 从连续字节流中识别 0xAA 0x55 帧头
    2. 校验 XOR checksum
    3. 自动丢弃坏帧, 重新同步
    4. 处理粘包 (多个帧拼在一起)
    5. 处理半包 (帧被截断)
    6. 零依赖, 纯 Python

设计原则:
    - 状态机驱动, 每次只处理一个字节
    - 不使用 readline(), 不依赖 \n 分隔
    - 适用于蓝牙/串口等不可靠链路

使用方式:
    parser = FrameParser()

    # 在串口读取循环中:
    while serial.in_waiting > 0:
        byte = serial.read(1)
        result = parser.feed(byte[0])
        if result is not None:
            frame_type, payload = result
            # 处理帧...
"""

import time


# ── 帧类型常量 ──
FRAME_TYPE_TELEMETRY = 0x01
FRAME_TYPE_STATUS    = 0x02
FRAME_TYPE_ACK       = 0x03
FRAME_TYPE_MOTOR_REG_DIAG = 0x7E

# ── 帧头 ──
HEADER_1 = 0xAA
HEADER_2 = 0x55

# ── 载荷长度 ──
PAYLOAD_LEN_TELEMETRY = 24
PAYLOAD_LEN_STATUS     = 7
PAYLOAD_LEN_MOTOR_REG_DIAG = 24


class FrameParser:
    """
    二进制帧字节流解析器。

    状态机:
        IDLE        → 等待 0xAA
        GOT_HEADER1 → 等待 0x55
        GOT_HEADER2 → 等待 TYPE
        GOT_TYPE    → 等待 LEN
        GOT_LEN     → 接收 PAYLOAD
        GOT_PAYLOAD → 等待 CHECKSUM

    每次 feed() 一个字节, 返回:
        (frame_type, payload_bytes)  — 一帧完整
        None                         — 还在接收中
    """

    # 状态常量
    S_IDLE        = 0
    S_GOT_HEADER1 = 1
    S_GOT_HEADER2 = 2
    S_GOT_TYPE    = 3
    S_GOT_LEN     = 4
    S_GOT_PAYLOAD = 5

    def __init__(self):
        self._state = self.S_IDLE
        self._type = 0
        self._len = 0
        self._payload = bytearray()
        self._checksum = 0

        # 统计
        self.frames_ok = 0
        self.frames_bad = 0
        self.bytes_total = 0
        self.resync_count = 0

    def reset(self):
        """重置解析器状态"""
        self._state = self.S_IDLE
        self._type = 0
        self._len = 0
        self._payload = bytearray()
        self._checksum = 0

    def feed(self, byte_val):
        """
        喂入一个字节, 返回解析结果。

        参数:
            byte_val: int (0~255)

        返回:
            (frame_type, payload) — 完整帧
            None — 还在接收中
        """
        self.bytes_total += 1
        b = byte_val & 0xFF

        if self._state == self.S_IDLE:
            if b == HEADER_1:
                self._state = self.S_GOT_HEADER1
            # else: 丢弃, 继续等待

        elif self._state == self.S_GOT_HEADER1:
            if b == HEADER_2:
                self._state = self.S_GOT_HEADER2
            elif b == HEADER_1:
                # 连续 0xAA, 保持在 GOT_HEADER1
                pass
            else:
                self._state = self.S_IDLE
                self.resync_count += 1

        elif self._state == self.S_GOT_HEADER2:
            self._type = b
            self._state = self.S_GOT_TYPE

        elif self._state == self.S_GOT_TYPE:
            self._len = b
            self._payload = bytearray()
            if self._len == 0:
                # 零长度载荷, 直接等校验
                self._state = self.S_GOT_PAYLOAD
            elif self._len > 64:
                # 载荷长度异常, 重新同步
                self._state = self.S_IDLE
                self.frames_bad += 1
                self.resync_count += 1
            else:
                self._state = self.S_GOT_LEN

        elif self._state == self.S_GOT_LEN:
            self._payload.append(b)
            if len(self._payload) >= self._len:
                self._state = self.S_GOT_PAYLOAD

        elif self._state == self.S_GOT_PAYLOAD:
            # 收到校验字节, 验证
            self._checksum = b
            if self._verify_checksum():
                self.frames_ok += 1
                self._state = self.S_IDLE
                result = (self._type, bytes(self._payload))
                return result
            else:
                # 校验失败, 重新同步
                self.frames_bad += 1
                self.resync_count += 1
                self._state = self.S_IDLE

        return None

    def _verify_checksum(self):
        """验证 XOR 校验: type XOR len XOR payload[0..N] == checksum"""
        cs = self._type ^ self._len
        for b in self._payload:
            cs ^= b
        return cs == self._checksum

    def feed_buffer(self, data):
        """
        一次性喂入多个字节 (用于测试/批量处理)。

        参数:
            data: bytes 或 bytearray

        返回:
            list of (frame_type, payload)
        """
        results = []
        for b in data:
            r = self.feed(b)
            if r is not None:
                results.append(r)
        return results

    def get_stats(self):
        """获取解析统计"""
        total = self.frames_ok + self.frames_bad
        rate = self.frames_bad / max(total, 1) * 100
        return {
            'frames_ok': self.frames_ok,
            'frames_bad': self.frames_bad,
            'bytes_total': self.bytes_total,
            'resync_count': self.resync_count,
            'error_rate_pct': round(rate, 2),
        }


# ══════════════════════════════════════════════════════════════
#  帧解码器
# ══════════════════════════════════════════════════════════════

def decode_telemetry(payload):
    """
    解码遥测帧 payload (24 bytes)。

    返回:
        dict: {s0, s1, s2, s3, m1, m2, m3, m4, error, pid_output, tick_ms, yaw}
    """
    if len(payload) < PAYLOAD_LEN_TELEMETRY:
        return None

    d = {
        's0': payload[0],
        's1': payload[1],
        's2': payload[2],
        's3': payload[3],
        'm1': _bytes_to_int16(payload[4], payload[5]),
        'm2': _bytes_to_int16(payload[6], payload[7]),
        'm3': _bytes_to_int16(payload[8], payload[9]),
        'm4': _bytes_to_int16(payload[10], payload[11]),
        'error': _bytes_to_int16(payload[12], payload[13]),
        'pid_output': _bytes_to_int16(payload[14], payload[15]),
        'tick_ms': _bytes_to_uint32(payload[16], payload[17],
                                     payload[18], payload[19]),
    }
    if len(payload) >= 24:
        d['yaw'] = _bytes_to_int32(payload[20], payload[21],
                                    payload[22], payload[23]) / 100.0
    else:
        d['yaw'] = 0.0
    return d


def decode_status(payload):
    """
    解码状态帧 payload (7 bytes)。

    返回:
        dict: {mode, lost, position, black, battery}
    """
    if len(payload) < PAYLOAD_LEN_STATUS:
        return None

    return {
        'mode': payload[0],
        'lost': payload[1],
        'position': _bytes_to_int16(payload[2], payload[3]),
        'black': payload[4],
        'battery': _bytes_to_uint16(payload[5], payload[6]),
    }


def decode_ack(payload):
    """解码 ACK 帧 payload"""
    try:
        return payload.decode('ascii', errors='ignore')
    except Exception:
        return ''


def decode_motor_register_diag(payload):
    """
    解码电机寄存器诊断帧 payload (24 bytes: 12 × uint16 LE).

    返回:
        dict: {tim2_cr1, tim2_arr, tim2_ccr1, tim2_ccr2, tim2_ccr3, tim2_ccr4,
               tim4_cr1, tim4_arr, tim4_ccr1, tim4_ccr2, tim4_ccr3, tim4_ccr4}
    """
    if len(payload) < PAYLOAD_LEN_MOTOR_REG_DIAG:
        return None

    regs = [_bytes_to_uint16(payload[i * 2], payload[i * 2 + 1]) for i in range(12)]
    return {
        'tim2_cr1':  regs[0],
        'tim2_arr':  regs[1],
        'tim2_ccr1': regs[2],
        'tim2_ccr2': regs[3],
        'tim2_ccr3': regs[4],
        'tim2_ccr4': regs[5],
        'tim4_cr1':  regs[6],
        'tim4_arr':  regs[7],
        'tim4_ccr1': regs[8],
        'tim4_ccr2': regs[9],
        'tim4_ccr3': regs[10],
        'tim4_ccr4': regs[11],
    }


# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

def _bytes_to_int16(lo, hi):
    """小端 int16 解码"""
    val = lo | (hi << 8)
    if val >= 0x8000:
        val -= 0x10000
    return val


def _bytes_to_uint16(lo, hi):
    """小端 uint16 解码"""
    return lo | (hi << 8)


def _bytes_to_int32(b0, b1, b2, b3):
    val = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24)
    if val >= 0x80000000:
        val -= 0x100000000
    return val


def _bytes_to_uint32(b0, b1, b2, b3):
    """小端 uint32 解码"""
    return b0 | (b1 << 8) | (b2 << 16) | (b3 << 24)