# -*- coding: utf-8 -*-
"""Task 1 (Ground Shakedown Recorder): offline ACK-aware fail-closed control core.

RED-GREEN discipline.  These tests drive the production module
`tools/shakedown_toolchain/ground_shakedown.py` which must NOT
yet exist when the first two tests are run (they fail at import/collection).

Coverage:
  - `ControlAwareMixedStreamParser` forwards fragmented `A,` / `S,` lines and
    ignores newline / `A,` bytes inside a checksum-valid binary telemetry frame.
  - `run_ground_session` applies all five bounded speed steps (each gated by
    exactly one correlated `A,` ACK) BEFORE START, then confirms START/RUNNING,
    heartbeats during the running window, and issues a final correlated STOP.
  - Fail-closed behavior: a rejected/malformed/mismatched ACK never sends
    START, issues the correlated STOP as the last control command, records the
    exact failure reason, and the waiter returns immediately rather than
    consuming its full timeout.
  - Missing final STOPPED/STOP confirm sets `cut_power_warning`.
  - The running window sends MCU command heartbeats before final STOP.

Offline only: `FirmwareScriptTransport` is an in-process queue-based fake; no
network, camera, serial, debugger, Keil, flash, hardware, or motion occurs.
"""

from __future__ import annotations

import json
import math
import os
import queue
import sys
import subprocess
import threading
import time
from pathlib import Path

import pytest

# The production tool lives under tools/shakedown_toolchain/.
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "tools", "shakedown_toolchain"))

from real_world.runtime_protocol import frame  # noqa: E402

from ground_shakedown import (  # noqa: E402
    ACK_TIMEOUT_S,
    ControlAwareMixedStreamParser,
    CameraStartError,
    FfmpegCameraRecorder,
    _connect_and_run_ground_session,
    compute_shakedown_verdict,
    make_evidence_dir,
    normalize_telemetry_units,
    orchestrate_shakedown,
    publish_report_atomic,
    run_ground_session,
    _parse_frame_rate,
    _relative_artifact_map,
    validate_duration,
)

import ground_shakedown  # noqa: E402  (module handle for offline monkeypatch)



def binary_frame(frame_type, payload):
    checksum = frame_type ^ len(payload)
    for value in payload:
        checksum ^= value
    return bytes([0xAA, 0x55, frame_type, len(payload)]) + payload + bytes([checksum])


def test_control_parser_forwards_fragmented_ack_and_status_not_binary_noise():
    lines = []
    parser = ControlAwareMixedStreamParser(on_line=lines.append)
    binary_payload = bytes([0x0A, ord("A"), ord(",")]) + bytes(21)
    blob = (
        frame("A,shake,1,APPLIED,APPLIED").encode("ascii")
        + binary_frame(0x01, binary_payload)
        + frame("S,shake,gnd00000001,STOPPED,STOP,2").encode("ascii")
    )
    for chunk in (blob[:7], blob[7:19], blob[19:43], blob[43:]):
        for value in chunk:
            parser.feed(value)
    assert lines == [
        frame("A,shake,1,APPLIED,APPLIED"),
        frame("S,shake,gnd00000001,STOPPED,STOP,2"),
    ]


class FirmwareScriptTransport(object):
    # Single-owner contract (2026-08-05): every supported transport declares a
    # finite positive bounded-I/O timeout at or below 0.1 s.  Subclasses inherit
    # this declaration while preserving the 0.01-second queue timeout.
    io_timeout_s = 0.1

    def __init__(self, run_id, reject_speed=None, reject_reason="STEP_LIMIT",
                 drop_final_stop_status=False):
        self.run_id = run_id
        self.reject_speed = reject_speed
        self.reject_reason = reject_reason
        self.drop_final_stop_status = drop_final_stop_status
        self.control_bodies = []
        self._rx = queue.Queue()
        self._stop_count = 0
        self._closed = False
        self.close_count = 0
        self._tick = 0
        # Firmware emits exactly one authoritative connection-time status
        # before any command (F8).  It is an exact matching STOPPED/STOP so
        # the session must isolate it as `initial_status` and never reuse it
        # to confirm pre-STOP/START/final STOP.
        self._put_status("STOPPED", "STOP")

    def _put_status(self, state, reason):
        self._tick += 1
        self._rx.put(frame(
            "S,{0},{1},{2},{3},{4}".format(
                "shake", self.run_id, state, reason, self._tick * 10)
        ).encode("ascii"))

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        self.control_bodies.append(body)
        parts = body.split(",")
        if parts[0] == "P":
            speed = int(parts[6])
            outcome = "REJECTED" if speed == self.reject_speed else "APPLIED"
            reason = self.reject_reason if outcome == "REJECTED" else "APPLIED"
            self._rx.put(frame(
                "A,{0},{1},{2},{3}".format(parts[1], parts[2], outcome, reason)
            ).encode("ascii"))
        elif parts[0] == "R" and parts[3] == "START":
            self._put_status("RUNNING", "START")
        elif parts[0] == "R" and parts[3] == "STOP":
            self._stop_count += 1
            if not (self.drop_final_stop_status and self._stop_count > 1):
                self._put_status("STOPPED", "STOP")

    def recv(self, _max_bytes):
        if self._closed:
            return None
        try:
            return self._rx.get(timeout=0.01)
        except queue.Empty:
            return b""

    def close(self):
        self._closed = True
        self.close_count += 1


def test_ground_session_applies_all_speed_steps_before_start_and_stops():
    transport = FirmwareScriptTransport("gnd00000001")
    result = run_ground_session(
        transport, "shake", "gnd00000001", 0.05
    )
    assert transport.control_bodies[:7] == [
        "R,shake,gnd00000001,STOP",
        "P,shake,1,35,0,10,580",
        "P,shake,2,35,0,10,480",
        "P,shake,3,35,0,10,380",
        "P,shake,4,35,0,10,280",
        "P,shake,5,35,0,10,260",
        "R,shake,gnd00000001,START",
    ]
    assert transport.control_bodies[-1] == "R,shake,gnd00000001,STOP"
    assert result["speed_override"]["applied_speeds"] == [580, 480, 380, 280, 260]
    assert result["start"]["confirmed"] is True
    assert result["stop"]["confirmed"] is True
    assert result["control_verdict"] == "PASS"
    socket_report = result["socket"]
    assert socket_report["connect"]["state"] == "NOT_EXECUTED"
    assert socket_report["close"]["state"] == "COMPLETED"
    assert socket_report["close"]["call_count"] == 1
    assert socket_report["close"]["completed_monotonic_s"] is not None
    assert socket_report["close"]["failed_monotonic_s"] is None


def _corrupt_checksum(line):
    """Return `line` with the last checksum hex digit flipped so the frame is
    checksum-invalid (XOR verification in parse_ack must fail)."""
    assert line.endswith("\n") and len(line.rstrip("\n")) >= 3
    body = line[:-1]
    digit = body[-2]
    new_digit = "0" if digit != "0" else "1"
    return body[:-2] + new_digit + body[-1] + "\n"


class CorruptFirstAckTransport(FirmwareScriptTransport):
    """Same deterministic script as FirmwareScriptTransport, but the FIRST
    parameter command receives a checksum-invalid `A,` line."""

    def __init__(self, run_id, reject_speed=None, reject_reason="STEP_LIMIT",
                 drop_final_stop_status=False):
        super().__init__(run_id, reject_speed, reject_reason,
                         drop_final_stop_status)
        self._p_count = 0

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        self.control_bodies.append(body)
        parts = body.split(",")
        if parts[0] == "P":
            self._p_count += 1
            reply = frame(
                "A,{0},{1},APPLIED,APPLIED".format(parts[1], parts[2]))
            if self._p_count == 1:
                reply = _corrupt_checksum(reply)
            self._rx.put(reply.encode("ascii"))
        elif parts[0] == "R" and parts[3] == "START":
            self._rx.put(frame(
                "S,{0},{1},RUNNING,START,1".format(parts[1], parts[2])
            ).encode("ascii"))
        elif parts[0] == "R" and parts[3] == "STOP":
            self._stop_count += 1
            if not (self.drop_final_stop_status and self._stop_count > 1):
                self._rx.put(frame(
                    "S,{0},{1},STOPPED,STOP,2".format(parts[1], parts[2])
                ).encode("ascii"))


def test_corrupt_first_ack_never_sends_start_and_stops_immediately():
    transport = CorruptFirstAckTransport("gnd00000001")
    started = time.monotonic()
    result = run_ground_session(transport, "shake", "gnd00000001", 0.05)
    elapsed = time.monotonic() - started
    # START is never sent; the correlated STOP is the last control command.
    assert not any(",START" in body for body in transport.control_bodies)
    assert transport.control_bodies[-1] == "R,shake,gnd00000001,STOP"
    # The parse error is recorded as evidence.
    assert any("A," in entry["line"] for entry in result["parse_errors"])
    assert result["speed_override"]["failure_reason"].startswith("PARSE_ERROR")
    # The waiter must return immediately, not consume its full ACK timeout.
    assert elapsed < ACK_TIMEOUT_S
    assert result["start"]["cmd_sent"] is False
    assert result["control_verdict"] == "FAIL"


class VersionMismatchFirstAckTransport(FirmwareScriptTransport):
    """Same deterministic script, but the FIRST parameter command receives an
    APPLIED ACK for a DIFFERENT version (campaign/version identity mismatch)."""

    def __init__(self, run_id, reject_speed=None, reject_reason="STEP_LIMIT",
                 drop_final_stop_status=False):
        super().__init__(run_id, reject_speed, reject_reason,
                         drop_final_stop_status)
        self._p_count = 0

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        self.control_bodies.append(body)
        parts = body.split(",")
        if parts[0] == "P":
            self._p_count += 1
            version = parts[2]
            reply_version = str(int(version) + 1) if self._p_count == 1 else version
            self._rx.put(frame(
                "A,{0},{1},APPLIED,APPLIED".format(parts[1], reply_version)
            ).encode("ascii"))
        elif parts[0] == "R" and parts[3] == "START":
            self._rx.put(frame(
                "S,{0},{1},RUNNING,START,1".format(parts[1], parts[2])
            ).encode("ascii"))
        elif parts[0] == "R" and parts[3] == "STOP":
            self._stop_count += 1
            if not (self.drop_final_stop_status and self._stop_count > 1):
                self._rx.put(frame(
                    "S,{0},{1},STOPPED,STOP,2".format(parts[1], parts[2])
                ).encode("ascii"))


def test_version_mismatch_first_ack_fails_closed():
    transport = VersionMismatchFirstAckTransport("gnd00000005")
    result = run_ground_session(transport, "shake", "gnd00000005", 0.05)
    assert not any(",START" in body for body in transport.control_bodies)
    assert transport.control_bodies[-1] == "R,shake,gnd00000005,STOP"
    assert result["speed_override"]["failure_reason"] == "MISMATCH"
    assert result["start"]["cmd_sent"] is False
    assert result["control_verdict"] == "FAIL"


def test_rejected_speed_step_never_sends_start_and_attempts_stop():
    transport = FirmwareScriptTransport("gnd00000002",
                                        reject_speed=380, reject_reason="STEP_LIMIT")
    result = run_ground_session(
        transport, "shake", "gnd00000002", 0.05
    )
    assert not any(",START" in body for body in transport.control_bodies)
    assert transport.control_bodies[-1] == "R,shake,gnd00000002,STOP"
    assert result["speed_override"]["failure_reason"] == "STEP_LIMIT"
    assert result["control_verdict"] == "FAIL"


def test_missing_final_stopped_sets_cut_power_warning():
    transport = FirmwareScriptTransport("gnd00000003", drop_final_stop_status=True)
    result = run_ground_session(transport, "shake", "gnd00000003", 0.05)
    assert result["stop"]["confirmed"] is False
    assert result["cut_power_warning"] is True
    assert result["control_verdict"] == "FAIL"


