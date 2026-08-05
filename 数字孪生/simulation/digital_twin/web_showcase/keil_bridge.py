from __future__ import print_function

import io
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path


PARAM_SPECS = {
    "PID_KP": ("float", 0.0, 100.0),
    "PID_KD": ("float", 0.0, 40.0),
    "SPEED_MAX": ("int", 360, 820),
    "SPEED_MIN": ("int", 80, 520),
    "SPEED_ERR_DECAY": ("float", 0.0, 80.0),
    "SPEED_INIT": ("float", 0.0, 820.0),
    "TURN_LIMIT": ("int", 120, 720),
    "ERR_OUTER": ("float", 0.5, 4.0),
    "ERR_INNER": ("float", 0.1, 1.5),
    "TURN_GAIN_K": ("float", 0.0, 2.0),
    "ERR_FILTER_OLD": ("float", 0.0, 1.0),
    "ERR_FILTER_NEW": ("float", 0.0, 1.0),
    "SPEED_FILTER_OLD": ("float", 0.0, 1.0),
    "SPEED_FILTER_NEW": ("float", 0.0, 1.0),
    "TURN_FILTER_OLD": ("float", 0.0, 1.0),
    "TURN_FILTER_NEW": ("float", 0.0, 1.0),
    "MOTOR_FILTER_OLD": ("float", 0.0, 1.0),
    "MOTOR_FILTER_NEW": ("float", 0.0, 1.0),
    "CURVE_REVERSE_ERR": ("float", 0.0, 4.0),
    "CURVE_REVERSE_POS": ("int", 0, 1),
    "CURVE_INNER_REVERSE": ("int", -500, 0),
    "CURVE_MIN_TURN_EXTRA": ("int", 0, 180),
    "CURVE_MID_INNER_REVERSE": ("int", -360, 0),
    "CURVE_MID_TURN_EXTRA": ("int", 0, 120),
    "D_LIMIT": ("float", 0.1, 2.5),
    "SENSOR_STABLE_COUNT": ("int", 0, 5),
    "LOST_HOLD_COUNT": ("int", 0, 12),
    "LOST_FAST_OUTER": ("int", 0, 720),
    "LOST_FAST_INNER": ("int", -520, 300),
    "MOTOR_LIMIT": ("int", 300, 820),
    "LOOP_DELAY_MS": ("int", 2, 20),
}

FLOAT_SUFFIX_RE = re.compile(r"[fF]\s*$")
DEFINE_RE_TEMPLATE = r"(?m)^([ \t]*#define[ \t]+{name}[ \t]+)([^ \t\r\n]+)(.*)$"
ERROR_RE = re.compile(r"\b(\d+)\s+Error\(s\)", re.IGNORECASE)
WARNING_RE = re.compile(r"\b(\d+)\s+Warning\(s\)", re.IGNORECASE)


def _read_text_with_encoding(path):
    payload = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1"), "latin-1"


def _read_text(path):
    return _read_text_with_encoding(path)[0]


def _write_text_atomic(path, content, encoding="utf-8"):
    temp_path = path.with_name(path.name + ".twintrack.tmp")
    with io.open(str(temp_path), "w", encoding=encoding, newline="") as handle:
        handle.write(content)
    os.replace(str(temp_path), str(path))


def _is_within(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _decode_log(path):
    if not path.exists():
        return ""
    payload = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "mbcs", "latin-1"):
        try:
            return payload.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("latin-1", errors="replace")


def _tail_lines(text, limit=180):
    lines = str(text or "").replace("\x00", "").splitlines()
    return "\n".join(lines[-limit:])


