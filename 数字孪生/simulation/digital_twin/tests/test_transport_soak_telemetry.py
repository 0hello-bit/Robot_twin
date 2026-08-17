"""Regression tests for the transport soak telemetry evidence boundary."""

from __future__ import annotations

import math
import os
import sys

import pytest

SHUTDOWN_TOOLCHAIN = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "tools", "shakedown_toolchain"
)
sys.path.insert(0, SHUTDOWN_TOOLCHAIN)

import transport_soak as ts  # noqa: E402


def _payload(length=26, yaw_deg_x100=-1234):
    payload = bytearray(length)
    payload[16:20] = (9876).to_bytes(4, "little")
    payload[20:24] = yaw_deg_x100.to_bytes(4, "little", signed=True)
    if length in (26, 42):
        payload[24] = 0x0F
        payload[25] = 0x21
    if length == 42:
        for offset, value in zip(
            range(26, 38, 2), (-32768, -1, 0, 1, 32767, -2222)
        ):
            payload[offset:offset + 2] = value.to_bytes(
                2, "little", signed=True)
        payload[38:42] = (0xF1234567).to_bytes(4, "little")
    return bytes(payload)


def _decode_with_session(payload):
    session = ts._SessionCtx(ts._ScriptedTransport(), ts.RawIoLogger())
    session._on_telemetry(payload)
    assert len(session.frames) == 1
    return session.frames[0]


def test_transport_soak_records_explicit_yaw_units_and_imu_evidence():
    record = _decode_with_session(_payload())

    assert record["yaw_deg"] == pytest.approx(-12.34)
    assert record["yaw_rad"] == pytest.approx(math.radians(-12.34))
    assert record["imu_yaw_deg_x100"] == -1234
    assert record["imu_validity"] == 0x0F
    assert record["imu_validity_known"] is True
    assert record["imu_init_status"] == 0x21
    assert record["imu_init_status_known"] is True


def test_transport_soak_marks_legacy_telemetry_imu_fields_unknown():
    record = _decode_with_session(_payload(length=24, yaw_deg_x100=250))

    assert record["yaw_deg"] == pytest.approx(2.5)
    assert record["yaw_rad"] == pytest.approx(math.radians(2.5))
    assert record["imu_yaw_deg_x100"] == 250
    assert record["imu_validity_known"] is False
    assert record["imu_init_status_known"] is False


def test_transport_soak_records_extended_raw_imu_fields():
    record = _decode_with_session(_payload(length=42))

    assert record["imu_ax_raw"] == -32768
    assert record["imu_ay_raw"] == -1
    assert record["imu_az_raw"] == 0
    assert record["imu_gx_raw"] == 1
    assert record["imu_gy_raw"] == 32767
    assert record["imu_gz_raw"] == -2222
    assert record["sample_seq"] == 0xF1234567
    assert record["imu_raw_known"] is True
