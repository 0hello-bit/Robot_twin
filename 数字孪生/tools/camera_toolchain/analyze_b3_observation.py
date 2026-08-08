"""Replay a retained synchronized session through the offline B3 gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence


_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_DIGITAL_TWIN_ROOT = _WORKSPACE_ROOT / "simulation" / "digital_twin"
_CANONICAL_REAL_SESSION_ROOTS = (
    _DIGITAL_TWIN_ROOT / "logs",
    _DIGITAL_TWIN_ROOT / "data" / "product" / "sessions" / "v1_b",
)
if str(_DIGITAL_TWIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_DIGITAL_TWIN_ROOT))

from v1_twin.v1_twin_observation_gate import (  # noqa: E402
    B3ObservationGateConfig,
    evaluate_observation_gate,
    load_frame_index,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("unable to read JSON object {0}: {1}".format(path, exc)) from exc
    if not isinstance(value, dict):
        raise ValueError("JSON artifact must be an object: {0}".format(path))
    return value


def _is_canonical_real_session(path: Path) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root.resolve() or root.resolve() in resolved.parents
        for root in _CANONICAL_REAL_SESSION_ROOTS
    )


def _write_new_json(path: Path, payload: dict) -> None:
    if path.exists():
        raise ValueError("refusing to overwrite existing derived report: {0}".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ValueError("refusing to reuse temporary report path: {0}".format(temporary))
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        if temporary.exists():
            temporary.unlink()
        raise ValueError("unable to write derived report: {0}".format(exc)) from exc


def build_observation_report(
    session_dir: str | Path,
    *,
    source: str,
    config: Optional[B3ObservationGateConfig] = None,
) -> dict:
    """Build a derived report without changing any session artifact."""

    session = Path(session_dir)
    if source == "REAL_SYNC" and not _is_canonical_real_session(session):
        raise ValueError(
            "REAL_SYNC source requires a session under the canonical capture roots"
        )
    frame_index_path = session / "frame_index.jsonl"
    sync_report_path = session / "sync_report.json"
    if not session.is_dir():
        raise ValueError("session directory does not exist: {0}".format(session))
    if not frame_index_path.is_file():
        raise ValueError("missing frame index: {0}".format(frame_index_path))
    if not sync_report_path.is_file():
        raise ValueError("missing sync report: {0}".format(sync_report_path))

    sync_report = _load_json_object(sync_report_path)
    sync_gate_verdict = sync_report.get("sync_gate_verdict")
    capture_verdict = sync_report.get("verdict")
    run_id = sync_report.get("run_id")
    records = load_frame_index(frame_index_path)
    report = evaluate_observation_gate(
        records,
        source=source,
        sync_gate_verdict=sync_gate_verdict,
        capture_verdict=capture_verdict,
        run_id=run_id,
        config=config,
    ).to_dict()
    report["input_artifacts"] = {
        "frame_index_path": "frame_index.jsonl",
        "frame_index_sha256": _sha256_file(frame_index_path),
        "sync_report_path": "sync_report.json",
        "sync_report_sha256": _sha256_file(sync_report_path),
    }
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay a retained session through the offline B3 observation gate."
    )
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--source", choices=("REAL_SYNC", "SYNTHETIC"), required=True
    )
    args = parser.parse_args(argv)

    try:
        payload = build_observation_report(
            args.session_dir,
            source=args.source,
            config=B3ObservationGateConfig(),
        )
        _write_new_json(Path(args.output), payload)
    except (ValueError, OSError) as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        return 1

    print(
        "observation gate: {0} ({1})".format(
            payload["verdict"], payload["evidence_status"]
        )
    )
    print("report: {0}".format(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
