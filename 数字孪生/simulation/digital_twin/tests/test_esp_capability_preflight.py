"""Offline tests for ESP capability diagnostic line evidence."""

from __future__ import annotations

import json

from tools.shakedown_toolchain.esp_capability_preflight import (
    build_capability_evidence,
    parse_capability_line,
    reassemble_capability_lines,
    write_preflight_artifacts,
)


NONCE = "offline1"


def _line(query, raw, index=0, count=1, status="OK"):
    return "D,ESP_CAPS,{0},{1},{2},{3},{4},{5}\n".format(
        NONCE, query, status, index, count, raw.hex().upper()
    )


def _complete_lines():
    return [
        _line("GMR", b"AT version: ESP-AT\r\nOK\r\n"),
        _line("CIPMUX", b"+CIPMUX:1\r\nOK\r\n"),
        _line("CIPMODE", b"+CIPMODE:0\r\nOK\r\n"),
        _line("CIPDINFO", b"+CIPDINFO:0\r\nOK\r\n"),
    ]


def test_complete_lines_reassemble_without_inferring_udp_support():
    parsed = [parse_capability_line(line) for line in _complete_lines()]
    result = reassemble_capability_lines(parsed, NONCE)

    assert result["verdict"] == "INSUFFICIENT EVIDENCE"
    assert result["queries"]["GMR"]["raw_bytes"] == b"AT version: ESP-AT\r\nOK\r\n"
    assert result["observations"]["cipmux"] == 1
    assert result["observations"]["cipmode"] == 0
    assert result["missing"] == ["udp_capability_source"]


def test_multichunk_query_requires_contiguous_unique_chunks():
    raw = bytes(range(100))
    lines = [
        _line("GMR", raw[48:96], index=1, count=3),
        _line("GMR", raw[:48], index=0, count=3),
        _line("GMR", raw[96:], index=2, count=3),
        *_complete_lines()[1:],
    ]

    result = reassemble_capability_lines(
        [parse_capability_line(line) for line in lines], NONCE
    )

    assert result["queries"]["GMR"]["raw_bytes"] == raw
    assert result["verdict"] == "INSUFFICIENT EVIDENCE"


def test_malformed_duplicate_wrong_nonce_and_non_ok_are_insufficient():
    lines = _complete_lines()[:-1] + [
        _line("CIPDINFO", b"", status="TIMEOUT"),
        _line("CIPMUX", b"+CIPMUX:1\r\nOK\r\n"),
    ]
    lines[0] = lines[0].replace(NONCE, "other")

    result = reassemble_capability_lines(
        [parse_capability_line(line) for line in lines], NONCE
    )

    assert result["verdict"] == "INSUFFICIENT EVIDENCE"
    assert result["missing"]
    assert result["wrong_nonce_count"] == 1
    assert "CIPDINFO" in result["missing"]


def test_evidence_writer_preserves_raw_lines_and_report(tmp_path):
    raw_lines = _complete_lines()
    parsed = [parse_capability_line(line) for line in raw_lines]
    result = reassemble_capability_lines(parsed, NONCE)
    evidence = build_capability_evidence(result)
    report = {"verdict": evidence["verdict"], "source": "offline_capture"}

    write_preflight_artifacts(tmp_path, raw_lines, evidence, report)

    assert json.loads((tmp_path / "raw_at_responses.json").read_text())[
        "raw_lines"
    ] == raw_lines
    assert json.loads((tmp_path / "esp_capability_evidence.json").read_text())[
        "verdict"
    ] == "INSUFFICIENT EVIDENCE"
    assert json.loads((tmp_path / "preflight_report.json").read_text())[
        "source"
    ] == "offline_capture"
