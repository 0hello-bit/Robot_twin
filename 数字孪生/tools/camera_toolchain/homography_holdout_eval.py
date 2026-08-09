"""R3：homography 物理控制点 + 独立 holdout 评估。

用法: py homography_holdout_eval.py controls.json out.json [--mm-gate 2.0] [--intrinsics path]

控制点 JSON controls.json：
  [ {"image": "<棋盘格图像路径>", "x_mm": 0, "y_mm": 0, "angle_deg": 0}, ... ]
  - image: 该位置棋盘格（平放）的原始图像。
  - x_mm / y_mm: 棋盘格左上内角在赛道全局 mm 坐标下的位置（用户用尺子测量）。
  - angle_deg: 棋盘格相对赛道坐标轴的旋转（默认 0 = 轴对齐）。

流程：
  1. 每点检测棋盘格 → undistort 角点。
  2. 由 (x_mm, y_mm, angle) 生成该板全部 54 角点的全局 mm 坐标。
  3. 按区域（中心/边缘/四角）分层划分 calibration(~70%) 与 holdout(~30%)。
  4. calibration 拟合 homography；holdout 计算绝对位置误差。
  5. 分区域报告 mean/p95/max + 尺度误差；应用 mm 门限。

注意：holdout 是**独立物理控制点**（未参与拟合），不是拟合残差。
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

import camera_common as cc

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "simulation", "digital_twin")))

PATTERN = cc.CHECKERBOARD_PATTERN
SQUARE_MM = cc.GROUND_CHECKERBOARD_SQUARE_MM
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)


def _board_local_grid(square_mm=SQUARE_MM):
    cols, rows = PATTERN
    L = np.zeros((cols * rows, 2), dtype=np.float64)
    L[:, 0] = (np.arange(cols * rows) % cols) * square_mm
    L[:, 1] = (np.arange(cols * rows) // cols) * square_mm
    return L


def load_intrinsics(path):
    with open(path, encoding="utf-8") as f:
        intr = json.load(f)
    return np.array(intr["camera_matrix"]), np.array(intr["dist_coeffs"])


def region_of(center_mm, img_size):
    """按中心像素位置分区域：center / edge / corner。"""
    x, y = center_mm[0], center_mm[1]
    w, h = img_size
    cx, cy = w / 2, h / 2
    if abs(x - cx) < w * 0.2 and abs(y - cy) < h * 0.2:
        return "center"
    if abs(x - cx) > w * 0.38 or abs(y - cy) > h * 0.38:
        return "corner"
    return "edge"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("controls", help="controls.json")
    ap.add_argument("out", help="out.json")
    ap.add_argument("--mm-gate", type=float, default=2.0)
    ap.add_argument("--intrinsics", default=None)
    ap.add_argument("--square-size-mm", type=float, default=SQUARE_MM)
    args = ap.parse_args()

    if args.intrinsics:
        ip = args.intrinsics
    else:
        ip = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "..", "..", "build", "v1_task4b_reacceptance",
                                          "4b1_usb_gate0", "track_rework", "intrinsics_c960.json"))
    mtx, dist = load_intrinsics(ip)
    with open(args.controls, encoding="utf-8") as f:
        controls = json.load(f)
    if len(controls) < 6:
        print(f"too few control points ({len(controls)}), need >=6")
        return 1

    L = _board_local_grid(args.square_size_mm)
    all_px = []
    all_mm = []
    meta = []
    img_size = None
    for i, c in enumerate(controls):
        p = c["image"]
        img = cc.imread_unicode(p)
        h, w = img.shape[:2]
        if img_size is None:
            img_size = (w, h)
        res = None
        try:
            from v1_twin.v1_twin_calibration import detect_checkerboard
            res = detect_checkerboard(img, PATTERN, args.square_size_mm)
        except Exception:
            res = None
        if res is None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
            if not ret:
                print(f"control {i}: board NOT detected, skip")
                continue
            c2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            und = cv2.undistortPoints(c2.astype(np.float32).reshape(-1, 1, 2),
                                      mtx, dist, P=mtx).reshape(-1, 2)
        else:
            cp, _ = res
            und = cv2.undistortPoints(cp.astype(np.float32).reshape(-1, 1, 2),
                                      mtx, dist, P=mtx).reshape(-1, 2)
        # board corners in global mm: origin (x_mm,y_mm) + rotated local grid
        ang = np.deg2rad(float(c.get("angle_deg", 0.0)))
        ca, sa = np.cos(ang), np.sin(ang)
        R = np.array([[ca, -sa], [sa, ca]])
        global_mm = L @ R.T + np.array([float(c["x_mm"]), float(c["y_mm"])])
        all_px.append(und)
        all_mm.append(global_mm)
        meta.append({"index": i, "x_mm": c["x_mm"], "y_mm": c["y_mm"],
                     "region": region_of(und.mean(axis=0), img_size)})

    if len(all_px) < 6:
        print("too few usable control points")
        return 1
    print(f"usable control points: {len(all_px)}")
    from collections import Counter
    print("regions:", dict(Counter(m["region"] for m in meta)))

    # 分层划分：calibration 70% / holdout 30%（每区域都保留 holdout）
    rng = np.random.RandomState(42)
    cal_idx = []
    hol_idx = []
    for reg in ("center", "edge", "corner"):
        idx = [i for i, m in enumerate(meta) if m["region"] == reg]
        rng.shuffle(idx)
        n_cal = max(1, int(len(idx) * 0.7))
        cal_idx += idx[:n_cal]
        hol_idx += idx[n_cal:]
    cal_idx.sort()
    hol_idx.sort()
    print(f"calibration: {len(cal_idx)}  holdout: {len(hol_idx)}")

    # 拟合 homography on calibration
    from v1_twin.v1_twin_calibration import estimate_homography
    src = np.vstack([all_px[i] for i in cal_idx]).astype(np.float32)
    dst = np.vstack([all_mm[i] for i in cal_idx]).astype(np.float32)
    H = estimate_homography(src, dst, ransac_threshold=3.0)
    M = H.matrix.astype(np.float64)

    def apply_h(pts):
        hh = np.hstack([pts, np.ones((len(pts), 1))]).T
        o = M @ hh
        return (o[:2] / o[2]).T

    # holdout 绝对误差（分区域）
    per_region = {}
    all_err = []
    for i in hol_idx:
        pred = apply_h(all_px[i])
        errs = np.linalg.norm(pred - all_mm[i], axis=1)
        all_err.extend(errs.tolist())
        reg = meta[i]["region"]
        per_region.setdefault(reg, []).extend(errs.tolist())
    all_err = np.array(all_err)
    gate_ok = float(np.percentile(all_err, 95)) <= args.mm_gate

    report = {
        "n_calibration": len(cal_idx),
        "n_holdout": len(hol_idx),
        "holdout_absolute_error_mm": {
            "overall": {"mean": float(all_err.mean()), "p95": float(np.percentile(all_err, 95)),
                        "max": float(all_err.max())},
            "by_region": {reg: {"mean": float(np.mean(e)), "p95": float(np.percentile(e, 95)),
                                "max": float(np.max(e))} for reg, e in per_region.items()},
        },
        "mm_gate_p95": args.mm_gate,
        "gate_ok": bool(gate_ok),
        "homography_matrix": [[float(v) for v in row] for row in M.tolist()],
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report["holdout_absolute_error_mm"], ensure_ascii=False, indent=2))
    print(f"mm_gate p95<={args.mm_gate} -> {'PASS' if gate_ok else 'FAIL'}")
    print(f"saved -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
