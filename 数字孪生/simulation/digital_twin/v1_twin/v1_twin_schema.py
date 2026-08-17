"""V1 数字孪生数据契约 (Task 4B-0)。

不可变数据结构 + JSON 序列化。单位硬约束（纲领 §6a 数据空间硬约束 / §12）：
- 位置: mm（地面二维坐标，原点由标定确定）
- 角度: rad（内部连续 rad，不转 degree 存储）
- PC 时间: ns（`time.monotonic_ns()`）
- MCU tick: ms（固件 `g_loop_count * LOOP_DELAY_MS`）
- error: 与固件 `error` 定义一致（原始误差单位）
- sensors: 0/1，唯一权威定义见固件 `main.c` 的 `SENSOR_THRESHOLD`（§12 第五项）

所有序列化载荷均携带 `schema_version`（§12 第二项）。

时间同步（§12 第四项）：禁止按数组下标拼合相机与遥测；同步必须通过独立
时间戳关联 `pc_ns ↔ mcu_tick_ms`。因此 `V1TelemetryFrame` 除 §6a Produces
所列核心字段外，额外携带 `pc_recv_ns`（PC 侧接收时间），用于 4B-4 时间同步。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from v1_twin.v1_twin_errors import (
    V1CalibrationHoldoutOverlapError,
    V1SchemaError,
)
from v1_twin.v1_twin_vehicle_geometry import VehicleBodyRectangle

# Task 4B-4 fix: bumped 1.0.0 → 1.1.0.
#   - V1TelemetryFrame 新增 yaw_rad（rad，可选；旧 JSON 缺失 → None = legacy/unknown）
#   - V1TelemetryFrame.pwm 改为有符号 int（负值表示轮子反转，不再钳零）
# 兼容行为：schema 1.0.0 旧 JSON（无 yaw、pwm 非负）仍可加载；
# from_dict 保留存储的 schema_version（可追溯数据来源）。
SCHEMA_VERSION = "1.1.0"
SENSOR_COUNT = 4
PWM_COUNT = 4


# ============================================================
# Validation helpers
# ============================================================


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V1SchemaError(message)


def _require_finite(value: Any, name: str) -> None:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value),
        "{0} must be a finite number".format(name),
    )


def _require_int(value: Any, name: str) -> None:
    _require(isinstance(value, int) and not isinstance(value, bool),
             "{0} must be an int".format(name))


def _require_binary(value: Any, name: str) -> None:
    _require(isinstance(value, int) and value in (0, 1),
             "{0} must be 0 or 1".format(name))


def _require_confidence(value: Any) -> None:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and 0.0 <= value <= 1.0,
        "confidence must be finite and within [0, 1]",
    )


def _require_run_id(value: Any) -> None:
    _require(isinstance(value, str) and value != "",
             "run_id must be a non-empty string")


def _require_schema_version(value: Any) -> None:
    _require(isinstance(value, str) and value != "",
             "schema_version must be a non-empty string")


# ============================================================
# Enums
# ============================================================


class V1SyncQuality(Enum):
    """同步数据点关联质量。"""
    OK = "ok"
    DEGRADED = "degraded"
    MISSING = "missing"


# ============================================================
# Data structures
# ============================================================


@dataclass(frozen=True)
class V1Pose:
    """车顶标记二维位姿真值。

    单位: x_mm/y_mm=mm（地面二维坐标，原点由标定确定）；yaw_rad=rad（连续，
    不转 degree 存储）；t_pc_ns=ns（PC monotonic clock）。confidence ∈ [0,1]。
    """
    x_mm: float
    y_mm: float
    yaw_rad: float
    confidence: float
    t_pc_ns: int
    source: str = "camera"                # "camera" | "simulated"
    schema_version: str = SCHEMA_VERSION
    body_rectangle: Optional[VehicleBodyRectangle] = None

    def __post_init__(self) -> None:
        _require_finite(self.x_mm, "x_mm")
        _require_finite(self.y_mm, "y_mm")
        _require_finite(self.yaw_rad, "yaw_rad")
        _require_confidence(self.confidence)
        _require_int(self.t_pc_ns, "t_pc_ns")
        _require(self.t_pc_ns >= 0, "t_pc_ns must be >= 0")
        _require(self.source in ("camera", "simulated"),
                 "source must be 'camera' or 'simulated'")
        _require_schema_version(self.schema_version)
        if self.body_rectangle is not None:
            _require(isinstance(self.body_rectangle, VehicleBodyRectangle),
                     "body_rectangle must be a VehicleBodyRectangle")

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "type": "V1Pose",
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "yaw_rad": self.yaw_rad,
            "confidence": self.confidence,
            "t_pc_ns": self.t_pc_ns,
            "source": self.source,
            "schema_version": self.schema_version,
        }
        if self.body_rectangle is not None:
            result["body_rectangle"] = self.body_rectangle.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V1Pose":
        body_rectangle_data = data.get("body_rectangle")
        body_rectangle = None
        if body_rectangle_data is not None:
            if not isinstance(body_rectangle_data, Mapping):
                raise V1SchemaError(
                    "body_rectangle must be an object or null"
                )
            try:
                body_rectangle = VehicleBodyRectangle.from_dict(body_rectangle_data)
            except KeyError as exc:
                raise V1SchemaError(
                    "body_rectangle is missing required field: {0}".format(exc.args[0])
                ) from exc
        return cls(
            x_mm=data["x_mm"],
            y_mm=data["y_mm"],
            yaw_rad=data["yaw_rad"],
            confidence=data["confidence"],
            t_pc_ns=data["t_pc_ns"],
            source=data.get("source", "camera"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            body_rectangle=body_rectangle,
        )


@dataclass(frozen=True)
class V1TelemetryFrame:
    """固件遥测帧。

    sensors[4]: 0/1，唯一权威定义=固件 `main.c` 的 `SENSOR_THRESHOLD`（§12 第五项）。
    error: 原始误差单位，与固件 error 定义一致。
    pid_output: PID 输出（固件量纲）。
    pwm[4]: 四路有符号 PWM（int16 语义，负值表示轮子反转）。
        固件 m1-m4 为 int16 可负；钳零会丢失方向信息（Task 4B-4 fix）。
    tick_ms: MCU tick，单位 ms（固件单调毫秒源；历史数据为 `g_loop_count * LOOP_DELAY_MS`）。
    pc_recv_ns: PC 侧接收时间，单位 ns（`time.monotonic_ns()`）。供 4B-4 用
        `pc_ns ↔ mcu_tick_ms` 独立时间戳关联（§12 第四项）。
    yaw_rad: 固件 IMU yaw（deg×100 int32 → rad），可选。
        - 新采集数据填充：rad 连续角。
        - 旧 JSON（schema 1.0.0）无该字段 → None，表示 legacy/unknown，
          不伪造真实值（Task 4B-4 fix）。
    """
    sensors: Tuple[int, int, int, int]
    error: float
    pid_output: float
    pwm: Tuple[int, int, int, int]
    tick_ms: int
    pc_recv_ns: int
    yaw_rad: Optional[float] = None
    schema_version: str = SCHEMA_VERSION
    imu_yaw_deg_x100: Optional[int] = None
    imu_validity: int = 0
    imu_validity_known: bool = False
    imu_init_status: int = 0
    imu_init_status_known: bool = False

    def __post_init__(self) -> None:
        _require(len(self.sensors) == SENSOR_COUNT,
                 "sensors must have exactly {0} entries".format(SENSOR_COUNT))
        for i, s in enumerate(self.sensors):
            _require_binary(s, "sensors[{0}]".format(i))
        _require_finite(self.error, "error")
        _require_finite(self.pid_output, "pid_output")
        _require(len(self.pwm) == PWM_COUNT,
                 "pwm must have exactly {0} entries".format(PWM_COUNT))
        for i, p in enumerate(self.pwm):
            _require_int(p, "pwm[{0}]".format(i))
        _require_int(self.tick_ms, "tick_ms")
        _require(self.tick_ms >= 0, "tick_ms must be >= 0")
        _require_int(self.pc_recv_ns, "pc_recv_ns")
        _require(self.pc_recv_ns >= 0, "pc_recv_ns must be >= 0")
        if self.yaw_rad is not None:
            _require_finite(self.yaw_rad, "yaw_rad")
        if self.imu_yaw_deg_x100 is not None:
            _require_int(self.imu_yaw_deg_x100, "imu_yaw_deg_x100")
            _require(-2147483648 <= self.imu_yaw_deg_x100 <= 2147483647,
                     "imu_yaw_deg_x100 must fit int32")
        _require_int(self.imu_validity, "imu_validity")
        _require(0 <= self.imu_validity <= 0xFF,
                 "imu_validity must fit uint8")
        _require(isinstance(self.imu_validity_known, bool),
                 "imu_validity_known must be bool")
        _require_int(self.imu_init_status, "imu_init_status")
        _require(0 <= self.imu_init_status <= 0xFF,
                 "imu_init_status must fit uint8")
        _require(isinstance(self.imu_init_status_known, bool),
                 "imu_init_status_known must be bool")
        _require_schema_version(self.schema_version)

    @property
    def imu_yaw_rad(self) -> Optional[float]:
        """Normalized IMU yaw in radians; eligibility is controlled by flags."""
        return self.yaw_rad

    @property
    def yaw_known(self) -> bool:
        """yaw_rad 是否来自真实固件数据（None = legacy/unknown）。"""
        return self.yaw_rad is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "V1TelemetryFrame",
            "sensors": list(self.sensors),
            "error": self.error,
            "pid_output": self.pid_output,
            "pwm": list(self.pwm),
            "tick_ms": self.tick_ms,
            "pc_recv_ns": self.pc_recv_ns,
            "yaw_rad": self.yaw_rad,
            "imu_yaw_rad": self.imu_yaw_rad,
            "imu_yaw_deg_x100": self.imu_yaw_deg_x100,
            "imu_validity": self.imu_validity,
            "imu_validity_known": self.imu_validity_known,
            "imu_init_status": self.imu_init_status,
            "imu_init_status_known": self.imu_init_status_known,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V1TelemetryFrame":
        return cls(
            sensors=tuple(data["sensors"]),
            error=data["error"],
            pid_output=data["pid_output"],
            pwm=tuple(data["pwm"]),
            tick_ms=data["tick_ms"],
            pc_recv_ns=data["pc_recv_ns"],
            yaw_rad=data.get("yaw_rad", data.get("imu_yaw_rad")),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            imu_yaw_deg_x100=data.get("imu_yaw_deg_x100"),
            imu_validity=data.get("imu_validity", 0),
            imu_validity_known=data.get("imu_validity_known", False),
            imu_init_status=data.get("imu_init_status", 0),
            imu_init_status_known=data.get("imu_init_status_known", False),
        )


@dataclass(frozen=True)
class V1SyncFrame:
    """同步数据点：位姿 + 遥测 + 关联质量。

    通过 pose.t_pc_ns（PC ns）↔ telemetry.tick_ms（MCU ms）独立时间戳关联
    （§12 第四项），禁止按数组下标拼合。
    """
    pose: V1Pose
    telemetry: V1TelemetryFrame
    sync_quality: V1SyncQuality
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(isinstance(self.pose, V1Pose), "pose must be a V1Pose")
        _require(isinstance(self.telemetry, V1TelemetryFrame),
                 "telemetry must be a V1TelemetryFrame")
        _require(isinstance(self.sync_quality, V1SyncQuality),
                 "sync_quality must be a V1SyncQuality")
        _require_schema_version(self.schema_version)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "V1SyncFrame",
            "pose": self.pose.to_dict(),
            "telemetry": self.telemetry.to_dict(),
            "sync_quality": self.sync_quality.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V1SyncFrame":
        try:
            quality = V1SyncQuality(data["sync_quality"])
        except ValueError as exc:
            raise V1SchemaError(
                "invalid sync_quality: {0!r}".format(data["sync_quality"])
            ) from exc
        return cls(
            pose=V1Pose.from_dict(data["pose"]),
            telemetry=V1TelemetryFrame.from_dict(data["telemetry"]),
            sync_quality=quality,
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class V1SensorModelConfig:
    """虚拟四路传感器几何配置。

    lateral_offsets_mm[4]: 四传感器相对车体中心线的横向偏移（mm）。
    sensor_bar_fore_aft_mm: 传感器横梁相对车体原点的前后偏移（mm，前为 +）。
    threshold: 灰度二值化阈值，唯一权威定义=固件 `SENSOR_THRESHOLD`（§12 第五项）。
    """
    lateral_offsets_mm: Tuple[float, float, float, float]
    sensor_bar_fore_aft_mm: float = 0.0
    threshold: float = 0.5
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(len(self.lateral_offsets_mm) == SENSOR_COUNT,
                 "lateral_offsets_mm must have exactly {0} entries".format(SENSOR_COUNT))
        for i, off in enumerate(self.lateral_offsets_mm):
            _require_finite(off, "lateral_offsets_mm[{0}]".format(i))
        _require_finite(self.sensor_bar_fore_aft_mm, "sensor_bar_fore_aft_mm")
        _require_finite(self.threshold, "threshold")
        _require_schema_version(self.schema_version)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "V1SensorModelConfig",
            "lateral_offsets_mm": list(self.lateral_offsets_mm),
            "sensor_bar_fore_aft_mm": self.sensor_bar_fore_aft_mm,
            "threshold": self.threshold,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V1SensorModelConfig":
        return cls(
            lateral_offsets_mm=tuple(data["lateral_offsets_mm"]),
            sensor_bar_fore_aft_mm=data.get("sensor_bar_fore_aft_mm", 0.0),
            threshold=data.get("threshold", 0.5),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class V1TrackMap:
    """赛道地图：俯视二值掩码 + 中心线点列 + 宽度。

    mask: 二值掩码（行=沿赛道方向），0/1，所有行等长。
    centerline_mm: 中心线点列 (x_mm, y_mm)，单位 mm。
    width_mm: 赛道宽度（mm），> 0。
    """
    mask: Tuple[Tuple[int, ...], ...]
    centerline_mm: Tuple[Tuple[float, float], ...]
    width_mm: float
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.mask:
            raise V1SchemaError("mask must not be empty")
        row_len = len(self.mask[0])
        for row in self.mask:
            _require(len(row) == row_len, "mask rows must have equal length")
            for v in row:
                _require_binary(v, "mask value")
        for pt in self.centerline_mm:
            _require(len(pt) == 2, "centerline point must be (x_mm, y_mm)")
            _require_finite(pt[0], "centerline x_mm")
            _require_finite(pt[1], "centerline y_mm")
        _require_finite(self.width_mm, "width_mm")
        _require(self.width_mm > 0.0, "width_mm must be > 0")
        _require_schema_version(self.schema_version)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "V1TrackMap",
            "mask": [list(row) for row in self.mask],
            "centerline_mm": [list(pt) for pt in self.centerline_mm],
            "width_mm": self.width_mm,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V1TrackMap":
        return cls(
            mask=tuple(tuple(row) for row in data["mask"]),
            centerline_mm=tuple(tuple(pt) for pt in data["centerline_mm"]),
            width_mm=data["width_mm"],
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class V1CalibrationSet:
    """校准集 run_id 清单（§12 第三项：按 run_id 完全隔离）。"""
    run_ids: frozenset
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for rid in self.run_ids:
            _require_run_id(rid)
        _require_schema_version(self.schema_version)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "V1CalibrationSet",
            "run_ids": sorted(self.run_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V1CalibrationSet":
        return cls(
            run_ids=frozenset(data["run_ids"]),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class V1HoldoutSet:
    """最终 holdout run_id 清单（§6i：模型冻结后追加全新 PID 组的 run_id）。

    与校准集交集必须为空（§12 第三项）；由 assert_disjoint 强制检查。
    """
    run_ids: frozenset
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for rid in self.run_ids:
            _require_run_id(rid)
        _require_schema_version(self.schema_version)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "V1HoldoutSet",
            "run_ids": sorted(self.run_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V1HoldoutSet":
        return cls(
            run_ids=frozenset(data["run_ids"]),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class V1ModelVersion:
    """冻结模型版本标识（§6h / §12 第二项）。"""
    model_name: str
    version: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(isinstance(self.model_name, str) and self.model_name != "",
                 "model_name must be a non-empty string")
        _require(isinstance(self.version, str) and self.version != "",
                 "version must be a non-empty string")
        _require_schema_version(self.schema_version)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "V1ModelVersion",
            "model_name": self.model_name,
            "version": self.version,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V1ModelVersion":
        return cls(
            model_name=data["model_name"],
            version=data["version"],
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


# ============================================================
# Calibration / holdout 隔离硬检查（§12 第三项）
# ============================================================


def assert_disjoint(calibration: V1CalibrationSet, holdout: V1HoldoutSet) -> None:
    """校准集与 holdout 的 run_id 交集必须为空，否则抛错。

    这是 Task 4B-7 程序硬检查的基础：同一数据不可既训练又验收。
    """
    if not isinstance(calibration, V1CalibrationSet):
        raise V1SchemaError("calibration must be a V1CalibrationSet")
    if not isinstance(holdout, V1HoldoutSet):
        raise V1SchemaError("holdout must be a V1HoldoutSet")
    overlap = sorted(calibration.run_ids & holdout.run_ids)
    if overlap:
        raise V1CalibrationHoldoutOverlapError(
            "calibration and holdout run_id sets overlap: {0}".format(
                ", ".join(overlap)
            )
        )


# ============================================================
# JSON serialization helpers
# ============================================================


def to_json(obj: Any) -> str:
    """序列化任意带 to_dict() 的 V1 数据结构为紧凑 JSON 字符串。"""
    if not hasattr(obj, "to_dict"):
        raise V1SchemaError("to_json expects an object with to_dict()")
    return json.dumps(
        obj.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def from_json(text: str, cls: type) -> Any:
    """从 JSON 字符串反序列化为 *cls* 实例（cls 需带 from_dict()）。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise V1SchemaError("invalid JSON: {0}".format(exc)) from exc
    if not isinstance(data, dict):
        raise V1SchemaError("serialized payload must be a JSON object")
    if not hasattr(cls, "from_dict"):
        raise V1SchemaError(
            "from_json expects a class with from_dict(): {0}".format(cls.__name__)
        )
    return cls.from_dict(data)
