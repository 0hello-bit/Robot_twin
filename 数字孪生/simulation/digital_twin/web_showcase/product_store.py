#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Versioned local product data storage for TwinTrack."""

from __future__ import print_function

import copy
import datetime
import json
import math
import os
import tempfile
import uuid

# Delegate campaign storage to the dedicated CampaignStore module.
# All campaign-related persistence lives there; ProductStore only
# exposes stable convenience methods that forward to it.
from real_world.campaign_store import CampaignStore as _CampaignStore


SCHEMA_VERSION = 1
MAX_PRESETS = 100
MAX_SESSION_SAMPLES = 12000


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def default_device_profile():
    return {
        "schema_version": SCHEMA_VERSION,
        "id": "default-car",
        "name": "我的麦轮巡线车",
        "setup_completed": False,
        "updated_at": utc_now(),
        "hardware": {
            "mcu": "STM32F103C8",
            "drive": "mecanum_differential_line_following",
            "line_sensors": 4,
            "imu": "MPU6050",
            "wifi": "ESP01S",
            "vision": "overhead_camera",
        },
        "dimensions_m": {
            "length": None,
            "width": None,
            "wheel_diameter": None,
            "wheelbase": None,
            "track_width": None,
            "sensor_forward_offset": None,
            "sensor_spacing": None,
            "tag_size": 0.05,
            "tag_height": None,
        },
        "notes": "",
    }


class ProductStoreError(ValueError):
    pass


