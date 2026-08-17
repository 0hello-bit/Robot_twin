# -*- coding: utf-8 -*-
"""ACK-aware fail-closed ground session (Ground Shakedown Recorder, Task 1).

Bounded offline control core.  Single-owner synchronous lifecycle
(2026-08-05 replacement of the rejected threaded implementation):

  - `run_ground_session()` validates the transport's bounded-I/O declaration
    and `duration_s` BEFORE any dependency call (preflight), then delegates to
    one internal `_SessionLoop`.
  - No reader thread and no heartbeat thread are created.  The calling thread
    exclusively sends, receives, parses, logs live raw I/O, schedules
    heartbeats, performs the once-only terminal STOP, closes the transport,
    freezes raw evidence, publishes it, and builds exactly one final result.
  - Every parsed ACK/status line becomes one JSON-serializable event envelope
    with a shared monotonically increasing `receive_seq` and host
    `receive_monotonic_s`; all public ACK/status records copy that provenance.
  - Every transport call is timed against `IO_CALL_BUDGET_S`; a call that
    returns over budget has completed (its return is preserved) but records
    `IO_CALL_BUDGET_EXCEEDED` and forces control FAIL.
  - The first failure is immutable (`primary_failure`); later STOP, close, and
    raw failures are appended to `secondary_errors` / `cleanup_errors` and can
    never hide or overwrite it.
  - Raw evidence is frozen only after transport close; `quiescence.proven` is
    true only when close completed and the final events freeze succeeded.
  - A supported transport must provide `send(bytes)`, `recv(max_bytes)`, and
    `close()` and declare `io_timeout_s` or `recv_timeout` as a finite
    positive number at or below 0.1 seconds.  A transport that can block
    indefinitely is unsupported by this design (worker-supervisor or process
    isolation were the separately rejected alternatives).

Importing this module and using the Task 1 control functions perform no
network, camera, serial, debugger, Keil, flash, or hardware I/O.  Task 2
opens camera/TCP resources only from the explicit `--execute` CLI path.
"""

from __future__ import annotations

import argparse
import copy
import datetime as _datetime
from fractions import Fraction
import importlib.util
import json
import math
import time
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

_RESOURCE_ROOT = Path(__file__).resolve().parents[2]
_TRANSPORT_SOAK_PATH = (_RESOURCE_ROOT / "tools" / "shakedown_toolchain"
                        / "transport_soak.py")