def test_running_window_sends_heartbeat_before_final_stop():
    transport = FirmwareScriptTransport("gnd00000004")
    run_ground_session(transport, "shake", "gnd00000004", 0.45)
    heartbeat_indexes = [i for i, body in enumerate(transport.control_bodies) if body.startswith("H,")]
    final_stop_index = len(transport.control_bodies) - 1
    assert len(heartbeat_indexes) >= 2
    assert max(heartbeat_indexes) < final_stop_index


class _FakeMonotonic(object):
    def __init__(self):
        self.value = 100.0

    def monotonic(self):
        return self.value

    def monotonic_ns(self):
        return int(self.value * 1e9)


class ConnectTrackingTransport(object):
    def __init__(self, fail_connect=False):
        self.fail_connect = fail_connect
        self.connect_calls = 0
        self.close_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self.fail_connect:
            raise OSError("connect exploded")

    def close(self):
        self.close_calls += 1


class CloseFailTrackingTransport(ConnectTrackingTransport):
    def __init__(self, fail_connect=False, fail_close=False, close_exception=None):
        super().__init__(fail_connect=fail_connect)
        self.fail_close = fail_close
        self.close_exception = close_exception

    def close(self):
        self.close_calls += 1
        if self.close_exception is not None:
            raise self.close_exception
        if self.fail_close:
            raise OSError("close exploded")


def test_connect_wrapper_records_completed_and_failed_connect_states():
    success_transport = ConnectTrackingTransport()
    success_result = _connect_and_run_ground_session(
        success_transport,
        "shake",
        "gnd00000999",
        0.05,
        session_runner=lambda transport, campaign_id, run_id, duration_s, raw_logger: {
            "control_verdict": "PASS",
            "raw_io": {"published": True},
            "telemetry": {"frames": [{}]},
        },
        raw_logger_factory=lambda: object(),
    )
    assert success_transport.connect_calls == 1
    assert success_result["socket"]["connect"]["state"] == "COMPLETED"
    assert success_result["socket"]["connect"]["call_count"] == 1
    assert success_result["socket"]["connect"]["completed_monotonic_s"] is not None
    assert success_result["socket"]["connect"]["failed_monotonic_s"] is None

    failed_transport = ConnectTrackingTransport(fail_connect=True)
    failed_result = _connect_and_run_ground_session(
        failed_transport,
        "shake",
        "gnd00001000",
        0.05,
        session_runner=lambda *args, **kwargs: pytest.fail("session_runner should not run"),
        raw_logger_factory=lambda: object(),
    )
    assert failed_transport.connect_calls == 1
    assert failed_transport.close_calls == 1
    assert failed_result["control_verdict"] == "FAIL"
    assert failed_result["socket"]["connect"]["state"] == "FAILED"
    assert failed_result["socket"]["connect"]["failed_monotonic_s"] is not None
    assert failed_result["socket"]["connect"]["error"]
    assert failed_result["socket"]["close"]["state"] == "COMPLETED"


def test_connect_wrapper_closes_once_when_raw_logger_factory_or_session_runner_fail():
    transport = ConnectTrackingTransport()
    with pytest.raises(RuntimeError, match="logger exploded"):
        _connect_and_run_ground_session(
            transport,
            "shake",
            "gnd00001001",
            0.05,
            raw_logger_factory=lambda: (_ for _ in ()).throw(RuntimeError("logger exploded")),
        )
    assert transport.connect_calls == 1
    assert transport.close_calls == 1

    transport = ConnectTrackingTransport()
    with pytest.raises(RuntimeError, match="session exploded"):
        _connect_and_run_ground_session(
            transport,
            "shake",
            "gnd00001002",
            0.05,
            session_runner=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("session exploded")),
            raw_logger_factory=lambda: object(),
        )
    assert transport.connect_calls == 1
    assert transport.close_calls == 1


def test_connect_wrapper_does_not_double_close_canonical_session_and_reports_close_failure():
    transport = ConnectTrackingTransport()
    result = _connect_and_run_ground_session(
        transport,
        "shake",
        "gnd00001003",
        0.05,
        session_runner=lambda transport, campaign_id, run_id, duration_s, raw_logger: {
            "control_verdict": "PASS",
            "raw_io": {"published": True},
            "telemetry": {"frames": [{}]},
            "socket": {
                "connect": {"state": "NOT_EXECUTED"},
                "close": {
                    "state": "COMPLETED",
                    "call_count": 1,
                    "started_monotonic_s": 1.0,
                    "completed_monotonic_s": 1.1,
                    "failed_monotonic_s": None,
                    "elapsed_s": 0.1,
                    "error": None,
                },
            },
        },
        raw_logger_factory=lambda: object(),
    )
    assert result["socket"]["connect"]["state"] == "COMPLETED"
    assert transport.close_calls == 0

    failing_transport = CloseFailTrackingTransport(fail_close=True)
    with pytest.raises(RuntimeError, match="logger exploded"):
        _connect_and_run_ground_session(
            failing_transport,
            "shake",
            "gnd00001004",
            0.05,
            raw_logger_factory=lambda: (_ for _ in ()).throw(RuntimeError("logger exploded")),
        )
    assert failing_transport.connect_calls == 1
    assert failing_transport.close_calls == 1


def test_connect_wrapper_does_not_retry_canonical_failed_close_attempt():
    transport = ConnectTrackingTransport()
    result = _connect_and_run_ground_session(
        transport,
        "shake",
        "gnd00001005",
        0.05,
        session_runner=lambda transport, campaign_id, run_id, duration_s, raw_logger: {
            "control_verdict": "FAIL",
            "raw_io": {"published": False, "write_error": "not published"},
            "telemetry": {"frames": []},
            "socket": {
                "connect": {"state": "NOT_EXECUTED"},
                "close": {
                    "state": "FAILED",
                    "call_count": 1,
                    "started_monotonic_s": 1.0,
                    "completed_monotonic_s": None,
                    "failed_monotonic_s": 1.1,
                    "elapsed_s": 0.1,
                    "error": "canonical close failed",
                },
            },
        },
        raw_logger_factory=lambda: object(),
    )
    assert transport.close_calls == 0
    assert result["socket"]["close"]["state"] == "FAILED"
    assert result["socket"]["close"]["call_count"] == 1
    assert result["socket"]["close"]["error"] == "canonical close failed"


def test_connect_wrapper_keyboard_interrupt_still_closes_and_preserves_original_exception():
    transport = CloseFailTrackingTransport(fail_close=True)
    with pytest.raises(KeyboardInterrupt, match="ctrl-c"):
        _connect_and_run_ground_session(
            transport,
            "shake",
            "gnd00001006",
            0.05,
            raw_logger_factory=lambda: (_ for _ in ()).throw(
                KeyboardInterrupt("ctrl-c")),
        )
    assert transport.connect_calls == 1
    assert transport.close_calls == 1


def test_connect_wrapper_non_dict_session_result_closes_and_attaches_failure_report():
    transport = ConnectTrackingTransport()
    with pytest.raises(TypeError, match="session_runner must return dict") as exc_info:
        _connect_and_run_ground_session(
            transport,
            "shake",
            "gnd00001008",
            0.05,
            session_runner=lambda *args, **kwargs: ["not", "a", "dict"],
            raw_logger_factory=lambda: object(),
        )
    assert transport.connect_calls == 1
    assert transport.close_calls == 1
    failure_report = exc_info.value.failure_report
    socket_report = failure_report["control"]["socket"]
    assert socket_report["connect"]["state"] == "COMPLETED"
    assert socket_report["close"]["state"] == "COMPLETED"
    assert socket_report["close"]["call_count"] == 1


def test_connect_wrapper_close_keyboard_interrupt_does_not_override_original_exception():
    transport = CloseFailTrackingTransport(
        close_exception=KeyboardInterrupt("close ctrl-c"))
    with pytest.raises(RuntimeError, match="logger exploded") as exc_info:
        _connect_and_run_ground_session(
            transport,
            "shake",
            "gnd00001009",
            0.05,
            raw_logger_factory=lambda: (_ for _ in ()).throw(
                RuntimeError("logger exploded")),
        )
    assert transport.connect_calls == 1
    assert transport.close_calls == 1
    failure_report = exc_info.value.failure_report
    socket_report = failure_report["control"]["socket"]
    assert socket_report["close"]["state"] == "FAILED"
    assert socket_report["close"]["call_count"] == 1
    assert "close ctrl-c" in socket_report["close"]["error"]


