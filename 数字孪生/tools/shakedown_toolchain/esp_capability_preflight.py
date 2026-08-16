"""Offline parser for the bounded ESP AT capability diagnostic channel.

This module deliberately has no socket or serial dependency.  It consumes
captured diagnostic lines and writes evidence only after validating the nonce,
query set, chunk boundaries, and raw hexadecimal bytes.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


QUERIES = ("GMR", "CIPMUX", "CIPMODE", "CIPDINFO")
STATUSES = ("OK", "ERROR", "TIMEOUT", "TRUNCATED", "REJECTED")
LINE_PREFIX = "D,ESP_CAPS,"
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
_HEX_RE = re.compile(r"^[0-9A-Fa-f]*$")


def _invalid_line(raw_line: Any, error: str) -> Dict[str, Any]:
    return {
        "valid": False,
        "raw_line": raw_line if isinstance(raw_line, str) else str(raw_line),
        "error": error,
    }


def parse_capability_line(line: str) -> Dict[str, Any]:
    """Parse one diagnostic line without discarding malformed input.

    The returned mapping always contains ``valid`` and ``raw_line``.  Invalid
    lines are represented as data so a capture can be classified as
    ``INSUFFICIENT EVIDENCE`` instead of aborting the whole offline report.
    """

    if not isinstance(line, str):
        return _invalid_line(line, "line must be text")
    raw_line = line
    text = line.rstrip("\r\n")
    if not text.startswith(LINE_PREFIX):
        return _invalid_line(raw_line, "missing diagnostic prefix")

    fields = text.split(",", 7)
    if len(fields) != 8 or fields[0] != "D" or fields[1] != "ESP_CAPS":
        return _invalid_line(raw_line, "expected eight comma-separated fields")

    _, _, nonce, query, status, index_text, count_text, hex_text = fields
    if not _NONCE_RE.fullmatch(nonce):
        return _invalid_line(raw_line, "invalid nonce")
    if query not in QUERIES:
        return _invalid_line(raw_line, "unknown query")
    if status not in STATUSES:
        return _invalid_line(raw_line, "unknown status")
    try:
        chunk_index = int(index_text, 10)
        chunk_count = int(count_text, 10)
    except ValueError:
        return _invalid_line(raw_line, "chunk index/count must be integers")
    if chunk_count <= 0 or chunk_index < 0 or chunk_index >= chunk_count:
        return _invalid_line(raw_line, "chunk bounds are invalid")
    if len(hex_text) % 2 or not _HEX_RE.fullmatch(hex_text):
        return _invalid_line(raw_line, "hex payload is invalid")
    try:
        raw_bytes = bytes.fromhex(hex_text)
    except ValueError:
        return _invalid_line(raw_line, "hex payload cannot be decoded")

    return {
        "valid": True,
        "raw_line": raw_line,
        "nonce": nonce,
        "query": query,
        "status": status,
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "hex": hex_text,
        "raw_bytes": raw_bytes,
    }


def _as_parsed(item: Any) -> Dict[str, Any]:
    if isinstance(item, str):
        return parse_capability_line(item)
    if isinstance(item, Mapping):
        return dict(item)
    return _invalid_line(item, "line must be text or a parsed mapping")


def _query_summary(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(items, key=lambda item: item["chunk_index"])
    first = ordered[0]
    expected_count = first["chunk_count"]
    indexes = [item["chunk_index"] for item in ordered]
    errors: List[str] = []
    if any(item["chunk_count"] != expected_count for item in ordered):
        errors.append("inconsistent chunk_count")
    if len(indexes) != len(set(indexes)):
        errors.append("duplicate chunk")
    if indexes != list(range(expected_count)):
        errors.append("incomplete chunk set")
    if any(item["status"] != first["status"] for item in ordered):
        errors.append("inconsistent status")
    raw_bytes = b"".join(item["raw_bytes"] for item in ordered)
    status = first["status"]
    if status != "OK":
        errors.append("non-OK status")
    return {
        "query": first["query"],
        "status": status,
        "chunk_count": expected_count,
        "chunk_indexes": indexes,
        "raw_bytes": raw_bytes,
        "raw_hex": raw_bytes.hex().upper(),
        "complete": not errors,
        "errors": errors,
    }


def _decode_ascii(raw_bytes: bytes) -> str:
    return raw_bytes.decode("utf-8", errors="replace")


def _extract_int(text: str, label: str) -> int | None:
    match = re.search(
        r"^\+" + re.escape(label) + r"\s*:\s*(-?\d+)",
        text,
        flags=re.MULTILINE,
    )
    return int(match.group(1)) if match else None


def reassemble_capability_lines(
    lines: Iterable[Any], nonce: str
) -> Dict[str, Any]:
    """Validate and reassemble a diagnostic capture for one nonce."""

    parsed = [_as_parsed(item) for item in lines]
    malformed_count = sum(1 for item in parsed if not item.get("valid", False))
    valid = [item for item in parsed if item.get("valid", False)]
    wrong_nonce_count = sum(
        1 for item in valid if item.get("nonce") != nonce
    )
    accepted = [item for item in valid if item.get("nonce") == nonce]
    grouped: Dict[str, List[Dict[str, Any]]] = {query: [] for query in QUERIES}
    for item in accepted:
        grouped[item["query"]].append(item)

    queries: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    for query in QUERIES:
        items = grouped[query]
        if not items:
            missing.append(query)
            continue
        queries[query] = _query_summary(items)
        if not queries[query]["complete"]:
            missing.append(query)

    if malformed_count:
        missing.append("malformed_lines")
    if wrong_nonce_count:
        missing.append("wrong_nonce")
    missing = list(dict.fromkeys(missing))

    observations: Dict[str, Any] = {
        "at_gmr": None,
        "cipmux": None,
        "cipmode": None,
        "ipd_header_mode": None,
    }
    if "GMR" in queries and queries["GMR"]["complete"]:
        observations["at_gmr"] = _decode_ascii(queries["GMR"]["raw_bytes"])
    if "CIPMUX" in queries and queries["CIPMUX"]["complete"]:
        observations["cipmux"] = _extract_int(
            _decode_ascii(queries["CIPMUX"]["raw_bytes"]), "CIPMUX"
        )
    if "CIPMODE" in queries and queries["CIPMODE"]["complete"]:
        observations["cipmode"] = _extract_int(
            _decode_ascii(queries["CIPMODE"]["raw_bytes"]), "CIPMODE"
        )
    if "CIPDINFO" in queries and queries["CIPDINFO"]["complete"]:
        # The query proves that the command was accepted, but it does not by
        # itself prove the UDP +IPD header shape used by a future transport.
        observations["ipd_header_mode"] = "observed_tcp_query_only"

    return {
        "verdict": "INSUFFICIENT EVIDENCE",
        "nonce": nonce,
        "line_count": len(parsed),
        "valid_line_count": len(valid),
        "malformed_count": malformed_count,
        "wrong_nonce_count": wrong_nonce_count,
        "queries": queries,
        "observations": observations,
        "udp_supported": None,
        "udp_capability_source": None,
        "missing": list(dict.fromkeys(missing + ["udp_capability_source"])),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def build_capability_evidence(results: Mapping[str, Any]) -> Dict[str, Any]:
    """Build a JSON-safe evidence document without UDP capability inference."""

    evidence = dict(results)
    observations = dict(evidence.get("observations", {}))
    evidence["observations"] = observations
    evidence["udp_supported"] = None
    evidence["udp_capability_source"] = None
    missing = list(evidence.get("missing", []))
    if "udp_capability_source" not in missing:
        missing.append("udp_capability_source")
    evidence["missing"] = list(dict.fromkeys(missing))
    evidence["verdict"] = "INSUFFICIENT EVIDENCE"
    return _jsonable(evidence)


def write_preflight_artifacts(
    out_dir: str | Path,
    raw_lines: Sequence[str],
    evidence: Mapping[str, Any],
    report: Mapping[str, Any],
) -> None:
    """Write the three offline preflight artifacts to a caller-selected path."""

    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "raw_at_responses.json": {"raw_lines": list(raw_lines)},
        "esp_capability_evidence.json": _jsonable(evidence),
        "preflight_report.json": _jsonable(report),
    }
    for name, payload in artifacts.items():
        (destination / name).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )


def _load_capture(path: Path) -> List[str]:
    if path.suffix.lower() == ".jsonl":
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [str(item) for item in payload]
    if isinstance(payload, Mapping) and isinstance(payload.get("raw_lines"), list):
        return [str(item) for item in payload["raw_lines"]]
    raise ValueError("capture must be a JSON list/object or JSONL")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    raw_lines = _load_capture(args.capture)
    result = reassemble_capability_lines(raw_lines, args.nonce)
    evidence = build_capability_evidence(result)
    report = {
        "verdict": evidence["verdict"],
        "source": "offline_capture",
        "capture": str(args.capture),
        "nonce": args.nonce,
        "missing": evidence["missing"],
    }
    write_preflight_artifacts(args.out_dir, raw_lines, evidence, report)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
