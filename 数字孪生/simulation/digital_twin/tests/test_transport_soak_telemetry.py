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
    if length == 26:
        payload[24] = 0x0F
        payload[25] = 0x21
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
