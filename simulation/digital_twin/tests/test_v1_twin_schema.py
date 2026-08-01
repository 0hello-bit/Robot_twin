"""Tests for V1 数字孪生数据契约 (Task 4B-0 schema)。

先写测试后实现：模块尚不存在时应 RED。

覆盖（纲领 §6a 卡片 / §12 数据与模型设计硬约束）：
- 每个数据结构的 JSON 往返
- frozen 不可变性
- 字段/单位校验（§6a 数据空间硬约束：位置 mm、角度 rad、PC 时间 ns、MCU tick ms）
- sensors 0/1 二进制（权威定义=固件 SENSOR_THRESHOLD，§12 第五项）
- 校准/holdout 按 run_id 完全隔离（§12 第三项）
- schema_version 始终序列化（§12 第二项）
- Produces 清单中全部数据结构对外暴露
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dataclasses import FrozenInstanceError

import pytest

from v1_twin.v1_twin_schema import (
    SCHEMA_VERSION,
    V1Pose,
    V1TelemetryFrame,
    V1SyncFrame,
    V1SyncQuality,
    V1SensorModelConfig,
    V1TrackMap,
    V1CalibrationSet,
    V1HoldoutSet,
    V1ModelVersion,
    assert_disjoint,
    to_json,
    from_json,
)
from v1_twin.v1_twin_errors import (
    V1SchemaError,
    V1CalibrationHoldoutOverlapError,
)


# ============================================================
# Test data helpers
# ============================================================


def make_pose(**kw):
    base = dict(x_mm=12.5, y_mm=-3.25, yaw_rad=0.314, confidence=0.97,
                t_pc_ns=1234567890123)
    base.update(kw)
    return V1Pose(**base)


def make_telemetry(**kw):
    base = dict(sensors=(1, 1, 0, 1), error=-2.5, pid_output=31.0,
                pwm=(400, 400, 300, 300), tick_ms=1234, pc_recv_ns=999)
    base.update(kw)
    return V1TelemetryFrame(**base)


def make_sensor_config(**kw):
    base = dict(lateral_offsets_mm=(-15.0, -5.0, 5.0, 15.0),
                sensor_bar_fore_aft_mm=0.0, threshold=0.5)
    base.update(kw)
    return V1SensorModelConfig(**base)


def make_track_map(**kw):
    base = dict(mask=((0, 0, 1, 1, 0, 0), (0, 1, 1, 1, 1, 0)),
                centerline_mm=((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)),
                width_mm=60.0)
    base.update(kw)
    return V1TrackMap(**base)


# ============================================================
# Contract completeness — Produces 清单（纲领 §6a）
# ============================================================


def test_contract_exposes_all_required_types():
    from v1_twin import v1_twin_schema as s
    required = [
        "V1Pose", "V1TelemetryFrame", "V1SyncFrame",
        "V1SensorModelConfig", "V1TrackMap",
        "V1CalibrationSet", "V1HoldoutSet", "V1ModelVersion",
    ]
    for name in required:
        assert hasattr(s, name), "missing required type: {0}".format(name)


# ============================================================
# JSON round-trips
# ============================================================


def test_pose_json_round_trip():
    pose = make_pose()
    restored = from_json(to_json(pose), V1Pose)
    assert restored == pose
    assert restored is not pose


def test_telemetry_json_round_trip():
    tel = make_telemetry()
    restored = from_json(to_json(tel), V1TelemetryFrame)
    assert restored == tel


def test_sync_frame_json_round_trip():
    frame = V1SyncFrame(pose=make_pose(), telemetry=make_telemetry(),
                        sync_quality=V1SyncQuality.DEGRADED)
    restored = from_json(to_json(frame), V1SyncFrame)
    assert restored == frame
    assert restored.pose.x_mm == frame.pose.x_mm
    assert restored.telemetry.tick_ms == frame.telemetry.tick_ms
    assert restored.sync_quality is V1SyncQuality.DEGRADED


def test_sensor_config_json_round_trip():
    cfg = make_sensor_config()
    restored = from_json(to_json(cfg), V1SensorModelConfig)
    assert restored == cfg
    assert tuple(restored.lateral_offsets_mm) == (-15.0, -5.0, 5.0, 15.0)


def test_track_map_json_round_trip():
    track = make_track_map()
    restored = from_json(to_json(track), V1TrackMap)
    assert restored == track
    assert restored.mask == ((0, 0, 1, 1, 0, 0), (0, 1, 1, 1, 1, 0))
    assert restored.width_mm == 60.0


def test_calibration_set_json_round_trip():
    cal = V1CalibrationSet(run_ids=frozenset({"run-01", "run-02", "run-03"}))
    restored = from_json(to_json(cal), V1CalibrationSet)
    assert restored == cal
    assert restored.run_ids == frozenset({"run-01", "run-02", "run-03"})


def test_holdout_set_json_round_trip():
    hold = V1HoldoutSet(run_ids=frozenset({"run-99", "run-98"}))
    restored = from_json(to_json(hold), V1HoldoutSet)
    assert restored == hold
    assert restored.run_ids == frozenset({"run-99", "run-98"})


def test_model_version_json_round_trip():
    version = V1ModelVersion(model_name="v1_twin", version="1.2.0")
    restored = from_json(to_json(version), V1ModelVersion)
    assert restored == version
    assert restored.schema_version == SCHEMA_VERSION


# ============================================================
# Immutability
# ============================================================


def test_pose_is_frozen():
    pose = make_pose()
    with pytest.raises(FrozenInstanceError):
        pose.x_mm = 0.0  # type: ignore[misc]


def test_telemetry_sensors_are_tuples_not_lists():
    tel = make_telemetry()
    assert isinstance(tel.sensors, tuple)
    assert isinstance(tel.pwm, tuple)
    assert isinstance(make_track_map().mask, tuple)


# ============================================================
# Unit / field validation（§6a 数据空间硬约束）
# ============================================================


def test_units_annotated_in_field_names():
    # 位置 mm、角度 rad、PC 时间 ns、MCU tick ms 必须以字段后缀体现
    pose = make_pose().to_dict()
    assert "x_mm" in pose and "y_mm" in pose
    assert "yaw_rad" in pose
    assert "t_pc_ns" in pose
    tel = make_telemetry().to_dict()
    assert "tick_ms" in tel
    assert "pc_recv_ns" in tel


def test_pose_rejects_nan_and_inf():
    with pytest.raises(V1SchemaError):
        make_pose(x_mm=float("nan"))
    with pytest.raises(V1SchemaError):
        make_pose(yaw_rad=float("inf"))
    with pytest.raises(V1SchemaError):
        make_pose(y_mm=float("-inf"))


def test_pose_rejects_negative_pc_time():
    with pytest.raises(V1SchemaError):
        make_pose(t_pc_ns=-1)


def test_pose_rejects_out_of_range_confidence():
    with pytest.raises(V1SchemaError):
        make_pose(confidence=1.5)
    with pytest.raises(V1SchemaError):
        make_pose(confidence=-0.1)


def test_telemetry_sensors_must_be_exactly_four_binary_values():
    with pytest.raises(V1SchemaError):
        make_telemetry(sensors=(1, 1, 1))
    with pytest.raises(V1SchemaError):
        make_telemetry(sensors=(1, 2, 0, 1))
    with pytest.raises(V1SchemaError):
        make_telemetry(sensors=("1", 1, 0, 1))


def test_telemetry_pwm_must_be_exactly_four_ints():
    with pytest.raises(V1SchemaError):
        make_telemetry(pwm=(400, 400, 300))
    with pytest.raises(V1SchemaError):
        make_telemetry(pwm=(400, 400.5, 300, 300))


def test_telemetry_pwm_allows_signed_values():
    """Task 4B-4 fix: 固件 m1-m4 为 int16 可负（反转时）。

    负 PWM 表示轮子反转，钳零会丢失方向信息（review 事实 #9）。
    V1TelemetryFrame 必须保留有符号四路 PWM，不得钳零丢方向。
    """
    tel = make_telemetry(pwm=(-400, 300, 250, -250))
    assert tel.pwm == (-400, 300, 250, -250)
    restored = from_json(to_json(tel), V1TelemetryFrame)
    assert restored.pwm == (-400, 300, 250, -250)


def test_telemetry_rejects_nan_error():
    with pytest.raises(V1SchemaError):
        make_telemetry(error=float("nan"))


# ============================================================
# yaw 字段（Task 4B-4 fix: 保存固件已有 yaw，旧 JSON 标 legacy）
# ============================================================


def test_telemetry_yaw_round_trip():
    """固件遥测帧携带 yaw（deg×100 → rad），schema 保存 yaw_rad。"""
    tel = make_telemetry(yaw_rad=0.25)
    restored = from_json(to_json(tel), V1TelemetryFrame)
    assert restored.yaw_rad == pytest.approx(0.25)
    assert restored == tel


def test_telemetry_yaw_defaults_unknown_for_legacy():
    """旧 JSON 没有 yaw 字段 → yaw_rad 必须是 None（legacy/unknown），
    不得伪造真实值（review 事实 #8、任务 C.2）。"""
    tel = make_telemetry()
    assert tel.yaw_rad is None