class ProductStore(object):
    def __init__(self, data_root):
        self.data_root = os.path.abspath(data_root)
        self.profile_path = os.path.join(self.data_root, "device_profile.json")
        self.presets_path = os.path.join(self.data_root, "presets.json")
        self.workspace_state_path = os.path.join(
            self.data_root,
            "workspace_state.json",
        )
        self.sessions_root = os.path.join(self.data_root, "sessions")
        self.reports_root = os.path.join(self.data_root, "calibration_reports")
        for path in (self.data_root, self.sessions_root, self.reports_root):
            os.makedirs(path, exist_ok=True)

    @staticmethod
    def _read_json(path, default):
        if not os.path.isfile(path):
            return copy.deepcopy(default)
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path, payload):
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        descriptor, temp_path = tempfile.mkstemp(
            prefix=".twintrack_",
            suffix=".json",
            dir=directory,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    @staticmethod
    def _optional_number(value, field, minimum, maximum):
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ProductStoreError("%s 必须是数字" % field)
        if not math.isfinite(number) or number < minimum or number > maximum:
            raise ProductStoreError(
                "%s 必须在 %.3f 到 %.3f 之间" % (field, minimum, maximum)
            )
        return round(number, 6)

    def load_profile(self):
        payload = self._read_json(self.profile_path, default_device_profile())
        base = default_device_profile()
        if isinstance(payload, dict):
            base.update({
                key: value
                for key, value in payload.items()
                if key not in ("hardware", "dimensions_m")
            })
            if isinstance(payload.get("hardware"), dict):
                base["hardware"].update(payload["hardware"])
            if isinstance(payload.get("dimensions_m"), dict):
                base["dimensions_m"].update(payload["dimensions_m"])
        return base

    def save_profile(self, payload):
        if not isinstance(payload, dict):
            raise ProductStoreError("设备档案格式无效")
        current = self.load_profile()
        name = str(payload.get("name", current["name"])).strip()
        if not name or len(name) > 80:
            raise ProductStoreError("设备名称应为1到80个字符")
        dimensions_input = payload.get("dimensions_m") or {}
        dimensions = dict(current["dimensions_m"])
        ranges = {
            "length": ("车长", 0.05, 2.0),
            "width": ("车宽", 0.05, 2.0),
            "wheel_diameter": ("轮径", 0.01, 0.5),
            "wheelbase": ("轴距", 0.02, 1.5),
            "track_width": ("轮距", 0.02, 1.5),
            "sensor_forward_offset": ("传感器前伸", 0.0, 1.0),
            "sensor_spacing": ("传感器间距", 0.001, 0.5),
            "tag_size": ("AprilTag边长", 0.01, 0.5),
            "tag_height": ("AprilTag高度", 0.0, 1.0),
        }
        for key, (label, minimum, maximum) in ranges.items():
            if key in dimensions_input:
                dimensions[key] = self._optional_number(
                    dimensions_input.get(key),
                    label,
                    minimum,
                    maximum,
                )
        current.update({
            "schema_version": SCHEMA_VERSION,
            "name": name,
            "setup_completed": bool(
                payload.get("setup_completed", current.get("setup_completed"))
            ),
            "dimensions_m": dimensions,
            "notes": str(payload.get("notes", current.get("notes", "")))[:1000],
            "updated_at": utc_now(),
        })
        self._write_json(self.profile_path, current)
        return current

    def load_presets(self):
        payload = self._read_json(
            self.presets_path,
            {"schema_version": SCHEMA_VERSION, "items": []},
        )
        items = payload.get("items") if isinstance(payload, dict) else []
        return items if isinstance(items, list) else []

    def save_presets(self, items):
        if not isinstance(items, list):
            raise ProductStoreError("参数预设必须是列表")
        normalized = []
        for item in items[-MAX_PRESETS:]:
            if not isinstance(item, dict) or not isinstance(item.get("params"), dict):
                continue
            normalized.append({
                "schema_version": SCHEMA_VERSION,
                "id": item.get("id") or uuid.uuid4().hex,
                "name": str(item.get("name") or "未命名预设")[:80],
                "note": str(item.get("note") or "")[:300],
                "created_at": (
                    item.get("created_at")
                    or item.get("createdAt")
                    or utc_now()
                ),
                "params": item["params"],
                "metrics": item.get("metrics"),
                "auto_tuned": bool(item.get("auto_tuned", False)),
            })
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now(),
            "items": normalized,
        }
        self._write_json(self.presets_path, payload)
        return normalized

    def load_workspace_state(self):
        return self._read_json(
            self.workspace_state_path,
            {
                "schema_version": SCHEMA_VERSION,
                "updated_at": None,
                "active_params": {},
                "model_calibration": {
                    "pwmToSpeed": 1.0,
                    "turnScale": 1.0,
                    "yawBlend": 0.55,
                },
            },
        )

    def save_workspace_state(self, payload):
        if not isinstance(payload, dict):
            raise ProductStoreError("当前调参状态格式无效")
        active_input = payload.get("active_params") or {}
        if not isinstance(active_input, dict) or len(active_input) > 100:
            raise ProductStoreError("当前参数集合格式无效")
        active_params = {}
        for key, value in active_input.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ProductStoreError("参数 %s 不是有效数字" % key)
            if not math.isfinite(number) or abs(number) > 100000:
                raise ProductStoreError("参数 %s 超出安全范围" % key)
            active_params[str(key)[:80]] = number

        calibration_input = payload.get("model_calibration") or {}
        calibration_ranges = {
            "pwmToSpeed": (0.25, 2.5, 1.0),
            "turnScale": (0.25, 2.5, 1.0),
            "yawBlend": (0.0, 1.0, 0.55),
        }
        model_calibration = {}
        for key, (minimum, maximum, default) in calibration_ranges.items():
            try:
                number = float(calibration_input.get(key, default))
            except (TypeError, ValueError):
                raise ProductStoreError("轨迹模型参数 %s 无效" % key)
            if not math.isfinite(number) or not minimum <= number <= maximum:
                raise ProductStoreError("轨迹模型参数 %s 超出范围" % key)
            model_calibration[key] = round(number, 6)
        state = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now(),
            "active_params": active_params,
            "model_calibration": model_calibration,
        }
        self._write_json(self.workspace_state_path, state)
        return state

    @staticmethod
    def _safe_identifier(value):
        text = "".join(
            character
            for character in str(value or "")
            if character.isalnum() or character in ("-", "_")
        )
        return text[:80]

    def save_session(self, payload):
        if not isinstance(payload, dict):
            raise ProductStoreError("运行记录格式无效")
        samples = payload.get("samples") or []
        if not isinstance(samples, list) or len(samples) < 2:
            raise ProductStoreError("运行记录至少需要2个数据点")
        if len(samples) > MAX_SESSION_SAMPLES:
            samples = samples[-MAX_SESSION_SAMPLES:]
        session_id = self._safe_identifier(payload.get("id")) or (
            datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        session = {
            "schema_version": SCHEMA_VERSION,
            "id": session_id,
            "name": str(payload.get("name") or "实车运行记录")[:80],
            "created_at": payload.get("created_at") or utc_now(),
            "source": str(payload.get("source") or "wifi")[:40],
            "metrics": payload.get("metrics"),
            "params": payload.get("params") or {},
            "track": payload.get("track"),
            "samples": samples,
        }
        self._write_json(
            os.path.join(self.sessions_root, session_id + ".json"),
            session,
        )
        return self.session_summary(session)

    @staticmethod
    def session_summary(session):
        samples = session.get("samples") or []
        duration_ms = 0
        if len(samples) > 1:
            duration_ms = max(
                0,
                int(samples[-1].get("tick_ms", 0))
                - int(samples[0].get("tick_ms", 0)),
            )
        return {
            "id": session.get("id"),
            "name": session.get("name"),
            "created_at": session.get("created_at"),
            "source": session.get("source"),
            "sample_count": len(samples),
            "duration_ms": duration_ms,
            "metrics": session.get("metrics"),
        }

    def list_sessions(self):
        summaries = []
        for name in os.listdir(self.sessions_root):
            if not name.endswith(".json"):
                continue
            try:
                session = self._read_json(
                    os.path.join(self.sessions_root, name),
                    {},
                )
                if isinstance(session, dict):
                    summaries.append(self.session_summary(session))
            except (OSError, ValueError):
                continue
        return sorted(
            summaries,
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )

    def load_session(self, session_id):
        safe_id = self._safe_identifier(session_id)
        if not safe_id:
            raise ProductStoreError("运行记录编号无效")
        path = os.path.join(self.sessions_root, safe_id + ".json")
        if not os.path.isfile(path):
            raise ProductStoreError("没有找到该运行记录")
        return self._read_json(path, {})

    def save_calibration_report(self, payload):
        if not isinstance(payload, dict):
            raise ProductStoreError("标定报告格式无效")
        report_id = self._safe_identifier(payload.get("id")) or (
            "cal-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        )
        report = dict(payload)
        report.update({
            "schema_version": SCHEMA_VERSION,
            "id": report_id,
            "created_at": payload.get("created_at") or utc_now(),
        })
        self._write_json(
            os.path.join(self.reports_root, report_id + ".json"),
            report,
        )
        return report

    def list_calibration_reports(self):
        reports = []
        for name in os.listdir(self.reports_root):
            if not name.endswith(".json"):
                continue
            try:
                report = self._read_json(
                    os.path.join(self.reports_root, name),
                    {},
                )
                if isinstance(report, dict):
                    reports.append(report)
            except (OSError, ValueError):
                continue
        return sorted(
            reports,
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )

    def bootstrap(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "device_profile": self.load_profile(),
            "presets": self.load_presets(),
            "workspace_state": self.load_workspace_state(),
            "sessions": self.list_sessions(),
            "calibration_reports": self.list_calibration_reports(),
        }

    def backup(self):
        sessions = []
        for summary in self.list_sessions():
            sessions.append(self.load_session(summary["id"]))
        return {
            "product": "TwinTrack-STM32",
            "schema_version": SCHEMA_VERSION,
            "exported_at": utc_now(),
            "device_profile": self.load_profile(),
            "presets": self.load_presets(),
            "workspace_state": self.load_workspace_state(),
            "sessions": sessions,
            "calibration_reports": self.list_calibration_reports(),
        }

    def restore_backup(self, payload):
        if not isinstance(payload, dict) or payload.get("product") != "TwinTrack-STM32":
            raise ProductStoreError("备份文件不是 TwinTrack-STM32 数据")
        if isinstance(payload.get("device_profile"), dict):
            self.save_profile(payload["device_profile"])
        if isinstance(payload.get("presets"), list):
            self.save_presets(payload["presets"])
        if isinstance(payload.get("workspace_state"), dict):
            self.save_workspace_state(payload["workspace_state"])
        restored_sessions = 0
        for session in payload.get("sessions") or []:
            try:
                self.save_session(session)
                restored_sessions += 1
            except ProductStoreError:
                continue
        restored_reports = 0
        for report in payload.get("calibration_reports") or []:
            try:
                self.save_calibration_report(report)
                restored_reports += 1
            except ProductStoreError:
                continue
        return {
            "device_profile": self.load_profile(),
            "presets": self.load_presets(),
            "workspace_state": self.load_workspace_state(),
            "sessions_restored": restored_sessions,
            "reports_restored": restored_reports,
        }

    # ----------------------------------------------------------
    # Campaign store delegation
    #
    # These methods forward to CampaignStore so that ProductStore
    # users have a single entry point without duplicating storage or
    # metrics logic.
    # ----------------------------------------------------------

    @property
    def _campaign_store(self):
        if not hasattr(self, "_campaign_store_instance"):
            self._campaign_store_instance = _CampaignStore(data_root=self.data_root)
        return self._campaign_store_instance

    def create_campaign(self, campaign_id, **kwargs):
        return self._campaign_store.create_campaign(campaign_id, **kwargs)

    def load_campaign(self, campaign_id):
        return self._campaign_store.load_campaign(campaign_id)

    def update_campaign_status(self, campaign_id, status):
        return self._campaign_store.update_campaign_status(campaign_id, status)

    def save_run(self, campaign_id, run_id, run_data):
        return self._campaign_store.save_run(campaign_id, run_id, run_data)

    def load_run(self, campaign_id, run_id):
        return self._campaign_store.load_run(campaign_id, run_id)

    def list_runs(self, campaign_id):
        return self._campaign_store.list_runs(campaign_id)

    def save_decision(self, campaign_id, version, decision_data):
        return self._campaign_store.save_decision(campaign_id, version, decision_data)

    def load_decision(self, campaign_id, version):
        return self._campaign_store.load_decision(campaign_id, version)

    def list_decisions(self, campaign_id):
        return self._campaign_store.list_decisions(campaign_id)

    def save_report(self, campaign_id, report_data):
        return self._campaign_store.save_report(campaign_id, report_data)

    def load_report(self, campaign_id):
        return self._campaign_store.load_report(campaign_id)

    def list_campaigns(self):
        return self._campaign_store.list_campaigns()