def test_orchestrate_failure_report_keeps_socket_lifecycle_from_wrapper_exception(
        tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    transport = CloseFailTrackingTransport(fail_close=True)

    def failing_session():
        return _connect_and_run_ground_session(
            transport,
            "shake",
            "gnd00001007",
            0.05,
            raw_logger_factory=lambda: (_ for _ in ()).throw(
                RuntimeError("logger exploded")),
        )

    with pytest.raises(RuntimeError, match="logger exploded"):
        orchestrate_shakedown(recorder, failing_session, evidence, "ground")
    report = json.loads((evidence / "shakedown_report.json").read_text(
        encoding="utf-8"))
    socket_report = report["control"]["socket"]
    assert socket_report["connect"]["state"] == "COMPLETED"
    assert socket_report["close"]["state"] == "FAILED"
    assert socket_report["close"]["call_count"] == 1
    assert socket_report["close"]["error"]


def test_orchestrate_failure_report_keeps_socket_lifecycle_for_non_dict_session_result(
        tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    transport = ConnectTrackingTransport()

    def failing_session():
        return _connect_and_run_ground_session(
            transport,
            "shake",
            "gnd00001010",
            0.05,
            session_runner=lambda *args, **kwargs: "not-a-dict",
            raw_logger_factory=lambda: object(),
        )

    with pytest.raises(TypeError, match="session_runner must return dict"):
        orchestrate_shakedown(recorder, failing_session, evidence, "ground")
    report = json.loads((evidence / "shakedown_report.json").read_text(
        encoding="utf-8"))
    socket_report = report["control"]["socket"]
    assert socket_report["connect"]["state"] == "COMPLETED"
    assert socket_report["close"]["state"] == "COMPLETED"
    assert socket_report["close"]["call_count"] == 1


class ContinuousRxUntilStopTransport(FirmwareScriptTransport):
    """Keeps RX non-empty after the running deadline until 0.3 s."""

    def __init__(self, run_id, clock):
        super().__init__(run_id)
        self.clock = clock
        self.start_time = None
        self.stop_time = None

    def send(self, data):
        text = data.decode("ascii")
        body = ",".join(text.rstrip("\n").split(",")[:-1])
        super().send(data)
        if body.endswith(",START"):
            self.start_time = self.clock.value
        elif body.endswith(",STOP") and self.start_time is not None:
            self.stop_time = self.clock.value

    def recv(self, _max_bytes):
        if self._closed:
            return None
        try:
            return self._rx.get_nowait()
        except queue.Empty:
            if (self.start_time is not None and self.stop_time is None
                    and self.clock.value < self.start_time + 0.3):
                self.clock.value += 0.02
                return b"\x00"
            return b""


class DelayedStartConfirmationTransport(FirmwareScriptTransport):
    def __init__(self, run_id):
        super().__init__(run_id)
        self.start_time = None
        self.stop_time = None
        self.pending_start = False

    def send(self, data):
        text = data.decode("ascii")
        body = ",".join(text.rstrip("\n").split(",")[:-1])
        if body.endswith(",START"):
            self.control_bodies.append(body)
            self.start_time = time.monotonic()
            self.pending_start = True
            return
        super().send(data)
        if body.endswith(",STOP") and self.start_time is not None:
            self.stop_time = time.monotonic()

    def recv(self, max_bytes):
        if self.pending_start:
            if time.monotonic() - self.start_time < 0.2:
                time.sleep(0.05)
                return b""
            if self.pending_start:
                self._put_status("RUNNING", "START")
                self.pending_start = False
        return super().recv(max_bytes)


class SlowFinalStopTransport(FirmwareScriptTransport):
    def __init__(self, run_id):
        super().__init__(run_id)
        self.start_time = None
        self.stop_time = None

    def send(self, data):
        text = data.decode("ascii")
        body = ",".join(text.rstrip("\n").split(",")[:-1])
        if body.endswith(",START"):
            self.start_time = time.monotonic()
        is_final_stop = body.endswith(",STOP") and self.start_time is not None
        if is_final_stop:
            time.sleep(0.1)
        super().send(data)
        if is_final_stop:
            self.stop_time = time.monotonic()


def test_terminal_stop_is_sent_at_running_deadline_without_input_drain(monkeypatch):
    clock = _FakeMonotonic()
    monkeypatch.setattr(ground_shakedown.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ground_shakedown.time, "monotonic_ns", clock.monotonic_ns)
    transport = ContinuousRxUntilStopTransport("gnd00000006", clock)

    result = run_ground_session(transport, "shake", "gnd00000006", 0.1)

    assert result["control_verdict"] == "PASS"
    assert transport.stop_time is not None
    assert transport.stop_time - transport.start_time <= 0.12


def test_running_deadline_includes_start_command_latency(monkeypatch):
    del monkeypatch
    transport = DelayedStartConfirmationTransport("gnd00000007")

    result = run_ground_session(transport, "shake", "gnd00000007", 0.3)

    assert result["control_verdict"] == "PASS"
    assert transport.stop_time is not None
    assert transport.stop_time - transport.start_time <= 0.32


def test_terminal_stop_reserves_transport_send_budget():
    transport = SlowFinalStopTransport("gnd00000008")

    result = run_ground_session(transport, "shake", "gnd00000008", 0.3)

    assert result["control_verdict"] == "PASS"
    assert transport.stop_time is not None
    assert transport.stop_time - transport.start_time <= 0.31


# ── Fix Round 1 regression suite (2026-08-05) ──────────────────────────────
# Each test independently breaks one of F1-F7.  These ran RED against the
# pre-fix module and GREEN after Fix Round 1.

class PSendErrorTransport(FirmwareScriptTransport):
    """Raises OSError when the given parameter version is sent (F1)."""

    def __init__(self, run_id, fail_version=2):
        super().__init__(run_id)
        self.fail_version = fail_version

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        parts = body.split(",")
        if parts[0] == "P" and int(parts[2]) == self.fail_version:
            raise OSError("injected P{0} send failure".format(self.fail_version))
        super().send(data)


class StartSendErrorTransport(FirmwareScriptTransport):
    """Raises OSError when START is sent (may have partially transmitted)."""

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        parts = body.split(",")
        if parts[0] == "R" and parts[3] == "START":
            raise OSError("injected START send failure")
        super().send(data)


class HeartbeatErrorTransport(FirmwareScriptTransport):
    """Raises OSError on every H heartbeat send (F7)."""

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        parts = body.split(",")
        if parts[0] == "H":
            raise OSError("injected heartbeat send failure")
        super().send(data)


class StaleAckFirstTransport(FirmwareScriptTransport):
    """Pre-queues a MATCHING APPLIED ACK for P1 before any command, then gives
    P1 NO ACK.  The stale pre-queued ACK must not authorize P1/START (F6)."""

    def __init__(self, run_id):
        super().__init__(run_id)
        self._rx.put(frame("A,shake,1,APPLIED,APPLIED").encode("ascii"))

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        self.control_bodies.append(body)
        parts = body.split(",")
        if parts[0] == "P":
            if int(parts[2]) != 1:
                self._rx.put(frame(
                    "A,{0},{1},APPLIED,APPLIED".format(parts[1], parts[2])
                ).encode("ascii"))
            return
        super().send(data)


class StaleStopConfirmTransport(FirmwareScriptTransport):
    """First STOP gets TWO STOPPED/STOP confirms (one stays stale for the
    final STOP); the final STOP receives NO response (F6 status boundary)."""

    def __init__(self, run_id):
        super().__init__(run_id)
        self._stop_count = 0

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        self.control_bodies.append(body)
        parts = body.split(",")
        if parts[0] == "R" and parts[3] == "STOP":
            self._stop_count += 1
            if self._stop_count == 1:
                reply = frame("S,{0},{1},STOPPED,STOP,2".format(parts[1], parts[2]))
                self._rx.put(reply.encode("ascii"))
                self._rx.put(reply.encode("ascii"))
        elif parts[0] == "R" and parts[3] == "START":
            self._rx.put(frame(
                "S,{0},{1},RUNNING,START,1".format(parts[1], parts[2])
            ).encode("ascii"))
        elif parts[0] == "P":
            self._rx.put(frame(
                "A,{0},{1},APPLIED,APPLIED".format(parts[1], parts[2])
            ).encode("ascii"))


class FailingRawLogger(object):
    """A raw-logger whose write() raises (F5): must not prevent reader/heartbeat
    cleanup or the single transport close."""

    def __init__(self):
        self.writes = 0

    def log_send(self, data):
        pass

    def log_recv(self, data, note=None):
        pass

    def events(self):
        return []

    def write(self):
        self.writes += 1
        raise OSError("injected raw write failure")


def test_psend_exception_before_start_issues_exit_stop_once():
    # F1: exception during a P send must still attempt the correlated exit STOP
    # exactly once, even though START was never sent.
    transport = PSendErrorTransport("gnd00000010", fail_version=2)
    result = run_ground_session(transport, "shake", "gnd00000010", 0.05)
    assert not any(",START" in b for b in transport.control_bodies)
    assert transport.control_bodies[-1] == "R,shake,gnd00000010,STOP"
    assert result["control_verdict"] == "FAIL"
    assert result["stop"]["attempted"] is True
    assert "OSError" in result["unexpected_exception"]
    assert transport.close_count == 1


def test_start_send_exception_still_attempts_exit_stop():
    # F1: a START send that may have partially transmitted must not leave the
    # session without a correlated exit STOP, and PASS must be impossible.
    transport = StartSendErrorTransport("gnd00000011")
    result = run_ground_session(transport, "shake", "gnd00000011", 0.05)
    assert result["control_verdict"] == "FAIL"
    assert transport.control_bodies[-1] == "R,shake,gnd00000011,STOP"
    assert result["stop"]["attempted"] is True
    assert transport.close_count == 1


class RunningReceiveErrorTransport(FirmwareScriptTransport):
    """Migrated F2 harness (single-owner replacement).

    Raises from the authorized running-window receive path once the first
    heartbeat has been sent and the RX queue is empty.  This replaces the old
    `soak._collect()` monkeypatch: the running loop itself is the collect, so a
    running `recv()` exception must become the immutable primary failure,
    deactivate heartbeat scheduling, and converge on terminal STOP.
    """

    def __init__(self, run_id):
        super().__init__(run_id)
        self._running_receive_armed = False

    def send(self, data):
        super().send(data)
        body = self.control_bodies[-1]
        if body.startswith("H,"):
            self._running_receive_armed = True

    def recv(self, max_bytes):
        if self._running_receive_armed and self._rx.empty():
            self._running_receive_armed = False
            raise OSError("injected running receive failure")
        return super().recv(max_bytes)


def test_running_receive_exception_deactivates_heartbeat_before_stop():
    transport = RunningReceiveErrorTransport("gnd00000012")
    result = run_ground_session(transport, "shake", "gnd00000012", 0.3)
    assert result["control_verdict"] == "FAIL"
    assert "OSError" in result["unexpected_exception"]
    assert result["heartbeat"]["started"] is True
    assert result["heartbeat"]["stopped_before_final_stop"] is True
    assert result["heartbeat"]["active_at_terminal_stop_reservation"] is False
    assert transport.control_bodies[-1] == "R,shake,gnd00000012,STOP"
    final_stop = len(transport.control_bodies) - 1
    heartbeats = [
        i for i, body in enumerate(transport.control_bodies)
        if body.startswith("H,")
    ]
    assert (not heartbeats) or max(heartbeats) < final_stop


def test_no_overall_shakedown_verdict_in_task1_results():
    # F3: Task 1 owns only the bounded control_verdict; the overall
    # shakedown verdict is Task 2's.
    ok = run_ground_session(
        FirmwareScriptTransport("gnd00000013"), "shake", "gnd00000013", 0.05)
    assert "shakedown_verdict" not in ok
    assert ok["control_verdict"] == "PASS"
    fail_transport = FirmwareScriptTransport(
        "gnd00000014", reject_speed=380, reject_reason="STEP_LIMIT")
    bad = run_ground_session(fail_transport, "shake", "gnd00000014", 0.05)
    assert "shakedown_verdict" not in bad
    assert bad["control_verdict"] == "FAIL"


def test_ack_evidence_and_rollback_fields_serializable():
    # F4: results must carry JSON-serializable parameter ACK records plus the
    # explicit rollback_requested / stop_confirmed separation.
    ok = run_ground_session(
        FirmwareScriptTransport("gnd00000015"), "shake", "gnd00000015", 0.05)
    acks = ok["parameter_acks"]
    assert len(acks) == 5
    for rec in acks:
        assert rec["campaign_id"] == "shake"
        assert rec["outcome"] == "APPLIED" and rec["reason"] == "APPLIED"
        assert set(rec) >= {"campaign_id", "version", "outcome", "reason",
                            "raw_line", "receive_seq", "receive_monotonic_s"}
    json.dumps(acks)
    assert ok["rollback_requested"] is True
    assert ok["stop_confirmed"] is True
    assert "shakedown_verdict" not in ok

    fail_transport = FirmwareScriptTransport(
        "gnd00000016", reject_speed=380, reject_reason="STEP_LIMIT")
    bad = run_ground_session(fail_transport, "shake", "gnd00000016", 0.05)
    rej = [r for r in bad["parameter_acks"] if r["outcome"] != "APPLIED"]
    assert len(rej) == 1
    assert rej[0]["reason"] == "STEP_LIMIT"
    json.dumps(bad["parameter_acks"])
    assert bad["rollback_requested"] is True
    assert bad["stop_confirmed"] is True


def test_stale_matching_ack_cannot_authorize_p1():
    # F6: a matching ACK queued before P1 is pre-boundary evidence and must
    # never authorize P1/START.
    transport = StaleAckFirstTransport("gnd00000017")
    result = run_ground_session(transport, "shake", "gnd00000017", 0.05)
    assert not any(",START" in b for b in transport.control_bodies)
    assert transport.control_bodies[-1] == "R,shake,gnd00000017,STOP"
    assert result["control_verdict"] == "FAIL"
    assert result["speed_override"]["failure_reason"].startswith("STALE_ACK")
    assert any(a["kind"] == "stale_ack" for a in result["protocol_anomalies"])


def test_stale_stopped_cannot_confirm_final_stop():
    # F6: a stale STOPPED/STOP queued before the final STOP cannot confirm a
    # final STOP whose response is absent.
    transport = StaleStopConfirmTransport("gnd00000018")
    result = run_ground_session(transport, "shake", "gnd00000018", 0.05)
    assert result["stop"]["confirmed"] is False
    assert result["stop_confirmed"] is False
    assert result["control_verdict"] == "FAIL"
    assert result["cut_power_warning"] is True
    assert any(a["kind"] == "stale_status" for a in result["protocol_anomalies"])


def test_heartbeat_send_failure_forces_control_fail():
    # F7: a heartbeat send failure must be observable, force control FAIL, and
    # appear in structured evidence.
    transport = HeartbeatErrorTransport("gnd00000019")
    result = run_ground_session(transport, "shake", "gnd00000019", 0.3)
    assert result["control_verdict"] == "FAIL"
    assert result["heartbeat"]["ok"] is False
    assert "heartbeat_send_error" in result["heartbeat"]["failure"]
    assert result["stop"]["confirmed"] is True  # exit STOP still confirmed


def test_final_raw_write_failure_preserves_control_verdict_and_marks_unpublished():
    # F5: a final raw_logger.write() exception must not prevent the single
    # transport close, must not mask the already-determined control verdict or
    # primary failure, and must mark raw evidence unpublished with a structured
    # write_error.
    transport = FirmwareScriptTransport("gnd00000020")
    logger = FailingRawLogger()
    result = run_ground_session(
        transport, "shake", "gnd00000020", 0.05, raw_logger=logger)
    assert transport._closed is True
    assert transport.close_count == 1
    assert logger.writes == 1
    assert "raw_write" in " ".join(result.get("cleanup_errors", []))
    assert result["control_verdict"] == "PASS"
    assert result["raw_io"]["published"] is False
    assert result["raw_io"]["write_error"]
    assert result["primary_failure"] is None


# ── Fix Round 2 regression suite (2026-08-05) ──────────────────────────────
# F8: the connection-time authoritative status must be recorded as top-level
# `initial_status` and must never confirm pre-STOP/START/final STOP.  F9: every
# post-command status waiter is first-event-decisive, so a post-START safety
# status (STOPPED/TIMEOUT) fails closed and is never overridden by a later
# RUNNING/START.

class TimeoutThenRunningTransport(FirmwareScriptTransport):
    """On START, emits an active-identity STOPPED/TIMEOUT (tick 199) and only
    then RUNNING/START (tick 200).  The first post-START status must be
    decisive; the later RUNNING/START must never override it (F9)."""

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        parts = body.split(",")
        if parts[0] == "R" and parts[3] == "START":
            self.control_bodies.append(body)
            self._rx.put(frame(
                "S,{0},{1},STOPPED,TIMEOUT,199".format(parts[1], parts[2])
            ).encode("ascii"))
            self._rx.put(frame(
                "S,{0},{1},RUNNING,START,200".format(parts[1], parts[2])
            ).encode("ascii"))
        else:
            super().send(data)


def test_initial_status_recorded_and_isolated_from_pre_stop():
    # F8: the exact matching connection-time status is queued before the reader
    # starts (tick 10); pre-STOP is confirmed by a distinct post-command
    # STOPPED/STOP (tick 20).  `initial_status` and `pre_stop.status` must both
    # be present with different ticks.
    transport = FirmwareScriptTransport("gnd00000021")
    result = run_ground_session(transport, "shake", "gnd00000021", 0.05)
    initial = result.get("initial_status")
    assert isinstance(initial, dict), "initial_status was not recorded"
    assert initial["tick_ms"] == 10
    pre_stop = result.get("pre_stop", {}).get("status")
    assert isinstance(pre_stop, dict), "pre-STOP confirmation absent"
    assert pre_stop["tick_ms"] != initial["tick_ms"]
    assert result["control_verdict"] == "PASS"


def test_post_start_safety_status_first_event_decisive():
    # F9: after START the first post-boundary status (STOPPED/TIMEOUT) is
    # decisive and fails the gate; the later RUNNING/START must not override.
    transport = TimeoutThenRunningTransport("gnd00000022")
    result = run_ground_session(transport, "shake", "gnd00000022", 0.05)
    assert result["control_verdict"] == "FAIL"
    assert result["start"]["confirmed"] is not True
    # TIMEOUT is retained in structured evidence.
    assert "TIMEOUT" in str(result["start"].get("status"))
    assert "TIMEOUT" in result["start"].get("failure_reason", "")
    # The final command is the single correlated STOP; START is never retried.
    assert transport.control_bodies[-1] == "R,shake,gnd00000022,STOP"
    assert [b for b in transport.control_bodies if ",START" in b] == [
        "R,shake,gnd00000022,START"]


# ── Fix Round 3 regression suite (2026-08-05) ──────────────────────────────
# Firmware source is authoritative (twin_control_protocol.c):
#   - `twin_control_init` sets identity to `none/none` (SENTINEL_CAMPAIGN/RUN)
#     and queues `INIT/MOTION_INHIBITED`;
#   - `twin_control_queue_authoritative_status()` re-emits the cached state
#     using the CURRENT identity, which can be the sentinel or a prior run;
#   - only parsing the new pre-STOP R command changes identity to the new
#     campaign/run (`parse_run`).
# Therefore the first valid CONNECT snapshot must be consumed and recorded
# WITHOUT comparing it to the not-yet-sent new identity; it is evidence only
# and can never confirm pre-STOP, START, or the final STOP.  From pre-STOP
# onward the existing strict identity + first-event-decisive checks are
# mandatory and untested-away.

class SentinelIdentityTransport(FirmwareScriptTransport):
    """Firmware-realistic CONNECT snapshot (Fix Round 3).

    Queues a `S,none,none,INIT,MOTION_INHIBITED` snapshot before the reader
    starts (the reset/cached state the firmware emits on CONNECT under its
    sentinel identity) and answers every subsequent command with the NEW
    session identity — mirroring firmware, which only adopts the new campaign/
    run once the pre-STOP R command is parsed.
    """

    def __init__(self, run_id, reject_speed=None, reject_reason="STEP_LIMIT",
                 drop_final_stop_status=False):
        self.run_id = run_id
        self.reject_speed = reject_speed
        self.reject_reason = reject_reason
        self.drop_final_stop_status = drop_final_stop_status
        self.control_bodies = []
        self._rx = queue.Queue()
        self._stop_count = 0
        self._closed = False
        self.close_count = 0
        self._tick = 1  # first _put_status reply lands on tick 20 (sentinel=10)
        self._rx.put(frame(
            "S,none,none,INIT,MOTION_INHIBITED,10").encode("ascii"))

    def _put_status(self, state, reason):
        # After the pre-STOP R command is parsed firmware uses the NEW identity.
        self._tick += 1
        self._rx.put(frame(
            "S,{0},{1},{2},{3},{4}".format(
                "shake", self.run_id, state, reason, self._tick * 10)
        ).encode("ascii"))


def test_sentinel_identity_connection_snapshot_is_evidence_only():
    # Fix Round 3: the firmware-realistic `none/none` INIT snapshot queued
    # before the reader starts is consumed and recorded WITHOUT identity
    # comparison (the new campaign/run has not been sent yet).  It is evidence
    # only: pre-STOP is confirmed by a distinct NEW-identity status, the normal
    # bounded sequence reaches control PASS, and every post-command identity
    # check remains strict.
    transport = SentinelIdentityTransport("gnd00000023")
    result = run_ground_session(transport, "shake", "gnd00000023", 0.05)
    initial = result.get("initial_status")
    assert isinstance(initial, dict), "sentinel connection snapshot was not recorded"
    # top-level initial_status retains the sentinel/prior identity.
    assert initial["campaign_id"] == "none" and initial["run_id"] == "none"
    assert initial["state"] == "INIT" and initial["reason"] == "MOTION_INHIBITED"
    pre_stop = result.get("pre_stop", {}).get("status")
    assert isinstance(pre_stop, dict), "pre-STOP confirmation absent"
    # pre_stop.status uses the new campaign/run and is a distinct event.
    assert pre_stop["campaign_id"] == "shake" and pre_stop["run_id"] == "gnd00000023"
    assert pre_stop["tick_ms"] != initial["tick_ms"]
    assert pre_stop["tick_ms"] > initial["tick_ms"]
    # The connection snapshot never confirms pre-STOP/START/final STOP, and the
    # normal bounded sequence can still reach control PASS.
    assert result["start"]["confirmed"] is True
    assert result["stop"]["confirmed"] is True
    assert result["control_verdict"] == "PASS"


# ── Single-owner lifecycle replacement regression suite (2026-08-05) ──────
# Each test drives the real `run_ground_session()` against the locked rejected
# production hash and must be RED for the named single-owner defect before the
# production edit is made.  All transports are deterministic in-memory fakes.

def test_all_public_status_records_include_host_receive_provenance():
    result = run_ground_session(
        SentinelIdentityTransport("gnd00000024"),
        "shake", "gnd00000024", 0.05,
    )
    public_statuses = [
        result["initial_status"],
        result["pre_stop"]["status"],
        result["start"]["status"],
        result["stop"]["status"],
    ] + result["statuses"]
    assert public_statuses
    for status in public_statuses:
        assert isinstance(status["receive_seq"], int)
        assert status["receive_seq"] > 0
        assert isinstance(status["receive_monotonic_s"], float)
        assert math.isfinite(status["receive_monotonic_s"])
    assert [s["receive_seq"] for s in result["statuses"]] == sorted(
        s["receive_seq"] for s in result["statuses"]
    )


class CallingThreadRecordingTransport(FirmwareScriptTransport):
    """Records threading.get_ident() on every transport call before delegating."""

    def __init__(self, run_id):
        super().__init__(run_id)
        self.call_threads = []

    def send(self, data):
        self.call_threads.append(threading.get_ident())
        super().send(data)

    def recv(self, max_bytes):
        self.call_threads.append(threading.get_ident())
        return super().recv(max_bytes)

    def close(self):
        self.call_threads.append(threading.get_ident())
        super().close()


class CallingThreadRecordingRawLogger(object):
    """Records threading.get_ident() on every raw-logger call before delegating."""

    def __init__(self):
        self.call_threads = []
        self._events = []

    def log_send(self, data):
        self.call_threads.append(threading.get_ident())
        self._events.append(
            {"dir": "TX", "monotonic_s": time.monotonic(),
             "wall_iso": "thread-test", "n_bytes": len(data),
             "bytes_hex": data.hex()})

    def log_recv(self, data, note=None):
        del note
        self.call_threads.append(threading.get_ident())
        self._events.append(
            {"dir": "RX", "monotonic_s": time.monotonic(),
             "wall_iso": "thread-test", "n_bytes": len(data),
             "bytes_hex": data.hex()})

    def events(self):
        self.call_threads.append(threading.get_ident())
        return list(self._events)

    def write(self):
        self.call_threads.append(threading.get_ident())


def test_single_owner_calls_transport_and_live_raw_logger_only_on_calling_thread():
    transport = CallingThreadRecordingTransport("gnd00000025")
    logger = CallingThreadRecordingRawLogger()
    caller = threading.get_ident()
    result = run_ground_session(
        transport, "shake", "gnd00000025", 0.25, raw_logger=logger)
    recorded = transport.call_threads + logger.call_threads
    assert recorded, "no transport/raw-logger call was recorded"
    for ident in recorded:
        assert ident == caller, "dependency call occurred off the calling thread"
    assert result["control_verdict"] == "PASS"
    assert result["quiescence"]["proven"] is True


class LateHeartbeatSendTransport(FirmwareScriptTransport):
    """First `H` send sleeps 0.18 s > IO_CALL_BUDGET_S (0.15 s)."""

    def __init__(self, run_id):
        super().__init__(run_id)
        self._late_sent = False

    def send(self, data):
        text = data.decode("ascii")
        body = ",".join(text.rstrip("\n").split(",")[:-1])
        if body.startswith("H,") and not self._late_sent:
            self._late_sent = True
            time.sleep(0.18)
        super().send(data)


def test_late_heartbeat_send_exceeds_io_budget_fails_and_no_heartbeat_follows_stop_reservation():
    transport = LateHeartbeatSendTransport("gnd00000026")
    result = run_ground_session(transport, "shake", "gnd00000026", 0.3)
    assert result["control_verdict"] == "FAIL"
    assert result["primary_failure"]["code"] == "IO_CALL_BUDGET_EXCEEDED"
    assert result["heartbeat"]["active_at_terminal_stop_reservation"] is False
    assert transport.control_bodies[-1].endswith(",STOP")
    stop_index = max(
        i for i, body in enumerate(transport.control_bodies)
        if body.endswith(",STOP")
    )
    assert not any(
        body.startswith("H,")
        for body in transport.control_bodies[stop_index + 1:]
    )


class PrimaryAndStopFailureTransport(FirmwareScriptTransport):
    """P2 send raises OSError; the SECOND STOP enqueues STOPPED/STOP then raises
    RuntimeError (a possibly-partial transmission must not hide the primary)."""

    def __init__(self, run_id):
        super().__init__(run_id)
        self._stop_count = 0
        self._p_count = 0

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        parts = body.split(",")
        if parts[0] == "P":
            self._p_count += 1
            if self._p_count == 2:
                raise OSError("primary P2 failure")
            self.control_bodies.append(body)
            self._rx.put(frame(
                "A,{0},{1},APPLIED,APPLIED".format(parts[1], parts[2])
            ).encode("ascii"))
            return
        if parts[0] == "R" and parts[3] == "STOP":
            self._stop_count += 1
            self.control_bodies.append(body)
            if self._stop_count == 2:
                self._rx.put(frame(
                    "S,{0},{1},STOPPED,STOP,99".format(parts[1], parts[2])
                ).encode("ascii"))
                raise RuntimeError("secondary STOP failure")
            self._rx.put(frame(
                "S,{0},{1},STOPPED,STOP,{2}".format(
                    parts[1], parts[2], self._stop_count)
            ).encode("ascii"))
            return
        super().send(data)


def test_primary_parameter_send_failure_survives_non_oserror_terminal_stop_failure():
    transport = PrimaryAndStopFailureTransport("gnd00000027")
    result = run_ground_session(transport, "shake", "gnd00000027", 0.05)
    assert result["control_verdict"] == "FAIL"
    # The P2 OSError is the immutable primary failure.
    assert "primary P2 failure" in result["primary_failure"]["detail"]
    assert "OSError" in result["unexpected_exception"]
    # The RuntimeError from the terminal STOP appears later, never overwriting it.
    assert any(
        "secondary STOP failure" in error.get("detail", "")
        for error in result["secondary_errors"]
    )
    assert result["stop"]["attempted"] is True
    assert result["stop"]["rollback_requested"] is True
    assert result["stop"]["cmd_sent"] is False
    assert result["stop"]["send_outcome"] == "AMBIGUOUS_EXCEPTION"
    assert result["stop"]["confirmed"] is True
    assert result["cut_power_warning"] is True


class LateRunningReceiveTransport(FirmwareScriptTransport):
    """Fault injector that intentionally violates its declared 0.1-second
    io_timeout_s contract.  NOT a supported transport: it exists only to
    deterministically reproduce the rejected architecture's post-publication
    raw writer (one running-window recv sleeps 2.7 s then returns a finite
    chunk)."""

    def __init__(self, run_id):
        super().__init__(run_id)
        self._late_receive_armed = False
        self._late_fired = False

    def send(self, data):
        super().send(data)
        body = self.control_bodies[-1]
        if body.startswith("H,"):
            self._late_receive_armed = True

    def recv(self, max_bytes):
        if (self._late_receive_armed and not self._late_fired
                and self._rx.empty()):
            self._late_receive_armed = False
            self._late_fired = True
            time.sleep(2.7)
            return b"LATE_RX\n"
        return super().recv(max_bytes)


class FreezingRawLogger(object):
    """Raw logger whose write() stores a frozen copy of its events."""

    def __init__(self):
        self._events = []
        self.frozen = None
        self.write_calls = 0

    def log_send(self, data):
        self._events.append(
            {"dir": "TX", "monotonic_s": time.monotonic(),
             "wall_iso": "frozen-test", "n_bytes": len(data),
             "bytes_hex": data.hex()})

    def log_recv(self, data, note=None):
        del note
        self._events.append(
            {"dir": "RX", "monotonic_s": time.monotonic(),
             "wall_iso": "frozen-test", "n_bytes": len(data),
             "bytes_hex": data.hex()})

    def events(self):
        return list(self._events)

    def write(self):
        self.write_calls += 1
        self.frozen = list(self._events)


def test_late_receive_cannot_mutate_frozen_raw_evidence_or_pass(monkeypatch):
    # STATUS_TIMEOUT_S = 0.05 so the rejected implementation's terminal-status
    # wait cannot absorb the 2.7 s reader block; the 2.7 s delay exceeds its
    # 0.30 s collection window, 0.05 s terminal-status wait, 2 s reader join,
    # and 0.25 s margin.
    monkeypatch.setattr(ground_shakedown, "STATUS_TIMEOUT_S", 0.05)
    transport = LateRunningReceiveTransport("gnd00000028")
    logger = FreezingRawLogger()
    result = run_ground_session(
        transport, "shake", "gnd00000028", 0.30, raw_logger=logger)
    assert result["primary_failure"]["code"] == "IO_CALL_BUDGET_EXCEEDED"
    assert result["control_verdict"] == "FAIL"
    assert result["quiescence"]["proven"] is True  # transport.close completed
    frozen = logger.frozen
    assert frozen is not None, "raw logger write() was not invoked"
    n_frozen = len(frozen)
    assert n_frozen > 0
    assert result["quiescence"]["n_frozen_raw_events"] == n_frozen
    assert result["raw"]["n_rx_events"] + result["raw"]["n_tx_events"] == n_frozen
    snapshot = list(frozen)
    time.sleep(0.5)
    # No post-publication writer may mutate the frozen snapshot or the live list.
    assert logger.frozen == snapshot
    assert logger.events() == snapshot
    assert result["quiescence"]["n_frozen_raw_events"] == n_frozen
    assert result["raw"]["n_rx_events"] + result["raw"]["n_tx_events"] == n_frozen


# ── Single-owner boundary suite (2026-08-05) ─────────────────────────────

class PreStopAmbiguousSendTransport(FirmwareScriptTransport):
    """The first STOP enqueues its STOPPED/STOP confirmation then raises, so
    pre-STOP must be promoted to the terminal stop record without a second STOP
    and without any P/START."""

    def send(self, data):
        text = data.decode("ascii")
        fields = text.rstrip("\n").split(",")
        body = ",".join(fields[:-1])
        parts = body.split(",")
        if parts[0] == "R" and parts[3] == "STOP":
            self.control_bodies.append(body)
            self._rx.put(frame(
                "S,{0},{1},STOPPED,STOP,9".format(parts[1], parts[2])
            ).encode("ascii"))
            raise OSError("injected pre-STOP ambiguous send")
        super().send(data)


def test_pre_stop_ambiguous_send_is_promoted_without_a_second_stop():
    transport = PreStopAmbiguousSendTransport("gnd00000029")
    result = run_ground_session(transport, "shake", "gnd00000029", 0.05)
    stops = [
        i for i, body in enumerate(transport.control_bodies)
        if body.endswith(",STOP")
    ]
    assert len(stops) == 1  # exactly one STOP invocation; no second STOP
    assert not any(",P," in body for body in transport.control_bodies)
    assert not any(",START" in body for body in transport.control_bodies)
    assert result["stop"]["send_outcome"] == "AMBIGUOUS_EXCEPTION"
    assert result["stop"]["confirmed"] is True
    assert result["stop"]["cmd_sent"] is False
    assert result["control_verdict"] == "FAIL"


class DeclarationsFailTransport(object):
    """Every method raises if called; used to prove preflight validation makes
    no dependency call."""

    def __init__(self, declaration):
        self.io_timeout_s = declaration

    def send(self, data):
        raise AssertionError("send must not be called during preflight")

    def recv(self, max_bytes):
        raise AssertionError("recv must not be called during preflight")

    def close(self):
        raise AssertionError("close must not be called during preflight")


class MissingSendTransport(object):
    io_timeout_s = 0.1

    def recv(self, max_bytes):
        raise AssertionError("recv must not be called")

    def close(self):
        raise AssertionError("close must not be called")


class MissingRecvTransport(object):
    io_timeout_s = 0.1

    def send(self, data):
        raise AssertionError("send must not be called")

    def close(self):
        raise AssertionError("close must not be called")


class MissingCloseTransport(object):
    io_timeout_s = 0.1

    def send(self, data):
        raise AssertionError("send must not be called")

    def recv(self, max_bytes):
        raise AssertionError("recv must not be called")


def _assert_presession_rejection(transport, duration_s):
    result = run_ground_session(transport, "shake", "gnd00000030", duration_s)
    assert result["control_verdict"] == "FAIL"
    assert result["primary_failure"]["code"] == "PRESESSION_VALIDATION"
    assert result["stop"]["attempted"] is False
    assert result["stop"]["send_outcome"] == "NOT_INVOKED"
    assert result["quiescence"]["proven"] is False
    assert result["cut_power_warning"] is True


def test_rejects_missing_or_invalid_bounded_io_declaration_before_control_io():
    # Invalid/absent timeout declarations, missing methods, and invalid
    # durations are all rejected before any dependency method is called.
    invalid_declarations = [
        None, "0.1", True, float("nan"), float("inf"), 0.0, -0.5, 0.100001,
    ]
    for declaration in invalid_declarations:
        _assert_presession_rejection(DeclarationsFailTransport(declaration), 0.05)
    for cls in (MissingSendTransport, MissingRecvTransport, MissingCloseTransport):
        _assert_presession_rejection(cls(), 0.05)
    # Invalid durations are rejected before any dependency call.  A raising fake
    # with a VALID declaration is used so the rejected (threaded) implementation
    # fails fast on its first dependency call instead of entering soak._collect
    # (which would loop forever on an infinite duration).
    for duration in (True, -1.0, float("nan"), float("inf")):
        _assert_presession_rejection(DeclarationsFailTransport(0.1), duration)


class ActiveRawLogFailLogger(object):
    """Raises from log_send only for the named P command; the transport send
    itself must still be recorded as a completed (not send-exception) outcome."""

    def __init__(self, fail_on_body):
        self.fail_on_body = fail_on_body
        self.log_send_calls = []

    def log_send(self, data):
        text = data.decode("ascii")
        body = ",".join(text.rstrip("\n").split(",")[:-1])
        self.log_send_calls.append(body)
        if body == self.fail_on_body:
            raise OSError("injected active raw-log send failure")

    def log_recv(self, data, note=None):
        pass

    def events(self):
        return []

    def write(self):
        pass


class ActiveRawRecvFailLogger(ActiveRawLogFailLogger):
    """Raises during active RX logging before any control command may follow."""

    def log_recv(self, data, note=None):
        del data, note
        raise OSError("injected active raw-log receive failure")


class FailNthRawRecvLogger(ActiveRawLogFailLogger):
    """Fails on one selected non-empty RX log call."""

    def __init__(self, fail_n):
        super().__init__(None)
        self.fail_n = fail_n
        self.recv_count = 0

    def log_recv(self, data, note=None):
        del note
        self.recv_count += 1
        if self.recv_count == self.fail_n:
            raise OSError("injected nth active raw-log receive failure")


class HeartbeatStatusTransport(FirmwareScriptTransport):
    """Adds one bounded RX event after H so the running log gate is exercised."""

    def send(self, data):
        super().send(data)
        text = data.decode("ascii")
        body = ",".join(text.rstrip("\n").split(",")[:-1])
        if body.startswith("H,"):
            parts = body.split(",")
            self._rx.put(frame(
                "S,{0},{1},RUNNING,START,99".format(parts[1], parts[2])
            ).encode("ascii"))


def test_active_raw_log_failure_is_primary_and_still_attempts_terminal_stop():
    transport = FirmwareScriptTransport("gnd00000031")
    logger = ActiveRawLogFailLogger("P,shake,2,35,0,10,480")
    result = run_ground_session(
        transport, "shake", "gnd00000031", 0.05, raw_logger=logger)
    assert result["control_verdict"] == "FAIL"
    assert result["primary_failure"]["code"] == "ACTIVE_RAW_LOG_FAILURE"
    assert "injected active raw-log send failure" in result["primary_failure"]["detail"]
    # The P transport send outcome was not reclassified as a send exception.
    assert "P,shake,2,35,0,10,480" in logger.log_send_calls
    # Terminal STOP is still attempted and confirmed after the active failure.
    assert transport.control_bodies[-1] == "R,shake,gnd00000031,STOP"
    assert result["stop"]["attempted"] is True
    assert result["stop"]["cmd_sent"] is True
    assert result["stop"]["send_outcome"] == "COMPLETED"
    assert result["stop"]["confirmed"] is True
    failed_index = transport.control_bodies.index(
        "P,shake,2,35,0,10,480")
    assert transport.control_bodies[failed_index + 1:] == [
        "R,shake,gnd00000031,STOP"
    ]


def test_active_raw_log_receive_failure_stops_before_control_commands():
    transport = FirmwareScriptTransport("gnd00000034")
    logger = ActiveRawRecvFailLogger(None)
    result = run_ground_session(
        transport, "shake", "gnd00000034", 0.05, raw_logger=logger)
    assert result["control_verdict"] == "FAIL"
    assert result["primary_failure"]["code"] == "ACTIVE_RAW_LOG_FAILURE"
    assert transport.control_bodies == ["R,shake,gnd00000034,STOP"]
    assert result["stop"]["confirmed"] is True


def test_active_raw_log_receive_failure_stops_at_every_control_gate():
    # RX #1 is the connection snapshot and #2 is pre-STOP.  The later cases
    # target P1 ACK, P5 ACK, START status, and a running-window RX event.
    cases = (
        (3, FirmwareScriptTransport, lambda bodies: not any(
            body.startswith("P,shake,2,") for body in bodies)),
        (7, FirmwareScriptTransport, lambda bodies: not any(
            ",START" in body for body in bodies)),
        (8, FirmwareScriptTransport, lambda bodies: not any(
            body.startswith("H,") for body in bodies)),
        (9, HeartbeatStatusTransport, lambda bodies: bodies.count(
            "H,shake,gnd00000037") == 1),
    )
    for fail_n, transport_cls, no_followup in cases:
        run_id = "gnd00000037"
        transport = transport_cls(run_id)
        logger = FailNthRawRecvLogger(fail_n)
        result = run_ground_session(
            transport, "shake", run_id, 0.25, raw_logger=logger)
        assert result["control_verdict"] == "FAIL"
        assert result["primary_failure"]["code"] == "ACTIVE_RAW_LOG_FAILURE"
        assert no_followup(transport.control_bodies)
        assert transport.control_bodies[-1] == (
            "R,shake,{0},STOP".format(run_id))


class LateCloseTransport(FirmwareScriptTransport):
    def close(self):
        self.close_count += 1
        self._closed = True
        time.sleep(0.18)


class FailingCloseTransport(FirmwareScriptTransport):
    def close(self):
        self.close_count += 1
        raise RuntimeError("injected close failure")


class KeyboardInterruptCloseTransport(FirmwareScriptTransport):
    def close(self):
        self.close_count += 1
        raise KeyboardInterrupt("close interrupt")


def test_late_or_failing_close_forces_fail_and_unproven_quiescence():
    for transport, expected_code in (
        (LateCloseTransport("gnd00000032"), "IO_CALL_BUDGET_EXCEEDED"),
        (FailingCloseTransport("gnd00000033"), "TRANSPORT_CLOSE_EXCEPTION"),
    ):
        result = run_ground_session(transport, "shake", transport.run_id, 0.05)
        assert transport.close_count == 1
        assert result["control_verdict"] == "FAIL"
        assert result["quiescence"]["proven"] is False
        assert result["primary_failure"]["code"] == expected_code


def test_keyboard_interrupt_close_still_returns_structured_failure_report():
    transport = KeyboardInterruptCloseTransport("gnd00000038")
    result = run_ground_session(transport, "shake", transport.run_id, 0.05)
    assert transport.close_count == 1
    assert result["control_verdict"] == "FAIL"
    assert result["primary_failure"]["code"] == "TRANSPORT_CLOSE_EXCEPTION"
    assert any("transport_close" in item for item in result["cleanup_errors"])
    assert result["socket"]["close"]["state"] == "FAILED"
    assert "close interrupt" in result["socket"]["close"]["error"]


# ---------------------------------------------------------------------------
# Task 2 RED/GREEN suite: immutable evidence and report boundary.
# ---------------------------------------------------------------------------

def test_evidence_directory_refuses_existing_target(tmp_path):
    target = tmp_path / "v1_ground_shakedown_20260804_220000"
    target.mkdir()
    with pytest.raises(FileExistsError):
        make_evidence_dir(tmp_path, "20260804_220000")


def test_new_report_labels_historical_yaw_value_as_degrees():
    report = {"telemetry": {"frames": [{"yaw_rad": 12.5}]}}
    result = normalize_telemetry_units(report)
    assert result is report
    assert report["telemetry"]["frames"] == [{"yaw_deg": 12.5}]
    assert report["telemetry_yaw_unit"] == "degree"


def test_unit_normalization_rejects_conflicting_dual_yaw_fields():
    report = {"telemetry": {"frames": [{"yaw_rad": 1.0, "yaw_deg": 2.0}]}}
    with pytest.raises(ValueError):
        normalize_telemetry_units(report)
    assert report["telemetry"]["frames"][0] == {
        "yaw_rad": 1.0, "yaw_deg": 2.0}


def test_duration_validation_rejects_resource_unsafe_values():
    for value in (float("nan"), float("inf"), float("-inf"), 0.0, -0.1,
                  True, "0.5"):
        with pytest.raises(ValueError):
            validate_duration(value)
    with pytest.raises(ValueError):
        validate_duration(3.1)
    assert validate_duration(3.1, allow_extended=True) == 3.1
    with pytest.raises(ValueError):
        validate_duration(20.1, allow_extended=True)


def test_publish_report_atomic_leaves_only_final_report(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    path = publish_report_atomic(evidence, {"verdict": "SHAKEDOWN_FAIL"})
    assert path == evidence / "shakedown_report.json"
    assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == (
        "SHAKEDOWN_FAIL")
    assert not list(evidence.glob(".shakedown_report*.tmp"))


class _FakeStdin(object):
    def __init__(self, broken=False):
        self.broken = broken
        self.writes = []
        self.closed = False

    def write(self, data):
        if self.broken:
            raise BrokenPipeError("stdin closed")
        self.writes.append(data)

    def flush(self):
        if self.broken:
            raise BrokenPipeError("stdin closed")

    def close(self):
        self.closed = True


class _FakeProcess(object):
    def __init__(self, returncode=None, broken_stdin=False,
                 wait_timeout=False, wait_code=0):
        self.returncode = returncode
        self.stdin = _FakeStdin(broken_stdin)
        self.wait_timeout = wait_timeout
        self.wait_code = wait_code
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.wait_timeout and self.kill_calls == 0:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        self.returncode = self.wait_code
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1
        self.returncode = self.wait_code


def _valid_ffprobe(stdout=None, returncode=0):
    if stdout is None:
        stdout = json.dumps({"streams": [{
            "codec_name": "mjpeg",
            "codec_tag_string": "MJPG",
            "codec_tag": "0x47504a4d",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
        }]})
    return subprocess.CompletedProcess(
        args=["ffprobe"], returncode=returncode, stdout=stdout, stderr="")


def test_missing_executable_rejected_before_evidence_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(ground_shakedown.shutil, "which", lambda name: None)
    root = tmp_path / "out"
    result = ground_shakedown.main([
        "--host", "127.0.0.1", "--port", "8888", "--duration", "0.5",
        "--run-kind", "elevated-wheels", "--out-root", str(root),
        "--execute",
    ])
    assert result != 0
    assert not root.exists()


def test_camera_immediate_exit_publishes_failure_and_blocks_session(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=1)
    calls = {"session": 0}
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )

    def session_runner():
        calls["session"] += 1
        return {"control_verdict": "PASS"}

    with pytest.raises(CameraStartError):
        orchestrate_shakedown(recorder, session_runner, evidence, "elevated-wheels")
    report = json.loads((evidence / "shakedown_report.json").read_text(
        encoding="utf-8"))
    assert calls["session"] == 0
    assert report["verdict"] == "SHAKEDOWN_FAIL"
    assert "camera.mkv" in report["missing_artifacts"]


def test_camera_graceful_shutdown_requires_mjpeg_1080p_30fps(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    recorder.start()
    (evidence / "camera.mkv").write_bytes(b"mkv")
    stopped = recorder.stop()
    report = recorder.validate()
    assert process.stdin.writes == [b"q"]
    assert stopped["clean_exit"] is True
    assert report["verdict"] == "PASS"
    assert report["video"]["fps"] == 30.0
    assert report["video"]["codec_name"] == "mjpeg"
    assert report["video"]["codec_tag_string"] == "MJPG"
    assert report["video"]["codec_tag"] == "0x47504a4d"
    assert report["codec_tag_evidence"]["status"] == "PASS"
    assert "codec_tag_string" in " ".join(report["ffprobe_command"])
    assert "video=EMEET SmartCam C960" in recorder.command


def test_camera_validation_accepts_matroska_when_directshow_input_tag_is_verified(
        tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    stdout = json.dumps({"streams": [{
        "codec_name": "mjpeg",
        "codec_tag_string": "[0][0][0][0]",
        "codec_tag": "0x0000",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30/1",
    }]})
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(stdout=stdout),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    recorder.start()
    (evidence / "camera.mkv").write_bytes(b"mkv")
    recorder.stop()
    (evidence / "camera_ffmpeg.log").write_text(
        "Input #0, dshow, from 'video=EMEET SmartCam C960':\n"
        "  Stream #0:0: Video: mjpeg (Baseline) "
        "(MJPG / 0x47504A4D), yuvj422p(pc), 1920x1080, 30 fps\n",
        encoding="utf-8",
    )
    report = recorder.validate()
    assert report["verdict"] == "PASS"
    assert report["video"]["codec_tag_string"] == "[0][0][0][0]"
    assert report["codec_tag_evidence"]["status"] == "CONTAINER_UNSPECIFIED"
    assert report["input_codec_tag_evidence"]["status"] == "PASS"
    assert report["input_codec_tag_evidence"]["codec_tag_string"] == "MJPG"


def test_camera_validation_keeps_codec_name_and_marks_missing_codec_tag_unknown(
        tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    stdout = json.dumps({"streams": [{
        "codec_name": "mjpeg",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30/1",
    }]})
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(stdout=stdout),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    recorder.start()
    (evidence / "camera.mkv").write_bytes(b"mkv")
    recorder.stop()
    report = recorder.validate()
    assert report["verdict"] == "FAIL"
    assert report["camera_verdict"] == "FAIL"
    assert report["video"]["codec_name"] == "mjpeg"
    assert report["video"]["codec_tag_string"] == "UNKNOWN"
    assert report["video"]["codec_tag"] is None
    assert report["codec_tag_evidence"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert any("codec tag" in error.lower() for error in report["errors"])


@pytest.mark.parametrize("codec_tag_string, codec_tag", [
    ("H264", "0x34363248"),
    ("MJPX", "0x47504a58"),
    ("MJPG", "0x00000000"),
])
def test_camera_validation_fails_closed_on_wrong_codec_tag(
        tmp_path, codec_tag_string, codec_tag):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    stdout = json.dumps({"streams": [{
        "codec_name": "mjpeg",
        "codec_tag_string": codec_tag_string,
        "codec_tag": codec_tag,
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30/1",
    }]})
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(stdout=stdout),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    recorder.start()
    (evidence / "camera.mkv").write_bytes(b"mkv")
    recorder.stop()
    report = recorder.validate()
    assert report["verdict"] == "FAIL"
    assert report["camera_verdict"] == "FAIL"
    assert report["video"]["codec_name"] == "mjpeg"
    assert report["codec_tag_evidence"]["status"] == "FAIL"
    assert report["codec_tag_evidence"]["codec_tag_string"] == codec_tag_string
    assert report["codec_tag_evidence"]["codec_tag"] == codec_tag


def test_recorder_default_factories_are_resolved_at_instance_time(tmp_path,
                                                                   monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    monkeypatch.setattr(
        ground_shakedown.subprocess, "Popen",
        lambda command, **kwargs: process)
    monkeypatch.setattr(
        ground_shakedown.subprocess, "run",
        lambda *args, **kwargs: _valid_ffprobe())
    recorder = FfmpegCameraRecorder(
        evidence,
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    recorder.start()
    (evidence / "camera.mkv").write_bytes(b"mkv")
    recorder.stop()
    assert recorder.validate()["verdict"] == "PASS"


def test_camera_stop_forces_terminate_then_kill_and_is_idempotent(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None, wait_timeout=True, wait_code=-9)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    recorder.start()
    first = recorder.stop()
    second = recorder.stop()
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert first is second
    assert first["forced_termination"] is True


def test_camera_start_probe_failure_reaps_process_and_closes_log(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None, wait_timeout=True, wait_code=-9)

    def broken_sleep(_seconds):
        raise RuntimeError("startup probe interrupted")

    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=broken_sleep,
    )
    with pytest.raises(CameraStartError, match="startup probe interrupted"):
        recorder.start()
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert recorder.log_handle.closed is True


def test_camera_start_keyboard_interrupt_reaps_process_and_closes_log(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None, wait_timeout=True, wait_code=-9)

    def interrupted_sleep(_seconds):
        raise KeyboardInterrupt()

    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=interrupted_sleep,
    )
    with pytest.raises(KeyboardInterrupt):
        recorder.start()
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert recorder.log_handle.closed is True


def test_camera_start_keyboard_interrupt_survives_cleanup_wait_interrupt(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    class _WaitKeyboardInterruptProcess(_FakeProcess):
        def wait(self, timeout=None):
            raise KeyboardInterrupt("wait interrupted during cleanup")

    process = _WaitKeyboardInterruptProcess(returncode=None)

    def interrupted_sleep(_seconds):
        raise KeyboardInterrupt("startup interrupted")

    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=interrupted_sleep,
    )
    with pytest.raises(KeyboardInterrupt, match="startup interrupted"):
        recorder.start()
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert recorder.log_handle.closed is True


class _WaitErrorProcess(_FakeProcess):
    def wait(self, timeout=None):
        if self.kill_calls == 0:
            raise RuntimeError("wait failed")
        return super().wait(timeout)


def test_camera_stop_reaps_after_non_timeout_wait_failure(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _WaitErrorProcess(returncode=None, wait_code=-9)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    recorder.start()
    report = recorder.stop()
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert report["forced_termination"] is True
    assert report["exit_code"] == -9
    assert any("wait" in item for item in report["cleanup_errors"])


def _valid_socket_report():
    return {
        "connect": {
            "state": "COMPLETED",
            "call_count": 1,
            "started_monotonic_s": 1.0,
            "completed_monotonic_s": 1.1,
            "failed_monotonic_s": None,
            "elapsed_s": 0.1,
            "error": None,
        },
        "close": {
            "state": "COMPLETED",
            "call_count": 1,
            "started_monotonic_s": 2.0,
            "completed_monotonic_s": 2.1,
            "failed_monotonic_s": None,
            "elapsed_s": 0.1,
            "error": None,
        },
    }


def test_verdict_precedence_failure_then_missing_evidence_then_pass():
    control = {
        "control_verdict": "FAIL",
        "telemetry": {"frames": [1]},
        "socket": _valid_socket_report(),
    }
    camera = {"verdict": "PASS", "clean_exit": True}
    complete = {name: True for name in (
        "camera.mkv", "camera_ffmpeg.log", "raw_io.json",
        "shakedown_report.json")}
    assert compute_shakedown_verdict(control, camera, {}) == "SHAKEDOWN_FAIL"
    control["control_verdict"] = "PASS"
    assert compute_shakedown_verdict(control, camera, {}) == (
        "INSUFFICIENT_EVIDENCE")
    assert compute_shakedown_verdict(control, camera, complete) == (
        "SHAKEDOWN_PASS")


def test_verdict_rejects_unpublished_raw_io_even_when_control_says_pass():
    control = {
        "control_verdict": "PASS",
        "raw_io": {"published": False, "write_error": "disk full"},
        "telemetry": {"frames": [{}]},
    }
    camera = {"verdict": "PASS", "clean_exit": True}
    complete = {name: True for name in (
        "camera.mkv", "camera_ffmpeg.log", "raw_io.json",
        "shakedown_report.json")}
    assert compute_shakedown_verdict(control, camera, complete) == (
        "SHAKEDOWN_FAIL")


def test_verdict_does_not_treat_missing_camera_verdict_as_pass():
    control = {"control_verdict": "PASS", "telemetry": {"frames": [{}]}}
    complete = {name: True for name in (
        "camera.mkv", "camera_ffmpeg.log", "raw_io.json",
        "shakedown_report.json")}
    assert compute_shakedown_verdict(control, {}, complete) == (
        "INSUFFICIENT_EVIDENCE")


def test_missing_camera_report_is_insufficient_not_known_failure():
    control = {"control_verdict": "PASS", "telemetry": {"frames": [{}]}}
    complete = {name: True for name in (
        "camera.mkv", "camera_ffmpeg.log", "raw_io.json",
        "shakedown_report.json")}
    assert compute_shakedown_verdict(control, None, complete) == (
        "INSUFFICIENT_EVIDENCE")


@pytest.mark.parametrize("failure_field", [
    "secondary_errors",
    "protocol_anomalies",
    "heartbeat_not_ok",
    "cut_power_warning",
    "raw_write_error",
    "stop_send_outcome",
])
def test_verdict_rejects_conflicting_control_failure_evidence(failure_field):
    control = {
        "control_verdict": "PASS",
        "telemetry": {"frames": [{}]},
        "secondary_errors": [],
        "protocol_anomalies": [],
        "heartbeat": {"ok": True},
        "cut_power_warning": False,
        "raw_io": {"published": True, "write_error": None},
        "stop": {"confirmed": True, "send_outcome": "COMPLETED"},
        "socket": _valid_socket_report(),
    }
    if failure_field == "heartbeat_not_ok":
        control["heartbeat"] = {"ok": False}
    elif failure_field == "cut_power_warning":
        control["cut_power_warning"] = True
    elif failure_field == "raw_write_error":
        control["raw_io"]["write_error"] = "disk full"
    elif failure_field == "stop_send_outcome":
        control["stop"]["send_outcome"] = "AMBIGUOUS_EXCEPTION"
    elif failure_field == "secondary_errors":
        control["secondary_errors"] = [{"code": "STOP_SEND_EXCEPTION"}]
    else:
        control["protocol_anomalies"] = [{"code": "STALE_STATUS"}]
    camera = {"verdict": "PASS", "clean_exit": True}
    complete = {name: True for name in (
        "camera.mkv", "camera_ffmpeg.log", "raw_io.json",
        "shakedown_report.json")}
    assert compute_shakedown_verdict(control, camera, complete) == (
        "SHAKEDOWN_FAIL")


def test_external_raw_io_path_cannot_satisfy_evidence_gate(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    external = tmp_path / "external_raw_io.json"
    external.write_text("{}", encoding="utf-8")
    control = {
        "control_verdict": "PASS",
        "telemetry": {"frames": [{}]},
        "raw_io": {"published": True, "path": str(external)},
        "socket": _valid_socket_report(),
    }
    artifact_map = _relative_artifact_map(evidence, control, include_report=True)
    assert artifact_map["raw_io.json"]["present"] is False
    assert compute_shakedown_verdict(
        control,
        {"verdict": "PASS", "clean_exit": True},
        artifact_map,
    ) == "INSUFFICIENT_EVIDENCE"


def test_verdict_requires_socket_lifecycle_evidence_for_pass():
    complete = {name: True for name in (
        "camera.mkv", "camera_ffmpeg.log", "raw_io.json",
        "shakedown_report.json")}
    control = {
        "control_verdict": "PASS",
        "telemetry": {"frames": [{}]},
        "raw_io": {"published": True, "write_error": None},
    }
    camera = {"verdict": "PASS", "clean_exit": True}
    assert compute_shakedown_verdict(control, camera, complete) == (
        "INSUFFICIENT_EVIDENCE")


@pytest.mark.parametrize("socket_report", [
    {"connect": {"state": "FAILED", "call_count": 1,
                  "started_monotonic_s": 1.0, "failed_monotonic_s": 1.1,
                  "completed_monotonic_s": None, "elapsed_s": 0.1,
                  "error": "boom"},
     "close": {"state": "COMPLETED", "call_count": 1,
                "started_monotonic_s": 2.0, "completed_monotonic_s": 2.1,
                "failed_monotonic_s": None, "elapsed_s": 0.1,
                "error": None}},
    {"connect": _valid_socket_report()["connect"],
     "close": {"state": "FAILED", "call_count": 1,
                "started_monotonic_s": 2.0, "completed_monotonic_s": None,
                "failed_monotonic_s": 2.1, "elapsed_s": 0.1,
                "error": "close boom"}},
    {"connect": _valid_socket_report()["connect"],
     "close": {"state": "COMPLETED", "call_count": 2,
                "started_monotonic_s": 2.0, "completed_monotonic_s": 2.1,
                "failed_monotonic_s": None, "elapsed_s": 0.1,
                "error": None}},
])
def test_verdict_fails_closed_on_bad_socket_lifecycle(socket_report):
    complete = {name: True for name in (
        "camera.mkv", "camera_ffmpeg.log", "raw_io.json",
        "shakedown_report.json")}
    control = {
        "control_verdict": "PASS",
        "telemetry": {"frames": [{}]},
        "raw_io": {"published": True, "write_error": None},
        "socket": socket_report,
    }
    camera = {"verdict": "PASS", "clean_exit": True}
    assert compute_shakedown_verdict(control, camera, complete) == (
        "SHAKEDOWN_FAIL")


def test_cli_dry_run_has_no_resource_side_effects(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("resource factory called during dry-run")
    monkeypatch.setattr(ground_shakedown.shutil, "which", forbidden)
    monkeypatch.setattr(ground_shakedown.subprocess, "Popen", forbidden)
    monkeypatch.setattr(ground_shakedown, "make_evidence_dir", forbidden)
    root = tmp_path / "out"
    assert ground_shakedown.main([
        "--duration", "0.5", "--run-kind", "elevated-wheels",
        "--out-root", str(root),
    ]) == 0
    output = capsys.readouterr().out
    assert "--execute" in output
    assert "--duration 0.5" in output
    assert "--allow-extended" not in output
    assert "--retry" not in output
    assert "--pid" not in output
    assert not root.exists()


def test_cli_execute_passes_runtime_timestamp_to_evidence_dir(
        tmp_path, monkeypatch):
    captured = {}
    evidence = tmp_path / "evidence"

    def fake_make_evidence_dir(root, timestamp):
        captured["root"] = Path(root)
        captured["timestamp"] = timestamp
        evidence.mkdir()
        return evidence

    def fake_orchestrate(recorder, session_runner, evidence_dir, run_kind,
                         **kwargs):
        captured["campaign_id"] = kwargs["campaign_id"]
        captured["run_id"] = kwargs["run_id"]
        captured["evidence_dir"] = evidence_dir
        captured["run_kind"] = run_kind
        return {"verdict": "INSUFFICIENT_EVIDENCE"}

    monkeypatch.setattr(
        ground_shakedown, "_resolve_camera_executables",
        lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(
        ground_shakedown, "make_evidence_dir", fake_make_evidence_dir)
    monkeypatch.setattr(
        ground_shakedown, "orchestrate_shakedown", fake_orchestrate)

    assert ground_shakedown.main([
        "--duration", "0.5", "--run-kind", "elevated-wheels",
        "--out-root", str(tmp_path / "out"), "--execute",
    ]) == 2

    timestamp = captured["timestamp"]
    assert isinstance(timestamp, str)
    assert len(timestamp) == 15 and timestamp.isdigit()
    assert captured["root"] == tmp_path / "out"
    assert captured["campaign_id"] == "s" + timestamp
    assert captured["run_id"] == "e" + timestamp
    assert captured["evidence_dir"] == evidence
    assert captured["run_kind"] == "elevated-wheels"


def test_session_telemetry_preserves_current_imu_evidence_fields():
    loop = ground_shakedown._SessionLoop.__new__(ground_shakedown._SessionLoop)
    loop.telemetry_frames = []
    payload = bytearray(26)
    payload[16:20] = (9876).to_bytes(4, "little")
    payload[20:24] = (-1234).to_bytes(4, "little", signed=True)
    payload[24] = 0x14
    payload[25] = 0x21

    loop._on_telemetry(bytes(payload))

    record = loop.telemetry_frames[0]
    assert record["imu_yaw_deg_x100"] == -1234
    assert record["imu_validity"] == 0x14
    assert record["imu_validity_known"] is True
    assert record["imu_init_status"] == 0x21
    assert record["imu_init_status_known"] is True


def test_imu_evidence_summary_verifies_fusion_ready_frames():
    summary = ground_shakedown.summarize_imu_evidence({
        "telemetry": {"frames": [{
            "imu_validity": 0x0F,
            "imu_validity_known": True,
            "imu_init_status": 0x00,
            "imu_init_status_known": True,
        }]}
    })

    assert summary["status"] == "VERIFIED"
    assert summary["verdict"] == "PASS"
    assert summary["reason"] == "VALID_INITIALIZED_FUSION_INPUT"
    assert summary["dt_clamped_frames"] == 0


def test_imu_evidence_summary_distinguishes_known_failure_from_unknown():
    failure = ground_shakedown.summarize_imu_evidence({
        "telemetry": {"frames": [{
            "imu_validity": 0x14,
            "imu_validity_known": True,
            "imu_init_status": 0x21,
            "imu_init_status_known": True,
        }]}
    })
    unknown = ground_shakedown.summarize_imu_evidence({
        "telemetry": {"frames": [{"tick_ms": 1}]}
    })

    assert failure["status"] == "VERIFIED"
    assert failure["verdict"] == "FAIL"
    assert failure["init_status_values"] == [0x21]
    assert failure["validity_values"] == [0x14]
    assert failure["dt_clamped_frames"] == 1
    assert "IMU_INIT_STATUS_NOT_OK" in failure["reason"]
    assert unknown["status"] == "INSUFFICIENT_EVIDENCE"
    assert unknown["verdict"] == "UNVERIFIED"


def test_invalid_cli_duration_is_rejected_before_any_execute_factory(tmp_path,
                                                                       monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("resource factory called before duration rejection")
    monkeypatch.setattr(ground_shakedown.shutil, "which", forbidden)
    monkeypatch.setattr(ground_shakedown, "make_evidence_dir", forbidden)
    for value in ("nan", "inf", "-inf", "0", "-1", "3.1", "20.1"):
        root = tmp_path / ("out_" + value.replace("-", "m"))
        result = ground_shakedown.main([
            "--duration={0}".format(value), "--run-kind", "ground",
            "--out-root", str(root), "--execute",
        ])
        assert result != 0
        assert not root.exists()


def test_camera_popen_failure_closes_log_and_never_runs_session(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    def failing_popen(command, **kwargs):
        raise OSError("popen denied")

    calls = {"session": 0}
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=failing_popen,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    with pytest.raises(CameraStartError):
        orchestrate_shakedown(
            recorder,
            lambda: calls.__setitem__("session", calls["session"] + 1),
            evidence,
            "ground",
        )
    assert calls["session"] == 0
    assert (evidence / "camera_ffmpeg.log").is_file()
    assert recorder.log_handle.closed is True


def test_camera_broken_pipe_is_recorded_as_camera_failure(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None, broken_stdin=True)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    recorder.start()
    (evidence / "camera.mkv").write_bytes(b"mkv")
    stop = recorder.stop()
    report = recorder.validate()
    assert stop["stdin_error"]
    assert report["verdict"] == "FAIL"


@pytest.mark.parametrize("probe_factory", [
    lambda: subprocess.CompletedProcess(["ffprobe"], 1, "{}", "bad"),
    lambda: (_ for _ in ()).throw(subprocess.TimeoutExpired("ffprobe", 5)),
    lambda: subprocess.CompletedProcess(["ffprobe"], 0, "not-json", ""),
    lambda: subprocess.CompletedProcess(["ffprobe"], 0, "{\"streams\": []}", ""),
    lambda: subprocess.CompletedProcess(["ffprobe"], 0, json.dumps(
        {"streams": [None]}), ""),
    lambda: subprocess.CompletedProcess(["ffprobe"], 0, json.dumps(
        {"streams": ["not-an-object"]}), ""),
    lambda: subprocess.CompletedProcess(["ffprobe"], 0, json.dumps({
        "streams": [{"codec_name": "h264", "width": 1920, "height": 1080,
                     "avg_frame_rate": "30/1"}]}), ""),
    lambda: subprocess.CompletedProcess(["ffprobe"], 0, json.dumps({
        "streams": [{"codec_name": "mjpeg", "width": 640, "height": 480,
                     "avg_frame_rate": "15/1"}]}), ""),
])
def test_ffprobe_faults_and_wrong_metadata_fail_closed(tmp_path, probe_factory):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: probe_factory(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    recorder.start()
    (evidence / "camera.mkv").write_bytes(b"mkv")
    recorder.stop()
    report = recorder.validate()
    assert report["verdict"] == "FAIL"
    assert report["errors"]


def test_frame_rate_overflow_fails_closed():
    assert _parse_frame_rate(10 ** 400) is None


def test_session_exception_stops_camera_and_publishes_before_reraise(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )

    def failing_session():
        raise RuntimeError("session exploded")

    with pytest.raises(RuntimeError, match="session exploded"):
        orchestrate_shakedown(recorder, failing_session, evidence, "ground")
    assert process.stdin.closed is True
    report = json.loads((evidence / "shakedown_report.json").read_text(
        encoding="utf-8"))
    assert report["verdict"] == "SHAKEDOWN_FAIL"
    assert "session exploded" in report["errors"][0]


def test_cli_rejects_missing_run_kind_and_above_twenty_seconds(capsys):
    with pytest.raises(SystemExit):
        ground_shakedown.main(["--duration", "0.5"])
    assert ground_shakedown.main([
        "--duration", "20.1", "--run-kind", "ground",
    ]) != 0
    assert "duration" in capsys.readouterr().out


def test_cli_dry_run_identities_are_sixteen_ascii_characters(capsys):
    assert ground_shakedown.main([
        "--duration", "0.5", "--run-kind", "ground",
    ]) == 0
    output = capsys.readouterr().out.splitlines()
    campaign = output[1].split(": ", 1)[1]
    run_id = output[2].split(": ", 1)[1]
    assert len(campaign) == len(run_id) == 16
    assert campaign.startswith("s") and run_id.startswith("g")
    assert campaign.isascii() and run_id.isascii()
    assert campaign[1:].isdigit() and run_id[1:].isdigit()


def test_extended_dry_run_future_command_preserves_allow_extended(capsys):
    assert ground_shakedown.main([
        "--duration", "4", "--allow-extended", "--run-kind", "ground",
    ]) == 0
    output = capsys.readouterr().out
    assert "--duration 4.0" in output
    assert "--allow-extended" in output


def test_normal_orchestration_publishes_pass_only_with_all_evidence(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )

    def session_runner():
        (evidence / "camera.mkv").write_bytes(b"mkv")
        (evidence / "raw_io.json").write_text("{}", encoding="utf-8")
        return {
            "campaign_id": "s260805010203000",
            "run_id": "g260805010203000",
            "requested_duration_s": 0.5,
            "control_verdict": "PASS",
            "stop_confirmed": True,
            "rollback_requested": True,
            "telemetry": {"frames": [{"tick_ms": 1, "yaw_rad": 4.0}]},
            "raw_io": {"published": True},
            "socket": _valid_socket_report(),
        }

    report = orchestrate_shakedown(recorder, session_runner, evidence, "ground")
    assert report["verdict"] == "SHAKEDOWN_PASS"
    assert report["control"]["telemetry"]["frames"] == [
        {"tick_ms": 1, "yaw_deg": 4.0}]
    assert report["imu_evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["imu_evidence"]["verdict"] == "UNVERIFIED"
    assert report["rollback_requested"] is True
    assert report["stop_confirmed"] is True
    assert report["missing_artifacts"] == []


def test_normal_orchestration_missing_raw_evidence_is_insufficient(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=None)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )

    def session_runner():
        (evidence / "camera.mkv").write_bytes(b"mkv")
        return {"control_verdict": "PASS", "telemetry": {"frames": [{}]}}

    report = orchestrate_shakedown(recorder, session_runner, evidence, "ground")
    assert report["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert "raw_io.json" in report["missing_artifacts"]


def test_unexpected_camera_start_exception_still_publishes_failure(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    class BrokenRecorder(object):
        def start(self):
            raise RuntimeError("unexpected camera start")

    with pytest.raises(RuntimeError, match="unexpected camera start"):
        orchestrate_shakedown(
            BrokenRecorder(), lambda: {"control_verdict": "PASS"},
            evidence, "ground")
    report = json.loads((evidence / "shakedown_report.json").read_text(
        encoding="utf-8"))
    assert report["verdict"] == "SHAKEDOWN_FAIL"
    assert "unexpected camera start" in report["errors"][0]


def test_camera_start_failure_report_keeps_cli_identity_and_duration(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    process = _FakeProcess(returncode=1)
    recorder = FfmpegCameraRecorder(
        evidence,
        popen_factory=lambda command, **kwargs: process,
        ffprobe_runner=lambda *args, **kwargs: _valid_ffprobe(),
        executable_resolver=lambda name: name,
        sleep_fn=lambda seconds: None,
    )
    with pytest.raises(CameraStartError):
        orchestrate_shakedown(
            recorder,
            lambda: {"control_verdict": "PASS"},
            evidence,
            "ground",
            campaign_id="s260805010203000",
            run_id="g260805010203000",
            requested_duration_s=0.5,
        )
    report = json.loads((evidence / "shakedown_report.json").read_text(
        encoding="utf-8"))
    assert report["campaign_id"] == "s260805010203000"
    assert report["run_id"] == "g260805010203000"
    assert report["requested_duration_s"] == 0.5


def test_camera_validation_errors_are_promoted_to_top_level_report(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    class FailingCamera(object):
        def start(self):
            return None

        def stop(self):
            return None

        def validate(self):
            return {"verdict": "FAIL", "errors": ["codec mismatch"]}

    def session_runner():
        (evidence / "camera.mkv").write_bytes(b"mkv")
        (evidence / "camera_ffmpeg.log").write_text("", encoding="utf-8")
        (evidence / "raw_io.json").write_text("{}", encoding="utf-8")
        return {"control_verdict": "PASS", "telemetry": {"frames": [{}]}}

    report = orchestrate_shakedown(
        FailingCamera(), session_runner, evidence, "ground")
    assert report["verdict"] == "SHAKEDOWN_FAIL"
    assert any("codec mismatch" in error for error in report["errors"])


def test_final_report_publication_failure_returns_structured_failure(tmp_path,
                                                                     monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    class PassingCamera(object):
        def start(self):
            return None

        def stop(self):
            return None

        def validate(self):
            return {"verdict": "PASS", "clean_exit": True}

    def session_runner():
        (evidence / "camera.mkv").write_bytes(b"mkv")
        (evidence / "camera_ffmpeg.log").write_text("", encoding="utf-8")
        (evidence / "raw_io.json").write_text("{}", encoding="utf-8")
        return {
            "campaign_id": "s260805010203000",
            "run_id": "g260805010203000",
            "requested_duration_s": 0.5,
            "control_verdict": "PASS",
            "telemetry": {"frames": [{}]},
            "raw_io": {"published": True},
        }

    def fail_publish(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ground_shakedown, "publish_report_atomic", fail_publish)
    report = orchestrate_shakedown(
        PassingCamera(), session_runner, evidence, "ground")
    assert report["verdict"] == "SHAKEDOWN_FAIL"
    assert report["publication_error"]
    assert any("disk full" in error for error in report["errors"])


def test_startup_report_publication_failure_attaches_structured_failure(
        tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    class BrokenRecorder(object):
        def start(self):
            raise CameraStartError("camera unavailable")

    def fail_publish(*_args, **_kwargs):
        raise OSError("report disk full")

    monkeypatch.setattr(ground_shakedown, "publish_report_atomic", fail_publish)
    with pytest.raises(CameraStartError) as exc_info:
        orchestrate_shakedown(
            BrokenRecorder(), lambda: {"control_verdict": "PASS"},
            evidence, "ground", campaign_id="s260805010203000",
            run_id="g260805010203000", requested_duration_s=0.5)
    failure = getattr(exc_info.value, "failure_report", None)
    assert failure is not None
    assert failure["verdict"] == "SHAKEDOWN_FAIL"
    assert failure["publication_error"]


def test_help_and_future_command_are_resource_free(capsys, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("resource factory called by --help")
    monkeypatch.setattr(ground_shakedown.shutil, "which", forbidden)
    with pytest.raises(SystemExit) as exc_info:
        ground_shakedown.main(["--help"])
    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--run-kind" in output
