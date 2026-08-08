"""从棋盘格视频拼接全局 homography（平面镶嵌 / bundle adjustment）。

原理：同一固定摄像头 + 同一地面平面，所有帧的棋盘格共享一个全局 homography H
（px→全局 mm）。每帧棋盘格有已知局部 mm 几何（9x6 网格 @15mm = 120x75mm）。
约束：H 把每帧棋盘格映射为与局部几何**全等**的刚体（所有角点间距离不变）。
对 H 做最优化（距离保持），不需要尺子量各位置偏移。

用法: py mosaic_homography.py [video.mp4] [out.json] [--max-frames 40] [--grid 4]

输出: out.json = {matrix, reproj_stats, used_frames, board_size_check}
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from scipy.optimize import least_squares

import camera_common as cc

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "simulation", "digital_twin")))

PATTERN = cc.CHECKERBOARD_PATTERN
SQUARE_MM = cc.CHECKERBOARD_SQUARE_MM
GRID = 4
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)


def _local_grid(square_mm=SQUARE_MM):
    cols, rows = PATTERN
    L = np.zeros((cols * rows, 2), dtype=np.float64)
    L[:, 0] = (np.arange(cols * rows) % cols) * square_mm
    L[:, 1] = (np.arange(cols * rows) // cols) * square_mm
    return L


def extract_detections(video_path, mtx, dist, max_frames=40, grid=GRID,
                       square_mm=SQUARE_MM):
    """扫描视频，按空间网格 + 清晰度选多样检测。返回 (undist_corners, local_mm)。"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open video {video_path}")
    L = _local_grid(square_mm)
    best = {}   # (r,c) -> (sharpness, undist_corners)
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        if ret:
            sh = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            if sh >= 80:
                c2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
                cx = c2.reshape(-1, 2).mean(axis=0)
                cg = min(grid - 1, int(cx[0] / gray.shape[1] * grid))
                rg = min(grid - 1, int(cx[1] / gray.shape[0] * grid))
                if (rg, cg) not in best or sh > best[(rg, cg)][0]:
                    und = cv2.undistortPoints(c2.astype(np.float32).reshape(-1, 1, 2),
                                              mtx, dist, P=mtx).reshape(-1, 2)
                    best[(rg, cg)] = (sh, und.astype(np.float64))
        idx += 1
    cap.release()
    dets = [v[1] for v in best.values()]
    print(f"extracted {len(dets)} detections covering {len(best)}/{grid*grid} cells")
    return dets, L


def _apply_h(H, pts):
    pts_h = np.hstack([pts, np.ones((len(pts), 1))]).T   # (3, N)
    out = H @ pts_h
    return (out[:2] / out[2]).T                            # (N, 2)


def fit_global_homography(dets, L):
    """Bundle adjustment：H（px→全局mm）+ 每位置刚体变换 (angle, tx, ty)。

    约束：H 把每帧棋盘格映射为其局部几何的刚体变换（R_i·L + t_i）。
    params = H(8) + 每位置 3 (i>=1)；位置 0 固定 gauge（angle=tx=ty=0）。
    比纯距离约束更稳健（显式刚体，避免局部极小）。
    """
    from v1_twin.v1_twin_calibration import estimate_homography
    n_pl = len(dets)
    H0 = estimate_homography(dets[0].astype(np.float32), L.astype(np.float32),
                             ransac_threshold=3.0).matrix
    x0 = [H0[0, 0], H0[0, 1], H0[0, 2], H0[1, 0], H0[1, 1], H0[1, 2], H0[2, 0], H0[2, 1]]
    for _ in range(1, n_pl):
        x0 += [0.0, 0.0, 0.0]
    x0 = np.array(x0, dtype=float)

    # 预计算每位置的局部刚性目标（旋转+平移会由优化求出）
    def resid(x):
        H = np.array([[x[0], x[1], x[2]], [x[3], x[4], x[5]], [x[6], x[7], 1.0]])
        r = []
        # 位置 0: gauge anchor，直接映射到局部坐标
        r.append((_apply_h(H, dets[0]) - L).ravel())
        for i in range(1, n_pl):
            ang, tx, ty = x[8 + 3 * (i - 1)], x[9 + 3 * (i - 1)], x[10 + 3 * (i - 1)]
            ca, sa = np.cos(ang), np.sin(ang)
            R = np.array([[ca, -sa], [sa, ca]])
            target = L @ R.T + np.array([tx, ty])
            r.append((_apply_h(H, dets[i]) - target).ravel())
        return np.concatenate(r)

    res = least_squares(resid, x0, method="lm", max_nfev=500, xtol=1e-12, ftol=1e-12)
    H = np.array([[res.x[0], res.x[1], res.x[2]],
                  [res.x[3], res.x[4], res.x[5]],
                  [res.x[6], res.x[7], 1.0]])
    return H, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--max-frames", type=int, default=40)
    ap.add_argument("--grid", type=int, default=GRID)
    ap.add_argument("--intrinsics", default=None)
    ap.add_argument("--square-size-mm", type=float, default=SQUARE_MM)
    args = ap.parse_args()

    # intrinsics: default to the authoritative full-cov file
    if args.intrinsics:
        ip = args.intrinsics
    else:
        ip = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "build",
            "v1_task4b_reacceptance", "4b1_usb_gate0", "track_rework", "intrinsics_c960.json"))
    with open(ip, encoding="utf-8") as f:
        intr = json.load(f)
    mtx = np.array(intr["camera_matrix"]); dist = np.array(intr["dist_coeffs"])

    dets, L = extract_detections(
        args.video, mtx, dist, args.max_frames, args.grid, args.square_size_mm
    )
    if len(dets) < 4:
        raise SystemExit("too few detections")
    H, res = fit_global_homography(dets, L)
    print(f"optimization: cost={res.cost:.3f}, success={res.success}, nfev={res.nfev}")

    # verification: board size at each detection
    board_w = (PATTERN[0] - 1) * args.square_size_mm
    board_h = (PATTERN[1] - 1) * args.square_size_mm
    sizes = []
    for P in dets:
        m = _apply_h(H, P)
        w = np.hypot(m[0][0] - m[8][0], m[0][1] - m[8][1])
        h = np.hypot(m[0][0] - m[45][0], m[0][1] - m[45][1])
        sizes.append((w, h, max(abs(w - board_w) / board_w,
                                 abs(h - board_h) / board_h) * 100))
    sizes = np.array(sizes)
    print(f"board-size check (expected {board_w:.1f}x{board_h:.1f} mm, error%):")
    print(f"  宽 mean={sizes[:,0].mean():.1f} 高 mean={sizes[:,1].mean():.1f} "
          f"误差 mean={sizes[:,2].mean():.1f}% max={sizes[:,2].max():.1f}%")

    out = {
        "type": "HomographyTransform",
        "matrix": [[float(v) for v in row] for row in H.tolist()],
        "source": f"mosaic from {args.video} ({len(dets)} detections)",
        "board_size_check": {
            "width_mean_mm": float(sizes[:, 0].mean()),
            "height_mean_mm": float(sizes[:, 1].mean()),
            "error_mean_pct": float(sizes[:, 2].mean()),
            "error_max_pct": float(sizes[:, 2].max()),
        },
        "optimization_cost": float(res.cost),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"saved -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
