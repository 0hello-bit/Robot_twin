import re
from pathlib import Path
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from v1_twin.v1_twin_errors import V1SchemaError  # noqa: E402
from v1_twin.v1_twin_schema import (  # noqa: E402
    SCHEMA_VERSION,
    V1TelemetryFrame,
)


RAW_FIELDS = (
    "imu_ax_raw",
    "imu_ay_raw",
    "imu_az_raw",
    "imu_gx_raw",
    "imu_gy_raw",
    "imu_gz_raw",
)


def make_frame(**overrides):
    values = {
        "sensors": (1, 0, 1, 0),
        "error": -7.0,
        "pid_output": 8.0,
        "pwm": (-321, 654, -123, 456),
        "tick_ms": 987654,
        "pc_recv_ns": 1_700_000_000_000,
        "yaw_rad": -1.25,
    }
    values.update(overrides)
    return V1TelemetryFrame(**values)


def test_raw_imu_fields_round_trip_through_v1_telemetry_schema():
    frame = make_frame(
        imu_ax_raw=-32768,
        imu_ay_raw=-1,
        imu_az_raw=0,
        imu_gx_raw=1,
        imu_gy_raw=32767,
        imu_gz_raw=-2222,
        sample_seq=0xF1234567,
        imu_raw_known=True,
    )

    encoded = frame.to_dict()
    restored = V1TelemetryFrame.from_dict(encoded)

    assert SCHEMA_VERSION == "1.2.0"
    assert encoded["imu_raw_known"] is True
    assert encoded["sample_seq"] == 0xF1234567
    assert restored == frame


def test_legacy_telemetry_dict_defaults_new_imu_fields_to_unknown():
    legacy = make_frame(schema_version="1.1.0").to_dict()
    for key in (*RAW_FIELDS, "sample_seq", "imu_raw_known"):
        legacy.pop(key, None)

    restored = V1TelemetryFrame.from_dict(legacy)

    assert all(getattr(restored, key) is None for key in RAW_FIELDS)
    assert restored.sample_seq is None
    assert restored.imu_raw_known is False
    assert restored.schema_version == "1.1.0"


@pytest.mark.parametrize(
    "field,value",
    [(RAW_FIELDS[0], -32769), (RAW_FIELDS[-1], 32768), ("sample_seq", -1),
     ("sample_seq", 0x1_0000_0000)],
)
def test_new_imu_fields_validate_wire_ranges(field, value):
    with pytest.raises(V1SchemaError, match=field):
        make_frame(**{field: value})


def test_binary_capture_callback_passes_all_extended_imu_fields():
    capture_source = Path(__file__).resolve().parents[3] / "tools" / \
        "camera_toolchain" / "capture_sync_run.py"
    source = capture_source.read_text(encoding="utf-8")
    match = re.search(
        r"frame = V1TelemetryFrame\((?P<body>.*?)\n        \)",
        source,
        re.DOTALL,
    )
    assert match is not None
    body = match.group("body")
    for field in RAW_FIELDS:
        assert f"{field}=" in body
        assert f'd["{field}"]' in body
    assert "sample_seq=" in body
    assert 'd["sample_seq"]' in body
    assert "imu_raw_known=bool(d[\"imu_raw_known\"])" in body