def test_telemetry_old_json_without_yaw_loads_as_legacy():
    """schema 1.0.0 旧 JSON（无 yaw、pwm 非负）必须仍可加载。"""
    old = {
        "type": "V1TelemetryFrame",
        "sensors": [1, 1, 0, 1],
        "error": -2.5,
        "pid_output": 31.0,
        "pwm": [400, 400, 300, 300],
        "tick_ms": 1234,
        "pc_recv_ns": 999,
        "schema_version": "1.0.0",
    }
    tel = from_json(json.dumps(old), V1TelemetryFrame)
    assert tel.yaw_rad is None
    assert tel.pwm == (400, 400, 300, 300)
    assert tel.schema_version == "1.0.0"


def test_telemetry_yaw_rejects_nan():
    with pytest.raises(V1SchemaError):
        make_telemetry(yaw_rad=float("nan"))
    with pytest.raises(V1SchemaError):
        make_telemetry(yaw_rad=float("inf"))


def test_track_map_rejects_nonpositive_width():
    with pytest.raises(V1SchemaError):
        make_track_map(width_mm=0.0)
    with pytest.raises(V1SchemaError):
        make_track_map(width_mm=-5.0)


def test_track_map_rejects_ragged_mask_rows():
    with pytest.raises(V1SchemaError):
        make_track_map(mask=((0, 1, 1, 0, 0), (0, 1, 1)))


