"""Tests for the offline B3 camera-observation gate."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "camera_toolchain"))

from v1_twin.v1_twin_observation_gate import (  # noqa: E402
    B3ObservationGateConfig,
    evaluate_observation_gate,
    load_frame_index,
)


def _records(rows, *, elapsed_ns=20_000_000):
    records = []
    for frame_index, detected, timestamp_ns in rows:
        records.append(
            {
                "frame_index": frame_index,
                "read_ok": True,
                "pose_detected": detected,
                "t_pc_ns": timestamp_ns,
                "failure_reason": None if detected else "candidates_rejected",
                "detect_elapsed_ns": elapsed_ns,
            }
        )
    return records


def test_real_sync_run_reports_verified_failed_observation_gate():
    records = _records(
        [(0, True, 0), (1, False, 33_333_333), (2, True, 66_666_666)],
        elapsed_ns=40_000_000,
    )

    report = evaluate_observation_gate(
        records,
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
        capture_verdict="PASS",
        run_id="run-1",
    )

    assert report.evidence_status == "VERIFIED"
    assert report.verdict == "FAIL"
    assert report.camera_frame_count == 3
    assert report.pose_frame_count == 2
    assert report.detection_ratio == pytest.approx(2 / 3)
    assert "detection_ratio_below_threshold" in report.reasons
    assert "detector_processing_over_budget" in report.reasons


def test_real_sync_run_passes_declared_observation_thresholds():
    rows = [
        (index, index != 10, index * 33_333_333)
        for index in range(20)
    ]

    report = evaluate_observation_gate(
        _records(rows),
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
        capture_verdict="PASS",
        run_id="run-pass",
    )

    assert report.evidence_status == "VERIFIED"
    assert report.verdict == "PASS"
    assert report.detection_ratio == pytest.approx(0.95)
    assert report.max_pose_gap_frames == pytest.approx(2.0)
    assert report.processing_p95_ns == 20_000_000
    assert report.reasons == ()


def test_non_real_source_is_insufficient_evidence():
    report = evaluate_observation_gate(
        _records([(0, True, 0), (1, True, 33_333_333)]),
        source="SYNTHETIC",
        sync_gate_verdict="PASS",
        capture_verdict="PASS",
    )

    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.verdict == "INSUFFICIENT_EVIDENCE"
    assert report.reasons == ("source_not_real_sync",)


def test_failed_sync_gate_cannot_promote_observation_to_verified():
    report = evaluate_observation_gate(
        _records([(0, True, 0), (1, True, 33_333_333)]),
        source="REAL_SYNC",
        sync_gate_verdict="FAIL",
        capture_verdict="PASS",
    )

    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.verdict == "INSUFFICIENT_EVIDENCE"
    assert report.reasons == ("sync_gate_not_pass",)


def test_legacy_pose_present_is_supported_and_read_failures_are_excluded():
    records = [
        {
            "frame_index": 0,
            "read_ok": True,
            "pose_present": True,
            "t_pc_ns": 0,
            "detect_elapsed_ns": 10_000_000,
        },
        {
            "frame_index": 1,
            "read_ok": False,
            "pose_present": False,
            "t_pc_ns": 33_333_333,
            "failure_reason": "camera_read_failed",
            "detect_elapsed_ns": 0,
        },
        {
            "frame_index": 2,
            "read_ok": True,
            "pose_present": True,
            "t_pc_ns": 66_666_666,
            "detect_elapsed_ns": 10_000_000,
        },
    ]

    report = evaluate_observation_gate(
        records,
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
        capture_verdict="PASS",
    )

    assert report.camera_frame_count == 2
    assert report.read_failure_count == 1
    assert report.pose_frame_count == 2
    assert report.detection_ratio == pytest.approx(1.0)


def test_invalid_record_shape_fails_closed():
    with pytest.raises(ValueError, match="read_ok"):
        evaluate_observation_gate(
            [{"frame_index": 0}],
            source="REAL_SYNC",
            sync_gate_verdict="PASS",
            capture_verdict="PASS",
        )


def test_non_monotonic_detected_timestamps_fail_closed():
    with pytest.raises(ValueError, match="timestamp"):
        evaluate_observation_gate(
            _records([(0, True, 100), (1, True, 90)]),
            source="REAL_SYNC",
            sync_gate_verdict="PASS",
            capture_verdict="PASS",
        )


def test_report_serializes_thresholds_units_and_failure_counts():
    report = evaluate_observation_gate(
        _records([(0, True, 0), (1, True, 33_333_333)]),
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
        capture_verdict="PASS",
        run_id="run-json",
    )

    payload = report.to_dict()
    assert payload["run_id"] == "run-json"
    assert payload["config"]["expected_fps"] == 30.0
    assert payload["units"]["timestamp"] == "ns"
    assert payload["failure_counts"] == {}


def test_overall_capture_failure_blocks_observation_verification():
    report = evaluate_observation_gate(
        _records([(0, True, 0), (1, True, 33_333_333)]),
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
        capture_verdict="FAIL",
    )

    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.verdict == "INSUFFICIENT_EVIDENCE"
    assert report.reasons == ("capture_verdict_not_pass",)


def test_missing_capture_verdict_fails_closed():
    report = evaluate_observation_gate(
        _records([(0, True, 0), (1, True, 33_333_333)]),
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
    )

    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.reasons == ("capture_verdict_not_pass",)


def test_frame_index_gap_fails_closed():
    with pytest.raises(ValueError, match="contiguous"):
        evaluate_observation_gate(
            _records([(0, True, 0), (2, True, 33_333_333)]),
            source="REAL_SYNC",
            sync_gate_verdict="PASS",
            capture_verdict="PASS",
        )


def test_partial_detector_timing_is_insufficient_evidence():
    records = _records([(0, True, 0), (1, True, 33_333_333)])
    del records[1]["detect_elapsed_ns"]

    report = evaluate_observation_gate(
        records,
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
        capture_verdict="PASS",
    )

    assert report.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert report.reasons == ("detector_timing_incomplete",)
    assert report.processing_timing_missing_count == 1


def test_read_failure_with_null_timestamp_is_supported():
    records = [
        {
            "frame_index": 0,
            "read_ok": False,
            "pose_detected": False,
            "t_pc_ns": None,
            "failure_reason": "camera_read_failed",
        },
        _records([(1, True, 33_333_333)])[0],
        _records([(2, True, 66_666_666)])[0],
    ]

    report = evaluate_observation_gate(
        records,
        source="REAL_SYNC",
        sync_gate_verdict="PASS",
        capture_verdict="PASS",
    )

    assert report.read_failure_count == 1
    assert report.camera_frame_count == 2
    assert report.evidence_status == "VERIFIED"


def test_non_detected_readable_timestamp_must_be_monotonic():
    with pytest.raises(ValueError, match="readable frame timestamp"):
        evaluate_observation_gate(
            _records([(0, True, 100), (1, False, 90), (2, True, 200)]),
            source="REAL_SYNC",
            sync_gate_verdict="PASS",
            capture_verdict="PASS",
        )


def test_load_frame_index_reads_jsonl_and_rejects_malformed_rows(tmp_path):
    path = tmp_path / "frame_index.jsonl"
    path.write_text(
        json.dumps(_records([(0, True, 0)])[0]) + "\n",
        encoding="utf-8",
    )
    assert load_frame_index(path)[0]["frame_index"] == 0

    bad = tmp_path / "bad.jsonl"
    bad.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_frame_index(bad)


def test_cli_writes_derived_report_and_refuses_overwrite(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "frame_index.jsonl").write_text(
        "\n".join(json.dumps(row) for row in _records(
            [(0, True, 0), (1, True, 33_333_333)]
        )) + "\n",
        encoding="utf-8",
    )
    (session / "sync_report.json").write_text(
        json.dumps({
            "run_id": "run-cli",
            "sync_gate_verdict": "PASS",
            "verdict": "PASS",
        }),
        encoding="utf-8",
    )
    output = tmp_path / "derived" / "report.json"

    from analyze_b3_observation import main

    assert main(
        [
            "--session-dir",
            str(session),
            "--output",
            str(output),
            "--source",
            "SYNTHETIC",
        ]
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-cli"
    assert payload["input_artifacts"]["frame_index_sha256"]
    assert payload["verdict"] == "INSUFFICIENT_EVIDENCE"

    assert main(
        [
            "--session-dir",
            str(session),
            "--output",
            str(output),
            "--source",
            "REAL_SYNC",
        ]
    ) == 1


def test_cli_rejects_real_source_for_noncanonical_session(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "frame_index.jsonl").write_text(
        "\n".join(json.dumps(row) for row in _records(
            [(0, True, 0), (1, True, 33_333_333)]
        )) + "\n",
        encoding="utf-8",
    )
    (session / "sync_report.json").write_text(
        json.dumps({
            "run_id": "run-failed",
            "sync_gate_verdict": "PASS",
            "verdict": "FAIL",
        }),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"

    from analyze_b3_observation import main

    assert main(
        [
            "--session-dir",
            str(session),
            "--output",
            str(output),
            "--source",
            "REAL_SYNC",
        ]
    ) == 1
    assert not output.exists()


def test_frame_index_must_start_at_zero():
    with pytest.raises(ValueError, match="start at 0"):
        evaluate_observation_gate(
            _records([(1, True, 33_333_333), (2, True, 66_666_666)]),
            source="REAL_SYNC",
            sync_gate_verdict="PASS",
            capture_verdict="PASS",
        )


def test_config_rejects_invalid_screening_thresholds():
    with pytest.raises(ValueError, match="min_detection_ratio"):
        B3ObservationGateConfig(min_detection_ratio=1.1)
    with pytest.raises(ValueError, match="max_pose_gap_frames"):
        B3ObservationGateConfig(max_pose_gap_frames=0)
