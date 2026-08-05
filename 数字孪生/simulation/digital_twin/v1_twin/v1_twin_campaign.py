"""Offline V1-B campaign contracts.

This module is the boundary between future real capture artifacts and the
existing V1 identification/model-registry interfaces.  It validates
metadata, raw-file provenance, stream units, timestamps, and calibration /
holdout separation.  It never opens a camera, socket, serial port, debugger,
or vehicle-control channel.

Synthetic fixtures are accepted only as ``SYNTHETIC_ONLY`` contract tests.
They cannot produce a real-calibration or twin-readiness verdict.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .v1_twin_errors import V1SchemaError
from .v1_twin_calibration_set import V1RunSplit, V1RunSplitError
from .v1_twin_schema import V1Pose, V1TelemetryFrame


CAMPAIGN_SCHEMA_VERSION = "v1b-manifest-1.0"
PROFILE_SCHEMA_VERSION = 1
RAW_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

RUN_TYPES = frozenset(("SMOKE", "CALIBRATION", "HOLDOUT", "EXCITATION"))
DATASET_PARTITIONS = frozenset(("calibration", "holdout", "excluded"))
DATA_ORIGINS = frozenset(("REAL_CAPTURE", "SYNTHETIC_TEST"))
RUN_STATUSES = frozenset(("DECLARED", "CAPTURED", "OFFLINE_FIXTURE", "INVALID"))
RAW_FILE_KINDS = frozenset(("pose", "telemetry", "camera_frames", "sync_report", "other"))
TRACK_SEGMENTS = frozenset(
    ("STRAIGHT", "ORDINARY_CURVE", "TARGET_HIGH_SPEED_ACUTE_CURVE")
)

# These are the units already used by the V1 schema.  The manifest repeats
# them so a future collector cannot silently reinterpret a raw stream.
DEFAULT_UNIT_CONTRACT = {
    "pc_time": "ns",
    "mcu_tick": "ms",
    "pose_position": "mm",
    "pose_yaw": "rad",
    "pwm": "signed_count",
    "pose_coordinate_frame": "track_ground_xy",
    "camera_to_ground_transform": "versioned_homography",
}


class V1BManifestError(ValueError):
    """Raised when a V1-B manifest or acceptance profile is malformed."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise V1BManifestError(f"{field} must be a non-empty string")
    return value


def _safe_id(value: Any, field: str) -> str:
    result = _text(value, field)
    if not SAFE_ID_RE.fullmatch(result):
        raise V1BManifestError(
            f"{field} must contain only ASCII letters, digits, '_' or '-': {result!r}"
        )
    return result


def _sha256(value: Any, field: str) -> str:
    result = _text(value, field)
    if not RAW_HASH_RE.fullmatch(result):
        raise V1BManifestError(f"{field} must be a 64-character SHA-256 hex string")
    return result.lower()


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 of one file without changing it."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _non_bool_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise V1BManifestError(f"{field} must be an int")
    return value


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V1BManifestError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise V1BManifestError(f"{field} must be finite")
    return result