def test_track_map_rejects_non_binary_mask():
    with pytest.raises(V1SchemaError):
        make_track_map(mask=((0, 2, 1, 1, 0, 0),))


def test_sensor_config_rejects_wrong_sensor_count():
    with pytest.raises(V1SchemaError):
        make_sensor_config(lateral_offsets_mm=(-15.0, -5.0, 5.0))


# ============================================================
# Calibration / holdout run_id 隔离（§12 第三项）
# ============================================================


def test_disjoint_sets_pass():
    cal = V1CalibrationSet(run_ids=frozenset({"run-01", "run-02"}))
    hold = V1HoldoutSet(run_ids=frozenset({"run-99", "run-98"}))
    assert_disjoint(cal, hold)  # 不应抛异常


def test_overlapping_sets_raise():
    cal = V1CalibrationSet(run_ids=frozenset({"run-01", "run-02"}))
    hold = V1HoldoutSet(run_ids=frozenset({"run-02", "run-03"}))
    with pytest.raises(V1CalibrationHoldoutOverlapError):
        assert_disjoint(cal, hold)


# ============================================================
# schema_version 始终序列化（§12 第二项）
# ============================================================


def test_all_serialized_payloads_carry_schema_version():
    objects = [
        make_pose(),
        make_telemetry(),
        make_sensor_config(),
        make_track_map(),
        V1CalibrationSet(run_ids=frozenset({"r1"})),
        V1HoldoutSet(run_ids=frozenset({"r2"})),
        V1ModelVersion(model_name="m", version="1"),
    ]
    for obj in objects:
        payload = json.loads(to_json(obj))
        assert payload["schema_version"] == SCHEMA_VERSION
