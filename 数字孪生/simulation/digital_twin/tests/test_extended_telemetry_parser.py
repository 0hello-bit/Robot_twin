import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from real_world.frame_parser import (  # noqa: E402
    FRAME_TYPE_TELEMETRY,
    PAYLOAD_LEN_TELEMETRY,
    PAYLOAD_LEN_TELEMETRY_CURRENT,
    PAYLOAD_LEN_TELEMETRY_EXTENDED,
    FrameParser,
    decode_telemetry,
)


def build_frame(payload):
    body = bytes([0xAA, 0x55, FRAME_TYPE_TELEMETRY, len(payload)])
    checksum = FRAME_TYPE_TELEMETRY ^ len(payload)
    for value in payload:
        checksum ^= value
    return body + bytes(payload) + bytes([checksum & 0xFF])


def make_extended_payload(sample_seq=0xF1234567, tick_ms=987654):
    payload = bytearray(PAYLOAD_LEN_TELEMETRY_EXTENDED)
    payload[0:4] = bytes([1, 0, 1, 0])
    for offset, value in ((4, -321), (6, 654), (8, -123), (10, 456)):
        payload[offset:offset + 2] = value.to_bytes(2, "little", signed=True)
    payload[12:14] = (-77).to_bytes(2, "little", signed=True)
    payload[14:16] = (88).to_bytes(2, "little", signed=True)
    payload[16:20] = tick_ms.to_bytes(4, "little")
    payload[20:24] = (-12345).to_bytes(4, "little", signed=True)
    payload[24] = 0x0F
    payload[25] = 0x21
    for offset, value in zip(
        range(26, 38, 2), (-32768, -1, 0, 1, 32767, -2222)
    ):
        payload[offset:offset + 2] = value.to_bytes(2, "little", signed=True)
    payload[38:42] = sample_seq.to_bytes(4, "little")
    return payload


def test_extended_telemetry_decodes_raw_imu_and_sample_sequence():
    payload = make_extended_payload()

    parser = FrameParser()
    results = parser.feed_buffer(build_frame(payload))

    assert len(results) == 1
    decoded = decode_telemetry(results[0][1])
    assert decoded["imu_ax_raw"] == -32768
    assert decoded["imu_ay_raw"] == -1
    assert decoded["imu_az_raw"] == 0
    assert decoded["imu_gx_raw"] == 1
    assert decoded["imu_gy_raw"] == 32767
    assert decoded["imu_gz_raw"] == -2222
    assert decoded["sample_seq"] == 0xF1234567
    assert decoded["imu_raw_known"] is True
    assert decoded["imu_yaw_deg_x100"] == -12345
    assert decoded["imu_validity"] == 0x0F
    assert decoded["imu_init_status"] == 0x21


def test_legacy_telemetry_lengths_keep_raw_imu_unknown():
    for length in (PAYLOAD_LEN_TELEMETRY, PAYLOAD_LEN_TELEMETRY_CURRENT):
        decoded = decode_telemetry(bytes(length))
        assert decoded["imu_ax_raw"] is None
        assert decoded["imu_ay_raw"] is None
        assert decoded["imu_az_raw"] is None
        assert decoded["imu_gx_raw"] is None
        assert decoded["imu_gy_raw"] is None
        assert decoded["imu_gz_raw"] is None
        assert decoded["sample_seq"] is None
        assert decoded["imu_raw_known"] is False


def test_three_extended_telemetry_frames_parse_individually():
    frames = [
        build_frame(make_extended_payload(sample_seq=seq, tick_ms=tick))
        for seq, tick in ((1, 100), (2, 120), (3, 140))
    ]

    parser = FrameParser()
    results = parser.feed_buffer(b"".join(frames))

    assert len(results) == 3
    assert parser.frames_ok == 3
    assert parser.frames_bad == 0
    assert [decode_telemetry(payload)["sample_seq"] for _, payload in results] == [
        1, 2, 3
    ]
