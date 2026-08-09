"""Fit a relative ground-plane model from checkerboard control images."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

import camera_common as cc
from tile_auto_align import CRITERIA, PATTERN, _fit_rigid_pose, board_local_points

_HERE = Path(__file__).resolve().parent
_DT_DIR = _HERE.parents[1] / "simulation" / "digital_twin"
if str(_DT_DIR) not in sys.path:
    sys.path.insert(0, str(_DT_DIR))

from mosaic_homography import _apply_h, fit_global_homography  # noqa: E402


def detect_control_corners(path):
    image = cc.imread_unicode(path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
    if not ret:
        raise ValueError(f"checkerboard not detected: {path}")
    refined = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
    return refined.reshape(-1, 2).astype(np.float64)


def error_metrics(errors):
    values = np.asarray(errors, dtype=np.float64).reshape(-1)
    if not len(values):
        raise ValueError("cannot summarize empty errors")
    return {
        "mean_mm": float(values.mean()),
        "p50_mm": float(np.percentile(values, 50)),
        "p95_mm": float(np.percentile(values, 95)),
        "max_mm": float(values.max()),
    }


def _pose_residuals(H, corners, local):
    ground = _apply_h(H, corners)
    angle_deg, tx_mm, ty_mm = _fit_rigid_pose(local, ground)
    angle = np.deg2rad(angle_deg)
    rotation = np.array(
        [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
    )
    predicted = local @ rotation.T + np.array([tx_mm, ty_mm])
    return angle_deg, tx_mm, ty_mm, np.linalg.norm(ground - predicted, axis=1)


def _holdout_report(detections, local, calibration_indices, holdout_indices):
    H, _ = fit_global_homography(
        [detections[index] for index in calibration_indices], local
    )
    errors = []
    for index in holdout_indices:
        _, _, _, view_errors = _pose_residuals(H, detections[index], local)
        errors.extend(view_errors.tolist())
    return {
        "n_calibration_views": len(calibration_indices),
        "n_holdout_views": len(holdout_indices),
        "corner_error_mm": error_metrics(errors),
    }


def fit_controls(controls):
    if len(controls) < 6:
        raise ValueError("at least six control images are required")

    detections = [detect_control_corners(control["image"]) for control in controls]
    local = board_local_points()
    H, result = fit_global_homography(detections, local)
    full_errors = np.linalg.norm(result.fun.reshape(-1, 2), axis=1)

    fitted_controls = []
    fitted_pose = []
    for index, control in enumerate(controls):
        if index == 0:
            angle_deg = tx_mm = ty_mm = 0.0
        else:
            angle_rad = result.x[8 + 3 * (index - 1)]
            angle_deg = float(np.degrees(angle_rad))
            tx_mm = float(result.x[9 + 3 * (index - 1)])
            ty_mm = float(result.x[10 + 3 * (index - 1)])
        item = dict(control)
        item["x_mm"] = round(tx_mm, 6)
        item["y_mm"] = round(ty_mm, 6)
        item["angle_deg"] = round(angle_deg, 6)
        fitted_controls.append(item)
        fitted_pose.append((tx_mm, ty_mm))

    indices = np.arange(len(detections))
    rows = np.array([index // 10 for index in indices])
    cols = np.array([index % 10 for index in indices])
    checker_cal = [int(i) for i in indices if (rows[i] + cols[i]) % 2 == 0]
    checker_hold = [int(i) for i in indices if (rows[i] + cols[i]) % 2 == 1]
    column_cal = [int(i) for i in indices if cols[i] % 3 != 0]
    column_hold = [int(i) for i in indices if cols[i] % 3 == 0]
    five_fold = []
    for fold in range(5):
        fold_cal = [int(i) for i in indices if cols[i] % 5 != fold]
        fold_hold = [int(i) for i in indices if cols[i] % 5 == fold]
        fold_report = _holdout_report(detections, local, fold_cal, fold_hold)
        five_fold.append({"fold": fold, **fold_report})
    five_fold_p95 = [fold["corner_error_mm"]["p95_mm"] for fold in five_fold]

    original_x = np.array([float(control["x_mm"]) for control in controls])
    original_y = np.array([float(control["y_mm"]) for control in controls])
    fitted_x = np.array([pose[0] for pose in fitted_pose])
    fitted_y = np.array([pose[1] for pose in fitted_pose])

    report = {
        "status": "EXPLORATORY_RELATIVE_PLANE_FIT",
        "input_domain": "RAW_PIXEL",
        "undistortion": "not_applied",
        "n_controls": len(controls),
        "detected_corner_sets": len(detections),
        "full_fit": {
            "optimization_success": bool(result.success),
            "nfev": int(result.nfev),
            "cost": float(result.cost),
            "corner_error_mm": error_metrics(full_errors),
        },
        "spatial_holdout": {
            "checkerboard_split": _holdout_report(
                detections, local, checker_cal, checker_hold
            ),
            "every_third_column_split": _holdout_report(
                detections, local, column_cal, column_hold
            ),
            "five_column_cross_validation": {
                "folds": five_fold,
                "p95_mean_mm": float(np.mean(five_fold_p95)),
                "p95_max_mm": float(np.max(five_fold_p95)),
            },
        },
        "original_grid_label_comparison": {
            "meaning": "joint-fit translation minus pixel-grid labels; not independent physical truth",
            "x_abs_error_mm": error_metrics(np.abs(fitted_x - original_x)),
            "y_abs_error_mm": error_metrics(np.abs(fitted_y - original_y)),
        },
        "evidence_boundary": (
            "Relative planar consistency only. Absolute ground accuracy requires "
            "an independently measured origin, translation, and orientation."
        ),
        "homography_matrix": [[float(value) for value in row] for row in H.tolist()],
    }
    return fitted_controls, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("controls")
    parser.add_argument("fitted_controls")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    if os.path.exists(args.fitted_controls) or os.path.exists(args.report):
        raise SystemExit("refusing to overwrite existing fit outputs")
    with open(args.controls, encoding="utf-8") as f:
        controls = json.load(f)
    fitted, report = fit_controls(controls)
    with open(args.fitted_controls, "w", encoding="utf-8") as f:
        json.dump(fitted, f, ensure_ascii=False, indent=2)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report["full_fit"], ensure_ascii=False, indent=2))
    print(json.dumps(report["spatial_holdout"], ensure_ascii=False, indent=2))
    print(f"saved fitted controls -> {args.fitted_controls}")
    print(f"saved report -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