def _load_transport_soak():
    """Load the shared transport-soak module read-only, or fail loudly."""
    if not _TRANSPORT_SOAK_PATH.exists():
        raise ImportError(
            "transport_soak module absent: {0}".format(
                _TRANSPORT_SOAK_PATH))
    spec = importlib.util.spec_from_file_location(
        "transport_soak", str(_TRANSPORT_SOAK_PATH))
    if spec is None or spec.loader is None:
        raise ImportError(
            "cannot build import spec for transport_soak at: {0}".format(
                _TRANSPORT_SOAK_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


soak = _load_transport_soak()

# `transport_soak` inserts the digital_twin source dir into sys.path during its
# own import; import the protocol and frame-decoder layers after loading it so
# `real_world` resolves regardless of how this module was reached.
from real_world.runtime_protocol import (  # noqa: E402
    ParameterCommand,
    RunCommand,
    frame,
    make_runtime_identifier,
    parse_ack,
    parse_status,
    validate_parameter_update,
)
from real_world.frame_parser import (  # noqa: E402
    decode_health,
    decode_telemetry,
)

# ── ground-shakedown constants ──────────────────────────────────────────
SPEED_STEPS = (580, 480, 380, 280, 260)
BASELINE = ParameterCommand("baseline", 1, 35.0, 0.0, 10.0, 680)

ACK_TIMEOUT_S = 5.0          # per-P ACK gate; error/reject returns immediately
STATUS_TIMEOUT_S = 2.0       # pre-STOP / START / final-STOP confirm windows

# Single-owner lifecycle constants (2026-08-05 specification).
HEARTBEAT_PERIOD_S = 0.2
MAX_DECLARED_IO_TIMEOUT_S = 0.1
IO_CALL_BUDGET_S = 0.15

# Task 2 camera/evidence constants.  These are declarations only: importing
# this module must not resolve executables, create directories, or start a
# process.
CAMERA_DEVICE_NAME = "EMEET SmartCam C960"
CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
CAMERA_FPS = 30.0
CAMERA_FPS_TOLERANCE = 0.5
MAX_DEFAULT_DURATION_S = 3.0
MAX_DURATION_S = 20.0
IMU_VALIDITY_FUSION_REQUIRED = 0x0F
IMU_VALIDITY_DT_CLAMPED = 0x10
IMU_INIT_STATUS_OK = 0x00
REQUIRED_ARTIFACTS = (
    "camera.mkv",
    "camera_ffmpeg.log",
    "raw_io.json",
    "shakedown_report.json",
)


class CameraStartError(RuntimeError):
    """The camera process could not reach the startup gate."""


class CameraValidationError(RuntimeError):
    """Camera shutdown or ffprobe evidence failed validation."""


class ControlAwareMixedStreamParser(soak.MixedStreamParser):
    """Historical mixed parser + forwarding of the suffix from the last `A,`/`S,`.

    The historical parser only surfaces `S,` lines.  The ground session also
    needs `A,` acknowledgement evidence, so on newline this adapter forwards
    the text beginning at the last `A,` or `S,` occurrence (ESP AT-echo noise
    that merges with the frame in one line is still stripped).
    """

    def feed(self, byte):
        if self._fp.busy:
            self._feed_binary(byte)
            return
        if byte == 0xAA:
            self._feed_binary(byte)
            return
        if byte == 0x0A:
            self._ascii.append(byte)
            line = self._ascii.decode("ascii", errors="replace")
            self._ascii.clear()
            if self._on_line is None:
                return
            index = max(line.rfind("A,"), line.rfind("S,"))
            if index >= 0:
                self._on_line(line[index:])
            return
        if byte == 0x0D:
            return
        if 0x20 <= byte <= 0x7E:
            self._ascii.append(byte)
        else:
            self._ascii.clear()


def _failure(stage, code, detail, now):
    """Build one structured failure record with exactly the specified keys."""
    return {
        "stage": stage,
        "code": code,
        "detail": detail,
        "monotonic_s": round(now, 6),
    }


def _socket_phase(state="NOT_EXECUTED", call_count=0,
                  started_monotonic_s=None, completed_monotonic_s=None,
                  failed_monotonic_s=None, elapsed_s=None, error=None):
    """Structured socket lifecycle evidence for connect/close."""
    return {
        "state": state,
        "call_count": call_count,
        "started_monotonic_s": started_monotonic_s,
        "completed_monotonic_s": completed_monotonic_s,
        "failed_monotonic_s": failed_monotonic_s,
        "elapsed_s": elapsed_s,
        "error": error,
    }


def _socket_close_phase_from_attempt(call_count, started_monotonic_s,
                                     completed_monotonic_s,
                                     failed_monotonic_s, error):
    end_time = (completed_monotonic_s if completed_monotonic_s is not None
                else failed_monotonic_s)
    elapsed_s = None
    if started_monotonic_s is not None and end_time is not None:
        elapsed_s = round(end_time - started_monotonic_s, 6)
    return _socket_phase(
        state=("FAILED" if error else
               ("COMPLETED" if call_count > 0 else "NOT_EXECUTED")),
        call_count=call_count,
        started_monotonic_s=started_monotonic_s,
        completed_monotonic_s=completed_monotonic_s,
        failed_monotonic_s=failed_monotonic_s,
        elapsed_s=elapsed_s,
        error=error,
    )


def _camera_codec_tag_evidence(stream):
    raw_tag_string = None
    raw_tag = None
    if isinstance(stream, dict):
        raw_tag_string = stream.get("codec_tag_string")
        raw_tag = stream.get("codec_tag")
    normalized = (str(raw_tag_string).strip().upper()
                  if raw_tag_string is not None and str(raw_tag_string).strip()
                  else "UNKNOWN")
    expected_tag = "0X47504A4D"
    tag_value = None if raw_tag in (None, "") else str(raw_tag)
    tag_upper = None if tag_value is None else tag_value.strip().upper()
    if normalized == "UNKNOWN":
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "codec_tag_string": "UNKNOWN",
            "codec_tag": tag_value,
            "error": "codec tag string missing",
        }
    if normalized == "[0][0][0][0]" and tag_upper in (
            "0X0000", "0X00000000"):
        return {
            "status": "CONTAINER_UNSPECIFIED",
            "codec_tag_string": raw_tag_string,
            "codec_tag": tag_value,
            "error": "container did not preserve a codec tag",
        }
    if normalized != "MJPG":
        return {
            "status": "FAIL",
            "codec_tag_string": raw_tag_string,
            "codec_tag": tag_value,
            "error": "codec tag string is not MJPG",
        }
    if tag_upper is not None and tag_upper != expected_tag:
        return {
            "status": "FAIL",
            "codec_tag_string": raw_tag_string,
            "codec_tag": tag_value,
            "error": "codec tag value does not match 0x47504A4D",
        }
    return {
        "status": "PASS",
        "codec_tag_string": raw_tag_string,
        "codec_tag": tag_value,
        "error": None,
    }


def _camera_input_codec_tag_evidence(log_text):
    """Extract the source FourCC from FFmpeg's DirectShow input report."""
    evidence = {
        "status": "INSUFFICIENT_EVIDENCE",
        "source": "ffmpeg_input_log",
        "codec_name": None,
        "codec_tag_string": None,
        "codec_tag": None,
        "raw_line": None,
        "error": "DirectShow input codec evidence unavailable",
    }
    if not isinstance(log_text, str) or not log_text.strip():
        return evidence
    input_seen = False
    for line in log_text.splitlines():
        if re.search(r"Input\s+#0,\s*dshow\b", line, re.IGNORECASE):
            input_seen = True
            continue
        if not input_seen:
            continue
        if re.search(r"Output\s+#0,", line, re.IGNORECASE):
            break
        if not re.search(r"^\s*Stream\s+#0:0:\s*Video:", line,
                         re.IGNORECASE):
            continue
        match = re.search(
            r"Video:\s*(?P<codec>[A-Za-z0-9_]+).*?"
            r"\((?P<tag>[A-Za-z0-9]{4})\s*/\s*"
            r"(?P<value>0x[0-9A-Fa-f]+)\)",
            line,
            re.IGNORECASE,
        )
        if match is None:
            evidence["error"] = "DirectShow input codec tag line is malformed"
            evidence["raw_line"] = line
            return evidence
        parsed = _camera_codec_tag_evidence({
            "codec_tag_string": match.group("tag"),
            "codec_tag": match.group("value"),
        })
        parsed["source"] = "ffmpeg_input_log"
        parsed["codec_name"] = match.group("codec").lower()
        parsed["raw_line"] = line
        if parsed["codec_name"] != "mjpeg":
            parsed["status"] = "FAIL"
            parsed["error"] = "DirectShow input codec is not mjpeg"
        return parsed
    return evidence


def _socket_lifecycle_failure(control_report):
    if not isinstance(control_report, dict):
        return False
    socket_report = control_report.get("socket")
    if not isinstance(socket_report, dict):
        return False
    connect = socket_report.get("connect")
    close = socket_report.get("close")
    if isinstance(connect, dict):
        if connect.get("state") == "FAILED":
            return True
    if isinstance(close, dict):
        if close.get("state") == "FAILED":
            return True
        if close.get("call_count") not in (None, 1):
            return True
        if close.get("state") not in (None, "COMPLETED"):
            return True
    return False


def _socket_lifecycle_complete(control_report):
    if not isinstance(control_report, dict):
        return False
    socket_report = control_report.get("socket")
    if not isinstance(socket_report, dict):
        return False
    connect = socket_report.get("connect")
    close = socket_report.get("close")
    if not isinstance(connect, dict) or not isinstance(close, dict):
        return False
    if connect.get("state") != "COMPLETED":
        return False
    if connect.get("call_count") != 1:
        return False
    if connect.get("started_monotonic_s") is None:
        return False
    if connect.get("completed_monotonic_s") is None:
        return False
    if close.get("state") != "COMPLETED":
        return False
    if close.get("call_count") != 1:
        return False
    if close.get("started_monotonic_s") is None:
        return False
    if close.get("completed_monotonic_s") is None:
        return False
    return True


def _socket_close_attempted(socket_report):
    if not isinstance(socket_report, dict):
        return False
    close = socket_report.get("close")
    if not isinstance(close, dict):
        return False
    try:
        call_count = int(close.get("call_count", 0))
    except (TypeError, ValueError):
        return False
    return call_count >= 1


def validate_speed_plan(campaign_id="shake"):
    """Build and validate the five-step bounded speed plan.

    Each step is `ParameterCommand(campaign_id, version 1..5, kp=35, ki=0,
    kd=10, speed)` and every step must satisfy `validate_parameter_update()`
    against the 680-speed baseline / prior step.
    """
    plan = []
    previous = BASELINE
    for version, speed in enumerate(SPEED_STEPS, start=1):
        command = ParameterCommand(campaign_id, version, 35.0, 0.0, 10.0, speed)
        validate_parameter_update(command, previous)
        plan.append(command)
        previous = command
    return plan


# ── pre-session validation (Step 5) ─────────────────────────────────────

def _validate_preflight(transport, duration_s):
    """Return a rejection detail string, or None when the session may start.

    No transport or raw-logger method is called on this path; the caller
    retains ownership until validation passes.
    """
    if isinstance(duration_s, bool):
        return "duration_s must not be boolean (got {0!r})".format(duration_s)
    if not isinstance(duration_s, (int, float)):
        return "duration_s must be numeric (got {0!r})".format(duration_s)
    if not math.isfinite(duration_s):
        return "duration_s must be finite (got {0!r})".format(duration_s)
    if duration_s < 0:
        return "duration_s must be >= 0 (got {0!r})".format(duration_s)
    for name in ("send", "recv", "close"):
        method = getattr(transport, name, None)
        if not callable(method):
            return "transport.{0} is missing or not callable".format(name)
    declaration = getattr(transport, "io_timeout_s", None)
    if declaration is None:
        declaration = getattr(transport, "recv_timeout", None)
    if declaration is None:
        return "transport must declare io_timeout_s or recv_timeout"
    if isinstance(declaration, bool):
        return ("transport io declaration must not be boolean (got {0!r})"
                .format(declaration))
    if not isinstance(declaration, (int, float)):
        return ("transport io declaration must be numeric (got {0!r})"
                .format(declaration))
    if not math.isfinite(declaration):
        return ("transport io declaration must be finite (got {0!r})"
                .format(declaration))
    if declaration <= 0:
        return ("transport io declaration must be positive (got {0!r})"
                .format(declaration))
    if declaration > MAX_DECLARED_IO_TIMEOUT_S:
        return ("transport io declaration must be <= {0}s (got {1!r})"
                .format(MAX_DECLARED_IO_TIMEOUT_S, declaration))
    return None


def _preflight_result(detail):
    """Structured control FAIL for a rejected pre-session declaration.

    No dependency method is called; `stop.attempted` is false,
    `send_outcome` is `NOT_INVOKED`, quiescence is unproven, and
    `cut_power_warning` is true because STOP was never proved.
    """
    now = time.monotonic()
    return {
        "run_mode": "run",
        "control_verdict": "FAIL",
        "cut_power_warning": True,
        "aborted_before_collect": True,
        "initial_status": None,
        "pre_stop": {"cmd_sent": False, "confirmed": False,
                     "status": None, "failure_reason": "PRESESSION_VALIDATION",
                     "cmd_hex": None},
        "speed_override": {"applied_speeds": [], "validated": False,
                           "failure_reason": "PRESESSION_VALIDATION"},
        "start": {"cmd_sent": False, "confirmed": False,
                  "status": None, "failure_reason": "PRESESSION_VALIDATION",
                  "cmd_hex": None},
        "stop": {"attempted": False, "rollback_requested": False,
                 "cmd_sent": False, "send_outcome": "NOT_INVOKED",
                 "send_error": None, "confirmed": False,
                 "stop_confirmed": False, "status": None,
                 "failure_reason": "PRESESSION_VALIDATION", "cmd_hex": None,
                 "reservation_monotonic_s": None, "reserved_receive_seq": 0,
                 "io_budget_exceeded": False},
        "parameter_acks": [],
        "protocol_anomalies": [],
        "statuses": [],
        "parse_errors": [],
        "telemetry": {"n": 0, "frames": []},
        "health_raw": [],
        "health": soak.compute_health_summary([]),
        "raw": {"n_rx_events": 0, "n_tx_events": 0,
                "n_rx_bytes": 0, "n_tx_bytes": 0},
        "rollback_requested": False,
        "stop_confirmed": False,
        "heartbeat": {"started": False, "ok": True, "n_sent": 0,
                      "failure": None, "stopped_before_final_stop": None,
                      "active_at_terminal_stop_reservation": None},
        "cleanup_errors": [],
        "unexpected_exception": None,
        "primary_failure": {"stage": "preflight",
                            "code": "PRESESSION_VALIDATION",
                            "detail": detail,
                            "monotonic_s": round(now, 6)},
        "secondary_errors": [],
        "quiescence": {"proven": False, "freeze_monotonic_s": None,
                       "n_frozen_raw_events": 0},
        "raw_io": {"published": False,
                   "write_error": "NOT_ATTEMPTED_PRESESSION_VALIDATION"},
        "socket": {
            "connect": _socket_phase(state="NOT_EXECUTED"),
            "close": _socket_phase(state="NOT_EXECUTED"),
        },
    }


class _SessionLoop(object):
    """Single-owner synchronous session.  `__init__` is state only; `run()` is
    the single convergence path.  The calling thread is the only actor that
    calls transport/raw-logger methods or mutates evidence."""

    def __init__(self, transport, campaign_id, run_id, duration_s, raw_logger):
        self.transport = transport
        self.campaign_id = campaign_id
        self.run_id = run_id
        self.duration_s = duration_s
        self.raw_logger = raw_logger

        # receive evidence
        self.receive_seq = 0
        self.ack_events = []          # FIFO of ACK / ACK-parse-error envelopes
        self.status_events = []       # FIFO of STATUS / STATUS-parse-error envelopes
        self.parameter_acks = []
        self.statuses = []            # every parsed status record (public)
        self.parse_errors = []
        self.protocol_anomalies = []
        self.telemetry_frames = []
        self.health_frames = []

        # parser
        self.parser = ControlAwareMixedStreamParser(
            on_telemetry=self._on_telemetry,
            on_line=self._on_line,
            on_health=self._on_health,
        )

        # deadlines
        self.overall_deadline = None

        # heartbeat
        self.hb_started = False
        self.hb_active = False
        self.hb_count = 0
        self.hb_failure = None
        self.hb_next_deadline = None
        self.hb_stopped_before_final_stop = None
        self.hb_active_at_terminal_stop_reservation = None

        # public records
        self.initial_status = None
        self.pre_stop_record = {
            "cmd_sent": False, "confirmed": False, "status": None,
            "failure_reason": None, "cmd_hex": None}
        self.speed_override = {"applied_speeds": [], "validated": False,
                               "failure_reason": None}
        self.applied_speeds = []
        self.start_record = {
            "cmd_sent": False, "confirmed": False, "status": None,
            "failure_reason": None, "cmd_hex": None}
        self.stop_record = None
        self.stop_reserved = False
        self.stop_raw_log_ok = True
        self.window_start_ns = None
        self.start_command_monotonic = None

        # failures and cleanup
        self.primary_failure = None
        self.secondary_errors = []
        self.cleanup_errors = []
        self.unexpected_exception = None

        # close / freeze / publication
        self.close_count = 0
        self.close_outcome = None
        self.close_started_monotonic_s = None
        self.close_completed_monotonic_s = None
        self.close_failed_monotonic_s = None
        self._close_ok = False
        self.frozen_raw_events = None
        self.freeze_monotonic_s = None
        self.quiescence_proven = False
        self.raw_io = {"published": False, "write_error": None}
        self.cut_power_warning = False
        self.aborted_before_collect = False

    # ── failure ordering ────────────────────────────────────────────────
    def _record_primary(self, stage, code, detail, exception_repr=None):
        if self.primary_failure is not None:
            return
        self.primary_failure = _failure(stage, code, detail, time.monotonic())
        if exception_repr is not None:
            self.unexpected_exception = exception_repr

    def _record_secondary(self, stage, code, detail):
        self.secondary_errors.append(_failure(stage, code, detail,
                                              time.monotonic()))

    def _record_cleanup(self, key, detail):
        self.cleanup_errors.append("{0}: {1}".format(key, detail))

    # ── receive envelope model (Step 6) ─────────────────────────────────
    def _status_record(self, parsed, envelope):
        return {
            "campaign_id": parsed["campaign_id"],
            "campaign": parsed["campaign_id"],
            "run_id": parsed["run_id"],
            "state": parsed["state"],
            "reason": parsed["reason"],
            "tick_ms": parsed["tick_ms"],
            "receive_seq": envelope["receive_seq"],
            "receive_monotonic_s": envelope["receive_monotonic_s"],
        }

    def _ack_record(self, parsed, envelope):
        return {
            "campaign_id": parsed["campaign_id"],
            "version": parsed["version"],
            "outcome": parsed["outcome"],
            "reason": parsed["reason"],
            "raw_line": envelope["raw_line"],
            "receive_seq": envelope["receive_seq"],
            "receive_monotonic_s": envelope["receive_monotonic_s"],
        }

    def _anomaly_status(self, parsed):
        return {
            "campaign": parsed["campaign_id"],
            "run_id": parsed["run_id"],
            "state": parsed["state"],
            "reason": parsed["reason"],
            "tick_ms": parsed["tick_ms"],
        }

    def _on_telemetry(self, payload):
        decoded = decode_telemetry(payload)
        if not decoded:
            return
        self.telemetry_frames.append({
            "tick_ms": int(decoded["tick_ms"]),
            "pc_recv_ns": time.monotonic_ns(),
            "s0": int(decoded["s0"]), "s1": int(decoded["s1"]),
            "s2": int(decoded["s2"]), "s3": int(decoded["s3"]),
            "m1": int(decoded["m1"]), "m2": int(decoded["m2"]),
            "m3": int(decoded["m3"]), "m4": int(decoded["m4"]),
            "error": int(decoded["error"]),
            "pid_output": int(decoded["pid_output"]),
            "yaw_rad": round(float(decoded.get("yaw", 0.0)), 6),
            "imu_yaw_deg_x100": int(decoded["imu_yaw_deg_x100"]),
            "imu_validity": int(decoded["imu_validity"]),
            "imu_validity_known": bool(decoded["imu_validity_known"]),
            "imu_init_status": int(decoded["imu_init_status"]),
            "imu_init_status_known": bool(decoded["imu_init_status_known"]),
            "imu_ax_raw": (
                int(decoded["imu_ax_raw"])
                if decoded["imu_ax_raw"] is not None else None
            ),
            "imu_ay_raw": (
                int(decoded["imu_ay_raw"])
                if decoded["imu_ay_raw"] is not None else None
            ),
            "imu_az_raw": (
                int(decoded["imu_az_raw"])
                if decoded["imu_az_raw"] is not None else None
            ),
            "imu_gx_raw": (
                int(decoded["imu_gx_raw"])
                if decoded["imu_gx_raw"] is not None else None
            ),
            "imu_gy_raw": (
                int(decoded["imu_gy_raw"])
                if decoded["imu_gy_raw"] is not None else None
            ),
            "imu_gz_raw": (
                int(decoded["imu_gz_raw"])
                if decoded["imu_gz_raw"] is not None else None
            ),
            "sample_seq": (
                int(decoded["sample_seq"])
                if decoded["sample_seq"] is not None else None
            ),
            "imu_raw_known": bool(decoded["imu_raw_known"]),
        })

    def _on_health(self, payload):
        decoded = decode_health(payload)
        if not decoded:
            return
        record = {"frame_ts_s": round(time.time(), 6),
                  "pc_recv_ns": time.monotonic_ns()}
        for key, value in decoded.items():
            record[key] = int(value)
        self.health_frames.append(record)

    def _on_line(self, line):
        self.receive_seq += 1
        seq = self.receive_seq
        received_at = time.monotonic()
        if line.startswith("A,"):
            try:
                ack = parse_ack(line)
            except Exception as exc:  # noqa: BLE001 - record, do not crash
                self.parse_errors.append({"line": line, "error": repr(exc)})
                self.ack_events.append({
                    "kind": "parse_error", "receive_seq": seq,
                    "receive_monotonic_s": round(received_at, 6),
                    "raw_line": line, "parsed": None, "error": repr(exc)})
                return
            parsed = {
                "campaign_id": ack.campaign_id,
                "version": ack.version,
                "outcome": ack.outcome,
                "reason": ack.reason,
            }
            envelope = {
                "kind": "ack", "receive_seq": seq,
                "receive_monotonic_s": round(received_at, 6),
                "raw_line": line, "parsed": parsed, "error": None,
            }
            self.ack_events.append(envelope)
            self.parameter_acks.append(self._ack_record(parsed, envelope))
            return
        if line.startswith("S,"):
            try:
                st = parse_status(line)
            except Exception as exc:  # noqa: BLE001 - record, do not crash
                self.parse_errors.append({"line": line, "error": repr(exc)})
                self.status_events.append({
                    "kind": "parse_error", "receive_seq": seq,
                    "receive_monotonic_s": round(received_at, 6),
                    "raw_line": line, "parsed": None, "error": repr(exc)})
                return
            parsed = {
                "campaign_id": st.campaign_id,
                "run_id": st.run_id,
                "state": st.state,
                "reason": st.reason,
                "tick_ms": st.tick_ms,
            }
            envelope = {
                "kind": "status", "receive_seq": seq,
                "receive_monotonic_s": round(received_at, 6),
                "raw_line": line, "parsed": parsed, "error": None,
            }
            self.status_events.append(envelope)
            self.statuses.append(self._status_record(parsed, envelope))
            return

    def _feed(self, data):
        for byte in data:
            self.parser.feed(byte)

    def _time_exceeded(self, deadline):
        return time.monotonic() >= deadline

    # ── timed I/O (Step 5/6) ────────────────────────────────────────────
    def _timed_send(self, data, stage):
        start = time.monotonic()
        try:
            self.transport.send(data)
            sent, error = True, None
        except Exception as exc:  # noqa: BLE001 - ambiguous transmission
            sent, error = False, exc
        elapsed = time.monotonic() - start
        io_budget = elapsed > IO_CALL_BUDGET_S
        if io_budget:
            self._record_primary(
                stage, "IO_CALL_BUDGET_EXCEEDED",
                "transport.send({0}) elapsed={1:.3f}s > budget {2:.2f}s"
                .format(stage, elapsed, IO_CALL_BUDGET_S))
        if error is not None:
            code = ("STOP_SEND_EXCEPTION" if stage == "stop"
                    else "HEARTBEAT_SEND_EXCEPTION" if stage == "heartbeat"
                    else "SEND_EXCEPTION")
            detail = "{0!r}".format(error)
            if self.primary_failure is None:
                self._record_primary(stage, code, detail,
                                     exception_repr=repr(error))
            else:
                self._record_secondary(stage, code, detail)
        return {
            "sent": sent, "error": error,
            "send_outcome": "COMPLETED" if sent else "AMBIGUOUS_EXCEPTION",
            "io_budget_exceeded": io_budget, "elapsed_s": elapsed,
            "started_monotonic": start,
        }

    def _raw_log_send_cmd(self, data):
        try:
            self.raw_logger.log_send(data)
            return {"ok": True, "error": None}
        except Exception as exc:  # noqa: BLE001 - active evidence failure
            detail = "log_send: {0!r}".format(exc)
            if self.primary_failure is None:
                self._record_primary("raw_log", "ACTIVE_RAW_LOG_FAILURE",
                                     detail, exception_repr=repr(exc))
            else:
                self._record_secondary("raw_log", "ACTIVE_RAW_LOG_FAILURE",
                                       detail)
            return {"ok": False, "error": detail}

    def _bounded_recv(self, deadline):
        start = time.monotonic()
        try:
            data = self.transport.recv(4096)
        except Exception as exc:  # noqa: BLE001 - running-window failure
            elapsed = time.monotonic() - start
            detail = "transport.recv raised: {0!r}".format(exc)
            if self.primary_failure is None:
                self._record_primary("recv", "RECEIVE_EXCEPTION", detail,
                                     exception_repr=repr(exc))
            else:
                self._record_secondary("recv", "RECEIVE_EXCEPTION", detail)
            if elapsed > IO_CALL_BUDGET_S:
                self._record_secondary(
                    "recv", "IO_CALL_BUDGET_EXCEEDED",
                    "transport.recv elapsed={0:.3f}s > budget {1:.2f}s"
                    .format(elapsed, IO_CALL_BUDGET_S))
            return None, "EXCEPTION"
        elapsed = time.monotonic() - start
        if data is not None and data != b"":
            try:
                self.raw_logger.log_recv(data)
            except Exception as exc:  # noqa: BLE001 - active evidence failure
                detail = "log_recv: {0!r}".format(exc)
                if self.primary_failure is None:
                    self._record_primary("raw_log", "ACTIVE_RAW_LOG_FAILURE",
                                         detail, exception_repr=repr(exc))
                else:
                    self._record_secondary("raw_log", "ACTIVE_RAW_LOG_FAILURE",
                                           detail)
        if elapsed > IO_CALL_BUDGET_S:
            detail = ("transport.recv elapsed={0:.3f}s > budget {1:.2f}s"
                      .format(elapsed, IO_CALL_BUDGET_S))
            if self.primary_failure is None:
                self._record_primary("recv", "IO_CALL_BUDGET_EXCEEDED",
                                     detail)
            else:
                self._record_secondary("recv", "IO_CALL_BUDGET_EXCEEDED",
                                       detail)
            return data, "BUDGET"
        return data, None

    def _drain_until_bounded_timeout(self, deadline):
        """Read until one bounded `b""` so pre-existing events receive
        pre-boundary sequence numbers.  Capped by the active phase and overall
        deadlines; continuous input that prevents a bounded boundary fails
        closed."""
        while True:
            if (self._time_exceeded(deadline)
                    or self._time_exceeded(self.overall_deadline)):
                return False
            data, status = self._bounded_recv(deadline)
            if status == "EXCEPTION":
                return False
            if data is None or data == b"":
                return True
            self._feed(data)

    # ── command send (transport + raw log as independent outcomes) ──────
    def _send_command(self, data, deadline):
        if self.stop_reserved:
            self._record_primary(
                "control", "INTERNAL_COMMAND_AFTER_STOP_RESERVATION",
                "a non-STOP control command was attempted after terminal STOP "
                "reservation")
            return {"sent": False, "error": None,
                    "send_outcome": "NOT_INVOKED",
                    "io_budget_exceeded": False, "drain_ok": False,
                    "rollback_requested": False, "send_error": None,
                    "raw_log": {"ok": False, "error": "not invoked"}}, \
                self.receive_seq
        drain_ok = self._drain_until_bounded_timeout(deadline)
        boundary = self.receive_seq
        if not drain_ok:
            self._record_primary(
                "command", "DRAIN_FAILED",
                "continuous input prevented a bounded pre-command boundary")
            return {"sent": False, "error": None,
                    "send_outcome": "NOT_INVOKED",
                    "io_budget_exceeded": False, "drain_ok": False,
                    "rollback_requested": False, "send_error": None,
                    "raw_log": {"ok": False, "error": "not invoked"}}, boundary
        result = self._timed_send(data, "command")
        result["drain_ok"] = True
        result["rollback_requested"] = True  # send invocation begins
        result["send_error"] = (repr(result["error"])
                                if result["error"] is not None else None)
        raw = self._raw_log_send_cmd(data)
        result["raw_log"] = raw
        return result, boundary

    # ── gates (Step 6) ──────────────────────────────────────────────────
    def _service_ack_gate(self, boundary, version, deadline):
        """First post-boundary ACK or ACK parse error is decisive for a P gate."""
        while True:
            if self.primary_failure is not None:
                return None, False, self.primary_failure["code"]
            if (self._time_exceeded(deadline)
                    or self._time_exceeded(self.overall_deadline)):
                return None, False, "TIMEOUT"
            while self.ack_events:
                event = self.ack_events[0]
                if event["receive_seq"] <= boundary:
                    self.ack_events.pop(0)
                    self.protocol_anomalies.append({
                        "kind": "stale_ack",
                        "seq": event["receive_seq"],
                        "boundary": boundary,
                        "line": event["raw_line"],
                    })
                    return None, False, (
                        "STALE_ACK_PRE_BOUNDARY:seq={0}<=boundary={1}".format(
                            event["receive_seq"], boundary))
                self.ack_events.pop(0)
                if event["kind"] == "parse_error":
                    return None, False, "PARSE_ERROR:" + (event["error"] or "?")
                parsed = event["parsed"]
                if (parsed["campaign_id"] != self.campaign_id
                        or parsed["version"] != version):
                    return None, False, "MISMATCH"
                if parsed["outcome"] != "APPLIED" or parsed["reason"] != "APPLIED":
                    return None, False, parsed["reason"]
                return parsed, True, "APPLIED"
            data, status = self._bounded_recv(deadline)
            if status == "EXCEPTION":
                return None, False, "RECEIVE_EXCEPTION"
            if data is None:
                return None, False, "EOF"
            if data:
                self._feed(data)

    def _service_status_gate(self, boundary, state, reason, deadline,
                             allow_after_primary=False):
        """First post-boundary status or status parse error is decisive for an
        R gate.  A stale required-kind event is recorded as an anomaly and
        fails the gate."""
        while True:
            if self.primary_failure is not None and not allow_after_primary:
                return None, False, self.primary_failure["code"], None
            if (self._time_exceeded(deadline)
                    or self._time_exceeded(self.overall_deadline)):
                return None, False, "TIMEOUT", None
            while self.status_events:
                event = self.status_events[0]
                if event["receive_seq"] <= boundary:
                    self.status_events.pop(0)
                    self.protocol_anomalies.append({
                        "kind": "stale_status",
                        "seq": event["receive_seq"],
                        "boundary": boundary,
                        "status": (self._anomaly_status(event["parsed"])
                                   if event["parsed"] else None),
                    })
                    return None, False, (
                        "STALE_STATUS_PRE_BOUNDARY:seq={0}<=boundary={1}"
                        .format(event["receive_seq"], boundary)), None
                self.status_events.pop(0)
                if event["kind"] == "parse_error":
                    return None, False, "PARSE_ERROR:" + (event["error"] or "?"), event
                parsed = event["parsed"]
                if (parsed["campaign_id"] == self.campaign_id
                        and parsed["run_id"] == self.run_id):
                    if parsed["state"] == state and parsed["reason"] == reason:
                        return parsed, True, None, event
                    fail_reason = "STATUS_MISMATCH:{0}/{1}".format(
                        parsed["state"], parsed["reason"])
                else:
                    fail_reason = "STATUS_IDENTITY_MISMATCH"
                self.protocol_anomalies.append({
                    "kind": "decisive_status",
                    "seq": event["receive_seq"],
                    "boundary": boundary,
                    "status": self._anomaly_status(parsed),
                    "expected": "{0}/{1}".format(state, reason),
                })
                return parsed, False, fail_reason, event
            data, status = self._bounded_recv(deadline)
            if status == "EXCEPTION":
                return None, False, "RECEIVE_EXCEPTION", None
            if data is None:
                return None, False, "EOF", None
            if data:
                self._feed(data)

    def _pop_first_status_event(self):
        """Pop the first valid status envelope (parse errors stay evidence)."""
        while self.status_events:
            event = self.status_events.pop(0)
            if event["kind"] == "status":
                return event
        return None

    # ── session phases (control sequence, Step 6) ───────────────────────
    def _derive_overall_deadline(self):
        # initial-status 2s + pre-STOP 2s + five ACK 5s + START-confirm 2s
        # + authorized duration + terminal-STOP 2s + 1s scheduling margin.
        return (STATUS_TIMEOUT_S + STATUS_TIMEOUT_S + 5 * ACK_TIMEOUT_S
                + STATUS_TIMEOUT_S + self.duration_s + STATUS_TIMEOUT_S + 1.0)

    def _consume_initial_status(self):
        deadline = min(time.monotonic() + STATUS_TIMEOUT_S,
                       self.overall_deadline)
        if not self._drain_until_bounded_timeout(deadline):
            self._record_primary(
                "initial_status", "INITIAL_STATUS_FAILED",
                "initial drain could not reach a bounded boundary")
            return None, False
        while True:
            if (self._time_exceeded(deadline)
                    or self._time_exceeded(self.overall_deadline)):
                self._record_primary(
                    "initial_status", "INITIAL_STATUS_TIMEOUT",
                    "no valid connection status within the initial-status "
                    "budget")
                return None, False
            event = self._pop_first_status_event()
            if event is not None:
                return event, True
            data, status = self._bounded_recv(deadline)
            if status == "EXCEPTION":
                return None, False
            if data is None:
                self._record_primary(
                    "initial_status", "EOF",
                    "transport reached EOF before a connection status")
                return None, False
            if data:
                self._feed(data)

    def _phase_pre_stop(self):
        deadline = min(time.monotonic() + STATUS_TIMEOUT_S,
                       self.overall_deadline)
        cmd = RunCommand(self.campaign_id, self.run_id, "STOP").encode().encode("ascii")
        result, boundary = self._send_command(cmd, deadline)
        if not result["drain_ok"]:
            self.pre_stop_record = {
                "cmd_sent": False, "confirmed": False, "status": None,
                "failure_reason": "DRAIN_FAILED", "cmd_hex": cmd.hex()}
            self._promote_pre_stop_to_stop(
                result, boundary, None, None, False, "DRAIN_FAILED", cmd.hex())
            return False
        parsed, ok, reason, envelope = self._service_status_gate(
            boundary, "STOPPED", "STOP", deadline,
            allow_after_primary=True)
        self.pre_stop_record = {
            "cmd_sent": result["sent"], "confirmed": ok,
            "status": (self._status_record(parsed, envelope)
                       if parsed else None),
            "failure_reason": reason, "cmd_hex": cmd.hex(),
        }
        if (not (ok and result["sent"] and result["raw_log"]["ok"])
                or self.primary_failure is not None):
            # Promote this exact attempt to the terminal stop record; no
            # second STOP and no P/START follow.
            self._promote_pre_stop_to_stop(
                result, boundary, parsed, envelope, ok, reason, cmd.hex())
            return False
        return True

    def _promote_pre_stop_to_stop(self, result, boundary, parsed, envelope,
                                  ok, reason, cmd_hex):
        now = time.monotonic()
        self.stop_reserved = True
        self.hb_active_at_terminal_stop_reservation = None  # hb never started
        self.hb_stopped_before_final_stop = None
        self.stop_raw_log_ok = result["raw_log"]["ok"]
        self.stop_record = {
            "attempted": True,
            "rollback_requested": result["rollback_requested"],
            "cmd_sent": result["sent"],
            "send_outcome": result["send_outcome"],
            "send_error": result["send_error"],
            "confirmed": ok,
            "stop_confirmed": ok,
            "status": (self._status_record(parsed, envelope)
                       if parsed else None),
            "failure_reason": reason,
            "cmd_hex": cmd_hex,
            "reservation_monotonic_s": round(now, 6),
            "reserved_receive_seq": boundary,
            "io_budget_exceeded": result["io_budget_exceeded"],
        }
        self.cut_power_warning = True

    def _phase_parameters(self):
        plan = validate_speed_plan(self.campaign_id)
        applied = []
        for command in plan:
            deadline = min(time.monotonic() + ACK_TIMEOUT_S,
                           self.overall_deadline)
            result, boundary = self._send_command(
                command.encode().encode("ascii"), deadline)
            if not result["drain_ok"]:
                self._record_primary(
                    "parameter", "DRAIN_FAILED",
                    "P{0} drain could not reach a bounded boundary"
                    .format(command.version))
                self._fail_speed_override(applied, "DRAIN_FAILED", command)
                self._fail_start_record()
                return False
            if (self.primary_failure is not None
                    or not result["sent"]
                    or not result["raw_log"]["ok"]):
                reason = (self.primary_failure["code"]
                          if self.primary_failure is not None
                          else "SEND_OR_RAW_LOG_FAILURE")
                self._fail_speed_override(applied, reason, command)
                self._fail_start_record()
                return False
            _ack, ok, reason = self._service_ack_gate(
                boundary, command.version, deadline)
            if self.primary_failure is not None:
                self._fail_speed_override(
                    applied, self.primary_failure["code"], command)
                self._fail_start_record()
                return False
            if not ok:
                self._fail_speed_override(applied, reason, command)
                self._fail_start_record()
                return False
            applied.append(command.speed_max)
        self.applied_speeds = applied
        self.speed_override = {"applied_speeds": applied, "validated": True,
                               "failure_reason": None}
        return True

    def _fail_speed_override(self, applied, reason, command):
        self.speed_override = {
            "applied_speeds": applied, "validated": False,
            "failure_reason": reason,
            "failed_version": command.version,
            "command": command.encode().rstrip("\n"),
        }

    def _fail_start_record(self):
        self.start_record = {"cmd_sent": False, "confirmed": False,
                             "status": None, "cmd_hex": None}

    def _phase_start(self):
        deadline = min(time.monotonic() + STATUS_TIMEOUT_S,
                       self.overall_deadline)
        cmd = RunCommand(self.campaign_id, self.run_id, "START").encode().encode("ascii")
        result, boundary = self._send_command(cmd, deadline)
        self.start_command_monotonic = result.get("started_monotonic")
        if not result["drain_ok"]:
            self.start_record = {
                "cmd_sent": False, "confirmed": False, "status": None,
                "failure_reason": "DRAIN_FAILED", "cmd_hex": cmd.hex()}
            return False
        if (self.primary_failure is not None
                or not result["sent"]
                or not result["raw_log"]["ok"]):
            reason = (self.primary_failure["code"]
                      if self.primary_failure is not None
                      else "SEND_OR_RAW_LOG_FAILURE")
            self.start_record = {
                "cmd_sent": result["sent"], "confirmed": False,
                "status": None, "failure_reason": reason,
                "cmd_hex": cmd.hex()}
            return False
        parsed, ok, reason, envelope = self._service_status_gate(
            boundary, "RUNNING", "START", deadline)
        if self.primary_failure is not None:
            ok = False
            reason = self.primary_failure["code"]
        self.start_record = {
            "cmd_sent": result["sent"], "confirmed": ok,
            "status": (self._status_record(parsed, envelope)
                       if parsed else None),
            "failure_reason": reason, "cmd_hex": cmd.hex(),
        }
        return ok

    # ── heartbeat + bounded running window (Step 6) ─────────────────────
    def _hb_send_one(self):
        if not self.hb_active:
            return False
        cmd = soak.HeartbeatCommand(
            self.campaign_id, self.run_id).encode().encode("ascii")
        result = self._timed_send(cmd, "heartbeat")
        if result["error"] is not None:
            self.hb_failure = "heartbeat_send_error: {0!r}".format(
                result["error"])
            self._hb_deactivate()
            return False
        if result["io_budget_exceeded"]:
            self.hb_failure = "heartbeat_io_budget_exceeded"
            self._hb_deactivate()
            return False
        raw = self._raw_log_send_cmd(cmd)
        if not raw["ok"]:
            self.hb_failure = "heartbeat_raw_log_error: {0}".format(raw["error"])
            self._hb_deactivate()
            return False
        self.hb_count += 1
        self.hb_next_deadline = time.monotonic() + HEARTBEAT_PERIOD_S
        return True

    def _hb_deactivate(self):
        self.hb_active = False

    def _phase_running(self):
        self.window_start_ns = time.monotonic_ns()
        self.hb_started = True
        self.hb_active = True
        start_origin = (self.start_command_monotonic
                        if self.start_command_monotonic is not None
                        else time.monotonic())
        running_budget_s = max(0.0, self.duration_s - IO_CALL_BUDGET_S)
        running_deadline = min(start_origin + running_budget_s,
                               self.overall_deadline)
        if (self._time_exceeded(running_deadline)
                or self._time_exceeded(self.overall_deadline)):
            self._hb_deactivate()
            return
        # First heartbeat immediately on the calling thread.
        if not self._hb_send_one():
            return
        while True:
            if (self._time_exceeded(running_deadline)
                    or self._time_exceeded(self.overall_deadline)):
                break
            if self.hb_active:
                now = time.monotonic()
                if now >= self.hb_next_deadline:
                    if now >= self.hb_next_deadline + HEARTBEAT_PERIOD_S:
                        self._record_primary(
                            "heartbeat", "HEARTBEAT_SCHEDULING_FAILURE",
                            "heartbeat deadline missed by at least one full "
                            "period")
                        self._hb_deactivate()
                        break
                    if not self._hb_send_one():
                        break
            data, status = self._bounded_recv(running_deadline)
            if status in ("EXCEPTION", "BUDGET"):
                break  # primary failure already recorded; converge on STOP
            if self.primary_failure is not None:
                break  # active raw logging failure; fail closed before more I/O
            if data is None:
                self._record_primary(
                    "recv", "EOF",
                    "transport reached EOF during the running window")
                break
            if data:
                self._feed(data)
        self._hb_deactivate()

    # ── terminal STOP (once-only, Step 7) ───────────────────────────────
    def _terminal_stop(self):
        if self.stop_reserved:
            return  # already reserved (pre-STOP promotion); no second STOP
        deadline = min(time.monotonic() + STATUS_TIMEOUT_S,
                       self.overall_deadline)
        now = time.monotonic()
        if self.hb_started:
            self.hb_active_at_terminal_stop_reservation = self.hb_active
            self.hb_stopped_before_final_stop = not self.hb_active
        else:
            self.hb_active_at_terminal_stop_reservation = None
        # Once RUNNING has been confirmed, the running window is a hard safety
        # deadline. Draining until an empty recv here can keep the firmware in
        # RUNNING while telemetry remains continuous, so establish the current
        # receive boundary and send STOP immediately. Pre-start failures keep
        # the bounded drain because no motor-on deadline is active yet.
        if self.hb_started:
            drain_ok = True
            boundary = self.receive_seq
            boundary_mode = "immediate_running_deadline"
        else:
            drain_ok = self._drain_until_bounded_timeout(deadline)
            boundary = self.receive_seq
            boundary_mode = "bounded_pre_command_drain"
        if not drain_ok:
            self._record_primary(
                "stop", "DRAIN_FAILED",
                "continuous input prevented a bounded terminal-STOP boundary")
        # Allocate the record at reservation, before encoding/sending.
        self.stop_reserved = True
        self.stop_record = {
            "attempted": True, "rollback_requested": False, "cmd_sent": False,
            "send_outcome": "NOT_INVOKED", "send_error": None,
            "confirmed": False, "stop_confirmed": False, "status": None,
            "failure_reason": None, "cmd_hex": None,
            "reservation_monotonic_s": round(now, 6),
            "reserved_receive_seq": boundary,
            "boundary_mode": boundary_mode,
            "drain_ok": drain_ok,
            "io_budget_exceeded": False,
        }
        if not drain_ok:
            self.stop_record["failure_reason"] = "DRAIN_FAILED"
            self.cut_power_warning = True
            return
        cmd = RunCommand(self.campaign_id, self.run_id, "STOP").encode().encode("ascii")
        self.stop_record["cmd_hex"] = cmd.hex()
        self.stop_record["rollback_requested"] = True  # send invocation begins
        result = self._timed_send(cmd, "stop")
        self.stop_record["cmd_sent"] = result["sent"]
        self.stop_record["send_outcome"] = result["send_outcome"]
        self.stop_record["io_budget_exceeded"] = result["io_budget_exceeded"]
        if result["error"] is not None:
            self.stop_record["send_error"] = repr(result["error"])
            self._record_secondary("stop", "STOP_SEND_EXCEPTION",
                                   "{0!r}".format(result["error"]))
        raw = self._raw_log_send_cmd(cmd)
        self.stop_raw_log_ok = raw["ok"]
        if not raw["ok"]:
            self._record_secondary("raw_log", "ACTIVE_RAW_LOG_FAILURE",
                                   raw["error"])
        # Service the bounded confirmation window even after an ambiguous send.
        parsed, ok, reason, envelope = self._service_status_gate(
            boundary, "STOPPED", "STOP", deadline,
            allow_after_primary=True)
        self.stop_record["confirmed"] = ok
        self.stop_record["stop_confirmed"] = ok
        self.stop_record["status"] = (self._status_record(parsed, envelope)
                                      if parsed else None)
        self.stop_record["failure_reason"] = reason
        self._compute_cut_power()

    def _compute_cut_power(self):
        stop = self.stop_record
        if stop is None:
            self.cut_power_warning = True
            return
        power_ok = (
            stop["cmd_sent"] is True
            and not stop["io_budget_exceeded"]
            and self.stop_raw_log_ok
            and stop["confirmed"] is True
        )
        self.cut_power_warning = not power_ok

    # ── close / freeze / publication (Step 7) ───────────────────────────
    def _close(self):
        self.close_count += 1
        start = time.monotonic()
        self.close_started_monotonic_s = round(start, 6)
        try:
            self.transport.close()
        except BaseException as exc:  # noqa: BLE001 - structured close failure
            elapsed = time.monotonic() - start
            self.close_failed_monotonic_s = round(time.monotonic(), 6)
            self.close_outcome = {"completed": False, "error": repr(exc)}
            self._record_cleanup("transport_close", repr(exc))
            detail = "{0!r}".format(exc)
            if self.primary_failure is None:
                self._record_primary("close", "TRANSPORT_CLOSE_EXCEPTION",
                                     detail, exception_repr=repr(exc))
            else:
                self._record_secondary("close", "TRANSPORT_CLOSE_EXCEPTION",
                                       detail)
            self._close_ok = False
            return
        elapsed = time.monotonic() - start
        self.close_completed_monotonic_s = round(time.monotonic(), 6)
        self.close_outcome = {"completed": True, "elapsed_s": elapsed}
        if elapsed > IO_CALL_BUDGET_S:
            detail = ("transport.close elapsed={0:.3f}s > budget {1:.2f}s"
                      .format(elapsed, IO_CALL_BUDGET_S))
            self._record_cleanup("transport_close",
                                 "IO_CALL_BUDGET_EXCEEDED {0}".format(detail))
            if self.primary_failure is None:
                self._record_primary("close", "IO_CALL_BUDGET_EXCEEDED", detail)
            else:
                self._record_secondary("close", "IO_CALL_BUDGET_EXCEEDED",
                                       detail)
            self._close_ok = False
            return
        self._close_ok = True

    def _freeze(self):
        try:
            events = self.raw_logger.events()
        except Exception as exc:  # noqa: BLE001 - prevents quiescence proof
            detail = "{0!r}".format(exc)
            self._record_cleanup("raw_events_freeze", detail)
            if self.primary_failure is None:
                self._record_primary("raw", "RAW_EVENTS_FREEZE_FAILURE",
                                     detail, exception_repr=repr(exc))
            else:
                self._record_secondary("raw", "RAW_EVENTS_FREEZE_FAILURE",
                                       detail)
            self.frozen_raw_events = []
            return False, []
        self.frozen_raw_events = list(events)
        self.freeze_monotonic_s = round(time.monotonic(), 6)
        return True, self.frozen_raw_events

    def _publish(self, events):
        del events
        try:
            self.raw_logger.write()
        except Exception as exc:  # noqa: BLE001 - publication evidence only
            self.raw_io = {"published": False, "write_error": repr(exc)}
            self._record_cleanup("raw_write", repr(exc))
            self._record_secondary("raw_write", "RAW_WRITE_FAILURE",
                                   "{0!r}".format(exc))
            return
        self.raw_io = {"published": True, "write_error": None}

    # ── single convergence path (Step 5/7) ──────────────────────────────
    def run(self):
        self.overall_deadline = time.monotonic() + self._derive_overall_deadline()
        try:
            self._session()
        except KeyboardInterrupt:
            self._record_primary("session", "KEYBOARD_INTERRUPT",
                                 "KeyboardInterrupt",
                                 exception_repr="KeyboardInterrupt")
        except Exception as exc:  # noqa: BLE001 - fail-closed convergence
            self._record_primary("session", "UNEXPECTED_EXCEPTION",
                                 repr(exc), exception_repr=repr(exc))
        # Finalization is fixed-order with no return before the end:
        # 1. finish/fail terminal STOP confirmation
        self._terminal_stop()
        # 2. transport close exactly once
        self._close()
        # 3. copy raw events into a stable frozen list
        # 4. set freeze timestamp and frozen count
        freeze_ok, events = self._freeze()
        # 5. raw publication exactly once
        self._publish(events)
        self.quiescence_proven = bool(self._close_ok and freeze_ok)
        # 6-7. build one result and return with no possible later mutation
        return self._build_result()

    def _session(self):
        event, ok = self._consume_initial_status()
        if not ok:
            self.aborted_before_collect = True
            self.initial_status = None
            self.pre_stop_record = {
                "cmd_sent": False, "confirmed": False, "status": None,
                "failure_reason": "INITIAL_STATUS_FAILED", "cmd_hex": None}
            self.start_record = {
                "cmd_sent": False, "confirmed": False, "status": None,
                "failure_reason": "INITIAL_STATUS_FAILED", "cmd_hex": None}
            self.speed_override = {"applied_speeds": [],
                                   "failure_reason": "INITIAL_STATUS_FAILED"}
            return
        self.initial_status = self._status_record(event["parsed"], event)
        if not self._phase_pre_stop():
            self.aborted_before_collect = True
            return
        if not self._phase_parameters():
            self.aborted_before_collect = True
            return
        if not self._phase_start():
            self.aborted_before_collect = True
            return
        self._phase_running()

    # ── result build (Step 7) ───────────────────────────────────────────
    def _build_result(self):
        events = (self.frozen_raw_events
                  if self.frozen_raw_events is not None else [])
        n_rx = sum(1 for e in events if e["dir"] == "RX")
        n_tx = sum(1 for e in events if e["dir"] == "TX")
        n_rx_bytes = sum(e["n_bytes"] for e in events if e["dir"] == "RX")
        n_tx_bytes = sum(e["n_bytes"] for e in events if e["dir"] == "TX")

        control_ok = (
            self.initial_status is not None
            and self.pre_stop_record.get("confirmed") is True
            and len(self.applied_speeds) == 5
            and self.start_record.get("confirmed") is True
            and self.hb_failure is None
            and self.hb_active is False
            and self.hb_active_at_terminal_stop_reservation is False
            and self.stop_record is not None
            and self.stop_record.get("cmd_sent") is True
            and self.stop_record.get("confirmed") is True
            and self._close_ok
            and self.quiescence_proven
            and self.primary_failure is None
        )

        result = {
            "run_mode": "run",
            "control_verdict": "PASS" if control_ok else "FAIL",
            "cut_power_warning": self.cut_power_warning,
            "aborted_before_collect": self.aborted_before_collect,
            "initial_status": self.initial_status,
            "pre_stop": self.pre_stop_record,
            "speed_override": self.speed_override,
            "start": self.start_record,
            "stop": self.stop_record,
            "parameter_acks": self.parameter_acks,
            "protocol_anomalies": self.protocol_anomalies,
            "statuses": self.statuses,
            "parse_errors": self.parse_errors,
            "telemetry": {"n": len(self.telemetry_frames),
                          "frames": self.telemetry_frames},
            "health_raw": self.health_frames,
            "health": soak.compute_health_summary(self.health_frames),
            "raw": {"n_rx_events": n_rx, "n_tx_events": n_tx,
                    "n_rx_bytes": n_rx_bytes, "n_tx_bytes": n_tx_bytes},
            "rollback_requested": bool(
                self.stop_record["rollback_requested"]
                if self.stop_record else False),
            "stop_confirmed": bool(
                self.stop_record["confirmed"]
                if self.stop_record else False),
            "heartbeat": {
                "started": self.hb_started,
                "ok": self.hb_failure is None,
                "n_sent": self.hb_count,
                "failure": self.hb_failure,
                "stopped_before_final_stop": self.hb_stopped_before_final_stop,
                "active_at_terminal_stop_reservation":
                    self.hb_active_at_terminal_stop_reservation,
            },
            "cleanup_errors": self.cleanup_errors,
            "unexpected_exception": self.unexpected_exception,
            "primary_failure": self.primary_failure,
            "secondary_errors": self.secondary_errors,
            "quiescence": {
                "proven": self.quiescence_proven,
                "freeze_monotonic_s": self.freeze_monotonic_s,
                "n_frozen_raw_events": len(events),
            },
            "raw_io": self.raw_io,
            "socket": {
                "connect": _socket_phase(state="NOT_EXECUTED"),
                "close": _socket_phase(
                    state=("COMPLETED" if self.close_outcome
                           and self.close_outcome.get("completed")
                           else ("FAILED" if self.close_count > 0
                                 else "NOT_EXECUTED")),
                    call_count=self.close_count,
                    started_monotonic_s=self.close_started_monotonic_s,
                    completed_monotonic_s=self.close_completed_monotonic_s,
                    failed_monotonic_s=self.close_failed_monotonic_s,
                    elapsed_s=(self.close_outcome or {}).get("elapsed_s"),
                    error=(self.close_outcome or {}).get("error"),
                ),
            },
        }
        if self.window_start_ns is not None:
            result["window_start_ns"] = self.window_start_ns
        return result


def run_ground_session(transport, campaign_id, run_id, duration_s,
                       raw_logger=None):
    """Offline ACK-aware fail-closed ground session (single-owner lifecycle).

    Validates the transport's bounded-I/O declaration and `duration_s` before
    any dependency call; a rejected declaration returns a structured control
    FAIL without calling any transport/raw method.  Otherwise one `_SessionLoop`
    runs the complete command sequence:

      connection status -> pre-STOP -> P1..P5 (one APPLIED/APPLIED ACK each)
      -> START/RUNNING -> immediate heartbeat -> bounded running window
      -> heartbeat deactivation -> once-only terminal STOP + STOPPED/STOP
      -> transport close -> raw freeze -> raw publication -> one result.

    Task 1 emits only `control_verdict`; the overall `shakedown_verdict`
    belongs to Task 2.
    """
    preflight_detail = _validate_preflight(transport, duration_s)
    if preflight_detail is not None:
        return _preflight_result(preflight_detail)
    if raw_logger is None:
        raw_logger = soak.RawIoLogger(None)
    loop = _SessionLoop(transport, campaign_id, run_id, duration_s, raw_logger)
    return loop.run()


def _connect_and_run_ground_session(transport, campaign_id, run_id, duration_s,
                                    session_runner=run_ground_session,
                                    raw_logger_factory=None):
    """Connect through the canonical transport boundary and record evidence."""
    raw_logger_factory = raw_logger_factory or (lambda: None)
    connect_calls = 0
    close_calls = 0
    connect_started = round(time.monotonic(), 6)
    connect_completed = None
    connect_failed = None
    connect_error = None
    close_started = None
    close_completed = None
    close_failed = None
    close_error = None
    connected = False

    def _build_post_connect_failure(exc):
        detail = repr(exc)
        return {
            "run_mode": "run",
            "control_verdict": "FAIL",
            "cut_power_warning": True,
            "aborted_before_collect": True,
            "initial_status": None,
            "pre_stop": {"cmd_sent": False, "confirmed": False,
                         "status": None, "failure_reason": "POST_CONNECT_EXCEPTION",
                         "cmd_hex": None},
            "speed_override": {"applied_speeds": [], "validated": False,
                               "failure_reason": "POST_CONNECT_EXCEPTION"},
            "start": {"cmd_sent": False, "confirmed": False,
                      "status": None, "failure_reason": "POST_CONNECT_EXCEPTION",
                      "cmd_hex": None},
            "stop": {"attempted": False, "rollback_requested": False,
                     "cmd_sent": False, "send_outcome": "NOT_INVOKED",
                     "send_error": None, "confirmed": False,
                     "stop_confirmed": False, "status": None,
                     "failure_reason": "POST_CONNECT_EXCEPTION", "cmd_hex": None,
                     "reservation_monotonic_s": None, "reserved_receive_seq": 0,
                     "io_budget_exceeded": False},
            "parameter_acks": [],
            "protocol_anomalies": [],
            "statuses": [],
            "parse_errors": [],
            "telemetry": {"n": 0, "frames": []},
            "health_raw": [],
            "health": soak.compute_health_summary([]),
            "raw": {"n_rx_events": 0, "n_tx_events": 0,
                    "n_rx_bytes": 0, "n_tx_bytes": 0},
            "rollback_requested": False,
            "stop_confirmed": False,
            "heartbeat": {"started": False, "ok": True, "n_sent": 0,
                          "failure": None, "stopped_before_final_stop": None,
                          "active_at_terminal_stop_reservation": None},
            "cleanup_errors": ([] if close_error is None else [
                "transport_close: {0}".format(close_error)]),
            "unexpected_exception": detail,
            "primary_failure": _failure(
                "session_wrapper", "POST_CONNECT_EXCEPTION",
                detail, time.monotonic()),
            "secondary_errors": [],
            "quiescence": {"proven": False, "freeze_monotonic_s": None,
                           "n_frozen_raw_events": 0},
            "raw_io": {"published": False,
                       "write_error": "NOT_ATTEMPTED_POST_CONNECT_EXCEPTION"},
            "socket": {
                "connect": _socket_phase(
                    state="COMPLETED",
                    call_count=connect_calls,
                    started_monotonic_s=connect_started,
                    completed_monotonic_s=connect_completed,
                    elapsed_s=(None if connect_completed is None else round(
                        connect_completed - connect_started, 6)),
                    error=None,
                ),
                "close": _socket_close_phase_from_attempt(
                    close_calls, close_started, close_completed,
                    close_failed, close_error),
            },
        }

    def _close_once_if_needed(force=False):
        nonlocal close_calls, close_started, close_completed
        nonlocal close_failed, close_error
        if not connected and not force:
            return None
        if close_calls > 0 and not force:
            return None
        close_calls += 1
        close_started = round(time.monotonic(), 6)
        try:
            transport.close()
        except BaseException as exc:  # noqa: BLE001 - cleanup evidence only
            close_failed = round(time.monotonic(), 6)
            close_error = repr(exc)
            return exc
        close_completed = round(time.monotonic(), 6)
        return None

    try:
        connect_calls += 1
        transport.connect()
        connect_completed = round(time.monotonic(), 6)
        connected = True
    except Exception as exc:  # noqa: BLE001 - fail-closed connect evidence
        connect_failed = round(time.monotonic(), 6)
        connect_error = repr(exc)
        _close_once_if_needed(force=True)
        return {
            "run_mode": "run",
            "control_verdict": "FAIL",
            "cut_power_warning": True,
            "aborted_before_collect": True,
            "initial_status": None,
            "pre_stop": {"cmd_sent": False, "confirmed": False,
                         "status": None, "failure_reason": "CONNECT_FAILED",
                         "cmd_hex": None},
            "speed_override": {"applied_speeds": [], "validated": False,
                               "failure_reason": "CONNECT_FAILED"},
            "start": {"cmd_sent": False, "confirmed": False,
                      "status": None, "failure_reason": "CONNECT_FAILED",
                      "cmd_hex": None},
            "stop": {"attempted": False, "rollback_requested": False,
                     "cmd_sent": False, "send_outcome": "NOT_INVOKED",
                     "send_error": None, "confirmed": False,
                     "stop_confirmed": False, "status": None,
                     "failure_reason": "CONNECT_FAILED", "cmd_hex": None,
                     "reservation_monotonic_s": None, "reserved_receive_seq": 0,
                     "io_budget_exceeded": False},
            "parameter_acks": [],
            "protocol_anomalies": [],
            "statuses": [],
            "parse_errors": [],
            "telemetry": {"n": 0, "frames": []},
            "health_raw": [],
            "health": soak.compute_health_summary([]),
            "raw": {"n_rx_events": 0, "n_tx_events": 0,
                    "n_rx_bytes": 0, "n_tx_bytes": 0},
            "rollback_requested": False,
            "stop_confirmed": False,
            "heartbeat": {"started": False, "ok": True, "n_sent": 0,
                          "failure": None, "stopped_before_final_stop": None,
                          "active_at_terminal_stop_reservation": None},
            "cleanup_errors": ([] if close_error is None else [
                "transport_close: {0}".format(close_error)]),
            "unexpected_exception": connect_error,
            "primary_failure": _failure(
                "connect", "TRANSPORT_CONNECT_EXCEPTION",
                connect_error, time.monotonic()),
            "secondary_errors": [],
            "quiescence": {"proven": False, "freeze_monotonic_s": None,
                           "n_frozen_raw_events": 0},
            "raw_io": {"published": False,
                       "write_error": "NOT_ATTEMPTED_CONNECT_FAILED"},
            "socket": {
                "connect": _socket_phase(
                    state="FAILED",
                    call_count=connect_calls,
                    started_monotonic_s=connect_started,
                    failed_monotonic_s=connect_failed,
                    elapsed_s=(None if connect_failed is None else round(
                        connect_failed - connect_started, 6)),
                    error=connect_error,
                ),
                "close": _socket_phase(
                    **_socket_close_phase_from_attempt(
                        close_calls, close_started, close_completed,
                        close_failed, close_error)),
            },
        }
    try:
        raw_logger = raw_logger_factory()
        result = session_runner(transport, campaign_id, run_id, duration_s, raw_logger)
    except BaseException as exc:
        _close_once_if_needed()
        _attach_failure_report(exc, {"control": _build_post_connect_failure(exc)})
        raise
    if not isinstance(result, dict):
        exc = TypeError("session_runner must return dict, got {0}".format(
            type(result).__name__))
        _close_once_if_needed()
        _attach_failure_report(exc, {"control": _build_post_connect_failure(exc)})
        raise exc
    socket_report = result.get("socket")
    if not isinstance(socket_report, dict):
        socket_report = {}
        result["socket"] = socket_report
    socket_report["connect"] = _socket_phase(
        state="COMPLETED",
        call_count=connect_calls,
        started_monotonic_s=connect_started,
        completed_monotonic_s=connect_completed,
        elapsed_s=(None if connect_completed is None else round(
            connect_completed - connect_started, 6)),
        error=None,
    )
    close_report = socket_report.get("close")
    if not _socket_close_attempted(socket_report):
        _close_once_if_needed()
        socket_report["close"] = _socket_close_phase_from_attempt(
            close_calls, close_started, close_completed, close_failed, close_error)
    return result


# ---------------------------------------------------------------------------
# Task 2: immutable evidence and report boundary.
# ---------------------------------------------------------------------------

def validate_duration(duration_s, allow_extended=False):
    """Validate a positive bounded shakedown duration before resource use."""
    if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
        raise ValueError("duration must be a finite numeric value")
    if not math.isfinite(float(duration_s)):
        raise ValueError("duration must be finite")
    value = float(duration_s)
    if value <= 0.0:
        raise ValueError("duration must be greater than zero")
    if value > MAX_DURATION_S:
        raise ValueError("duration must not exceed {0}s".format(MAX_DURATION_S))
    if value > MAX_DEFAULT_DURATION_S and not allow_extended:
        raise ValueError(
            "duration above {0}s requires --allow-extended".format(
                MAX_DEFAULT_DURATION_S))
    return value


def make_evidence_dir(root, timestamp):
    """Create exactly one new timestamped evidence directory."""
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    target = root_path / "v1_ground_shakedown_{0}".format(timestamp)
    target.mkdir(parents=False, exist_ok=False)
    return target


def normalize_telemetry_units(report):
    """Normalize only the new report's historical yaw key to degrees.

    The first pass detects all unequal dual-field records before mutating any
    frame, so a conflict fails closed without leaving a partially normalized
    report.
    """
    telemetry = report.get("telemetry") if isinstance(report, dict) else None
    frames = telemetry.get("frames", []) if isinstance(telemetry, dict) else []
    if frames is None:
        frames = []
    if not isinstance(frames, list):
        raise ValueError("telemetry.frames must be a list")
    for frame_record in frames:
        if not isinstance(frame_record, dict):
            continue
        if "yaw_rad" in frame_record and "yaw_deg" in frame_record:
            if frame_record["yaw_rad"] != frame_record["yaw_deg"]:
                raise ValueError("conflicting yaw_rad and yaw_deg values")
    for frame_record in frames:
        if not isinstance(frame_record, dict):
            continue
        if "yaw_rad" in frame_record:
            frame_record["yaw_deg"] = frame_record.pop("yaw_rad")
    if isinstance(report, dict):
        report["telemetry_yaw_unit"] = "degree"
    return report


def summarize_imu_evidence(report):
    """Classify the IMU fields without promoting unknown data to a pass."""
    telemetry = report.get("telemetry") if isinstance(report, dict) else None
    frames = telemetry.get("frames", []) if isinstance(telemetry, dict) else []
    if not isinstance(frames, list):
        frames = []
    records = []
    unknown_count = 0
    for frame_record in frames:
        if not isinstance(frame_record, dict):
            unknown_count += 1
            continue
        if (frame_record.get("imu_validity_known") is not True or
                frame_record.get("imu_init_status_known") is not True):
            unknown_count += 1
            continue
        try:
            validity = int(frame_record["imu_validity"])
            init_status = int(frame_record["imu_init_status"])
        except (KeyError, TypeError, ValueError):
            unknown_count += 1
            continue
        records.append((validity, init_status))

    validity_values = sorted({validity for validity, _ in records})
    init_status_values = sorted({init_status for _, init_status in records})
    dt_clamped_frames = sum(
        1 for validity, _ in records
        if validity & IMU_VALIDITY_DT_CLAMPED)
    summary = {
        "status": "INSUFFICIENT_EVIDENCE",
        "verdict": "UNVERIFIED",
        "reason": "IMU_VALIDITY_OR_INIT_STATUS_UNKNOWN",
        "n_frames": len(frames),
        "n_known_frames": len(records),
        "validity_values": validity_values,
        "init_status_values": init_status_values,
        "dt_clamped_frames": dt_clamped_frames,
    }
    if not frames:
        summary["reason"] = "NO_TELEMETRY_FRAMES"
        return summary
    if unknown_count:
        return summary

    failures = []
    if any(init_status != IMU_INIT_STATUS_OK
           for _, init_status in records):
        failures.append("IMU_INIT_STATUS_NOT_OK")
    if any((validity & IMU_VALIDITY_FUSION_REQUIRED) !=
           IMU_VALIDITY_FUSION_REQUIRED for validity, _ in records):
        failures.append("IMU_VALIDITY_MASK_INCOMPLETE")
    if dt_clamped_frames:
        failures.append("DT_CLAMPED")
    summary["status"] = "VERIFIED"
    summary["verdict"] = "FAIL" if failures else "PASS"
    summary["reason"] = ("|".join(failures)
                          if failures else "VALID_INITIALIZED_FUSION_INPUT")
    return summary


def publish_report_atomic(evidence_dir, report):
    """Publish one JSON report through a same-directory atomic replacement."""
    evidence_path = Path(evidence_dir)
    if not evidence_path.is_dir():
        raise FileNotFoundError("evidence directory does not exist: {0}".format(
            evidence_path))
    final_path = evidence_path / "shakedown_report.json"
    temporary_path = evidence_path / ".shakedown_report_{0}.tmp".format(
        uuid.uuid4().hex)
    try:
        with open(temporary_path, "x", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(final_path))
    finally:
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass
    return final_path


def _artifact_present(value):
    """Interpret an artifact evidence value without treating a name as proof."""
    if isinstance(value, dict):
        if "present" in value:
            return bool(value["present"])
        if "path" in value:
            value = value["path"]
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        path = Path(value)
    except TypeError:
        return False
    return path.is_file() and os.access(str(path), os.R_OK)


def _known_control_failure(control_report):
    if not isinstance(control_report, dict):
        return True
    if control_report.get("control_verdict") != "PASS":
        return True
    if control_report.get("primary_failure"):
        return True
    if control_report.get("unexpected_exception"):
        return True
    if control_report.get("parse_errors"):
        return True
    if control_report.get("cleanup_errors"):
        return True
    if control_report.get("secondary_errors"):
        return True
    if control_report.get("protocol_anomalies"):
        return True
    heartbeat = control_report.get("heartbeat")
    if isinstance(heartbeat, dict) and heartbeat.get("ok") is False:
        return True
    if control_report.get("cut_power_warning") is True:
        return True
    raw_io = control_report.get("raw_io")
    if isinstance(raw_io, dict):
        if raw_io.get("published") is False or raw_io.get("write_error"):
            return True
    stop = control_report.get("stop")
    if isinstance(stop, dict):
        if stop.get("confirmed") is False:
            return True
        send_outcome = stop.get("send_outcome")
        if send_outcome is not None and send_outcome != "COMPLETED":
            return True
    if control_report.get("stop_confirmed") is False:
        return True
    if _socket_lifecycle_failure(control_report):
        return True
    return False


def _known_camera_failure(camera_report):
    if camera_report is None:
        return False
    if not isinstance(camera_report, dict):
        return True
    if camera_report.get("verdict") == "FAIL":
        return True
    if camera_report.get("camera_verdict") == "FAIL":
        return True
    if camera_report.get("startup_error") or camera_report.get("finalization_error"):
        return True
    if camera_report.get("forced_termination"):
        return True
    if camera_report.get("cleanup_errors"):
        return True
    if camera_report.get("errors"):
        return True
    if camera_report.get("clean_exit") is False:
        return True
    return False


def compute_shakedown_verdict(control_report, camera_report, artifacts):
    """Apply deterministic failure, evidence, then PASS precedence."""
    if _known_control_failure(control_report) or _known_camera_failure(camera_report):
        return "SHAKEDOWN_FAIL"
    if not _socket_lifecycle_complete(control_report):
        return "INSUFFICIENT_EVIDENCE"
    if not (isinstance(camera_report, dict)
            and (camera_report.get("verdict") == "PASS"
                 or camera_report.get("camera_verdict") == "PASS")):
        return "INSUFFICIENT_EVIDENCE"
    artifact_map = artifacts if isinstance(artifacts, dict) else {}
    missing = [name for name in REQUIRED_ARTIFACTS
               if not _artifact_present(artifact_map.get(name))]
    if missing:
        return "INSUFFICIENT_EVIDENCE"
    telemetry = control_report.get("telemetry", {}) if isinstance(
        control_report, dict) else {}
    frames = telemetry.get("frames", []) if isinstance(telemetry, dict) else []
    if not frames:
        return "INSUFFICIENT_EVIDENCE"
    return "SHAKEDOWN_PASS"


def _resolve_executable(executable_resolver, name):
    try:
        resolved = executable_resolver(name)
    except Exception as exc:  # noqa: BLE001 - convert resolver errors at boundary
        raise CameraStartError(
            "unable to resolve {0}: {1}".format(name, repr(exc))) from exc
    if not resolved:
        raise CameraStartError("required executable not found: {0}".format(name))
    return str(resolved)


def _parse_frame_rate(value):
    try:
        if isinstance(value, (int, float)):
            result = float(value)
        else:
            result = float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return result if math.isfinite(result) else None


class FfmpegCameraRecorder(object):
    """Injectable DirectShow ffmpeg lifecycle with bounded shutdown."""

    def __init__(self, evidence_dir, popen_factory=None,
                 ffprobe_runner=None,
                 executable_resolver=None, sleep_fn=None,
                 ffmpeg_path=None, ffprobe_path=None):
        self.evidence_dir = Path(evidence_dir)
        self.popen_factory = popen_factory or subprocess.Popen
        self.ffprobe_runner = ffprobe_runner or subprocess.run
        self.executable_resolver = executable_resolver or shutil.which
        self.sleep_fn = sleep_fn or time.sleep
        self.ffmpeg_path = str(ffmpeg_path) if ffmpeg_path else None
        self.ffprobe_path = str(ffprobe_path) if ffprobe_path else None
        self.video_path = self.evidence_dir / "camera.mkv"
        self.log_path = self.evidence_dir / "camera_ffmpeg.log"
        self.command = None
        self.ffprobe_command = None
        self.process = None
        self.log_handle = None
        self._log_closed = False
        self._stopped = False
        self._stop_report = None
        self._validation_report = None
        self._start_report = None

    def _close_log(self):
        if self._log_closed:
            return None
        self._log_closed = True
        if self.log_handle is None:
            return None
        try:
            self.log_handle.close()
            return None
        except BaseException as exc:  # noqa: BLE001 - report cleanup failure
            return repr(exc)

    def _build_command(self):
        return [
            self.ffmpeg_path,
            "-hide_banner", "-loglevel", "info",
            "-f", "dshow", "-rtbufsize", "256M",
            "-video_size", "{0}x{1}".format(CAMERA_WIDTH, CAMERA_HEIGHT),
            "-framerate", "30",
            "-vcodec", "mjpeg",
            "-i", "video={0}".format(CAMERA_DEVICE_NAME),
            "-an", "-c:v", "copy", str(self.video_path),
        ]

    def start(self):
        if self.process is not None and not self._stopped:
            raise CameraStartError("camera recorder already started")
        if not self.evidence_dir.is_dir():
            raise CameraStartError(
                "evidence directory does not exist: {0}".format(self.evidence_dir))
        if not os.access(str(self.evidence_dir), os.W_OK):
            raise CameraStartError(
                "evidence directory is not writable: {0}".format(self.evidence_dir))
        if self.ffmpeg_path is None:
            self.ffmpeg_path = _resolve_executable(
                self.executable_resolver, "ffmpeg")
        if self.ffprobe_path is None:
            self.ffprobe_path = _resolve_executable(
                self.executable_resolver, "ffprobe")
        self.command = self._build_command()
        try:
            self.log_handle = open(self.log_path, "w", encoding="utf-8",
                                   newline="\n")
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.process = self.popen_factory(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self.log_handle,
                creationflags=creationflags,
            )
        except BaseException as exc:  # noqa: BLE001 - startup gate boundary
            cleanup_error = self._close_log()
            detail = "ffmpeg start failed: {0}".format(repr(exc))
            if cleanup_error:
                detail += "; log close failed: {0}".format(cleanup_error)
            if isinstance(exc, Exception):
                raise CameraStartError(detail) from exc
            raise
        try:
            self.sleep_fn(1.0)
            return_code = self.process.poll()
        except BaseException as exc:  # noqa: BLE001 - startup gate boundary
            cleanup_error = None
            try:
                cleanup = self.stop()
                if cleanup.get("cleanup_errors"):
                    cleanup_error = "; ".join(cleanup["cleanup_errors"])
            except BaseException as cleanup_exc:  # noqa: BLE001 - preserve startup cause
                cleanup_error = repr(cleanup_exc)
            detail = "ffmpeg startup probe failed: {0}".format(repr(exc))
            if cleanup_error:
                detail += "; cleanup failed: {0}".format(cleanup_error)
            if isinstance(exc, Exception):
                raise CameraStartError(detail) from exc
            raise
        if return_code is not None:
            cleanup_error = self._close_log()
            detail = "ffmpeg exited during startup with code {0}".format(
                return_code)
            if cleanup_error:
                detail += "; log close failed: {0}".format(cleanup_error)
            raise CameraStartError(detail)
        self._start_report = {
            "started": True,
            "startup_gate": "RUNNING_AFTER_1S",
            "command": list(self.command),
            "device": CAMERA_DEVICE_NAME,
            "mode": "dshow",
        }
        return dict(self._start_report)

    def stop(self):
        if self._stop_report is not None:
            return self._stop_report
        report = {
            "attempted": self.process is not None,
            "q_sent": False,
            "stdin_error": None,
            "wait_actions": [],
            "exit_code": None,
            "forced_termination": False,
            "clean_exit": False,
            "cleanup_errors": [],
        }
        process = self.process
        if process is not None:
            stdin = getattr(process, "stdin", None)
            if stdin is not None:
                try:
                    stdin.write(b"q")
                    stdin.flush()
                    report["q_sent"] = True
                except BaseException as exc:  # noqa: BLE001 - bounded cleanup
                    report["stdin_error"] = repr(exc)
                try:
                    stdin.close()
                except BaseException as exc:  # noqa: BLE001 - bounded cleanup
                    report["cleanup_errors"].append("stdin close: {0}".format(
                        repr(exc)))
            try:
                report["wait_actions"].append("wait:5s")
                report["exit_code"] = process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._force_shutdown(process, report)
            except BaseException as exc:  # noqa: BLE001 - bounded cleanup
                report["forced_termination"] = True
                report["cleanup_errors"].append("wait: {0}".format(repr(exc)))
                self._force_shutdown(process, report)
            try:
                if report["exit_code"] is None:
                    report["exit_code"] = process.poll()
            except BaseException as exc:  # noqa: BLE001
                report["cleanup_errors"].append("poll: {0}".format(repr(exc)))
        log_error = self._close_log()
        if log_error:
            report["cleanup_errors"].append("log close: {0}".format(log_error))
        report["clean_exit"] = (
            report["exit_code"] == 0
            and not report["forced_termination"]
            and not report["stdin_error"]
            and not report["cleanup_errors"]
        )
        self._stopped = True
        self._stop_report = report
        return report

    @staticmethod
    def _force_shutdown(process, report):
        """Bound every terminate/kill transition, including wait errors."""
        report["forced_termination"] = True
        try:
            process.terminate()
            report["wait_actions"].append("terminate")
        except BaseException as exc:  # noqa: BLE001 - bounded cleanup
            report["cleanup_errors"].append("terminate: {0}".format(
                repr(exc)))
        try:
            report["wait_actions"].append("wait_after_terminate:1s")
            report["exit_code"] = process.wait(timeout=1.0)
            return
        except subprocess.TimeoutExpired:
            pass
        except BaseException as exc:  # noqa: BLE001 - continue to kill
            report["cleanup_errors"].append(
                "wait after terminate: {0}".format(repr(exc)))
        try:
            process.kill()
            report["wait_actions"].append("kill")
        except BaseException as exc:  # noqa: BLE001 - bounded cleanup
            report["cleanup_errors"].append("kill: {0}".format(repr(exc)))
        try:
            report["wait_actions"].append("wait_after_kill:1s")
            report["exit_code"] = process.wait(timeout=1.0)
        except BaseException as exc:  # noqa: BLE001 - final bounded cleanup
            report["cleanup_errors"].append(
                "wait after kill: {0}".format(repr(exc)))

    def validate(self):
        """Run ffprobe once and validate the required MJPEG video contract."""
        if self._validation_report is not None:
            return self._validation_report
        if self._stop_report is None:
            self.stop()
        errors = []
        stop_report = self._stop_report or {}
        try:
            ffmpeg_log_text = self.log_path.read_text(encoding="utf-8",
                                                      errors="replace")
        except OSError:
            ffmpeg_log_text = None
        input_codec_tag_evidence = _camera_input_codec_tag_evidence(
            ffmpeg_log_text)
        if not stop_report.get("clean_exit"):
            errors.append("ffmpeg did not exit cleanly")
        if not self.video_path.is_file():
            errors.append("camera.mkv is missing")
        elif self.video_path.stat().st_size <= 0:
            errors.append("camera.mkv is empty")
        self.ffprobe_command = [
            self.ffprobe_path or "ffprobe",
            "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "stream=codec_name,codec_tag_string,codec_tag,width,height,avg_frame_rate",
            "-of", "json", str(self.video_path),
        ]
        probe_data = None
        probe_result = None
        try:
            probe_result = self.ffprobe_runner(
                self.ffprobe_command, capture_output=True, text=True,
                timeout=5.0, check=False)
            if getattr(probe_result, "returncode", None) != 0:
                errors.append("ffprobe exited with code {0}".format(
                    getattr(probe_result, "returncode", None)))
            else:
                stdout = getattr(probe_result, "stdout", "")
                probe_data = json.loads(stdout)
        except subprocess.TimeoutExpired as exc:
            errors.append("ffprobe timeout: {0}".format(repr(exc)))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append("ffprobe invalid JSON: {0}".format(repr(exc)))
        except Exception as exc:  # noqa: BLE001 - final validation boundary
            errors.append("ffprobe failed: {0}".format(repr(exc)))

        video = {}
        codec_tag_evidence = {
            "status": "INSUFFICIENT_EVIDENCE",
            "codec_tag_string": "UNKNOWN",
            "codec_tag": None,
            "error": "codec tag evidence unavailable",
        }
        if probe_data is not None:
            streams = probe_data.get("streams") if isinstance(probe_data, dict) else None
            if not isinstance(streams, list) or not streams:
                errors.append("ffprobe returned no video stream")
            else:
                stream = streams[0]
                if not isinstance(stream, dict):
                    errors.append("ffprobe video stream is not an object")
                    stream = {}
                if stream.get("codec_name") != "mjpeg":
                    errors.append("video codec is not mjpeg")
                if stream.get("width") != CAMERA_WIDTH:
                    errors.append("video width is not 1920")
                if stream.get("height") != CAMERA_HEIGHT:
                    errors.append("video height is not 1080")
                fps = _parse_frame_rate(stream.get("avg_frame_rate"))
                if fps is None or abs(fps - CAMERA_FPS) > CAMERA_FPS_TOLERANCE:
                    errors.append("video average frame rate is not 30 +/- 0.5 fps")
                codec_tag_evidence = _camera_codec_tag_evidence(stream)
                output_tag_status = codec_tag_evidence.get("status")
                if output_tag_status == "CONTAINER_UNSPECIFIED":
                    if input_codec_tag_evidence.get("status") != "PASS":
                        errors.append(
                            "DirectShow input codec tag validation failed: {0}"
                            .format(input_codec_tag_evidence.get("error")))
                elif output_tag_status != "PASS":
                    errors.append("video codec tag validation failed: {0}".format(
                        codec_tag_evidence.get("error")))
                codec_tag_string = stream.get("codec_tag_string")
                video = {
                    "codec_name": stream.get("codec_name"),
                    "codec_tag_string": (codec_tag_string
                                          if codec_tag_string else "UNKNOWN"),
                    "codec_tag": stream.get("codec_tag"),
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "avg_frame_rate": stream.get("avg_frame_rate"),
                    "fps": fps,
                }
        verdict = "PASS" if not errors else "FAIL"
        self._validation_report = {
            "verdict": verdict,
            "camera_verdict": verdict,
            "mode": "dshow",
            "device": CAMERA_DEVICE_NAME,
            "video_path": "camera.mkv",
            "clean_exit": bool(stop_report.get("clean_exit")),
            "forced_termination": bool(stop_report.get("forced_termination")),
            "stop": stop_report,
            "ffmpeg_command": list(self.command or []),
            "ffprobe_command": list(self.ffprobe_command),
            "ffprobe": probe_data,
            "ffprobe_returncode": getattr(probe_result, "returncode", None),
            "video": video,
            "codec_tag_evidence": codec_tag_evidence,
            "input_codec_tag_evidence": input_codec_tag_evidence,
            "errors": errors,
        }
        return self._validation_report


def _relative_artifact_map(evidence_dir, control_report, include_report=False):
    evidence_path = Path(evidence_dir)
    evidence_root = evidence_path.resolve()
    raw_value = None
    if isinstance(control_report, dict):
        raw_value = control_report.get("raw_io_path")
        raw = control_report.get("raw_io")
        if isinstance(raw, dict):
            raw_value = raw.get("path", raw_value)
    raw_inside_evidence = True
    if raw_value:
        raw_path = Path(raw_value)
        if not raw_path.is_absolute():
            raw_path = evidence_path / raw_path
        try:
            raw_inside_evidence = (
                raw_path.resolve().relative_to(evidence_root) is not None)
        except (OSError, ValueError):
            raw_inside_evidence = False
    else:
        raw_path = evidence_path / "raw_io.json"
    values = {
        "camera.mkv": evidence_path / "camera.mkv",
        "camera_ffmpeg.log": evidence_path / "camera_ffmpeg.log",
        "raw_io.json": raw_path,
        "shakedown_report.json": (
            True if include_report else evidence_path / "shakedown_report.json"),
    }
    return {
        name: {"path": str(value), "present": (
            _artifact_present(value)
            and (name != "raw_io.json" or raw_inside_evidence))}
        if name != "shakedown_report.json" or not isinstance(value, bool)
        else {"path": name, "present": value}
        for name, value in values.items()
    }


def _artifact_paths(evidence_dir, artifact_map):
    evidence_path = Path(evidence_dir)
    result = {}
    for name, value in artifact_map.items():
        if isinstance(value, dict) and value.get("present"):
            raw_path = value.get("path", name)
            try:
                result[name] = str(Path(raw_path).relative_to(evidence_path))
            except (ValueError, TypeError):
                result[name] = name
        else:
            result[name] = None
    return result


def _missing_artifacts(artifact_map):
    return [name for name in REQUIRED_ARTIFACTS
            if not _artifact_present(artifact_map.get(name))]


def _minimal_failure_report(evidence_dir, run_kind, reason, control=None,
                            camera=None, attempted_actions=(),
                            campaign_id=None, run_id=None,
                            requested_duration_s=None):
    artifact_map = _relative_artifact_map(evidence_dir, control, include_report=False)
    control_data = control if isinstance(control, dict) else {}
    imu_evidence = summarize_imu_evidence(control_data)
    report_campaign_id = (campaign_id if campaign_id is not None
                          else control_data.get("campaign_id", ""))
    report_run_id = (run_id if run_id is not None
                     else control_data.get("run_id", ""))
    report_duration = (requested_duration_s
                       if requested_duration_s is not None
                       else control_data.get("requested_duration_s"))
    return {
        "schema_version": 1,
        "run_kind": run_kind,
        "phase": "failure",
        "verdict": "SHAKEDOWN_FAIL",
        "campaign_id": report_campaign_id,
        "run_id": report_run_id,
        "requested_duration_s": report_duration,
        "imu_evidence_status": imu_evidence["status"],
        "imu_evidence": imu_evidence,
        "control": control,
        "camera": camera,
        "artifact_paths": _artifact_paths(evidence_dir, artifact_map),
        "missing_artifacts": _missing_artifacts(artifact_map),
        "errors": [reason],
        "attempted_actions": list(attempted_actions),
        "known_paths": {name: str(Path(evidence_dir) / name)
                        for name in REQUIRED_ARTIFACTS},
    }


def _publish_report_best_effort(evidence_dir, report, fallback=None):
    """Publish once and retain a structured in-memory failure on error."""
    try:
        publish_report_atomic(evidence_dir, report)
        return report, None
    except Exception as exc:  # noqa: BLE001 - publication is a report boundary
        target = fallback if fallback is not None else report
        errors = target.get("errors")
        if not isinstance(errors, list):
            errors = []
        errors.append("report publication failed: {0}".format(repr(exc)))
        target["errors"] = errors
        target["publication_error"] = repr(exc)
        target["report_published"] = False
        target["verdict"] = "SHAKEDOWN_FAIL"
        missing = target.get("missing_artifacts")
        if not isinstance(missing, list):
            missing = []
        if "shakedown_report.json" not in missing:
            missing.append("shakedown_report.json")
        target["missing_artifacts"] = missing
        return target, exc


def _attach_failure_report(exc, report):
    try:
        setattr(exc, "failure_report", report)
    except Exception:  # noqa: BLE001 - some BaseException implementations reject attrs
        pass


def orchestrate_shakedown(recorder, session_runner, evidence_dir, run_kind,
                          campaign_id=None, run_id=None,
                          requested_duration_s=None):
    """Own camera/report resources while invoking the session exactly once."""
    evidence_path = Path(evidence_dir)
    if not evidence_path.is_dir():
        raise FileNotFoundError("evidence directory does not exist: {0}".format(
            evidence_path))
    started = False
    control_report = None
    camera_report = None
    session_exception = None
    try:
        try:
            recorder.start()
            started = True
        except CameraStartError as exc:
            failure = _minimal_failure_report(
                evidence_path, run_kind, "camera startup failed: {0}".format(
                    repr(exc)), camera={"verdict": "FAIL", "startup_error": repr(exc)},
                attempted_actions=("camera_start",),
                campaign_id=campaign_id, run_id=run_id,
                requested_duration_s=requested_duration_s)
            failure, _ = _publish_report_best_effort(evidence_path, failure)
            if failure.get("publication_error"):
                _attach_failure_report(exc, failure)
            raise
        except BaseException as exc:  # noqa: BLE001 - publish before re-raise
            failure = _minimal_failure_report(
                evidence_path, run_kind,
                "unexpected camera startup failure: {0}".format(repr(exc)),
                camera={"verdict": "FAIL", "startup_error": repr(exc)},
                attempted_actions=("camera_start",),
                campaign_id=campaign_id, run_id=run_id,
                requested_duration_s=requested_duration_s)
            failure, _ = _publish_report_best_effort(evidence_path, failure)
            _attach_failure_report(exc, failure)
            raise
        try:
            control_report = session_runner()
        except BaseException as exc:  # noqa: BLE001 - publish before re-raise
            session_exception = exc
            attached_report = getattr(exc, "failure_report", None)
            if control_report is None and isinstance(attached_report, dict):
                attached_control = attached_report.get("control")
                if isinstance(attached_control, dict):
                    control_report = attached_control
    finally:
        if started:
            try:
                recorder.stop()
            except BaseException as exc:  # noqa: BLE001 - cleanup evidence
                session_exception = session_exception or exc
            try:
                camera_report = recorder.validate()
            except BaseException as exc:  # noqa: BLE001 - cleanup evidence
                session_exception = session_exception or exc

    if session_exception is not None:
        failure = _minimal_failure_report(
            evidence_path, run_kind,
            "session/camera execution failed: {0}".format(repr(session_exception)),
            control=control_report, camera=camera_report,
            attempted_actions=("camera_start", "session", "camera_stop",
                                "camera_validate"),
            campaign_id=campaign_id, run_id=run_id,
            requested_duration_s=requested_duration_s)
        failure, _ = _publish_report_best_effort(evidence_path, failure)
        _attach_failure_report(session_exception, failure)
        raise session_exception

    if control_report is None:
        control_report = {"control_verdict": "FAIL",
                          "primary_failure": {"code": "NO_CONTROL_REPORT"}}
    control_copy = copy.deepcopy(control_report)
    errors = []
    try:
        normalize_telemetry_units(control_copy)
    except ValueError as exc:
        errors.append("telemetry unit normalization failed: {0}".format(repr(exc)))
    if isinstance(camera_report, dict):
        for key in ("startup_error", "finalization_error", "cleanup_errors", "errors"):
            value = camera_report.get(key)
            if isinstance(value, list):
                errors.extend("camera {0}: {1}".format(key, item)
                              for item in value)
            elif value:
                errors.append("camera {0}: {1}".format(key, value))
    artifact_map = _relative_artifact_map(evidence_path, control_copy,
                                          include_report=True)
    verdict = compute_shakedown_verdict(control_copy, camera_report, artifact_map)
    if errors:
        verdict = "SHAKEDOWN_FAIL"
    report_campaign_id = (campaign_id if campaign_id is not None
                          else control_copy.get("campaign_id", ""))
    report_run_id = (run_id if run_id is not None
                     else control_copy.get("run_id", ""))
    report_duration = (requested_duration_s
                       if requested_duration_s is not None
                       else control_copy.get("requested_duration_s"))
    imu_evidence = summarize_imu_evidence(control_copy)
    report = {
        "schema_version": 1,
        "run_kind": run_kind,
        "phase": "complete",
        "verdict": verdict,
        "campaign_id": report_campaign_id,
        "run_id": report_run_id,
        "requested_duration_s": report_duration,
        "imu_evidence_status": imu_evidence["status"],
        "imu_evidence": imu_evidence,
        "control": control_copy,
        "camera": camera_report,
        "speed_plan": list(SPEED_STEPS),
        "rollback_requested": bool(control_copy.get("rollback_requested", False)),
        "stop_confirmed": bool(control_copy.get("stop_confirmed", False)),
        "artifact_paths": _artifact_paths(evidence_path, artifact_map),
        "missing_artifacts": _missing_artifacts(artifact_map),
        "errors": errors,
    }
    publication_fallback = _minimal_failure_report(
        evidence_path, run_kind, "final report publication failed",
        attempted_actions=("camera_start", "session", "camera_stop",
                            "camera_validate", "report_publish"),
        campaign_id=report_campaign_id, run_id=report_run_id,
        requested_duration_s=report_duration)
    published_report, _ = _publish_report_best_effort(
        evidence_path, report, fallback=publication_fallback)
    return published_report


def _resolve_camera_executables(resolver=None):
    resolver = resolver or shutil.which
    return (_resolve_executable(resolver, "ffmpeg"),
            _resolve_executable(resolver, "ffprobe"))


def _dry_run_command(args):
    extended = " --allow-extended" if args.allow_extended else ""
    return (
        "py -3.11 tools/shakedown_toolchain/ground_shakedown.py "
        "--host {0} --port {1} --duration {2} --run-kind {3} "
        "--out-root {4}{5} --execute"
    ).format(args.host, args.port, args.duration, args.run_kind, args.out_root,
             extended)


def _build_cli_parser():
    parser = argparse.ArgumentParser(
        description="Fail-closed Robot Twin AI ground shakedown recorder")
    parser.add_argument("--host", default="192.168.110.236")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--out-root", default="simulation/digital_twin/logs")
    parser.add_argument("--run-kind", choices=("elevated-wheels", "ground"),
                        required=True)
    parser.add_argument("--allow-extended", action="store_true")
    parser.add_argument("--execute", action="store_true",
                        help="required before camera/TCP resources are opened")
    return parser


def main(argv=None):
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    try:
        duration = validate_duration(args.duration, args.allow_extended)
    except ValueError as exc:
        print("ERROR: {0}".format(exc))
        return 2
    now = _datetime.datetime.now()
    campaign_id = make_runtime_identifier("s", now=now)
    timestamp = campaign_id[1:]
    run_prefix = "e" if args.run_kind == "elevated-wheels" else "g"
    run_id = make_runtime_identifier(run_prefix, now=now)
    if not args.execute:
        print("DRY RUN: no camera, TCP socket, process, or evidence directory opened")
        print("campaign_id: {0}".format(campaign_id))
        print("run_id: {0}".format(run_id))
        print("future command: {0}".format(_dry_run_command(args)))
        return 0

    try:
        ffmpeg_path, ffprobe_path = _resolve_camera_executables()
    except CameraStartError as exc:
        print("ERROR: {0}".format(exc))
        return 2
    try:
        evidence_path = make_evidence_dir(args.out_root, timestamp)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print("ERROR: evidence directory: {0}".format(exc))
        return 2
    recorder = FfmpegCameraRecorder(
        evidence_path, ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)

    def session_runner():
        transport = soak.SocketTransport(args.host, args.port)
        result = _connect_and_run_ground_session(
            transport, campaign_id, run_id, duration,
            raw_logger_factory=lambda: soak.RawIoLogger(str(evidence_path)))
        result["campaign_id"] = campaign_id
        result["run_id"] = run_id
        result["requested_duration_s"] = duration
        return result

    try:
        report = orchestrate_shakedown(
            recorder, session_runner, evidence_path, args.run_kind,
            campaign_id=campaign_id, run_id=run_id,
            requested_duration_s=duration)
    except CameraStartError as exc:
        print("ERROR: camera startup: {0}".format(exc))
        return 1
    except BaseException as exc:  # noqa: BLE001 - report was published first
        print("ERROR: shakedown execution: {0}".format(exc))
        return 1
    print("VERDICT: {0}".format(report["verdict"]))
    print("evidence: {0}".format(evidence_path))
    if report["verdict"] == "SHAKEDOWN_PASS":
        return 0
    if report["verdict"] == "INSUFFICIENT_EVIDENCE":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
