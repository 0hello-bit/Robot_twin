"""Offline regression tests for quiet-window causal clock sampling."""

from __future__ import annotations

import os
import socket
import sys
import time

import pytest

from v1_twin.clock_event_identity import (
    CLOCK_DOMAIN_MCU_MONOTONIC_MS,
    CLOCK_DOMAIN_PC_MONOTONIC_NS,
    EVENT_PC_Q_SENT,
    EVENT_PC_T_RECEIVED,
    EVENT_Q_PARSE_DONE,
    EVENT_Q_UART_RX_ISR,
    EVENT_T_PAYLOAD_GENERATED,
    EVENT_T_TRANSACTION_STARTED,
    ClockExchangeIdentity,
)

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "tools", "camera_toolchain"
    ),
)

import capture_sync_run
from real_world.runtime_protocol import frame as protocol_frame


def _causal_record(sequence, tick_ms, sample_role="formal", included_in_fit=True):
    identity = ClockExchangeIdentity(transport="tcp", sequence=sequence)
    pc_tx_ns = tick_ms * 1_000_000
    return {
        "capture_id": "local",
        "observation_id": identity.exchange_id,
        "sequence": sequence,
        "pc_tx_ns": pc_tx_ns,
        "pc_tx_event_id": identity.event(EVENT_PC_Q_SENT),
        "pc_tx_event_kind": EVENT_PC_Q_SENT,
        "pc_tx_event_clock_domain": CLOCK_DOMAIN_PC_MONOTONIC_NS,
        "pc_tx_event_validity": "observed_boundary",
        "pc_tx_event_uncertainty_ns": 1_000_000,
        "pc_tx_event_observed_ns": pc_tx_ns,
        "pc_tx_event_data_age_ns": 0,
        "q_event_id": identity.event(EVENT_Q_UART_RX_ISR),
        "q_event_tick_ms": tick_ms,
        "q_event_observed_tick_ms": tick_ms,
        "q_event_data_age_ms": 0,
        "q_event_kind": EVENT_Q_UART_RX_ISR,
        "q_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "q_event_validity": "observed_boundary",
        "q_event_uncertainty_ns": 1_000_000,
        "q_parse_event_id": identity.event(EVENT_Q_PARSE_DONE),
        "q_parse_causal_parent_event_id": identity.event(EVENT_Q_UART_RX_ISR),
        "q_parse_done_tick_ms": tick_ms + 1,
        "q_parse_event_kind": EVENT_Q_PARSE_DONE,
        "q_parse_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "q_parse_event_validity": "reported_boundary",
        "q_parse_event_uncertainty_ns": 1_000_000,
        "q_parse_event_observed_tick_ms": None,
        "q_parse_event_data_age_ms": None,
        "q_parse_role": "diagnostic_only",
        "t_event_id": identity.event(EVENT_T_TRANSACTION_STARTED),
        "t_event_tick_ms": tick_ms + 2,
        "t_event_observed_tick_ms": tick_ms + 2,
        "t_event_data_age_ms": 0,
        "t_event_kind": EVENT_T_TRANSACTION_STARTED,
        "t_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "t_event_validity": "observed_boundary",
        "t_event_uncertainty_ns": 1_000_000,
        "t_payload_event_id": identity.event(EVENT_T_PAYLOAD_GENERATED),
        "t_payload_causal_parent_event_id": identity.event(
            EVENT_T_TRANSACTION_STARTED
        ),
        "t_payload_generated_tick_ms": tick_ms + 3,
        "t_payload_event_kind": EVENT_T_PAYLOAD_GENERATED,
        "t_payload_event_clock_domain": CLOCK_DOMAIN_MCU_MONOTONIC_MS,
        "t_payload_event_validity": "reported_boundary",
        "t_payload_event_uncertainty_ns": 1_000_000,
        "t_payload_event_observed_tick_ms": None,
        "t_payload_event_data_age_ms": None,
        "t_payload_role": "diagnostic_only",
        "pc_rx_ns": pc_tx_ns + 10_000_000,
        "pc_rx_event_id": identity.event(EVENT_PC_T_RECEIVED),
        "pc_rx_event_kind": EVENT_PC_T_RECEIVED,
        "pc_rx_event_clock_domain": CLOCK_DOMAIN_PC_MONOTONIC_NS,
        "pc_rx_event_validity": "observed_boundary",
        "pc_rx_event_uncertainty_ns": 1_000_000,
        "pc_rx_event_observed_ns": pc_tx_ns + 10_000_000,
        "pc_rx_event_data_age_ns": 0,
        "timestamp_schema_version": 2,
        "sample_role": sample_role,
        "included_in_fit": included_in_fit,
    }


