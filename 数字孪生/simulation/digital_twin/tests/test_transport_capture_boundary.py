"""Focused tests for the B3 transport/capture evidence boundary."""

from __future__ import annotations

import os
import sys

import pytest

TOOLS = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "tools",
    "camera_toolchain",
)
SHAKEDOWN = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "tools",
    "shakedown_toolchain",
)
sys.path.insert(0, TOOLS)
sys.path.insert(0, SHAKEDOWN)

from real_world.runtime_protocol import RunStatus  # noqa: E402
from capture_sync_run import TelemetryCaptureBoundary  # noqa: E402
from transport_soak import RawIoLogger  # noqa: E402


def test_recv_batch_timestamp_is_shared_and_decode_time_is_diagnostic():
    boundary = TelemetryCaptureBoundary("sync", "run-1")
    boundary.observe_status(RunStatus("sync", "run-1", "RUNNING", "START", 10))

    boundary.begin_recv(1_000)
    first = boundary.observe_frame(tick_ms=30, decode_pc_ns=1_010)
    second = boundary.observe_frame(tick_ms=60, decode_pc_ns=1_020)

    assert first["phase"] == "inside_window"
    assert second["phase"] == "inside_window"
    assert first["arrival_pc_ns"] == second["arrival_pc_ns"] == 1_000
    assert first["decode_pc_ns"] == 1_010
    assert second["decode_pc_ns"] == 1_020


def test_pre_and_post_window_frames_are_boundary_evidence_only():
    boundary = TelemetryCaptureBoundary("sync", "run-1")

    boundary.begin_recv(100)
    before = boundary.observe_frame(tick_ms=1, decode_pc_ns=101)
    boundary.observe_status(RunStatus("sync", "run-1", "RUNNING", "START", 2))
    boundary.begin_recv(200)
    inside = boundary.observe_frame(tick_ms=30, decode_pc_ns=201)
    boundary.close_window("collection_deadline")
    boundary.begin_recv(300)
    after = boundary.observe_frame(tick_ms=60, decode_pc_ns=301)

    assert before["phase"] == "before_window"
    assert inside["phase"] == "inside_window"
    assert after["phase"] == "after_window"
    assert boundary.formal_count == 1
    assert boundary.boundary_count == 2
    assert [item["tick_ms"] for item in boundary.formal_records] == [30]
    assert [item["tick_ms"] for item in boundary.boundary_records] == [1, 60]


def test_matching_stop_status_closes_formal_window():
    boundary = TelemetryCaptureBoundary("sync", "run-1")
    boundary.observe_status(RunStatus("sync", "run-1", "RUNNING", "START", 10))
    assert boundary.phase == "inside_window"
    boundary.observe_status(RunStatus("sync", "run-1", "STOPPED", "STOP", 20))
    assert boundary.phase == "after_window"


def test_raw_io_can_record_one_arrival_timestamp_for_a_recv_batch():
    log = RawIoLogger(None)
    log.log_recv(b"abc", arrival_pc_ns=4_321)
    event = log.events()[0]
    assert event["arrival_pc_ns"] == 4_321
    assert event["pc_recv_ns"] == 4_321
