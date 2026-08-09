"""Add relative in-plane angles to an existing tile controls.json."""

from __future__ import annotations

import argparse
import json
import os

import cv2

import camera_common as cc
from tile_auto_align import CRITERIA, PATTERN, estimate_board_pose


def _detect_corners(path):
    image = cc.imread_unicode(path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
    if not ret:
        raise ValueError(f"checkerboard not detected: {path}")
    refined = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
    return refined.reshape(-1, 2)


def correct_controls(controls):
    if not controls:
        raise ValueError("controls.json is empty")

    reference = None
    corrected = []
    angles = []
    for index, control in enumerate(controls):
        corners = _detect_corners(control["image"])
        if reference is None:
            reference = corners.copy()
            angle_deg = 0.0
            tx_mm = 0.0
            ty_mm = 0.0
        else:
            angle_deg, tx_mm, ty_mm = estimate_board_pose(reference, corners)
        item = dict(control)
        item["angle_deg"] = round(angle_deg, 6)
        corrected.append(item)
        angles.append({
            "index": index,
            "angle_deg": item["angle_deg"],
            "relative_tx_mm": round(tx_mm, 6),
            "relative_ty_mm": round(ty_mm, 6),
        })

    return corrected, {
        "angle_source": "relative_planar_reference_first_view",
        "reference_index": 0,
        "n_controls": len(corrected),
        "angles": angles,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("controls")
    parser.add_argument("out")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    if os.path.exists(args.out) or os.path.exists(args.report):
        raise SystemExit("refusing to overwrite existing angle-correction outputs")
    with open(args.controls, encoding="utf-8") as f:
        controls = json.load(f)
    corrected, report = correct_controls(controls)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(corrected, f, ensure_ascii=False, indent=2)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"corrected {len(corrected)} controls")
    print(f"saved controls -> {args.out}")
    print(f"saved report -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
