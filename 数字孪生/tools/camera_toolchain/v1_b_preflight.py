"""No-device preflight for the V1-B offline contract.

The preflight is intentionally narrower than the capture tool.  It checks
imports, syntax, paths, the capture entry point's ``--help`` path, and a
temporary synthetic campaign.  It never opens a camera, socket, serial port,
debugger, or sends a control command.
"""

from __future__ import annotations

import argparse
import compileall
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
DEFAULT_WORKSPACE_ROOT = HERE.parents[1]
DEFAULT_PROFILE = (
    DEFAULT_WORKSPACE_ROOT
    / "simulation"
    / "digital_twin"
    / "data"
    / "product"
    / "acceptance_profiles"
    / "v1b_first_campaign_v1.json"
)


def _configure_import_path(workspace_root: Path) -> None:
    digital_twin_dir = workspace_root / "simulation" / "digital_twin"
    camera_toolchain_dir = workspace_root / "tools" / "camera_toolchain"
    for path in (digital_twin_dir, camera_toolchain_dir):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_paths(workspace_root: Path, profile_path: Path) -> list[str]:
    expected = (
        workspace_root / "simulation" / "digital_twin" / "v1_twin",
        workspace_root / "simulation" / "digital_twin" / "tests",
        workspace_root / "tools" / "camera_toolchain" / "capture_sync_run.py",
        workspace_root / "tools" / "camera_toolchain" / "camera_common.py",
        profile_path,
    )
    return [f"missing path: {path}" for path in expected if not path.exists()]


def _check_imports(workspace_root: Path) -> list[str]:
    _configure_import_path(workspace_root)
    modules = (
        "v1_twin.v1_twin_schema",
        "v1_twin.v1_twin_capture",
        "v1_twin.v1_twin_calibration_set",
        "v1_twin.v1_twin_identification",
        "v1_twin.v1_twin_model_registry",
        "v1_twin.v1_twin_validator",
        "v1_twin.v1_twin_campaign",
    )
    errors = []
    for module_name in modules:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # Keep all preflight failures in the report.
            errors.append(f"import failed: {module_name}: {exc}")
    return errors


def _check_syntax(workspace_root: Path) -> list[str]:
    errors = []
    for relative in ("simulation/digital_twin", "tools"):
        path = workspace_root / relative
        if not compileall.compile_dir(str(path), quiet=1):
            errors.append(f"syntax check failed: {path}")
    return errors


