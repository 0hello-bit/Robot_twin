"""Offline B1 contract tests for V1-B manifests and preflight.

These fixtures are explicitly synthetic.  They prove that the contract can
reject data leakage and malformed evidence; they are not real calibration
evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from v1_twin.v1_twin_schema import V1Pose, V1TelemetryFrame

try:
    from v1_twin.v1_twin_campaign import (
        CAMPAIGN_SCHEMA_VERSION,
        DEFAULT_UNIT_CONTRACT,
        V1BAcceptanceProfile,
        V1BCampaignManifest,
        V1BManifestError,
        build_raw_file_manifest,
        load_acceptance_profile,
        make_v1_b_run_id,
        validate_campaign,
    )
except ImportError as exc:  # Keep the initial RED state as a test failure.
    _CAMPAIGN_IMPORT_ERROR = exc
else:
    _CAMPAIGN_IMPORT_ERROR = None


ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = (
    ROOT
    / "simulation"
    / "digital_twin"
    / "data"
    / "product"
    / "acceptance_profiles"
    / "v1b_first_campaign_v1.json"
)
PREFLIGHT = ROOT / "tools" / "camera_toolchain" / "v1_b_preflight.py"


def _require_campaign_module() -> None:
    assert _CAMPAIGN_IMPORT_ERROR is None, str(_CAMPAIGN_IMPORT_ERROR)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_sha256() -> str:
    return hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest()


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _run_manifest(
    runs_root: Path,
    run_id: str,
    partition: str,
    start_ns: int,
    profile_id: str,
    *,
    run_type: str | None = None,
) -> dict:
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True)
    poses = [
        V1Pose(0.0, 0.0, 0.0, 1.0, start_ns).to_dict(),
        V1Pose(10.0, 0.0, 0.0, 1.0, start_ns + 100_000_000).to_dict(),
    ]
    telemetry = [
        V1TelemetryFrame(
            (0, 0, 0, 0),
            0.0,
            0.0,
            (260, 260, 260, 260),
            1,
            start_ns,
            0.0,
        ).to_dict(),
        V1TelemetryFrame(
            (0, 0, 0, 0),
            0.0,
            0.0,
            (300, 300, 300, 300),
            101,
            start_ns + 100_000_000,
            0.0,
        ).to_dict(),
    ]
    _write_jsonl(run_dir / "pose.jsonl", poses)
    _write_jsonl(run_dir / "telemetry.jsonl", telemetry)
    (run_dir / "sync_report.json").write_text(
        json.dumps({"run_id": run_id, "verdict": "OFFLINE_FIXTURE"}, sort_keys=True),
        encoding="utf-8",
    )
    raw_files = build_raw_file_manifest(
        run_dir,
        {
            "pose": "pose.jsonl",
            "telemetry": "telemetry.jsonl",
            "sync_report": "sync_report.json",
        },
    )
    return {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "run_id": run_id,
        "run_type": run_type or ("CALIBRATION" if partition == "calibration" else "HOLDOUT"),
        "dataset_partition": partition,
        "data_origin": "SYNTHETIC_TEST",
        "robot_id": "synthetic-line-follower",
        "track_id": "track-fixture",
        "track_map_version": "track-map-fixture-v1",
        "firmware_sha256": _sha("synthetic firmware"),
        "controller_version": "runtime-pid-v1-fixture",
        "input_profile_id": profile_id,
        "camera_config_hash": _sha("synthetic camera config"),
        "calibration_set_id": "cal-set-1" if partition == "calibration" else None,
        "holdout_set_id": "holdout-set-1" if partition == "holdout" else None,
        "started_at_utc": "2026-08-05T00:00:00Z",
        "duration_s": 0.1,
        "authorization_reference": "offline-test-only",
        "sample_interval_pc_ns": {
            "start": start_ns,
            "end": start_ns + 100_000_000,
        },
        "covered_track_segments": [
            "STRAIGHT",
            "ORDINARY_CURVE",
            "TARGET_HIGH_SPEED_ACUTE_CURVE",
        ],
        "unit_contract": dict(DEFAULT_UNIT_CONTRACT),
        "raw_files": [item.to_dict() for item in raw_files],
        "status": "OFFLINE_FIXTURE",
    }


def _campaign_payload(tmp_path: Path) -> tuple[dict, Path]:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    runs = []
    for index in range(3):
        runs.append(
            _run_manifest(
                runs_root,
                f"cal-{index + 1}",
                "calibration",
                index * 1_000_000_000,
                "nominal-command-260-380",
            )
        )
    for index in range(2):
        runs.append(
            _run_manifest(
                runs_root,
                f"hold-{index + 1}",
                "holdout",
                (index + 10) * 1_000_000_000,
                "target-command-480-680",
            )
        )
    return (
        {
            "schema_version": CAMPAIGN_SCHEMA_VERSION,
            "campaign_id": "v1b-synthetic-campaign",
            "acceptance_profile_id": "v1b-first-campaign-20260805-v1",
            "acceptance_profile_sha256": (
                hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest()
                if PROFILE_PATH.exists()
                else _sha("profile fixture")
            ),
            "declared_before_capture": True,
            "created_at_utc": "2026-08-05T00:00:00Z",
            "calibration_set_id": "cal-set-1",
            "holdout_set_id": "holdout-set-1",
            "calibration_run_ids": ["cal-1", "cal-2", "cal-3"],
            "holdout_run_ids": ["hold-1", "hold-2"],
            "runs": runs,
            "status": "OFFLINE_FIXTURE",
        },
        runs_root,
    )


def test_valid_synthetic_campaign_is_accepted_but_marked_non_real(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)

    campaign = V1BCampaignManifest.from_dict(payload)
    profile = load_acceptance_profile(PROFILE_PATH)
    report = validate_campaign(
        campaign,
        runs_root,
        profile=profile,
        profile_sha256=_profile_sha256(),
    )

    assert report.status == "OFFLINE_CONTRACT_PASS", report.errors
    assert report.evidence_level == "SYNTHETIC_ONLY"
    assert report.hardware_accessed is False
    assert "READY" not in report.status
    assert "TWIN_USABLE" not in report.status


def test_missing_acceptance_profile_is_rejected(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    campaign = V1BCampaignManifest.from_dict(payload)

    report = validate_campaign(campaign, runs_root)

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("acceptance profile is required" in error for error in report.errors)


def test_missing_acceptance_profile_hash_is_rejected(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    campaign = V1BCampaignManifest.from_dict(payload)
    profile = load_acceptance_profile(PROFILE_PATH)

    report = validate_campaign(campaign, runs_root, profile=profile)

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("acceptance profile sha256 is required" in error for error in report.errors)


def test_acceptance_profile_hash_mismatch_is_rejected(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    campaign = V1BCampaignManifest.from_dict(payload)
    profile = load_acceptance_profile(PROFILE_PATH)

    report = validate_campaign(
        campaign,
        runs_root,
        profile=profile,
        profile_sha256=_sha("different profile bytes"),
    )

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("acceptance profile sha256 does not match" in error for error in report.errors)


def test_missing_run_id_is_rejected(tmp_path):
    _require_campaign_module()
    payload, _ = _campaign_payload(tmp_path)
    del payload["runs"][0]["run_id"]

    with pytest.raises(V1BManifestError, match="run_id"):
        V1BCampaignManifest.from_dict(payload)


def test_duplicate_run_ids_are_rejected(tmp_path):
    _require_campaign_module()
    payload, _ = _campaign_payload(tmp_path)
    payload["runs"][1]["run_id"] = payload["runs"][0]["run_id"]

    with pytest.raises(V1BManifestError, match="duplicate"):
        V1BCampaignManifest.from_dict(payload)


def test_calibration_and_holdout_run_id_overlap_is_rejected(tmp_path):
    _require_campaign_module()
    payload, _ = _campaign_payload(tmp_path)
    payload["holdout_run_ids"] = ["cal-1", "hold-2"]

    with pytest.raises(V1BManifestError, match="overlap"):
        V1BCampaignManifest.from_dict(payload)


def test_calibration_and_holdout_raw_hash_overlap_is_rejected(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    payload["runs"][3]["raw_files"][0]["sha256"] = payload["runs"][0]["raw_files"][0]["sha256"]

    campaign = V1BCampaignManifest.from_dict(payload)
    report = validate_campaign(campaign, runs_root, profile=load_acceptance_profile(PROFILE_PATH))

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("calibration/holdout raw hash overlap" in error for error in report.errors)


def test_calibration_and_holdout_sample_intervals_overlap_is_rejected(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    payload["runs"][3]["sample_interval_pc_ns"] = dict(payload["runs"][0]["sample_interval_pc_ns"])

    campaign = V1BCampaignManifest.from_dict(payload)
    report = validate_campaign(campaign, runs_root, profile=load_acceptance_profile(PROFILE_PATH))

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("sample interval overlap" in error for error in report.errors)


def test_missing_firmware_hash_is_rejected(tmp_path):
    _require_campaign_module()
    payload, _ = _campaign_payload(tmp_path)
    payload["runs"][0]["firmware_sha256"] = ""

    with pytest.raises(V1BManifestError, match="firmware_sha256"):
        V1BCampaignManifest.from_dict(payload)


def test_campaign_readiness_status_variant_is_rejected(tmp_path):
    _require_campaign_module()
    payload, _ = _campaign_payload(tmp_path)
    payload["status"] = "TWIN_USABLE_FOR_CANDIDATE_SCREENING"

    with pytest.raises(V1BManifestError, match="status"):
        V1BCampaignManifest.from_dict(payload)


def test_mixed_units_are_rejected(tmp_path):
    _require_campaign_module()
    payload, _ = _campaign_payload(tmp_path)
    payload["runs"][0]["unit_contract"]["pose_position"] = "cm"

    with pytest.raises(V1BManifestError, match="unit"):
        V1BCampaignManifest.from_dict(payload)


def test_non_monotonic_pose_timestamps_are_rejected(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    pose_path = runs_root / "cal-1" / "pose.jsonl"
    records = [json.loads(line) for line in pose_path.read_text("utf-8").splitlines()]
    records.reverse()
    _write_jsonl(pose_path, records)
    payload["runs"][0]["raw_files"] = [
        item.to_dict()
        for item in build_raw_file_manifest(
            runs_root / "cal-1",
            {"pose": "pose.jsonl", "telemetry": "telemetry.jsonl", "sync_report": "sync_report.json"},
        )
    ]

    campaign = V1BCampaignManifest.from_dict(payload)
    report = validate_campaign(campaign, runs_root, profile=load_acceptance_profile(PROFILE_PATH))

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("monotonic" in error for error in report.errors)


def test_telemetry_timestamp_outside_sample_interval_is_rejected(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    telemetry_path = runs_root / "hold-1" / "telemetry.jsonl"
    records = [json.loads(line) for line in telemetry_path.read_text("utf-8").splitlines()]
    records[1]["pc_recv_ns"] += 100_000_000
    _write_jsonl(telemetry_path, records)
    payload["runs"][3]["raw_files"] = [
        item.to_dict()
        for item in build_raw_file_manifest(
            runs_root / "hold-1",
            {"pose": "pose.jsonl", "telemetry": "telemetry.jsonl", "sync_report": "sync_report.json"},
        )
    ]

    campaign = V1BCampaignManifest.from_dict(payload)
    report = validate_campaign(campaign, runs_root, profile=load_acceptance_profile(PROFILE_PATH))

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("outside sample_interval_pc_ns" in error for error in report.errors)


def test_malformed_v1_raw_record_is_reported_as_rejection(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    pose_path = runs_root / "cal-1" / "pose.jsonl"
    records = [json.loads(line) for line in pose_path.read_text("utf-8").splitlines()]
    records[0]["x_mm"] = "not-a-number"
    _write_jsonl(pose_path, records)
    payload["runs"][0]["raw_files"] = [
        item.to_dict()
        for item in build_raw_file_manifest(
            runs_root / "cal-1",
            {"pose": "pose.jsonl", "telemetry": "telemetry.jsonl", "sync_report": "sync_report.json"},
        )
    ]

    campaign = V1BCampaignManifest.from_dict(payload)
    report = validate_campaign(campaign, runs_root, profile=load_acceptance_profile(PROFILE_PATH))

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("invalid raw stream" in error for error in report.errors)


def test_mixed_units_in_pose_stream_are_rejected(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    pose_path = runs_root / "cal-1" / "pose.jsonl"
    records = [json.loads(line) for line in pose_path.read_text("utf-8").splitlines()]
    records[0]["x_cm"] = records[0]["x_mm"] / 10.0
    _write_jsonl(pose_path, records)
    payload["runs"][0]["raw_files"] = [
        item.to_dict()
        for item in build_raw_file_manifest(
            runs_root / "cal-1",
            {"pose": "pose.jsonl", "telemetry": "telemetry.jsonl", "sync_report": "sync_report.json"},
        )
    ]

    campaign = V1BCampaignManifest.from_dict(payload)
    report = validate_campaign(campaign, runs_root, profile=load_acceptance_profile(PROFILE_PATH))

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("mixed units in pose stream" in error for error in report.errors)


def test_modified_raw_file_fails_hash_verification(tmp_path):
    _require_campaign_module()
    payload, runs_root = _campaign_payload(tmp_path)
    (runs_root / "hold-1" / "telemetry.jsonl").write_text("tampered\n", encoding="utf-8")

    campaign = V1BCampaignManifest.from_dict(payload)
    report = validate_campaign(campaign, runs_root, profile=load_acceptance_profile(PROFILE_PATH))

    assert report.status == "OFFLINE_CONTRACT_REJECT"
    assert any("sha256" in error for error in report.errors)


def test_profile_has_two_frozen_command_ranges_and_all_target_segments():
    _require_campaign_module()
    profile = load_acceptance_profile(PROFILE_PATH)

    assert isinstance(profile, V1BAcceptanceProfile)
    assert profile.declared_before_capture is True
    assert profile.thresholds_locked is True
    assert len(profile.input_profiles) >= 2
    required = set(profile.campaign.required_track_segments)
    assert required == {"STRAIGHT", "ORDINARY_CURVE", "TARGET_HIGH_SPEED_ACUTE_CURVE"}
    assert profile.sync_gate.common_coverage_min == pytest.approx(0.95)
    assert profile.sync_gate.p95_time_diff_ms_max == pytest.approx(33.3)
    assert profile.model_gate.lateral_error_p95_mm_max == pytest.approx(10.0)
    assert profile.model_gate.rms_relative_error_max == pytest.approx(0.15)
    assert profile.model_gate.max_relative_error_max == pytest.approx(0.15)
    assert profile.model_gate.completion_time_relative_error_max == pytest.approx(0.10)


def test_run_id_factory_has_safe_subsecond_entropy():
    _require_campaign_module()
    now = __import__("datetime").datetime(2026, 8, 5, tzinfo=__import__("datetime").timezone.utc)

    first = make_v1_b_run_id(prefix="sync", now=now, token="aaaa1111")
    second = make_v1_b_run_id(prefix="sync", now=now, token="bbbb2222")

    assert first != second
    assert first.startswith("sync-20260805T000000000000Z-")
    assert second.startswith("sync-20260805T000000000000Z-")


def test_preflight_help_is_offline_and_has_no_capture_side_effect(tmp_path):
    result = subprocess.run(
        [sys.executable, str(PREFLIGHT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0
    assert "offline" in result.stdout.lower()


def test_preflight_fake_check_never_reports_real_readiness(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(PREFLIGHT),
            "--workspace-root",
            str(ROOT),
            "--profile",
            str(PROFILE_PATH),
            "--fake-check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "OFFLINE_PREFLIGHT_PASS" in result.stdout
    assert "READY" not in result.stdout
    assert "TWIN_USABLE" not in result.stdout
    assert "hardware_accessed=false" in result.stdout


def test_preflight_default_workspace_root_is_the_formal_workspace():
    result = subprocess.run(
        [sys.executable, str(PREFLIGHT), "--fake-check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "OFFLINE_PREFLIGHT_PASS" in result.stdout


def test_preflight_checks_output_directory_isolation_offline():
    toolchain_root = ROOT / "tools" / "camera_toolchain"
    if str(toolchain_root) not in sys.path:
        sys.path.insert(0, str(toolchain_root))
    from v1_b_preflight import _check_output_directory_isolation

    assert _check_output_directory_isolation() == []
