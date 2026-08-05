"""Exporter 测试：用临时源/输出目录覆盖全部防错契约。

先写测试后实现：exporter 尚不存在时应 RED。

覆盖（handoff §5 防错契约）：
- 恰好写出 calibration_profile.json + verification_report.json；
- 记录 RAW_PIXEL / EXPLORATORY_RELATIVE_ONLY / formal_2mm_gate=REJECT /
  pose_absolute_accuracy=UNVERIFIED_TAG_HEIGHT_PARALLAX；
- 保留源矩阵与四个误差指标；
- SHA 不匹配在创建输出前拒绝；
- 缺失/错误的 anchor_correction 拒绝；
- 已存在且非空输出目录拒绝（不删除不覆盖不补写）；
- 相同输入在两个不同空输出目录生成逐字节一致 JSON（确定性）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TOOLS_DIR = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "camera_toolchain"
)
sys.path.insert(0, str(_TOOLS_DIR))

import pytest

from export_exploratory_profile import (
    CORRECTED_ANCHOR_CORRECTION,
    build_profile,
    export_profile,
)
from v1_twin.v1_twin_calibration_profile import CalibrationProfileError

SOURCE_DICT = {
    "method": "joint pixel-to-mm homography plus one in-plane angle per training view",
    "evidence_class": "MODEL_ESTIMATED_NOT_PHYSICALLY_INDEPENDENT_ANGLE",
    "coordinate_convention": {
        "anchor_correction": CORRECTED_ANCHOR_CORRECTION,
    },
    "optimizer": {"undistortion": "disabled"},
    "inputs": {"image_size": [1280, 720]},
    "full_16_view_fit_in_sample": {
        "homography_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    },
    "stratified_9_7": {
        "holdout": {
            "independent_anchor_position_mm": {"p95": 10.6, "max": 10.8},
        },
    },
    "leave_one_view_out": {
        "independent_anchor_position_mm": {"p95": 11.0, "max": 11.6},
    },
}


def _copy_source() -> dict:
    return json.loads(json.dumps(SOURCE_DICT))


def _write_source(workspace: Path) -> Path:
    src_dir = workspace / "immutable"
    src_dir.mkdir(parents=True, exist_ok=True)
    src = src_dir / "source.json"
    src.write_text(json.dumps(SOURCE_DICT), encoding="utf-8", newline="\n")
    return src


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_export_writes_exactly_two_files_and_identity(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _write_source(ws)
    out = ws / "r1"
    export_profile(src, out, ws, _sha256_of(src))

    names = sorted(p.name for p in out.iterdir())
    assert names == ["calibration_profile.json", "verification_report.json"]
    profile = json.loads(
        (out / "calibration_profile.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (out / "verification_report.json").read_text(encoding="utf-8")
    )
    assert profile["input_domain"] == "RAW_PIXEL"
    assert profile["quality"] == "EXPLORATORY_RELATIVE_ONLY"
    assert profile["pose_absolute_accuracy"] == "UNVERIFIED_TAG_HEIGHT_PARALLAX"
    assert profile["provenance"]["source"] == "immutable/source.json"
    assert "/" in profile["provenance"]["source"]
    assert report["status"] == "EXPLORATORY_PROFILE_EXPORTED"
    assert report["formal_2mm_gate"] == "REJECT"
    assert report["hardware_used"] is False


def test_export_preserves_matrix_and_four_metrics(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _write_source(ws)
    out = ws / "r1"
    result = export_profile(src, out, ws, _sha256_of(src))
    profile = result["profile"]
    assert profile.ground_transform.matrix.tolist() == [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
    ]
    assert profile.accuracy.stratified_holdout_p95_mm == pytest.approx(10.6)
    assert profile.accuracy.stratified_holdout_max_mm == pytest.approx(10.8)
    assert profile.accuracy.loo_p95_mm == pytest.approx(11.0)
    assert profile.accuracy.loo_max_mm == pytest.approx(11.6)
    # 写盘 JSON 与内存一致
    on_disk = json.loads(
        (out / "calibration_profile.json").read_text(encoding="utf-8")
    )
    assert on_disk["ground_transform"]["matrix"] == [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
    ]
    assert on_disk["accuracy_evidence"]["stratified_holdout_p95_mm"] == pytest.approx(
        10.6
    )
    assert on_disk["accuracy_evidence"]["loo_max_mm"] == pytest.approx(11.6)


def test_export_rejects_sha_mismatch_before_creating_output(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _write_source(ws)
    out = ws / "r1"
    with pytest.raises(CalibrationProfileError, match="SHA-256 mismatch"):
        export_profile(src, out, ws, "0" * 64)
    assert not out.exists()


def test_export_rejects_missing_anchor_correction(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    data = _copy_source()
    del data["coordinate_convention"]["anchor_correction"]
    src = ws / "immutable" / "source.json"
    src.parent.mkdir(parents=True)
    src.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    with pytest.raises(CalibrationProfileError, match="anchor_correction"):
        export_profile(src, ws / "r1", ws, _sha256_of(src))
    assert not (ws / "r1").exists()


def test_export_rejects_wrong_anchor_correction(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    data = _copy_source()
    data["coordinate_convention"]["anchor_correction"] = (
        "corner0=inner+R(angle)*[15,15]"
    )
    src = ws / "immutable" / "source.json"
    src.parent.mkdir(parents=True)
    src.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    with pytest.raises(CalibrationProfileError, match="anchor_correction"):
        export_profile(src, ws / "r1", ws, _sha256_of(src))
    assert not (ws / "r1").exists()


def _write_custom_source(ws: Path, data: dict) -> Path:
    src_dir = ws / "immutable"
    src_dir.mkdir(parents=True, exist_ok=True)
    src = src_dir / "source.json"
    src.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    return src


def test_export_rejects_missing_method(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    data = _copy_source()
    del data["method"]
    src = _write_custom_source(ws, data)
    with pytest.raises(CalibrationProfileError, match="method"):
        export_profile(src, ws / "r1", ws, _sha256_of(src))
    assert not (ws / "r1").exists()


def test_export_rejects_wrong_method(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    data = _copy_source()
    data["method"] = "some other method"
    src = _write_custom_source(ws, data)
    with pytest.raises(CalibrationProfileError, match="method"):
        export_profile(src, ws / "r1", ws, _sha256_of(src))
    assert not (ws / "r1").exists()


def test_export_rejects_missing_optimizer(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    data = _copy_source()
    del data["optimizer"]
    src = _write_custom_source(ws, data)
    with pytest.raises(CalibrationProfileError, match="undistortion"):
        export_profile(src, ws / "r1", ws, _sha256_of(src))
    assert not (ws / "r1").exists()


def test_export_rejects_undistortion_not_disabled(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    data = _copy_source()
    data["optimizer"]["undistortion"] = "intrinsics file"
    src = _write_custom_source(ws, data)
    with pytest.raises(CalibrationProfileError, match="undistortion"):
        export_profile(src, ws / "r1", ws, _sha256_of(src))
    assert not (ws / "r1").exists()


def test_export_rejects_real_undistorted_source(tmp_path):
    """Regression: joint_current_undistortion.json (undistortion='intrinsics file')
    must be rejected before any output directory is created."""
    ws = Path(__file__).resolve().parents[3]
    src = (
        ws
        / "simulation"
        / "digital_twin"
        / "tests"
        / "fixtures"
        / "joint_current_undistortion.json"
    )
    assert src.is_file(), f"regression source missing: {src}"
    out = tmp_path / "r1"
    with pytest.raises(CalibrationProfileError, match="undistortion"):
        export_profile(src, out, ws, _sha256_of(src))
    assert not out.exists()


def test_export_rejects_non_empty_output_directory(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _write_source(ws)
    out = ws / "r1"
    out.mkdir()
    marker = out / "existing.txt"
    marker.write_text("do not touch", encoding="utf-8")
    with pytest.raises(CalibrationProfileError, match="not empty"):
        export_profile(src, out, ws, _sha256_of(src))
    assert marker.read_text(encoding="utf-8") == "do not touch"
    assert not (out / "calibration_profile.json").exists()
    assert not (out / "verification_report.json").exists()


def test_export_identical_bytes_in_two_empty_output_dirs(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _write_source(ws)
    out1 = ws / "r1"
    out2 = ws / "r2"
    export_profile(src, out1, ws, _sha256_of(src))
    export_profile(src, out2, ws, _sha256_of(src))
    for name in ("calibration_profile.json", "verification_report.json"):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


def test_export_json_is_utf8_lf_and_sorted_keys(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _write_source(ws)
    out = ws / "r1"
    export_profile(src, out, ws, _sha256_of(src))
    for name in ("calibration_profile.json", "verification_report.json"):
        raw = (out / name).read_bytes()
        assert b"\r\n" not in raw  # LF only
        text = raw.decode("utf-8")
        obj = json.loads(text)
        # 排序键验证：顶层键按序
        assert list(obj) == sorted(obj)


def test_build_profile_records_relative_source_and_identity(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    src = _write_source(ws)
    profile = build_profile(src, ws)
    assert profile.calibration_id == "c960_r3_raw_global_exploratory_v1"
    assert profile.provenance.source == "immutable/source.json"
    assert profile.provenance.sha256 == _sha256_of(src)
    assert profile.pixel_domain.value == "RAW_PIXEL"
    assert profile.quality.value == "EXPLORATORY_RELATIVE_ONLY"
