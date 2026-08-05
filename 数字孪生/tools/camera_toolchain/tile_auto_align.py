"""棋盘格自动对齐放置（R3 控制点，工具检测"严丝合缝"，无需人眼/尺子）。

原理：棋盘格 120x75mm。工具用角点检测实时测量棋盘格左上内角位置，
与目标格原点对齐（亚像素级）。对齐稳定 N 帧后**自动保存**，无需按空格。

mm 坐标 = 目标格索引 × 棋盘格尺寸（120*col, 75*row），假设网格物理连续。

用法: py tile_auto_align.py [index] [outdir] [--tolerance 6]

操作：
  1. 先把棋盘格平放画面任意处 → 量尺寸。
  2. 网格（棋盘格等大连续平铺）生成，红色=当前目标格原点。
  3. 把棋盘格滑到红色目标附近，工具检测到角点对齐（稳定 ~0.4s）→ 自动保存并跳下一格。
  4. ESC 结束。
产出: view_NN.png + controls.json。
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

import camera_common as cc

PATTERN = (9, 6)
SQUARE_MM = 15.0
MM_W = 8 * SQUARE_MM   # 120
MM_H = 5 * SQUARE_MM   # 75
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)
STABLE_FRAMES = 12   # 对齐稳定帧数


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("index", nargs="?", type=int, default=None)
    ap.add_argument("outdir", nargs="?", default=None)
    ap.add_argument("--tolerance", type=float, default=6.0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    index = cc.get_camera_index(args.index)
    outdir = args.outdir or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "tile_auto_controls")
    os.makedirs(outdir, exist_ok=True)
    cap, aw, ah = cc.open_camera(index, args.width, args.height)

    # Phase 1: 量棋盘格图像尺寸
    print("请把棋盘格平放画面任意处（量尺寸）...", flush=True)
    tw = th = None
    while tw is None:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        if ret:
            c2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            pts = c2.reshape(-1, 2)
            tw = int(np.hypot(pts[0][0] - pts[8][0], pts[0][1] - pts[8][1]))
            th = int(np.hypot(pts[0][0] - pts[45][0], pts[0][1] - pts[45][1]))
            print(f"棋盘格尺寸: {tw}x{th}px", flush=True)
        cv2.putText(frame, "把棋盘格平放任意处(量尺寸)...", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imshow("Tile 自动对齐", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            cap.release(); cv2.destroyAllWindows(); return 1

    # 网格目标原点（从画面左上连续平铺）
    cols = max(1, aw // tw)
    rows = max(1, ah // th)
    total = cols * rows
    # 目标顺序：行优先
    targets = [(r, c) for r in range(rows) for c in range(cols)]
    print(f"网格 {cols}x{rows}={total} 格, 容差 {args.tolerance}px", flush=True)

    controls = []
    n = 0
    ti = 0   # 当前目标索引
    stable = 0
    cv2.namedWindow("Tile 自动对齐", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Tile 自动对齐", 960, 540)
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        save_img = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        tl_corner = None
        if ret:
            c2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            cv2.drawChessboardCorners(frame, PATTERN, c2, ret)
            tl_corner = c2.reshape(-1, 2)[0]   # 棋盘格左上内角

        # 当前目标格原点（像素）
        tr, tc = targets[ti] if ti < total else (None, None)
        tx, ty = tc * tw, tr * th

        # 对齐检测
        captured = False
        if tl_corner is not None and tr is not None:
            d = float(np.hypot(tl_corner[0] - tx, tl_corner[1] - ty))
            if d <= args.tolerance:
                stable += 1
                if stable >= STABLE_FRAMES:
                    p = os.path.join(outdir, f"view_{n:02d}.png")
                    cc.imwrite_unicode(p, save_img)
                    controls.append({"image": os.path.abspath(p),
                                     "x_mm": MM_W * tc, "y_mm": MM_H * tr, "angle_deg": 0})
                    n += 1
                    print(f"AUTO saved view_{n-1:02d} cell({tr},{tc}) mm=({MM_W*tc:.0f},{MM_H*tr:.0f})",
                          flush=True)
                    stable = 0
                    ti += 1
                    captured = True
            else:
                stable = 0

        # 绘制
        for r in range(rows):
            for c in range(cols):
                x0, y0 = c * tw, r * th
                cv2.rectangle(frame, (x0, y0), (x0 + tw, y0 + th), (100, 100, 100), 1)
        if tr is not None:
            cv2.rectangle(frame, (tx, ty), (tx + tw, ty + th), (0, 0, 255), 2)
            cv2.circle(frame, (int(tx), int(ty)), 4, (0, 0, 255), -1)
            cv2.putText(frame, f"NEXT({tr},{tc}) mm=({MM_W*tc:.0f},{MM_H*tr:.0f}) 对齐 {stable}/{STABLE_FRAMES}",
                        (tx + 4, ty - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        if tl_corner is not None:
            cv2.circle(frame, (int(tl_corner[0]), int(tl_corner[1])), 5, (255, 0, 0), -1)
        cv2.putText(frame, f"saved {n}/{total}  把棋盘格左上角滑到红点, 自动捕捉  ESC结束",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow("Tile 自动对齐", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27 or ti >= total:
            break

    cap.release()
    cv2.destroyAllWindows()
    cj = os.path.join(outdir, "controls.json")
    with open(cj, "w", encoding="utf-8") as f:
        json.dump(controls, f, ensure_ascii=False, indent=2)
    print(f"saved {len(controls)} control points -> {cj}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
