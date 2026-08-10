"""Tests for the separate alignment and causal-sync report boundaries."""

from __future__ import annotations

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "tools", "camera_toolchain"
    ),
)

import capture_sync_run
from v1_twin.v1_twin_causal_sync import build_causal_sync_report


def _build_report(causal_sync=None):
    return capture_sync_run.build_sync_report(
        host="127.0.0.1",
        duration_s=1.0,
        run_id="run-001",
        camera_mode={"width": 1920, "height": 1080},
        actions={
            "stop_sent": True,
            "stop_confirmed": True,
            "socket_closed": True,
            "camera_released": True,
            "reader_joined": True,
        },
        outcome="ok",
        n_poses=20,
        n_telemetry=20,
        clock={"a": 1_000_000.0, "b": 0.0, "n_samples": 20},
        residuals={"rms_ns": 0.0, "max_ns": 0.0},
        sync={
            "coverage": 1.0,
            "p95_time_diff_ns": 1.0,
            "tolerance_ns": 33_333_333,
            "n_sync_frames": 20,
            "common_interval_start_ns": 0.0,
            "common_interval_end_ns": 1_000_000_000.0,
            "common_interval_duration_ns": 1_000_000_000.0,
            "n_common_poses": 20,
            "telemetry_interval_max_ns": 30_000_000.0,
            "telemetry_interval_p95_ns": 30_000_000.0,
            "n_telemetry_distinct": 20,
            "max_telemetry_reuse": 1,
            "verdict": "PASS",
            "gate_reason": "alignment passes",
        },
        diagnostics={"video_evidence": {"enabled": False}},
        causal_sync=causal_sync,
    )


def test_report_marks_missing_clock_exchanges_insufficient_evidence():
    report = build_causal_sync_report([])

    assert report["verdict"] == "INSUFFICIENT EVIDENCE"
    assert report["reason"] == "no clock exchange samples recorded"
    assert report["sample_count"] == 0


def test_coarse_alignment_pass_does_not_promote_causal_sync():
    report = _build_report(build_causal_sync_report([]))

    assert report["alignment_verdict"] == "PASS"
    assert report["causal_sync"]["verdict"] == "INSUFFICIENT EVIDENCE"
    assert report["verdict"] == "INSUFFICIENT EVIDENCE"
