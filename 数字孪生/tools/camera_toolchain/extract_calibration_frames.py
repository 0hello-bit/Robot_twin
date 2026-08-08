"""从棋盘格视频解析内参标定视图（后处理）。

用法: py extract_calibration_frames.py [video.mp4] [outdir] [--grid 4] [--min-sharpness 100]

两步扫描：
  1. 逐帧检测 9x6 棋盘格，记录 (中心格子, 清晰度(Laplacian 方差), 表观纵横比)。
  2. 每个 4x4 空间格子取清晰度最高的 1-2 帧（纵横比差异大 = 角度不同），
     再回读视频保存选中帧。

过滤运动模糊（慢录是关键）；确保全画面覆盖（边缘畸变约束）。
输出 view_NN.png，之后用标定脚本（v1_twin_calibration.calibrate_camera）拟合。
"""
import argparse
import os
import sys

import cv2
import numpy as np

import camera_common as cc

PATTERN = cc.CHECKERBOARD_PATTERN
GRID = 4          # 4x4 空间网格
PER_CELL = 2      # 每格最多取 2 帧
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def board_aspect(corners2: np.ndarray) -> float:
    pts = corners2.reshape(-1, 2)
    w = np.hypot(pts[0][0] - pts[8][0], pts[0][1] - pts[8][1])
    h = np.hypot(pts[0][0] - pts[45][0], pts[0][1] - pts[45][1])
    return float(w / h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("outdir")
    ap.add_argument("--grid", type=int, default=GRID)
    ap.add_argument("--min-sharpness", type=float, default=100.0)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"FAIL: cannot open video {args.video}")
        return 1
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"video: {total} frames {w}x{h}")

    # Pass 1: scan, keep top candidates per cell
    best = {}   # (r,c) -> list of (sharpness, aspect, frame_idx)
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        if ret:
            sh = sharpness(gray)
            if sh >= args.min_sharpness:
                corners2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
                cx = corners2.reshape(-1, 2).mean(axis=0)
                c = min(args.grid - 1, int(cx[0] / w * args.grid))
                r = min(args.grid - 1, int(cx[1] / h * args.grid))
                asp = board_aspect(corners2)
                lst = best.setdefault((r, c), [])
                lst.append((sh, asp, idx))
                # keep top PER_CELL by sharpness
                lst.sort(key=lambda x: -x[0])
                del lst[PER_CELL:]
        idx += 1
        if idx % 500 == 0:
            print(f"  scanned {idx}/{total}", flush=True)
    cap.release()

    # select: per cell, keep frames whose aspect differs (angle diversity)
    selected = []   # (frame_idx, r, c, asp)
    for (r, c), cands in sorted(best.items()):
        picked = []
        for sh, asp, fi in cands:
            if all(abs(asp - a) > 0.15 for _, a in picked):
                picked.append((fi, asp))
        for fi, asp in picked:
            selected.append((fi, r, c, asp))
    selected.sort(key=lambda x: x[0])
    print(f"cells covered: {len(best)}/{args.grid*args.grid}, selected {len(selected)} frames")

    # Pass 2: re-read and save selected frames
    cap = cv2.VideoCapture(args.video)
    idx = 0
    sel_set = {fi for fi, _, _, _ in selected}
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in sel_set:
            p = os.path.join(args.outdir, f"view_{n:02d}.png")
            cc.imwrite_unicode(p, frame)
            n += 1
        idx += 1
    cap.release()
    print(f"saved {n} views -> {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