def _utc_timestamp(value: Any, field: str) -> str:
    result = _text(value, field)
    if not result.endswith("Z"):
        raise V1BManifestError(f"{field} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(result[:-1] + "+00:00")
    except ValueError as exc:
        raise V1BManifestError(f"{field} is not a valid RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise V1BManifestError(f"{field} must use UTC")
    return result


def _relative_path(value: Any, field: str) -> str:
    result = _text(value, field)
    if "\\" in result:
        raise V1BManifestError(f"{field} must use '/' separators")
    path = PurePosixPath(result)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise V1BManifestError(f"{field} must be a workspace-relative path")
    if path.parts[0] == "derived":
        raise V1BManifestError(f"{field} must point to raw evidence, not derived/")
    return path.as_posix()


def _unique_ids(values: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise V1BManifestError(f"{field} must be a list of run IDs")
    result = tuple(_safe_id(value, f"{field}[{index}]") for index, value in enumerate(values))
    if not allow_empty and not result:
        raise V1BManifestError(f"{field} must not be empty")
    if len(set(result)) != len(result):
        raise V1BManifestError(f"duplicate run ID in {field}")
    return result


def _segments(values: Any, field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise V1BManifestError(f"{field} must be a list")
    result = tuple(_text(value, f"{field}[{index}]").upper() for index, value in enumerate(values))
    if len(set(result)) != len(result):
        raise V1BManifestError(f"duplicate track segment in {field}")
    unknown = set(result) - TRACK_SEGMENTS
    if unknown:
        raise V1BManifestError(f"unknown track segment(s) in {field}: {sorted(unknown)}")
    return result


def _interval(value: Any, field: str) -> tuple[int, int]:
    if not isinstance(value, Mapping):
        raise V1BManifestError(f"{field} must be an object")
    start_value = value.get("start_pc_ns", value.get("start"))
    end_value = value.get("end_pc_ns", value.get("end"))
    start = _non_bool_int(start_value, f"{field}.start_pc_ns")
    end = _non_bool_int(end_value, f"{field}.end_pc_ns")
    if start < 0 or end <= start:
        raise V1BManifestError(f"{field} must have 0 <= start < end")
    return start, end


@dataclass(frozen=True)
class V1BRawFile:
    """Hash and size record for one immutable raw artifact."""

    path: str
    kind: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _relative_path(self.path, "raw_files.path"))
        object.__setattr__(self, "kind", _text(self.kind, "raw_files.kind"))
        if self.kind not in RAW_FILE_KINDS:
            raise V1BManifestError(f"unknown raw file kind: {self.kind}")
        object.__setattr__(self, "sha256", _sha256(self.sha256, "raw_files.sha256"))
        size = _non_bool_int(self.size_bytes, "raw_files.size_bytes")
        if size < 0:
            raise V1BManifestError("raw_files.size_bytes must be >= 0")
        object.__setattr__(self, "size_bytes", size)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "V1BRawFile":
        try:
            return cls(
                path=data["path"],
                kind=data["kind"],
                sha256=data["sha256"],
                size_bytes=data["size_bytes"],
            )
        except KeyError as exc:
            raise V1BManifestError(f"raw_files missing field: {exc.args[0]}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class V1BRunManifest:
    """One session manifest; raw files remain outside this object."""

    schema_version: str
    run_id: str
    run_type: str
    dataset_partition: str
    data_origin: str
    robot_id: str
    track_id: str
    track_map_version: str
    firmware_sha256: str
    controller_version: str
    input_profile_id: str
    camera_config_hash: str
    calibration_set_id: str | None
    holdout_set_id: str | None
    started_at_utc: str
    duration_s: float
    authorization_reference: str
    sample_interval_pc_ns: tuple[int, int]
    covered_track_segments: tuple[str, ...]
    unit_contract: tuple[tuple[str, str], ...]
    raw_files: tuple[V1BRawFile, ...]
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != CAMPAIGN_SCHEMA_VERSION:
            raise V1BManifestError(
                f"unsupported run manifest schema_version: {self.schema_version!r}"
            )
        _safe_id(self.run_id, "run_id")
        if self.run_type not in RUN_TYPES:
            raise V1BManifestError(f"unknown run_type: {self.run_type!r}")
        if self.dataset_partition not in DATASET_PARTITIONS:
            raise V1BManifestError(
                f"unknown dataset_partition: {self.dataset_partition!r}"
            )
        if self.run_type == "SMOKE" and self.dataset_partition != "excluded":
            raise V1BManifestError("SMOKE runs must use dataset_partition='excluded'")
        if self.run_type == "CALIBRATION" and self.dataset_partition != "calibration":
            raise V1BManifestError("CALIBRATION runs must use calibration partition")
        if self.run_type == "HOLDOUT" and self.dataset_partition != "holdout":
            raise V1BManifestError("HOLDOUT runs must use holdout partition")
        if self.run_type == "EXCITATION" and self.dataset_partition == "excluded":
            raise V1BManifestError("EXCITATION must belong to calibration or holdout")
        if self.data_origin not in DATA_ORIGINS:
            raise V1BManifestError(f"unknown data_origin: {self.data_origin!r}")
        for field in (
            "robot_id",
            "track_id",
            "track_map_version",
            "controller_version",
            "input_profile_id",
            "authorization_reference",
        ):
            _text(getattr(self, field), field)
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(self, "firmware_sha256", _sha256(self.firmware_sha256, "firmware_sha256"))
        object.__setattr__(self, "camera_config_hash", _sha256(self.camera_config_hash, "camera_config_hash"))
        object.__setattr__(self, "started_at_utc", _utc_timestamp(self.started_at_utc, "started_at_utc"))
        duration = _finite_number(self.duration_s, "duration_s")
        if duration < 0.0:
            raise V1BManifestError("duration_s must be >= 0")
        object.__setattr__(self, "duration_s", duration)
        start, end = self.sample_interval_pc_ns
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
            raise V1BManifestError("sample_interval_pc_ns must contain integer ns values")
        if start < 0 or end <= start:
            raise V1BManifestError("sample_interval_pc_ns must have 0 <= start < end")
        object.__setattr__(self, "sample_interval_pc_ns", (start, end))
        normalized_segments = _segments(self.covered_track_segments, "covered_track_segments")
        object.__setattr__(self, "covered_track_segments", normalized_segments)
        units = dict(self.unit_contract)
        if units != DEFAULT_UNIT_CONTRACT:
            raise V1BManifestError(
                "unit contract must exactly match V1 schema; mixed or missing units are not allowed"
            )
        object.__setattr__(self, "unit_contract", tuple(sorted(units.items())))
        if not self.raw_files:
            raise V1BManifestError("raw_files must not be empty")
        if len({item.path for item in self.raw_files}) != len(self.raw_files):
            raise V1BManifestError("duplicate raw file path")
        if self.dataset_partition == "calibration":
            if not self.calibration_set_id or self.holdout_set_id is not None:
                raise V1BManifestError("calibration run must identify only calibration_set_id")
        elif self.dataset_partition == "holdout":
            if not self.holdout_set_id or self.calibration_set_id is not None:
                raise V1BManifestError("holdout run must identify only holdout_set_id")
        elif self.calibration_set_id is not None or self.holdout_set_id is not None:
            raise V1BManifestError("excluded run must not identify a calibration or holdout set")
        status = _text(self.status, "status")
        if status in ("READY", "TWIN_USABLE") or status not in RUN_STATUSES:
            raise V1BManifestError(f"unsupported or unsafe run status: {status!r}")
        object.__setattr__(self, "status", status)
        if self.dataset_partition in ("calibration", "holdout"):
            kinds = {item.kind for item in self.raw_files}
            if not {"pose", "telemetry"}.issubset(kinds):
                raise V1BManifestError("calibration/holdout raw_files require pose and telemetry")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "V1BRunManifest":
        try:
            raw_files_value = data["raw_files"]
            if isinstance(raw_files_value, (str, bytes)) or not isinstance(raw_files_value, Sequence):
                raise V1BManifestError("raw_files must be a list")
            raw_files = tuple(V1BRawFile.from_dict(item) for item in raw_files_value)
            interval = _interval(data["sample_interval_pc_ns"], "sample_interval_pc_ns")
            units = data["unit_contract"]
            if not isinstance(units, Mapping):
                raise V1BManifestError("unit_contract must be an object")
            return cls(
                schema_version=data["schema_version"],
                run_id=data["run_id"],
                run_type=data["run_type"],
                dataset_partition=data["dataset_partition"],
                data_origin=data["data_origin"],
                robot_id=data["robot_id"],
                track_id=data["track_id"],
                track_map_version=data["track_map_version"],
                firmware_sha256=data["firmware_sha256"],
                controller_version=data["controller_version"],
                input_profile_id=data["input_profile_id"],
                camera_config_hash=data["camera_config_hash"],
                calibration_set_id=data["calibration_set_id"],
                holdout_set_id=data["holdout_set_id"],
                started_at_utc=data["started_at_utc"],
                duration_s=data["duration_s"],
                authorization_reference=data["authorization_reference"],
                sample_interval_pc_ns=interval,
                covered_track_segments=tuple(data["covered_track_segments"]),
                unit_contract=tuple((str(key), value) for key, value in units.items()),
                raw_files=raw_files,
                status=data["status"],
            )
        except KeyError as exc:
            raise V1BManifestError(f"run manifest missing field: {exc.args[0]}") from exc

    def to_dict(self) -> dict[str, Any]:
        start, end = self.sample_interval_pc_ns
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "run_type": self.run_type,
            "dataset_partition": self.dataset_partition,
            "data_origin": self.data_origin,
            "robot_id": self.robot_id,
            "track_id": self.track_id,
            "track_map_version": self.track_map_version,
            "firmware_sha256": self.firmware_sha256,
            "controller_version": self.controller_version,
            "input_profile_id": self.input_profile_id,
            "camera_config_hash": self.camera_config_hash,
            "calibration_set_id": self.calibration_set_id,
            "holdout_set_id": self.holdout_set_id,
            "started_at_utc": self.started_at_utc,
            "duration_s": self.duration_s,
            "authorization_reference": self.authorization_reference,
            "sample_interval_pc_ns": {
                "start_pc_ns": start,
                "end_pc_ns": end,
            },
            "covered_track_segments": list(self.covered_track_segments),
            "unit_contract": dict(self.unit_contract),
            "raw_files": [item.to_dict() for item in self.raw_files],
            "status": self.status,
        }


@dataclass(frozen=True)
class V1BSyncGate:
    common_coverage_min: float
    p95_time_diff_ms_max: float
    timestamps_monotonic_required: bool
    pose_and_telemetry_non_empty: bool
    camera_fourcc: str
    camera_width_px: int
    camera_height_px: int
    camera_fps: float
    stop_confirmed_required: bool
    one_time_cleanup_required: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "V1BSyncGate":
        try:
            coverage = _finite_number(data["common_coverage_min"], "sync_gate.common_coverage_min")
            p95 = _finite_number(data["p95_time_diff_ms_max"], "sync_gate.p95_time_diff_ms_max")
            width = _non_bool_int(data["camera_width_px"], "sync_gate.camera_width_px")
            height = _non_bool_int(data["camera_height_px"], "sync_gate.camera_height_px")
            fps = _finite_number(data["camera_fps"], "sync_gate.camera_fps")
            if not 0.0 < coverage <= 1.0 or p95 <= 0.0:
                raise V1BManifestError("sync gate numeric thresholds are invalid")
            if width <= 0 or height <= 0 or fps <= 0.0:
                raise V1BManifestError("sync gate camera dimensions/fps are invalid")
            if data["camera_fourcc"] != "MJPG":
                raise V1BManifestError("sync gate camera_fourcc must be MJPG")
            return cls(
                common_coverage_min=coverage,
                p95_time_diff_ms_max=p95,
                timestamps_monotonic_required=data["timestamps_monotonic_required"],
                pose_and_telemetry_non_empty=data["pose_and_telemetry_non_empty"],
                camera_fourcc=data["camera_fourcc"],
                camera_width_px=width,
                camera_height_px=height,
                camera_fps=fps,
                stop_confirmed_required=data["stop_confirmed_required"],
                one_time_cleanup_required=data["one_time_cleanup_required"],
            )
        except KeyError as exc:
            raise V1BManifestError(f"sync_gate missing field: {exc.args[0]}") from exc

    def __post_init__(self) -> None:
        for field in (
            "timestamps_monotonic_required",
            "pose_and_telemetry_non_empty",
            "stop_confirmed_required",
            "one_time_cleanup_required",
        ):
            if not isinstance(getattr(self, field), bool):
                raise V1BManifestError(f"sync_gate.{field} must be bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "common_coverage_min": self.common_coverage_min,
            "p95_time_diff_ms_max": self.p95_time_diff_ms_max,
            "timestamps_monotonic_required": self.timestamps_monotonic_required,
            "pose_and_telemetry_non_empty": self.pose_and_telemetry_non_empty,
            "camera_fourcc": self.camera_fourcc,
            "camera_width_px": self.camera_width_px,
            "camera_height_px": self.camera_height_px,
            "camera_fps": self.camera_fps,
            "stop_confirmed_required": self.stop_confirmed_required,
            "one_time_cleanup_required": self.one_time_cleanup_required,
        }


@dataclass(frozen=True)
class V1BModelGate:
    lateral_error_p95_mm_max: float
    rms_relative_error_max: float
    max_relative_error_max: float
    completion_time_relative_error_max: float
    min_unseen_groups: int
    nominal_improvement_min_relative: float
    primary_outputs: tuple[str, ...]
    no_regression_outputs: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "V1BModelGate":
        try:
            values = {
                field: _finite_number(data[field], f"model_gate.{field}")
                for field in (
                    "lateral_error_p95_mm_max",
                    "rms_relative_error_max",
                    "max_relative_error_max",
                    "completion_time_relative_error_max",
                    "nominal_improvement_min_relative",
                )
            }
            groups = _non_bool_int(data["min_unseen_groups"], "model_gate.min_unseen_groups")
            primary = tuple(_text(value, "model_gate.primary_outputs[]") for value in data["primary_outputs"])
            no_regression = tuple(_text(value, "model_gate.no_regression_outputs[]") for value in data["no_regression_outputs"])
        except KeyError as exc:
            raise V1BManifestError(f"model_gate missing field: {exc.args[0]}") from exc
        if any(value <= 0.0 for value in values.values()) or any(value > 1.0 for field, value in values.items() if field != "lateral_error_p95_mm_max"):
            raise V1BManifestError("model gate numeric thresholds are invalid")
        if groups < 1 or not primary or not no_regression:
            raise V1BManifestError("model gate coverage/output declarations are invalid")
        return cls(
            **values,
            min_unseen_groups=groups,
            primary_outputs=primary,
            no_regression_outputs=no_regression,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lateral_error_p95_mm_max": self.lateral_error_p95_mm_max,
            "rms_relative_error_max": self.rms_relative_error_max,
            "max_relative_error_max": self.max_relative_error_max,
            "completion_time_relative_error_max": self.completion_time_relative_error_max,
            "min_unseen_groups": self.min_unseen_groups,
            "nominal_improvement_min_relative": self.nominal_improvement_min_relative,
            "primary_outputs": list(self.primary_outputs),
            "no_regression_outputs": list(self.no_regression_outputs),
        }


@dataclass(frozen=True)
class V1BInputProfile:
    profile_id: str
    command_unit: str
    speed_command_min: int
    speed_command_max: int
    required_track_segments: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "V1BInputProfile":
        try:
            profile_id = _safe_id(data["profile_id"], "input_profiles.profile_id")
            unit = _text(data["command_unit"], "input_profiles.command_unit")
            speed_min = _non_bool_int(data["speed_command_min"], "input_profiles.speed_command_min")
            speed_max = _non_bool_int(data["speed_command_max"], "input_profiles.speed_command_max")
            segments = _segments(data["required_track_segments"], "input_profiles.required_track_segments")
        except KeyError as exc:
            raise V1BManifestError(f"input profile missing field: {exc.args[0]}") from exc
        if unit != "speed_cap_pwm_command" or speed_min < 260 or speed_max > 680 or speed_max <= speed_min:
            raise V1BManifestError("input profile must use the bounded speed_cap_pwm_command range 260..680")
        return cls(profile_id, unit, speed_min, speed_max, segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "command_unit": self.command_unit,
            "speed_command_min": self.speed_command_min,
            "speed_command_max": self.speed_command_max,
            "required_track_segments": list(self.required_track_segments),
        }


@dataclass(frozen=True)
class V1BCampaignRules:
    minimum_calibration_runs: int
    minimum_holdout_runs: int
    minimum_distinct_input_profiles: int
    required_track_segments: tuple[str, ...]
    each_run_must_cover_all_segments: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "V1BCampaignRules":
        try:
            calibration = _non_bool_int(data["minimum_calibration_runs"], "campaign.minimum_calibration_runs")
            holdout = _non_bool_int(data["minimum_holdout_runs"], "campaign.minimum_holdout_runs")
            profiles = _non_bool_int(data["minimum_distinct_input_profiles"], "campaign.minimum_distinct_input_profiles")
            segments = _segments(data["required_track_segments"], "campaign.required_track_segments")
            each_run = data["each_run_must_cover_all_segments"]
        except KeyError as exc:
            raise V1BManifestError(f"campaign rules missing field: {exc.args[0]}") from exc
        if calibration < 3 or holdout < 2 or profiles < 2 or not isinstance(each_run, bool):
            raise V1BManifestError("campaign rules are below the frozen first-campaign minimum")
        return cls(calibration, holdout, profiles, segments, each_run)

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum_calibration_runs": self.minimum_calibration_runs,
            "minimum_holdout_runs": self.minimum_holdout_runs,
            "minimum_distinct_input_profiles": self.minimum_distinct_input_profiles,
            "required_track_segments": list(self.required_track_segments),
            "each_run_must_cover_all_segments": self.each_run_must_cover_all_segments,
        }


@dataclass(frozen=True)
class V1BAcceptanceProfile:
    schema_version: int
    profile_id: str
    declared_before_capture: bool
    thresholds_locked: bool
    input_profiles: tuple[V1BInputProfile, ...]
    campaign: V1BCampaignRules
    sync_gate: V1BSyncGate
    model_gate: V1BModelGate
    threshold_basis: tuple[Mapping[str, Any], ...]
    evidence_boundary: str

    def __post_init__(self) -> None:
        if self.schema_version != PROFILE_SCHEMA_VERSION:
            raise V1BManifestError(f"unsupported acceptance profile schema_version: {self.schema_version}")
        _safe_id(self.profile_id, "profile_id")
        if self.declared_before_capture is not True or self.thresholds_locked is not True:
            raise V1BManifestError("acceptance profile must be declared and locked before capture")
        if len(self.input_profiles) < self.campaign.minimum_distinct_input_profiles:
            raise V1BManifestError("acceptance profile has too few input profiles")
        ids = [item.profile_id for item in self.input_profiles]
        if len(set(ids)) != len(ids):
            raise V1BManifestError("duplicate input profile_id")
        required = set(self.campaign.required_track_segments)
        if not required.issubset(TRACK_SEGMENTS):
            raise V1BManifestError("campaign required_track_segments contains unknown values")
        if not any(required.issubset(set(item.required_track_segments)) for item in self.input_profiles):
            raise V1BManifestError("no input profile covers all required track segments")
        _text(self.evidence_boundary, "evidence_boundary")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "V1BAcceptanceProfile":
        try:
            inputs = tuple(V1BInputProfile.from_dict(item) for item in data["input_profiles"])
            basis = tuple(data["threshold_basis"])
            return cls(
                schema_version=data["schema_version"],
                profile_id=data["profile_id"],
                declared_before_capture=data["declared_before_capture"],
                thresholds_locked=data["thresholds_locked"],
                input_profiles=inputs,
                campaign=V1BCampaignRules.from_dict(data["campaign"]),
                sync_gate=V1BSyncGate.from_dict(data["sync_gate"]),
                model_gate=V1BModelGate.from_dict(data["model_gate"]),
                threshold_basis=basis,
                evidence_boundary=data["evidence_boundary"],
            )
        except KeyError as exc:
            raise V1BManifestError(f"acceptance profile missing field: {exc.args[0]}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "declared_before_capture": self.declared_before_capture,
            "thresholds_locked": self.thresholds_locked,
            "input_profiles": [item.to_dict() for item in self.input_profiles],
            "campaign": self.campaign.to_dict(),
            "sync_gate": self.sync_gate.to_dict(),
            "model_gate": self.model_gate.to_dict(),
            "threshold_basis": list(self.threshold_basis),
            "evidence_boundary": self.evidence_boundary,
        }


@dataclass(frozen=True)
class V1BCampaignManifest:
    schema_version: str
    campaign_id: str
    acceptance_profile_id: str
    acceptance_profile_sha256: str
    declared_before_capture: bool
    created_at_utc: str
    calibration_set_id: str
    holdout_set_id: str
    calibration_run_ids: tuple[str, ...]
    holdout_run_ids: tuple[str, ...]
    runs: tuple[V1BRunManifest, ...]
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != CAMPAIGN_SCHEMA_VERSION:
            raise V1BManifestError(f"unsupported campaign schema_version: {self.schema_version!r}")
        _safe_id(self.campaign_id, "campaign_id")
        _safe_id(self.acceptance_profile_id, "acceptance_profile_id")
        _sha256(self.acceptance_profile_sha256, "acceptance_profile_sha256")
        if self.declared_before_capture is not True:
            raise V1BManifestError("campaign must be declared_before_capture=true")
        _utc_timestamp(self.created_at_utc, "created_at_utc")
        _safe_id(self.calibration_set_id, "calibration_set_id")
        _safe_id(self.holdout_set_id, "holdout_set_id")
        if self.calibration_set_id == self.holdout_set_id:
            raise V1BManifestError("calibration_set_id and holdout_set_id must differ")
        calibration = _unique_ids(self.calibration_run_ids, "calibration_run_ids")
        holdout = _unique_ids(self.holdout_run_ids, "holdout_run_ids")
        try:
            V1RunSplit.from_run_ids(calibration, holdout)
        except V1RunSplitError as exc:
            raise V1BManifestError(str(exc)) from exc
        object.__setattr__(self, "calibration_run_ids", calibration)
        object.__setattr__(self, "holdout_run_ids", holdout)
        if not self.runs:
            raise V1BManifestError("runs must not be empty")
        run_ids = tuple(run.run_id for run in self.runs)
        if len(set(run_ids)) != len(run_ids):
            raise V1BManifestError("duplicate run ID in runs")
        run_calibration = tuple(run.run_id for run in self.runs if run.dataset_partition == "calibration")
        run_holdout = tuple(run.run_id for run in self.runs if run.dataset_partition == "holdout")
        if set(run_calibration) != set(calibration) or set(run_holdout) != set(holdout):
            raise V1BManifestError("campaign run lists do not match run manifest partitions")
        for run in self.runs:
            if run.calibration_set_id not in (None, self.calibration_set_id):
                raise V1BManifestError("run calibration_set_id does not match campaign")
            if run.holdout_set_id not in (None, self.holdout_set_id):
                raise V1BManifestError("run holdout_set_id does not match campaign")
        status = _text(self.status, "status")
        if status not in RUN_STATUSES:
            raise V1BManifestError(
                "unsupported or unsafe campaign status: {0!r}".format(status)
            )
        object.__setattr__(self, "status", status)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "V1BCampaignManifest":
        try:
            runs_value = data["runs"]
            if isinstance(runs_value, (str, bytes)) or not isinstance(runs_value, Sequence):
                raise V1BManifestError("runs must be a list")
            runs = tuple(V1BRunManifest.from_dict(item) for item in runs_value)
            return cls(
                schema_version=data["schema_version"],
                campaign_id=data["campaign_id"],
                acceptance_profile_id=data["acceptance_profile_id"],
                acceptance_profile_sha256=data["acceptance_profile_sha256"],
                declared_before_capture=data["declared_before_capture"],
                created_at_utc=data["created_at_utc"],
                calibration_set_id=data["calibration_set_id"],
                holdout_set_id=data["holdout_set_id"],
                calibration_run_ids=tuple(data["calibration_run_ids"]),
                holdout_run_ids=tuple(data["holdout_run_ids"]),
                runs=runs,
                status=data["status"],
            )
        except KeyError as exc:
            raise V1BManifestError(f"campaign manifest missing field: {exc.args[0]}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "acceptance_profile_id": self.acceptance_profile_id,
            "acceptance_profile_sha256": self.acceptance_profile_sha256,
            "declared_before_capture": self.declared_before_capture,
            "created_at_utc": self.created_at_utc,
            "calibration_set_id": self.calibration_set_id,
            "holdout_set_id": self.holdout_set_id,
            "calibration_run_ids": list(self.calibration_run_ids),
            "holdout_run_ids": list(self.holdout_run_ids),
            "runs": [run.to_dict() for run in self.runs],
            "status": self.status,
        }


@dataclass(frozen=True)
class V1BValidationReport:
    status: str
    evidence_level: str
    hardware_accessed: bool
    checked_run_ids: tuple[str, ...]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evidence_level": self.evidence_level,
            "hardware_accessed": self.hardware_accessed,
            "checked_run_ids": list(self.checked_run_ids),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def build_raw_file_manifest(
    run_dir: str | Path,
    files: Mapping[str, str],
) -> tuple[V1BRawFile, ...]:
    """Hash raw files for a new manifest; never writes or overwrites artifacts."""

    root = Path(run_dir).resolve()
    if not root.is_dir():
        raise V1BManifestError(f"run directory does not exist: {root}")
    result = []
    for kind, relative in sorted(files.items(), key=lambda item: (item[0], item[1])):
        record = V1BRawFile(
            path=_relative_path(relative, "raw file path"),
            kind=kind,
            sha256="0" * 64,
            size_bytes=0,
        )
        target = (root / Path(record.path)).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise V1BManifestError(f"raw file escapes run directory: {record.path}") from exc
        if not target.is_file():
            raise V1BManifestError(f"raw file does not exist: {record.path}")
        result.append(
            V1BRawFile(
                path=record.path,
                kind=record.kind,
                sha256=sha256_file(target),
                size_bytes=target.stat().st_size,
            )
        )
    return tuple(result)


def _raw_target(root: Path, raw_file: V1BRawFile) -> Path:
    target = (root / Path(raw_file.path)).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise V1BManifestError(f"raw file escapes run directory: {raw_file.path}") from exc
    return target


def _read_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        records = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise V1BManifestError(f"invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(item, Mapping):
                raise V1BManifestError(f"JSONL record at {path}:{line_number} must be an object")
            records.append(dict(item))
        return records
    if isinstance(value, list):
        if any(not isinstance(item, Mapping) for item in value):
            raise V1BManifestError(f"records in {path} must be objects")
        return [dict(item) for item in value]
    if isinstance(value, Mapping):
        return [dict(value)]
    raise V1BManifestError(f"records in {path} must be a JSON object or list")


def _check_monotonic(values: Sequence[int], field: str) -> str | None:
    if any(current < previous for previous, current in zip(values, values[1:])):
        return f"{field} timestamps are not monotonic"
    return None


def _wrong_unit_keys(record: Mapping[str, Any], stream: str) -> list[str]:
    forbidden = {
        "pose": {"t_pc_ms", "t_pc_s", "x_cm", "y_cm", "yaw_deg"},
        "telemetry": {"tick_ns", "tick_s", "pc_recv_ms", "pc_recv_s", "yaw_deg"},
    }.get(stream, set())
    return sorted(key for key in record if key in forbidden)


def _validate_run_files(run: V1BRunManifest, root: Path) -> list[str]:
    errors: list[str] = []
    run_root = (root / run.run_id).resolve()
    if not run_root.is_dir():
        return [f"run directory missing: {run.run_id}"]
    hashes: dict[str, str] = {}
    paths_by_kind: dict[str, Path] = {}
    for raw_file in run.raw_files:
        try:
            target = _raw_target(run_root, raw_file)
        except V1BManifestError as exc:
            errors.append(str(exc))
            continue
        if not target.is_file():
            errors.append(f"raw file missing: {run.run_id}/{raw_file.path}")
            continue
        actual_size = target.stat().st_size
        actual_hash = sha256_file(target)
        if actual_size != raw_file.size_bytes:
            errors.append(f"raw file size mismatch: {run.run_id}/{raw_file.path}")
        if actual_hash != raw_file.sha256:
            errors.append(f"raw file sha256 mismatch: {run.run_id}/{raw_file.path}")
        if raw_file.kind in paths_by_kind:
            errors.append(f"multiple raw files for kind {raw_file.kind}: {run.run_id}")
        paths_by_kind[raw_file.kind] = target
        if raw_file.kind in ("pose", "telemetry"):
            if actual_hash in hashes:
                errors.append(
                    f"duplicate raw file sha256 in run {run.run_id}: {hashes[actual_hash]}"
                )
            hashes[actual_hash] = raw_file.path

    pose_path = paths_by_kind.get("pose")
    telemetry_path = paths_by_kind.get("telemetry")
    if pose_path is None or telemetry_path is None:
        return errors
    try:
        pose_records = _read_records(pose_path)
        telemetry_records = _read_records(telemetry_path)
        for record in pose_records:
            bad_keys = _wrong_unit_keys(record, "pose")
            if bad_keys:
                errors.append(f"mixed units in pose stream: {', '.join(bad_keys)}")
        for record in telemetry_records:
            bad_keys = _wrong_unit_keys(record, "telemetry")
            if bad_keys:
                errors.append(f"mixed units in telemetry stream: {', '.join(bad_keys)}")
        poses = [V1Pose.from_dict(record) for record in pose_records]
        telemetry = [V1TelemetryFrame.from_dict(record) for record in telemetry_records]
        if not poses or not telemetry:
            errors.append(f"pose and telemetry streams must be non-empty: {run.run_id}")
        pose_times = [item.t_pc_ns for item in poses]
        tick_times = [item.tick_ms for item in telemetry]
        receive_times = [item.pc_recv_ns for item in telemetry]
        for values, field in (
            (pose_times, "pose.t_pc_ns"),
            (tick_times, "telemetry.tick_ms"),
            (receive_times, "telemetry.pc_recv_ns"),
        ):
            error = _check_monotonic(values, field)
            if error:
                errors.append(f"{run.run_id}: {error}")
        if poses:
            start, end = run.sample_interval_pc_ns
            if pose_times[0] != start or pose_times[-1] != end:
                errors.append(f"sample_interval_pc_ns does not match pose stream: {run.run_id}")
            if receive_times and (min(receive_times) < start or max(receive_times) > end):
                errors.append(
                    f"telemetry.pc_recv_ns outside sample_interval_pc_ns: {run.run_id}"
                )
    except (KeyError, TypeError, ValueError, V1BManifestError, V1SchemaError) as exc:
        errors.append(f"invalid raw stream in {run.run_id}: {exc}")
    return errors


def validate_campaign(
    campaign: V1BCampaignManifest,
    runs_root: str | Path,
    *,
    profile: V1BAcceptanceProfile | None = None,
    profile_sha256: str | None = None,
) -> V1BValidationReport:
    """Validate a campaign and return an auditable offline-only report."""

    root = Path(runs_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not root.is_dir():
        errors.append(f"runs root does not exist: {root}")
    if profile is None:
        errors.append("acceptance profile is required for V1-B validation")
    else:
        if campaign.acceptance_profile_id != profile.profile_id:
            errors.append("campaign acceptance_profile_id does not match profile")
        if profile_sha256 is None:
            errors.append("acceptance profile sha256 is required for V1-B validation")
        elif campaign.acceptance_profile_sha256 != _sha256(profile_sha256, "profile_sha256"):
            errors.append("campaign acceptance profile sha256 does not match profile file")
        calibration_count = len(campaign.calibration_run_ids)
        holdout_count = len(campaign.holdout_run_ids)
        if calibration_count < profile.campaign.minimum_calibration_runs:
            errors.append("calibration run count is below the frozen profile minimum")
        if holdout_count < profile.campaign.minimum_holdout_runs:
            errors.append("holdout run count is below the frozen profile minimum")
        used_profiles = {
            run.input_profile_id
            for run in campaign.runs
            if run.dataset_partition in ("calibration", "holdout")
        }
        if len(used_profiles) < profile.campaign.minimum_distinct_input_profiles:
            errors.append("campaign uses fewer input profiles than the frozen minimum")
        known_profiles = {item.profile_id for item in profile.input_profiles}
        required_segments = set(profile.campaign.required_track_segments)
        for run in campaign.runs:
            if run.dataset_partition in ("calibration", "holdout"):
                if run.input_profile_id not in known_profiles:
                    errors.append(f"unknown input profile in run {run.run_id}")
                if profile.campaign.each_run_must_cover_all_segments and not required_segments.issubset(set(run.covered_track_segments)):
                    errors.append(f"run {run.run_id} does not cover all required track segments")
    if root.is_dir():
        for run in campaign.runs:
            errors.extend(_validate_run_files(run, root))

    calibration_runs = [run for run in campaign.runs if run.dataset_partition == "calibration"]
    holdout_runs = [run for run in campaign.runs if run.dataset_partition == "holdout"]
    calibration_hashes: dict[str, str] = {}
    for run in calibration_runs:
        for raw_file in run.raw_files:
            calibration_hashes[raw_file.sha256] = run.run_id
    for run in holdout_runs:
        for raw_file in run.raw_files:
            if raw_file.sha256 in calibration_hashes:
                errors.append(
                    f"calibration/holdout raw hash overlap: {raw_file.sha256} "
                    f"({calibration_hashes[raw_file.sha256]} and {run.run_id})"
                )
    for calibration in calibration_runs:
        c_start, c_end = calibration.sample_interval_pc_ns
        for holdout in holdout_runs:
            h_start, h_end = holdout.sample_interval_pc_ns
            if c_start < h_end and h_start < c_end:
                errors.append(
                    f"calibration/holdout sample interval overlap: {calibration.run_id} and {holdout.run_id}"
                )

    origins = {run.data_origin for run in campaign.runs if run.dataset_partition in ("calibration", "holdout")}
    if len(origins) > 1:
        errors.append("calibration and holdout data origins are mixed")
    if origins == {"SYNTHETIC_TEST"}:
        evidence_level = "SYNTHETIC_ONLY"
        warnings.append("synthetic fixtures prove contract behavior only; no real calibration evidence")
    elif origins == {"REAL_CAPTURE"}:
        evidence_level = "REAL_DATA_CONTRACT_ONLY"
        warnings.append("real raw data contract is checked; model fit and holdout evidence are not performed by B1")
    else:
        evidence_level = "INSUFFICIENT_EVIDENCE"
        errors.append("calibration and holdout origin is missing")

    status = "OFFLINE_CONTRACT_PASS" if not errors else "OFFLINE_CONTRACT_REJECT"
    return V1BValidationReport(
        status=status,
        evidence_level=evidence_level,
        hardware_accessed=False,
        checked_run_ids=tuple(run.run_id for run in campaign.runs),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def load_acceptance_profile(path: str | Path) -> V1BAcceptanceProfile:
    profile_path = Path(path)
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V1BManifestError(f"cannot load acceptance profile: {profile_path}") from exc
    if not isinstance(data, Mapping):
        raise V1BManifestError("acceptance profile must be a JSON object")
    return V1BAcceptanceProfile.from_dict(data)


def make_v1_b_run_id(
    *,
    prefix: str = "v1b",
    now: datetime | None = None,
    token: str | None = None,
) -> str:
    """Create a collision-resistant, filesystem-safe run ID."""

    prefix = _safe_id(prefix, "run_id prefix")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    suffix = token or secrets.token_hex(4)
    suffix = _safe_id(suffix, "run_id token")
    return f"{prefix}-{current:%Y%m%dT%H%M%S%fZ}-{suffix}"