def _encode_telemetry_frame(tick_ms=100):
    payload = bytearray(24)
    payload[16:20] = int(tick_ms).to_bytes(4, "little")
    checksum = 0x01 ^ len(payload)
    for value in payload:
        checksum ^= value
    return bytes([0xAA, 0x55, 0x01, len(payload)]) + bytes(payload) + bytes([checksum])


def _status(campaign, run_id, state, reason, tick_ms=0):
    return protocol_frame(
        "S,{0},{1},{2},{3},{4}".format(
            campaign, run_id, state, reason, int(tick_ms)
        )
    ).encode("ascii")


class QuietClockSocket:
    """Fake socket that answers Q immediately and records command order."""

    def __init__(self):
        self.sent = []
        self.pending = []
        self.start_seen = False
        self.closed = False
        self.telemetry_sent = False

    def settimeout(self, _timeout):
        pass

    def sendall(self, data):
        data = bytes(data)
        self.sent.append(data)
        text = data.decode("ascii")
        if text.startswith("Q,"):
            sequence = int(text.split(",")[1])
            rx_tick = 1_000 + sequence
            self.pending.append(
                protocol_frame(
                    "T,{0},{1},{2},{3},{4},2".format(
                        sequence, rx_tick, rx_tick + 1,
                        rx_tick + 2, rx_tick + 3,
                    )
                ).encode("ascii")
            )
        elif ",START," in text:
            fields = text.strip().split(",")
            self.start_seen = True
            self.pending.append(_status(fields[1], fields[2], "RUNNING", "START"))
            self.pending.append(_encode_telemetry_frame())
        elif ",STOP," in text:
            fields = text.strip().split(",")
            self.pending.append(_status(fields[1], fields[2], "STOPPED", "STOP"))

    def recv(self, _size):
        if self.pending:
            return self.pending.pop(0)
        if not self.start_seen:
            raise socket.timeout()
        if not self.telemetry_sent:
            self.telemetry_sent = True
            return _encode_telemetry_frame(101)
        if self.closed:
            return b""
        time.sleep(0.001)
        raise socket.timeout()

    def close(self):
        self.closed = True


class DropFirstClockReplySocket(QuietClockSocket):
    """Drop one Q reply while preserving the rest of the fake session."""

    def __init__(self):
        super().__init__()
        self.drop_next_q_reply = True

    def sendall(self, data):
        data = bytes(data)
        if self.drop_next_q_reply and data.decode("ascii").startswith("Q,"):
            self.drop_next_q_reply = False
            self.sent.append(data)
            return
        super().sendall(data)


class BackToBackClockReplySocket(QuietClockSocket):
    """Observe when a Q probe would overlap the firmware response slot."""

    def __init__(self, minimum_gap_s):
        super().__init__()
        self.minimum_gap_s = float(minimum_gap_s)
        self.q_send_times = []
        self.too_soon_sequences = []

    def sendall(self, data):
        data = bytes(data)
        text = data.decode("ascii")
        if text.startswith("Q,"):
            sequence = int(text.split(",")[1])
            now = time.monotonic()
            if self.q_send_times and (
                now - self.q_send_times[-1][1] < self.minimum_gap_s
            ):
                self.too_soon_sequences.append(sequence)
            self.q_send_times.append((sequence, now))
        super().sendall(data)


class OneFrameCamera:
    def read(self):
        return False, None

    def release(self):
        pass


class NoopTracker:
    def track(self, _frame, t_pc_ns=None):
        return None


