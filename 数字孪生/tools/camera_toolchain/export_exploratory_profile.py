"""从修正后的 R3 raw-pixel 联合拟合报告导出不可变 exploratory profile。

严格契约（handoff 2026-08-04-ds-r3-exploratory-profile.md §5）：
- input_domain=RAW_PIXEL，不得暗含/重复去畸变；
- quality=EXPLORATORY_RELATIVE_ONLY；
- 验证源 SHA-256、anchor_correction、矩阵与四个独立误差指标；
- 输出目录已存在且非空时失败：不删除、不覆盖、不补写；
- 生成 JSON 确定性：UTF-8、LF、排序键、无时间戳。

用法：
  py -3.11 export_exploratory_profile.py <source.json> <out_dir> \
      --workspace-root <workspace_root> --expected-sha256 <sha256>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

_HERE = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _HERE.parents[1]
_DT_DIR = _WORKSPACE_ROOT / "simulation" / "digital_twin"
if str(_DT_DIR) not in sys.path:
    sys.path.insert(0, str(_DT_DIR))

from v1_twin.v1_twin_calibration_profile import (
    CalibrationProfile,
    CalibrationProfileError,
)

CORRECTED_ANCHOR_CORRECTION = "corner0=outer+R(angle)*[15,15]"
KNOWN_EVIDENCE_CLASS = "MODEL_ESTIMATED_NOT_PHYSICALLY_INDEPENDENT_ANGLE"
REQUIRED_METHOD = (
    "joint pixel-to-mm homography plus one in-plane angle per training view"
)
REQUIRED_UNDISTORTION = "disabled"
CALIBRATION_ID = "c960_r3_raw_global_exploratory_v1"
CAMERA_MODEL = "EMEET SmartCam C960"
FORMAL_2MM_REJECT_REASON = "independent ground holdout p95 exceeds 2.0 mm"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serialize(data: Dict[str, Any]) -> str:
    """确定性 JSON：排序键、UTF-8、LF（由 write_text newline 保证）、无时间戳。"""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _write_deterministic(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(_serialize(data), encoding="utf-8", newline="\n")


def build_profile(source: Path, workspace_root: Path) -> CalibrationProfile:
    """从修正后的源 JSON 构建 CalibrationProfile（不含 SHA 校验）。"""
    source = Path(source)
    data = json.loads(source.read_text(encoding="utf-8"))

    # 像素域来源证明：只有原始（未去畸变）联合拟合才能声明 RAW_PIXEL。
    # 缺少或不同的 method / optimizer.undistortion 一律拒绝，且发生在任何输出目录创建前。
    if data.get("method") != REQUIRED_METHOD:
        raise CalibrationProfileError(
            "source method is not the raw-pixel joint-fit convention "
            f"(expected {REQUIRED_METHOD!r}, got {data.get('method')!r})"
        )
    optimizer = data.get("optimizer")
    undistortion = (
        optimizer.get("undistortion") if isinstance(optimizer, dict) else None
    )
    if undistortion != REQUIRED_UNDISTORTION:
        raise CalibrationProfileError(
            "source optimizer.undistortion must be exactly "
            f"{REQUIRED_UNDISTORTION!r} to claim RAW_PIXEL "
            f"(got {undistortion!r})"
        )

    try:
        anchor_correction = data["coordinate_convention"]["anchor_correction"]
    except (KeyError, TypeError):
        raise CalibrationProfileError(
            "source coordinate_convention.anchor_correction is missing"
        )
    if anchor_correction != CORRECTED_ANCHOR_CORRECTION:
        raise CalibrationProfileError(
            "source anchor_correction is not the corrected convention "
            f"(expected {CORRECTED_ANCHOR_CORRECTION!r})"
        )

    evidence_class = data["evidence_class"]
    if evidence_class != KNOWN_EVIDENCE_CLASS:
        raise CalibrationProfileError(
            f"source evidence_class is not {KNOWN_EVIDENCE_CLASS!r}"
        )

    image_size = list(data["inputs"]["image_size"])
    matrix = data["full_16_view_fit_in_sample"]["homography_matrix"]
    holdout = data["stratified_9_7"]["holdout"]["independent_anchor_position_mm"]
    loo = data["leave_one_view_out"]["independent_anchor_position_mm"]

    rel_source = source.resolve().relative_to(workspace_root.resolve()).as_posix()

    profile_data = {
        "schema_version": 1,
        "calibration_id": CALIBRATION_ID,
        "camera": {"model": CAMERA_MODEL, "image_size": image_size},
        "input_domain": "RAW_PIXEL",
        "quality": "EXPLORATORY_RELATIVE_ONLY",
        "ground_transform": {"type": "HomographyTransform", "matrix": matrix},
        "accuracy_evidence": {
            "scope": "GROUND_CONTROL_POINTS_ONLY",
            "stratified_holdout_p95_mm": float(holdout["p95"]),
            "stratified_holdout_max_mm": float(holdout["max"]),
            "loo_p95_mm": float(loo["p95"]),
            "loo_max_mm": float(loo["max"]),
            "evidence_class": evidence_class,
        },
        "pose_absolute_accuracy": "UNVERIFIED_TAG_HEIGHT_PARALLAX",
        "provenance": {
            "source": rel_source,
            "sha256": _sha256(source),
        },
    }
    return CalibrationProfile.from_dict(profile_data)


def export_profile(
    source: Path,
    out_dir: Path,
    workspace_root: Path,
    expected_sha256: str,
) -> Dict[str, Any]:
    """严格导出；任何失败在写盘前抛出 CalibrationProfileError。"""
    source = Path(source)
    out_dir = Path(out_dir)
    workspace_root = Path(workspace_root)

    actual_sha = _sha256(source)
    if actual_sha.lower() != expected_sha256.strip().lower():
        raise CalibrationProfileError(
            "source SHA-256 mismatch: expected "
            f"{expected_sha256.strip().lower()!r}, got {actual_sha!r}"
        )

    profile = build_profile(source, workspace_root)
    profile_data = profile.to_dict()
    profile_json = _serialize(profile_data)
    profile_sha = hashlib.sha256(profile_json.encode("utf-8")).hexdigest()

    if out_dir.exists():
        if not out_dir.is_dir():
            raise CalibrationProfileError(
                "output path exists and is not a directory"
            )
        if next(out_dir.iterdir(), None) is not None:
            raise CalibrationProfileError(
                "output directory exists and is not empty; refusing to "
                "overwrite, delete or top up evidence"
            )
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_deterministic(out_dir / "calibration_profile.json", profile_data)
    report = {
        "status": "EXPLORATORY_PROFILE_EXPORTED",
        "formal_2mm_gate": "REJECT",
        "reason": FORMAL_2MM_REJECT_REASON,
        "source_sha256": actual_sha,
        "profile_sha256": profile_sha,
        "old_runtime_chain_accuracy": "NOT_ESTABLISHED_BY_THIS_PROFILE",
        "hardware_used": False,
    }
    _write_deterministic(out_dir / "verification_report.json", report)

    return {
        "out_dir": out_dir,
        "profile": profile,
        "profile_json": profile_json,
        "profile_sha256": profile_sha,
        "source_sha256": actual_sha,
        "report": report,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export the corrected R3 raw-pixel mapping as an "
            "EXPLORATORY_RELATIVE_ONLY calibration profile."
        )
    )
    parser.add_argument("source", type=Path, help="corrected joint-fit JSON")
    parser.add_argument(
        "out_dir", type=Path, help="new evidence output directory"
    )
    parser.add_argument(
        "--workspace-root", type=Path, required=True, help="workspace root"
    )
    parser.add_argument(
        "--expected-sha256", required=True, help="expected source SHA-256"
    )
    args = parser.parse_args(argv)

    try:
        result = export_profile(
            args.source,
            args.out_dir,
            args.workspace_root,
            args.expected_sha256,
        )
    except CalibrationProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"status={result['report']['status']}")
    print(f"formal_2mm_gate={result['report']['formal_2mm_gate']}")
    print(f"source_sha256={result['source_sha256']}")
    print(f"profile_sha256={result['profile_sha256']}")
    print(f"profile_path={result['out_dir'] / 'calibration_profile.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
