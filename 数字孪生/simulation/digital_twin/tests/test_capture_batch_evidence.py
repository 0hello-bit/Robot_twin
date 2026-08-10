"""Tests for raw TCP receive-batch evidence used by causal-sync diagnosis."""

from __future__ import annotations

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "tools", "camera_toolchain"
    ),
)

from capture_sync_run import TelemetryCaptureBoundary


def test_boundary_retains_receive_batch_identity_and_tick_span():
    boundary = TelemetryCaptureBoundary("sync", "run-001")
    boundary.begin_recv(1_000, recv_batch_bytes=62)
    boundary.observe_frame(tick_ms=10, decode_pc_ns=1_010)
    boundary.observe_frame(tick_ms=20, decode_pc_ns=1_020)
    boundary.begin_recv(2_000, recv_batch_bytes=31)
    boundary.observe_frame(tick_ms=50, decode_pc_ns=2_010)

    evidence = boundary.to_dict()

    assert [record["recv_batch_id"] for record in evidence["records"]] == [1, 1, 2]
    assert evidence["recv_batches"] == [
        {
            "recv_batch_id": 1,
            "recv_batch_bytes": 62,
            "frame_count": 2,
            "first_tick_ms": 10,
            "last_tick_ms": 20,
            "tick_span_ms": 10,
        },
        {
            "recv_batch_id": 2,
            "recv_batch_bytes": 31,
            "frame_count": 1,
            "first_tick_ms": 50,
            "last_tick_ms": 50,
            "tick_span_ms": 0,
        },
    ]