def test_causal_clock_probes_stay_outside_motion_window(monkeypatch):
    monkeypatch.setattr(capture_sync_run, "CLOCK_PREFLIGHT_EXCHANGES", 2)
    monkeypatch.setattr(capture_sync_run, "CLOCK_POSTFLIGHT_EXCHANGES", 2)
    monkeypatch.setattr(capture_sync_run, "CLOCK_QUIET_PROBE_TIMEOUT_S", 0.5)

    sock = QuietClockSocket()
    diagnostics = {}
    _telemetry, _poses, actions, outcome = capture_sync_run.run_sync_capture_session(
        sock,
        OneFrameCamera(),
        NoopTracker(),
        "run-quiet-clock",
        0.01,
        0.5,
        diagnostics=diagnostics,
    )

    assert outcome == "ok"
    assert actions["start_sent"] is True
    assert actions["stop_confirmed"] is True

    phase = "before_start"
    for raw in sock.sent:
        text = raw.decode("ascii")
        if ",START," in text:
            phase = "during_run"
        elif ",STOP," in text:
            phase = "after_stop"
        elif text.startswith("Q,"):
            assert phase in {"before_start", "after_stop"}

    records = diagnostics["clock_exchanges"]["records"]
    assert [record["phase"] for record in records] == [
        "pre_start_quiet",
        "pre_start_quiet",
        "pre_start_quiet",
        "post_stop_quiet",
        "post_stop_quiet",
        "post_stop_quiet",
    ]
    assert [record["sample_role"] for record in records] == [
        "arm_probe", "formal", "formal", "arm_probe", "formal", "formal",
    ]
    assert [record["fit_requested"] for record in records] == [
        False, True, True, False, True, True,
    ]
    assert [record["included_in_fit"] for record in records] == [
        False, False, False, False, False, False,
    ]
    assert [record["fit_exclusion_reason"] for record in records] == [
        "sample_role_excluded",
        "uncertainty_unverified",
        "uncertainty_unverified",
        "sample_role_excluded",
        "uncertainty_unverified",
        "uncertainty_unverified",
    ]


def test_clock_exchange_uses_recv_boundary_timestamp_in_session(monkeypatch):
    monkeypatch.setattr(capture_sync_run, "CLOCK_PREFLIGHT_EXCHANGES", 1)
    monkeypatch.setattr(capture_sync_run, "CLOCK_POSTFLIGHT_EXCHANGES", 0)
    monkeypatch.setattr(capture_sync_run, "CLOCK_QUIET_PROBE_TIMEOUT_S", 0.5)

    clock_value = {"value": 0}

    def fake_clock():
        clock_value["value"] += 100
        return clock_value["value"]

    monkeypatch.setattr(capture_sync_run, "capture_pc_clock_ns", fake_clock)
    sock = QuietClockSocket()
    diagnostics = {}

    _telemetry, _poses, _actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock,
            OneFrameCamera(),
            NoopTracker(),
            "run-clock-rx",
            0.01,
            0.5,
            diagnostics=diagnostics,
        )
    )

    assert outcome == "ok"
    record = diagnostics["clock_exchanges"]["records"][0]
    t_reply = next(
        event for event in diagnostics["raw_io"]["events"]
        if event["dir"] == "RX"
        and bytes.fromhex(event["bytes_hex"]).startswith(b"T,")
    )
    assert record["pc_rx_ns"] == t_reply["pc_recv_ns"]


def test_quiet_clock_retries_one_lost_probe_with_a_new_sequence(monkeypatch):
    monkeypatch.setattr(capture_sync_run, "CLOCK_PREFLIGHT_EXCHANGES", 1)
    monkeypatch.setattr(capture_sync_run, "CLOCK_POSTFLIGHT_EXCHANGES", 0)
    monkeypatch.setattr(capture_sync_run, "CLOCK_QUIET_PROBE_TIMEOUT_S", 0.01)

    sock = DropFirstClockReplySocket()
    diagnostics = {}
    _telemetry, _poses, actions, outcome = capture_sync_run.run_sync_capture_session(
        sock,
        OneFrameCamera(),
        NoopTracker(),
        "run-clock-retry",
        0.01,
        0.5,
        diagnostics=diagnostics,
    )

    assert outcome == "ok"
    assert actions["start_sent"] is True
    assert diagnostics["clock_sync_sampling"]["pre_start_retries"] == 1
    assert [record["sequence"] for record in diagnostics["clock_exchanges"]["records"]] == [2, 3]
    assert len(diagnostics["clock_sync_parse_errors"]) == 1


