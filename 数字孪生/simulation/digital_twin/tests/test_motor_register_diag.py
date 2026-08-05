"""Tests for motor-register diagnostic frame (type 0x7E) parsing.

Verifies:
  - FrameParser successfully parses a valid type-0x7E frame
  - decode_motor_register_diag correctly decodes 12 uint16 LE values
  - Deterministic values round-trip correctly
  - Checksum validation passes
  - Unknown type 0x7E does not break existing frame types
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from real_world.frame_parser import (
    FrameParser,
    FRAME_TYPE_MOTOR_REG_DIAG,
    decode_motor_register_diag,
    PAYLOAD_LEN_MOTOR_REG_DIAG,
)


def _build_0x7e_frame(regs):
    """Build a complete AA55 type-0x7E frame from 12 uint16 register values."""
    payload = bytearray()
    for val in regs:
        payload.append(val & 0xFF)
        payload.append((val >> 8) & 0xFF)
    assert len(payload) == PAYLOAD_LEN_MOTOR_REG_DIAG

    cs = FRAME_TYPE_MOTOR_REG_DIAG ^ PAYLOAD_LEN_MOTOR_REG_DIAG
    for b in payload:
        cs ^= b

    frame = bytearray()
    frame.append(0xAA)
    frame.append(0x55)
    frame.append(FRAME_TYPE_MOTOR_REG_DIAG)
    frame.append(PAYLOAD_LEN_MOTOR_REG_DIAG)
    frame.extend(payload)
    frame.append(cs)
    return bytes(frame)


def test_frame_parser_detects_type_0x7e():
    """FrameParser should return type 0x7E for a valid diagnostic frame."""
    regs = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    frame = _build_0x7e_frame(regs)
    parser = FrameParser()
    results = parser.feed_buffer(frame)
    assert len(results) == 1
    frame_type, payload = results[0]
    assert frame_type == FRAME_TYPE_MOTOR_REG_DIAG
    assert len(payload) == PAYLOAD_LEN_MOTOR_REG_DIAG


def test_decode_zero_values():
    """All-zero registers should decode to all zeros."""
    regs = [0] * 12
    frame = _build_0x7e_frame(regs)
    parser = FrameParser()
    _, payload = parser.feed_buffer(frame)[0]
    d = decode_motor_register_diag(payload)
    for key, val in d.items():
        assert val == 0, f"{key} should be 0, got {val}"


def test_decode_deterministic_values():
    """Deterministic values 1..12 should decode correctly."""
    regs = list(range(1, 13))
    frame = _build_0x7e_frame(regs)
    parser = FrameParser()
    _, payload = parser.feed_buffer(frame)[0]
    d = decode_motor_register_diag(payload)
    assert d["tim2_cr1"] == 1
    assert d["tim2_arr"] == 2
    assert d["tim2_ccr1"] == 3
    assert d["tim2_ccr2"] == 4
    assert d["tim2_ccr3"] == 5
    assert d["tim2_ccr4"] == 6
    assert d["tim4_cr1"] == 7
    assert d["tim4_arr"] == 8
    assert d["tim4_ccr1"] == 9
    assert d["tim4_ccr2"] == 10
    assert d["tim4_ccr3"] == 11
    assert d["tim4_ccr4"] == 12


def test_decode_large_values():
    """Values that span both bytes should verify LE decoding."""
    regs = [0xABCD, 0x0102, 0xF0F0, 0x1234, 0x5678, 0x9ABC,
            0xDEAD, 0xBEEF, 0xCAFE, 0xBA98, 0x7654, 0x3210]
    frame = _build_0x7e_frame(regs)
    parser = FrameParser()
    _, payload = parser.feed_buffer(frame)[0]
    d = decode_motor_register_diag(payload)
    assert d["tim2_cr1"] == 0xABCD
    assert d["tim2_ccr4"] == 0x9ABC
    assert d["tim4_cr1"] == 0xDEAD
    assert d["tim4_arr"] == 0xBEEF
    assert d["tim4_ccr4"] == 0x3210


def test_unknown_type_0x7e_does_not_disrupt_telemetry():
    """A type-0x7E frame should not affect subsequent type-0x01 telemetry parsing."""
    # Build a 0x7E frame
    regs = [0] * 12
    diag_frame = _build_0x7e_frame(regs)

    # Build a normal telemetry frame (type 0x01)
    tel_payload = bytearray(24)
    tel_cs = 0x01 ^ 24
    for b in tel_payload:
        tel_cs ^= b
    tel_frame = bytearray()
    tel_frame.append(0xAA)
    tel_frame.append(0x55)
    tel_frame.append(0x01)  # telemetry type
    tel_frame.append(24)
    tel_frame.extend(tel_payload)
    tel_frame.append(tel_cs)

    combined = diag_frame + bytes(tel_frame)
    parser = FrameParser()
    results = parser.feed_buffer(combined)
    assert len(results) == 2
    assert results[0][0] == FRAME_TYPE_MOTOR_REG_DIAG
    assert results[1][0] == 0x01


def test_bad_checksum_rejected():
    """Frame with invalid XOR checksum should be rejected by FrameParser."""
    regs = [0] * 12
    frame = bytearray(_build_0x7e_frame(regs))
    # Corrupt the checksum byte
    frame[-1] ^= 0xFF
    parser = FrameParser()
    results = parser.feed_buffer(bytes(frame))
    assert len(results) == 0  # rejected
    assert parser.frames_bad == 1
