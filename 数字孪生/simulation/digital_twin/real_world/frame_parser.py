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
FRAME_TYPE_IMU_DIAGNOSTIC = 0x7D
FRAME_TYPE_TIMING_DIAGNOSTIC = 0x7F
# Health baseline (Round 2 item 1): 0x02 语义复用。旧 STATUS 是孑遗定义
# （len=7，从未被固件发射）；0x02(len=106) 是新增健康诊断帧。
FRAME_TYPE_HEALTH    = 0x02

# ── 帧头 ──
HEADER_1 = 0xAA
HEADER_2 = 0x55

# ── 载荷长度 ──
PAYLOAD_LEN_TELEMETRY = 24
PAYLOAD_LEN_TELEMETRY_CURRENT = 26
PAYLOAD_LEN_STATUS     = 7
PAYLOAD_LEN_MOTOR_REG_DIAG = 24
PAYLOAD_LEN_IMU_DIAGNOSTIC = 4
PAYLOAD_LEN_TIMING_DIAGNOSTIC = 48
PAYLOAD_LEN_HEALTH     = 106
# 载荷长度上限：原 len>64 拒绝 → 改为 len>106 拒绝（容纳 0x02，设计 §8.2）。
PAYLOAD_LEN_MAX        = 106

# MPU6050 boot status values carried in current telemetry payload byte 25.
MPU6050_INIT_STATUS_OK = 0x00
MPU6050_INIT_STATUS_NOT_ATTEMPTED = 0x01
MPU6050_INIT_STATUS_RESET_WRITE = 0x10
MPU6050_INIT_STATUS_WAKE_WRITE = 0x11
MPU6050_INIT_STATUS_SAMPLE_RATE_WRITE = 0x12
MPU6050_INIT_STATUS_CONFIG_WRITE = 0x13
MPU6050_INIT_STATUS_GYRO_CONFIG_WRITE = 0x14
MPU6050_INIT_STATUS_ACCEL_CONFIG_WRITE = 0x15
MPU6050_INIT_STATUS_WHO_AM_I_READ = 0x20
MPU6050_INIT_STATUS_WHO_AM_I_MISMATCH = 0x21
MPU6050_INIT_STATUS_BIAS_READ = 0x30


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
            elif self._len > PAYLOAD_LEN_MAX:
                # 载荷长度异常, 重新同步
                self._state = self.S_IDLE
                self.frames_bad += 1
                self.resync_count += 1
            elif self._type == FRAME_TYPE_HEALTH and \
                    self._len != PAYLOAD_LEN_HEALTH and \
                    self._len != PAYLOAD_LEN_STATUS:
                # 0x02 联合分流（Round 2 项 1）：仅 7(旧 STATUS)/106(health)
                # 合法；其它 0x02 长度判坏丢弃，绝不广播成 car_status。
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
    if len(payload) not in (PAYLOAD_LEN_TELEMETRY,
                            PAYLOAD_LEN_TELEMETRY_CURRENT):
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
    yaw_deg_x100 = _bytes_to_int32(payload[20], payload[21],
                                   payload[22], payload[23])
    d['yaw'] = yaw_deg_x100 / 100.0
    d['imu_yaw_deg_x100'] = yaw_deg_x100
    d['imu_validity'] = payload[24] if len(payload) == 26 else 0
    d['imu_validity_known'] = len(payload) == 26
    d['imu_init_status'] = payload[25] if len(payload) == 26 else 0
    d['imu_init_status_known'] = len(payload) == 26
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