def test_quiet_clock_sampler_spaces_probes_for_firmware_response_slot(monkeypatch):
    monkeypatch.setattr(capture_sync_run, "CLOCK_PREFLIGHT_EXCHANGES", 2)
    monkeypatch.setattr(capture_sync_run, "CLOCK_POSTFLIGHT_EXCHANGES", 0)
    monkeypatch.setattr(capture_sync_run, "CLOCK_PROBE_PERIOD_S", 0.25)
    monkeypatch.setattr(capture_sync_run, "CLOCK_QUIET_PROBE_TIMEOUT_S", 0.2)

    sock = BackToBackClockReplySocket(minimum_gap_s=0.2)
    diagnostics = {}
    _telemetry, _poses, _actions, outcome = (
        capture_sync_run.run_sync_capture_session(
            sock,
            OneFrameCamera(),
            NoopTracker(),
            "run-clock-gap",
            0.01,
            0.5,
            diagnostics=diagnostics,
        )
    )

    assert sock.too_soon_sequences == []
    assert outcome == "ok"


def test_arm_probe_is_retained_but_excluded_from_causal_fit():
    records = [
        _causal_record(1, 100, "arm_probe", False),
        _causal_record(2, 120),
        _causal_record(3, 140),
    ]

    report = capture_sync_run.build_causal_sync_report(records)

    assert report["record_count"] == 3
    assert report["excluded_record_count"] == 1
    assert report["sample_count"] == 2


def test_clock_probe_rejects_unknown_sample_role_at_collection_boundary():
    collector = capture_sync_run.ClockExchangeCollector()

    with pytest.raises(ValueError, match="sample role"):
        collector.begin_probe(
            1,
            1_000,
            sample_role="legacy",
            included_in_fit=False,
        )


def test_clock_probe_rejects_inconsistent_sample_role_at_collection_boundary():
    collector = capture_sync_run.ClockExchangeCollector()

    with pytest.raises(ValueError, match="included_in_fit"):
        collector.begin_probe(
            1,
            1_000,
            sample_role="arm_probe",
            included_in_fit=True,
        )


def _formal_records(count=8):
    records = []
    for sequence in range(1, count + 1):
        tick_ms = 1_000 + sequence * 10
        records.append(_causal_record(sequence, tick_ms))
    return records


def test_unclassified_legacy_record_fails_closed_instead_of_entering_fit():
    records = _formal_records()
    legacy_record = dict(records[0])
    legacy_record.pop("sample_role")
    legacy_record.pop("included_in_fit")
    records.append(legacy_record | {"sequence": 99})

    report = capture_sync_run.build_causal_sync_report(records)

    assert report["verdict"] == "INSUFFICIENT EVIDENCE"
    assert report["sample_count"] == 0
    assert report["unclassified_record_count"] == 1
    assert report["fit"] is None


def test_sample_role_and_fit_inclusion_must_agree():
    records = _formal_records()
    records[0]["sample_role"] = "arm_probe"

    report = capture_sync_run.build_causal_sync_report(records)

    assert report["verdict"] == "INSUFFICIENT EVIDENCE"
    assert report["sample_count"] == 0
    assert "sample_role" in report["reason"]


def test_fail_closed_causal_reports_keep_a_uniform_schema():
    excluded = _formal_records(1)[0]
    excluded["sample_role"] = "arm_probe"
    excluded["included_in_fit"] = False

    for report in (
        capture_sync_run.build_causal_sync_report([]),
        capture_sync_run.build_causal_sync_report([excluded]),
    ):
        assert report["verdict"] == "INSUFFICIENT EVIDENCE"
        assert "record_count" in report
        assert "excluded_record_count" in report
        assert "sample_count" in report
        assert "policy" in report
        assert "fit" in report
        assert "exchange_fields" in report