def _check_capture_help(workspace_root: Path) -> list[str]:
    capture = workspace_root / "tools" / "camera_toolchain" / "capture_sync_run.py"
    try:
        result = subprocess.run(
            [sys.executable, str(capture), "--help"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"capture --help check failed to execute: {exc}"]
    if result.returncode != 0:
        return [f"capture --help returned {result.returncode}: {result.stderr.strip()}"]
    if "--host" not in result.stdout or "--duration" not in result.stdout:
        return ["capture --help output is incomplete"]
    return []


def _check_output_directory_isolation() -> list[str]:
    try:
        from v1_twin.v1_twin_capture import CaptureConfigError, resolve_run_output_dir
    except Exception as exc:
        return [f"output directory isolation check import failed: {exc}"]

    try:
        with tempfile.TemporaryDirectory(prefix="v1b-output-isolation-") as temp_dir:
            resolve_run_output_dir(temp_dir, "preflight-isolation", ())
            try:
                resolve_run_output_dir(temp_dir, "preflight-isolation", ())
            except CaptureConfigError:
                return []
    except Exception as exc:
        return [f"output directory isolation check failed: {exc}"]
    return ["output directory isolation check did not reject an existing run directory"]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _synthetic_campaign(profile_path: Path, root: Path):
    from v1_twin.v1_twin_campaign import (
        CAMPAIGN_SCHEMA_VERSION,
        DEFAULT_UNIT_CONTRACT,
        V1BCampaignManifest,
        build_raw_file_manifest,
        load_acceptance_profile,
        validate_campaign,
    )
    from v1_twin.v1_twin_schema import V1Pose, V1TelemetryFrame

    profile = load_acceptance_profile(profile_path)
    runs_root = root / "runs"
    runs_root.mkdir()
    runs = []
    calibration_ids = []
    holdout_ids = []
    for index in range(5):
        is_calibration = index < 3
        run_id = f"preflight-{index + 1}"
        partition = "calibration" if is_calibration else "holdout"
        run_type = "CALIBRATION" if is_calibration else "HOLDOUT"
        profile_id = "nominal-command-260-380" if is_calibration else "target-command-480-680"
        start_ns = (index + 1) * 1_000_000_000
        run_dir = runs_root / run_id
        run_dir.mkdir()
        _write_jsonl(
            run_dir / "pose.jsonl",
            [
                V1Pose(0.0, 0.0, 0.0, 1.0, start_ns).to_dict(),
                V1Pose(10.0, 0.0, 0.0, 1.0, start_ns + 100_000_000).to_dict(),
            ],
        )
        _write_jsonl(
            run_dir / "telemetry.jsonl",
            [
                V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (260, 260, 260, 260), 1, start_ns, 0.0).to_dict(),
                V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (300, 300, 300, 300), 101, start_ns + 100_000_000, 0.0).to_dict(),
            ],
        )
        (run_dir / "sync_report.json").write_text(
            json.dumps({"run_id": run_id, "verdict": "OFFLINE_FIXTURE"}, sort_keys=True),
            encoding="utf-8",
        )
        raw_files = build_raw_file_manifest(
            run_dir,
            {"pose": "pose.jsonl", "telemetry": "telemetry.jsonl", "sync_report": "sync_report.json"},
        )
        if is_calibration:
            calibration_ids.append(run_id)
        else:
            holdout_ids.append(run_id)
        runs.append(
            {
                "schema_version": CAMPAIGN_SCHEMA_VERSION,
                "run_id": run_id,
                "run_type": run_type,
                "dataset_partition": partition,
                "data_origin": "SYNTHETIC_TEST",
                "robot_id": "preflight-fixture",
                "track_id": "track-fixture",
                "track_map_version": "track-map-fixture-v1",
                "firmware_sha256": hashlib.sha256(b"synthetic firmware").hexdigest(),
                "controller_version": "runtime-pid-v1-fixture",
                "input_profile_id": profile_id,
                "camera_config_hash": hashlib.sha256(b"synthetic camera config").hexdigest(),
                "calibration_set_id": "cal-set-1" if is_calibration else None,
                "holdout_set_id": "holdout-set-1" if not is_calibration else None,
                "started_at_utc": "2026-08-05T00:00:00Z",
                "duration_s": 0.1,
                "authorization_reference": "offline-preflight-only",
                "sample_interval_pc_ns": {
                    "start_pc_ns": start_ns,
                    "end_pc_ns": start_ns + 100_000_000,
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
        )
    payload = {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": "v1b-preflight-fixture",
        "acceptance_profile_id": profile.profile_id,
        "acceptance_profile_sha256": _sha256(profile_path),
        "declared_before_capture": True,
        "created_at_utc": "2026-08-05T00:00:00Z",
        "calibration_set_id": "cal-set-1",
        "holdout_set_id": "holdout-set-1",
        "calibration_run_ids": calibration_ids,
        "holdout_run_ids": holdout_ids,
        "runs": runs,
        "status": "OFFLINE_FIXTURE",
    }
    campaign = V1BCampaignManifest.from_dict(payload)
    return validate_campaign(
        campaign,
        runs_root,
        profile=profile,
        profile_sha256=_sha256(profile_path),
    )


def run_preflight(
    *,
    workspace_root: Path,
    profile_path: Path,
    fake_check: bool,
    campaign_path: Path | None,
    runs_root: Path | None,
) -> tuple[int, dict[str, object]]:
    workspace_root = workspace_root.resolve()
    profile_path = profile_path.resolve()
    errors = _check_paths(workspace_root, profile_path)
    if not errors:
        errors.extend(_check_imports(workspace_root))
        errors.extend(_check_syntax(workspace_root))
        errors.extend(_check_capture_help(workspace_root))
        errors.extend(_check_output_directory_isolation())

    report = None
    if not errors and fake_check:
        with tempfile.TemporaryDirectory(prefix="v1b-preflight-") as temp_dir:
            report = _synthetic_campaign(profile_path, Path(temp_dir))
    if not errors and campaign_path is not None:
        try:
            from v1_twin.v1_twin_campaign import (
                V1BCampaignManifest,
                load_acceptance_profile,
                validate_campaign,
            )

            profile = load_acceptance_profile(profile_path)
            data = json.loads(campaign_path.read_text(encoding="utf-8"))
            campaign = V1BCampaignManifest.from_dict(data)
            if runs_root is None:
                errors.append("--runs-root is required with --campaign-manifest")
            else:
                report = validate_campaign(
                    campaign,
                    runs_root,
                    profile=profile,
                    profile_sha256=_sha256(profile_path),
                )
        except Exception as exc:  # The report remains explicitly offline.
            errors.append(f"campaign preflight failed: {exc}")

    if report is not None and report.errors:
        errors.extend(report.errors)
    result = {
        "status": "OFFLINE_PREFLIGHT_PASS" if not errors else "OFFLINE_PREFLIGHT_REJECT",
        "hardware_accessed": False,
        "errors": errors,
        "contract_status": None if report is None else report.status,
        "evidence_level": None if report is None else report.evidence_level,
    }
    return (0 if not errors else 1), result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline-only V1-B preflight; it does not access hardware or run capture."
    )
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--campaign-manifest", type=Path)
    parser.add_argument("--runs-root", type=Path)
    parser.add_argument("--fake-check", action="store_true", help="run the temporary synthetic contract check")
    args = parser.parse_args(argv)
    code, result = run_preflight(
        workspace_root=args.workspace_root,
        profile_path=args.profile,
        fake_check=args.fake_check,
        campaign_path=args.campaign_manifest,
        runs_root=args.runs_root,
    )
    print(f"status={result['status']}")
    print(f"hardware_accessed={str(result['hardware_accessed']).lower()}")
    print(f"contract_status={result['contract_status']}")
    print(f"evidence_level={result['evidence_level']}")
    for error in result["errors"]:
        print(f"error={error}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