def decode_health(payload):
    """
    解码 0x02 健康诊断帧 payload (106 bytes)。字段名/单位与 C 布局一致
    (health_frame.h / 设计 §5.2)：含 snapshot_tick_ms 与 health_* 六项。
    全部 LE。
    """
    if len(payload) != PAYLOAD_LEN_HEALTH:
        return None

    return {
        'fw_schema_version': payload[0],
        'fw_build_id': payload[1],
        'reset_cause': payload[2],
        'motion_state': payload[3],
        'lease_active': payload[4],
        'heartbeat_last_reason': payload[5],
        'heartbeat_timeout_count': _bytes_to_uint16(payload[6], payload[7]),
        'heartbeat_count': _bytes_to_uint16(payload[8], payload[9]),
        'heartbeat_age_ms': _bytes_to_uint32(payload[10], payload[11],
                                             payload[12], payload[13]),
        'connection_generation': _bytes_to_uint32(payload[14], payload[15],
                                                  payload[16], payload[17]),
        'snapshot_tick_ms': _bytes_to_uint32(payload[18], payload[19],
                                             payload[20], payload[21]),
        'loop_seq': _bytes_to_uint32(payload[22], payload[23],
                                     payload[24], payload[25]),
        'loop_last_gap_ms': _bytes_to_uint16(payload[26], payload[27]),
        'loop_max_gap_ms': _bytes_to_uint16(payload[28], payload[29]),
        'telemetry_generated': _bytes_to_uint16(payload[30], payload[31]),
        'telemetry_overwritten': _bytes_to_uint16(payload[32], payload[33]),
        'telemetry_tx_started': _bytes_to_uint16(payload[34], payload[35]),
        'telemetry_tx_ok': _bytes_to_uint16(payload[36], payload[37]),
        'telemetry_tx_failed': _bytes_to_uint16(payload[38], payload[39]),
        'cipsend_started': _bytes_to_uint16(payload[40], payload[41]),
        'cipsend_completed': _bytes_to_uint16(payload[42], payload[43]),
        'cipsend_ok': _bytes_to_uint16(payload[44], payload[45]),
        'cipsend_error': _bytes_to_uint16(payload[46], payload[47]),
        'cipsend_prompt_timeout': _bytes_to_uint16(payload[48], payload[49]),
        'cipsend_sendok_timeout': _bytes_to_uint16(payload[50], payload[51]),
        'cipsend_closed': _bytes_to_uint16(payload[52], payload[53]),
        'cipsend_last_duration_ms': _bytes_to_uint32(payload[54], payload[55],
                                                    payload[56], payload[57]),
        'cipsend_max_duration_ms': _bytes_to_uint32(payload[58], payload[59],
                                                   payload[60], payload[61]),
        'ack_started': _bytes_to_uint16(payload[62], payload[63]),
        'status_started': _bytes_to_uint16(payload[64], payload[65]),
        'telemetry_started': _bytes_to_uint16(payload[66], payload[67]),
        'diag_health_started': _bytes_to_uint16(payload[68], payload[69]),
        'status_retry': _bytes_to_uint16(payload[70], payload[71]),
        'ack_retry': _bytes_to_uint16(payload[72], payload[73]),
        'boundary_aborts': _bytes_to_uint16(payload[74], payload[75]),
        'uart_rx_bytes': _bytes_to_uint32(payload[76], payload[77],
                                          payload[78], payload[79]),
        'uart_tx_bytes': _bytes_to_uint32(payload[80], payload[81],
                                          payload[82], payload[83]),
        'uart_rx_overflow': _bytes_to_uint16(payload[84], payload[85]),
        'uart_tx_overflow': _bytes_to_uint16(payload[86], payload[87]),
        'uart_ore_events': _bytes_to_uint16(payload[88], payload[89]),
        'uart_rx_high_water': _bytes_to_uint16(payload[90], payload[91]),
        'uart_tx_high_water': _bytes_to_uint16(payload[92], payload[93]),
        'health_generated': _bytes_to_uint16(payload[94], payload[95]),
        'health_dropped': _bytes_to_uint16(payload[96], payload[97]),
        'health_started': _bytes_to_uint16(payload[98], payload[99]),
        'health_ok': _bytes_to_uint16(payload[100], payload[101]),
        'health_failed': _bytes_to_uint16(payload[102], payload[103]),
        'health_last_duration_ms': _bytes_to_uint16(payload[104], payload[105]),
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


def decode_imu_diagnostic(payload):
    """Decode IMU identity/status plus the hardware-I2C2 identity cross-check."""
    if len(payload) != PAYLOAD_LEN_IMU_DIAGNOSTIC:
        return None

    return {
        'observed_id': payload[0],
        'init_status': payload[1],
        'validity_flags': payload[2],
        'hardware_observed_id': payload[3],
    }


def decode_timing_diagnostic(payload):
    """Decode the additive 0x7F stage/batch timing diagnostic frame."""
    if len(payload) != PAYLOAD_LEN_TIMING_DIAGNOSTIC:
        return None

    values = {}
    offset = 8
    for key in (
        't_imu_start_ms', 't_imu_done_ms', 't_sensor_done_ms',
        't_state_ms', 't_enqueue_ms', 't_tx_start_ms', 't_send_ok_ms',
        'batch_first_tick_ms', 'batch_last_tick_ms', 'sample_seq',
    ):
        values[key] = _bytes_to_uint32(
            payload[offset], payload[offset + 1],
            payload[offset + 2], payload[offset + 3])
        offset += 4

    return {
        'schema_version': payload[0],
        'flags': payload[1],
        'batch_id': _bytes_to_uint16(payload[2], payload[3]),
        'batch_count': payload[4],
        'pending_count': payload[5],
        'overwrite_total': _bytes_to_uint16(payload[6], payload[7]),
        **values,
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