class KeilBridge(object):
    def __init__(self, base_dir, config_name="keil_bridge_config.json"):
        self.base_dir = Path(base_dir).resolve()
        self.config_path = self.base_dir / config_name
        self.config = self._load_config()
        self.workspace_root = self._resolve_workspace_root()
        self.busy = False
        self.phase = "idle"
        self.last_result = None
        self.flash_armed = False
        self._flash_tokens = {}
        self._state_lock = threading.Lock()

    def _load_config(self):
        if not self.config_path.exists():
            return {}
        try:
            return json.loads(_read_text(self.config_path))
        except (ValueError, OSError):
            return {}

    def _save_config(self):
        serialized = json.dumps(self.config, ensure_ascii=False, indent=2) + "\n"
        _write_text_atomic(self.config_path, serialized)

    def _resolve_workspace_root(self):
        raw = self.config.get("workspace_root") or "..\\..\\.."
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.base_dir / candidate
        return candidate.resolve()

    def _resolve_keil_executable(self):
        raw = str(self.config.get("keil_executable") or "").strip()
        if raw:
            candidate = Path(raw)
            if candidate.is_file():
                return candidate.resolve()
        found = shutil.which("UV4.exe")
        return Path(found).resolve() if found else None

    def _resolve_project(self):
        raw = str(self.config.get("project_file") or "").strip()
        if not raw:
            return None
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        candidate = candidate.resolve()
        if not _is_within(candidate, self.workspace_root):
            return None
        return candidate

    def discover_projects(self):
        projects = []
        selected = self._resolve_project()
        if not self.workspace_root.exists():
            return projects
        for project in sorted(self.workspace_root.rglob("*.uvprojx")):
            if not project.is_file():
                continue
            metadata = self._project_metadata(project)
            projects.append({
                "path": str(project.relative_to(self.workspace_root)),
                "name": project.parent.name,
                "target": metadata.get("target") or "",
                "device": metadata.get("device") or "",
                "selected": bool(selected and project.resolve() == selected),
            })
        return projects

    def _project_metadata(self, project):
        result = {
            "target": "",
            "device": "",
            "output_name": "",
            "flash_configured": False,
        }
        if not project or not project.is_file():
            return result
        try:
            root = ET.parse(str(project)).getroot()
            target = root.find("./Targets/Target")
            if target is None:
                return result
            result["target"] = target.findtext("TargetName") or ""
            common = target.find("./TargetOption/TargetCommonOption")
            if common is not None:
                result["device"] = common.findtext("Device") or ""
                result["output_name"] = common.findtext("OutputName") or ""
                result["flash_configured"] = bool(common.findtext("FlashDriverDll"))
        except (ET.ParseError, OSError):
            pass
        return result

    def status_payload(self, include_projects=False):
        executable = self._resolve_keil_executable()
        project = self._resolve_project()
        metadata = self._project_metadata(project)
        firmware_id = ""
        source_modified_at = None
        if project and project.is_file():
            try:
                main_path = self._find_main_c(project)
                with main_path.open("rb") as handle:
                    firmware_id = "src-" + hashlib.sha256(
                        handle.read()
                    ).hexdigest()[:10]
                source_modified_at = int(main_path.stat().st_mtime * 1000)
            except (OSError, ValueError):
                pass
        payload = {
            "available": bool(executable and project and project.is_file()),
            "busy": self.busy,
            "phase": self.phase,
            "keil_found": bool(executable),
            "keil_executable": str(executable or ""),
            "project_found": bool(project and project.is_file()),
            "project": (
                str(project.relative_to(self.workspace_root))
                if project and _is_within(project, self.workspace_root)
                else ""
            ),
            "target": str(self.config.get("target") or metadata.get("target") or ""),
            "device": metadata.get("device") or "",
            "flash_configured": bool(metadata.get("flash_configured")),
            "flash_armed": self.flash_armed,
            "firmware_id": firmware_id,
            "source_modified_at": source_modified_at,
            "last_result": self.last_result,
        }
        if include_projects:
            payload["projects"] = self.discover_projects()
        return payload

    def select_project(self, project_value):
        candidate = (self.workspace_root / str(project_value or "")).resolve()
        allowed = {
            project.resolve(): project
            for project in self.workspace_root.rglob("*.uvprojx")
            if project.is_file()
        }
        if candidate not in allowed:
            raise ValueError("所选工程不在当前工作区的 Keil 工程列表中")
        metadata = self._project_metadata(candidate)
        self.config["project_file"] = str(candidate.relative_to(self.workspace_root))
        self.config["target"] = metadata.get("target") or "Target 1"
        self.set_flash_armed(False)
        self._save_config()
        return self.status_payload(include_projects=True)

    def read_project_parameters(self):
        project = self._resolve_project()
        if not project or not project.is_file():
            raise RuntimeError("未找到已配置的 Keil 工程")
        main_path = self._find_main_c(project)
        source = _read_text(main_path)
        parameters = {}
        missing = []
        invalid = []
        for name, (kind, minimum, maximum) in PARAM_SPECS.items():
            pattern = re.compile(DEFINE_RE_TEMPLATE.format(name=re.escape(name)))
            match = pattern.search(source)
            if not match:
                missing.append(name)
                continue
            token = FLOAT_SUFFIX_RE.sub("", match.group(2))
            try:
                numeric = float(token)
            except (TypeError, ValueError):
                invalid.append(name)
                continue
            if not math.isfinite(numeric) or numeric < minimum or numeric > maximum:
                invalid.append(name)
                continue
            parameters[name] = int(round(numeric)) if kind == "int" else numeric
        return {
            "success": not missing and not invalid,
            "parameters": parameters,
            "missing": missing,
            "invalid": invalid,
            "main_file": str(main_path.relative_to(self.workspace_root)),
        }

    def set_flash_armed(self, enabled):
        if self.busy:
            raise RuntimeError("Keil 正在执行操作，不能改变烧录锁")
        self.flash_armed = bool(enabled)
        self._flash_tokens = {}
        return self.status_payload()

    def open_project(self):
        executable, project, _target = self._validated_environment()
        subprocess.Popen(
            [str(executable), str(project)],
            cwd=str(project.parent),
            close_fds=True,
        )
        return {
            "success": True,
            "message": "已请求 Keil5 打开当前工程",
            "project": str(project.relative_to(self.workspace_root)),
        }

    def prepare_flash(self):
        _executable, project, target = self._validated_environment()
        if not self.flash_armed:
            raise RuntimeError("实际烧录当前处于锁定状态")
        metadata = self._project_metadata(project)
        if not metadata.get("flash_configured"):
            raise RuntimeError("当前 Keil 工程没有配置 Flash 下载算法")
        token = secrets.token_urlsafe(24)
        now = time.time()
        self._flash_tokens = {
            key: value for key, value in self._flash_tokens.items()
            if value["expires_at"] > now
        }
        self._flash_tokens[token] = {
            "project": str(project),
            "target": target,
            "expires_at": now + 30.0,
        }
        return {
            "success": True,
            "token": token,
            "expires_in_s": 30,
            "project": str(project.relative_to(self.workspace_root)),
            "target": target,
            "device": metadata.get("device") or "",
            "warning": "烧录会覆盖小车控制器中现有程序。请先架空车轮并确认下载器连接正确。",
        }

    def consume_flash_token(self, token):
        if not self.flash_armed:
            raise ValueError("实际烧录当前处于锁定状态")
        entry = self._flash_tokens.pop(str(token or ""), None)
        project = self._resolve_project()
        target = self._target_name(project)
        if not entry or entry["expires_at"] < time.time():
            raise ValueError("烧录确认已过期，请重新确认")
        if not project or entry["project"] != str(project) or entry["target"] != target:
            raise ValueError("工程或目标已变化，请重新确认")

    def _validated_environment(self):
        executable = self._resolve_keil_executable()
        if not executable:
            raise RuntimeError("未找到 Keil5 的 UV4.exe")
        project = self._resolve_project()
        if not project or not project.is_file():
            raise RuntimeError("未找到已配置的 Keil 工程")
        if not _is_within(project, self.workspace_root):
            raise RuntimeError("Keil 工程不在允许的工作区内")
        return executable, project, self._target_name(project)

    def _target_name(self, project):
        metadata = self._project_metadata(project)
        return str(self.config.get("target") or metadata.get("target") or "Target 1")

    def _find_main_c(self, project):
        try:
            root = ET.parse(str(project)).getroot()
            for file_node in root.findall(".//File"):
                if (file_node.findtext("FileName") or "").lower() != "main.c":
                    continue
                raw_path = (file_node.findtext("FilePath") or "").replace("\\", os.sep)
                candidate = (project.parent / raw_path).resolve()
                if candidate.is_file() and _is_within(candidate, project.parent):
                    return candidate
        except (ET.ParseError, OSError):
            pass
        fallback = (project.parent / "User" / "main.c").resolve()
        if fallback.is_file() and _is_within(fallback, project.parent):
            return fallback
        raise RuntimeError("当前工程中没有找到 User/main.c")

    def _validate_params(self, params):
        if not isinstance(params, dict):
            raise ValueError("网页参数格式无效")
        validated = {}
        for name, value in params.items():
            if name not in PARAM_SPECS:
                continue
            kind, minimum, maximum = PARAM_SPECS[name]
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                raise ValueError("参数 %s 不是数字" % name)
            if not math.isfinite(numeric) or numeric < minimum or numeric > maximum:
                raise ValueError("参数 %s 超出安全范围" % name)
            if kind == "int":
                if abs(numeric - round(numeric)) > 1e-6:
                    raise ValueError("参数 %s 必须是整数" % name)
                validated[name] = str(int(round(numeric)))
            else:
                formatted = ("%.6f" % numeric).rstrip("0").rstrip(".")
                if "." not in formatted:
                    formatted += ".0"
                validated[name] = formatted + "f"
        if not validated:
            raise ValueError("没有收到可同步的固件参数")
        return validated

    def sync_parameters(self, project, params):
        values = self._validate_params(params)
        main_path = self._find_main_c(project)
        original, source_encoding = _read_text_with_encoding(main_path)
        updated = original
        changed = []
        missing = []
        for name, formatted in values.items():
            pattern = re.compile(DEFINE_RE_TEMPLATE.format(name=re.escape(name)))
            match = pattern.search(updated)
            if not match:
                missing.append(name)
                continue
            old_token = match.group(2)
            replacement = formatted
            if PARAM_SPECS[name][0] == "float" and FLOAT_SUFFIX_RE.search(old_token):
                replacement = formatted
            elif PARAM_SPECS[name][0] == "float":
                replacement = formatted[:-1]
            if old_token != replacement:
                updated = pattern.sub(
                    lambda item: item.group(1) + replacement + item.group(3),
                    updated,
                    count=1,
                )
                changed.append(name)
        if missing:
            raise RuntimeError(
                "当前 main.c 缺少 %d 个网页参数定义，未写入任何参数：%s"
                % (len(missing), ", ".join(missing[:8]))
            )
        backup_path = ""
        if updated != original:
            backup_dir = main_path.parent / ".twintrack_backups"
            backup_dir.mkdir(exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            backup = backup_dir / ("main_%s_%03d.c" % (stamp, int(time.time() * 1000) % 1000))
            shutil.copy2(str(main_path), str(backup))
            _write_text_atomic(main_path, updated, encoding=source_encoding)
            backup_path = str(backup.relative_to(self.workspace_root))
        return {
            "main_file": str(main_path.relative_to(self.workspace_root)),
            "changed_count": len(changed),
            "changed": changed,
            "backup": backup_path,
        }

    def run(self, action, params):
        executable, project, target = self._validated_environment()
        if action not in ("build", "build_flash"):
            raise ValueError("不支持的 Keil 操作")
        if self._uv4_is_running():
            raise RuntimeError(
                "Keil5 图形界面正在运行。请先保存并关闭 Keil5，再从网页编译或烧录"
            )
        with self._state_lock:
            if self.busy:
                raise RuntimeError("Keil 正在执行另一项操作")
            self.busy = True
        started = time.time()
        try:
            self.phase = "syncing"
            sync_result = self.sync_parameters(project, params)
            self.phase = "building"
            build_result = self._run_uv4(
                executable,
                project,
                target,
                command="-b",
                timeout_s=int(self.config.get("build_timeout_s") or 180),
                log_name="keil-build.log",
            )
            result = {
                "operation": action,
                "success": bool(build_result["success"]),
                "phase": "build",
                "message": (
                    "编译成功"
                    if build_result["success"]
                    else "编译失败，未执行烧录"
                ),
                "sync": sync_result,
                "build": build_result,
                "flash": None,
                "duration_s": round(time.time() - started, 2),
            }
            if action == "build_flash" and build_result["success"]:
                self.phase = "flashing"
                flash_result = self._run_uv4(
                    executable,
                    project,
                    target,
                    command="-f",
                    timeout_s=int(self.config.get("flash_timeout_s") or 120),
                    log_name="keil-flash.log",
                )
                result["flash"] = flash_result
                result["phase"] = "flash"
                result["success"] = bool(flash_result["success"])
                result["message"] = (
                    "编译并烧录成功"
                    if flash_result["success"]
                    else "编译成功，但烧录失败"
                )
                result["duration_s"] = round(time.time() - started, 2)
            self.last_result = {
                "operation": result["operation"],
                "success": result["success"],
                "message": result["message"],
                "phase": result["phase"],
                "duration_s": result["duration_s"],
                "finished_at": int(time.time() * 1000),
            }
            return result
        finally:
            if action == "build_flash":
                self.flash_armed = False
                self._flash_tokens = {}
            self.phase = "idle"
            self.busy = False

    @staticmethod
    def _uv4_is_running():
        if os.name != "nt":
            return False
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            output = subprocess.check_output(
                [
                    "tasklist",
                    "/FI",
                    "IMAGENAME eq UV4.exe",
                    "/FO",
                    "CSV",
                    "/NH",
                ],
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
        return "uv4.exe" in output.decode("mbcs", errors="ignore").lower()

    def _run_uv4(self, executable, project, target, command, timeout_s, log_name):
        log_path = self.base_dir / log_name
        if log_path.exists():
            log_path.unlink()
        args = [
            str(executable),
            command,
            str(project),
            "-t",
            target,
            "-j0",
            "-o",
            str(log_path),
        ]
        started = time.time()
        timed_out = False
        try:
            process = subprocess.Popen(
                args,
                cwd=str(project.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
            )
            stdout, stderr = process.communicate(timeout=timeout_s)
            return_code = int(process.returncode)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()
            return_code = -1
        log_text = _decode_log(log_path)
        if stdout:
            log_text += "\n" + stdout.decode("gb18030", errors="replace")
        if stderr:
            log_text += "\n" + stderr.decode("gb18030", errors="replace")
        errors = self._extract_count(ERROR_RE, log_text)
        warnings = self._extract_count(WARNING_RE, log_text)
        success = not timed_out and return_code in (0, 1) and errors == 0
        if command == "-f":
            success = (
                not timed_out
                and return_code == 0
                and bool(re.search(r"Verify\s+OK|Programming\s+Done", log_text, re.IGNORECASE))
            )
        return {
            "success": success,
            "return_code": return_code,
            "errors": errors,
            "warnings": warnings,
            "timed_out": timed_out,
            "duration_s": round(time.time() - started, 2),
            "log": _tail_lines(log_text),
        }

    @staticmethod
    def _extract_count(pattern, text):
        matches = pattern.findall(text or "")
        return int(matches[-1]) if matches else 0
