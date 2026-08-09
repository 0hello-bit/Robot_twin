"""棋盘格等大矩形网格放置（R3 物理控制点，无需尺子）。

原理：棋盘格 120x75mm。窗口叠加与其等大的矩形网格（相邻连续平铺），
你把棋盘格**严丝合缝**放进每个格子。格子 (row,col) 的 mm 原点 =
(120*col, 75*row)（假设相邻格子物理连续 = 棋盘格自身当标尺，每次移动恰好
一个棋盘格宽/高）。

用法: py tile_placement.py [index] [outdir]

操作：
  1. 启动后先把棋盘格平放画面任意处 → 工具量出其图像尺寸。
  2. 网格行列数**自动** = 画面尺寸 ÷ 棋盘格图像尺寸（棋盘格等大平铺）。
  3. 按红色高亮格，把棋盘格严丝合缝放进去（与前一个格子物理连续）。
  4. 按 空格 保存（自动记录 mm = 120*col, 75*row）。ESC 随时结束。
产出: view_NN.png + controls.json（image, x_mm, y_mm, angle=0）。
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

import camera_common as cc

PATTERN = (9, 6)
SQUARE_MM = cc.GROUND_CHECKERBOARD_SQUARE_MM
MM_W = 8 * SQUARE_MM   # 120
MM_H = 5 * SQUARE_MM   # 75
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("index", nargs="?", type=int, default=None)
    ap.add_argument("outdir", nargs="?", default=None)
    ap.add_argument("--width", type=int, default=cc.DEFAULT_WIDTH)
    ap.add_argument("--height", type=int, default=cc.DEFAULT_HEIGHT)
    args = ap.parse_args()

    index = cc.get_camera_index(args.index)
    outdir = args.outdir or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "tile_controls")
    os.makedirs(outdir, exist_ok=True)
    cap, aw, ah = cc.open_camera(index, args.width, args.height)

    # Phase 1: 等待棋盘格入画，测量其图像尺寸 → 决定网格
    print("请先把棋盘格平放画面任意处（量尺寸用）...", flush=True)
    tile_w = tile_h = None
    while tile_w is None:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        if ret:
            c2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            pts = c2.reshape(-1, 2)
            wpx = float(np.hypot(pts[0][0] - pts[8][0], pts[0][1] - pts[8][1]))
            hpx = float(np.hypot(pts[0][0] - pts[45][0], pts[0][1] - pts[45][1]))
            tile_w, tile_h = int(wpx), int(hpx)
            print(f"棋盘格图像尺寸: {tile_w}x{tile_h}px", flush=True)
        cv2.putText(frame, "把棋盘格平放任意处(量尺寸)...", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imshow("Tile 放置", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            cap.release(); cv2.destroyAllWindows(); return 1

    # 网格行列数自动 = 画面 ÷ 棋盘格图像尺寸（等大平铺）
    cols = max(1, aw // max(tile_w, 1))
    rows = max(1, ah // max(tile_h, 1))
    total = cols * rows
    print(f"棋盘格图像尺寸: {tile_w}x{tile_h}px -> 网格 {cols}x{rows}={total} 格", flush=True)
    controls = []
    n = 0
    cv2.namedWindow("Tile 放置", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Tile 放置", 960, 540)
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        save_img = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        # 当前棋盘格中心落在哪个格子
        cur_cell = None
        if ret:
            c2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            cx = c2.reshape(-1, 2).mean(axis=0)
            cv2.drawChessboardCorners(frame, PATTERN, c2, ret)
            if cx[0] < cols * tile_w and cx[1] < rows * tile_h:
                cur_cell = (int(cx[1] // tile_h), int(cx[0] // tile_w))

        # 绘制网格
        covered = set((int(c["x_mm"] / MM_W), int(c["y_mm"] / MM_H)) for c in controls)
        nxt = None
        for r in range(rows):
            for c in range(cols):
                x0, y0 = c * tile_w, r * tile_h
                cv2.rectangle(frame, (x0, y0), (x0 + tile_w, y0 + tile_h),
                              (0, 255, 0) if (r, c) in covered else (255, 255, 255), 2)
                if (r, c) not in covered and nxt is None:
                    nxt = (r, c)
        if nxt is not None:
            x0, y0 = nxt[1] * tile_w, nxt[0] * tile_h
            cv2.rectangle(frame, (x0, y0), (x0 + tile_w, y0 + tile_h), (0, 0, 255), 3)
            cv2.putText(frame, f"NEXT ({nxt[0]},{nxt[1]}) mm=({MM_W*nxt[1]:.0f},{MM_H*nxt[0]:.0f})",
                        (x0 + 4, y0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        cv2.putText(frame, f"saved {len(controls)}/{total}  空格保存  ESC结束(可提前)  放 {nxt} 格",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, "严丝合缝放进红色格(与前格物理连续, 用棋盘格当标尺)", (10, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.imshow("Tile 放置", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27 or len(controls) >= total:
            break
        if key == 32:   # SPACE
            if cur_cell is None:
                print("未检测到棋盘格/不在网格内", flush=True)
                continue
            r, c = cur_cell
            if (r, c) in covered:
                print(f"格子({r},{c})已保存，请移到下一个", flush=True)
                continue
            p = os.path.join(outdir, f"view_{n:02d}.png")
            cc.imwrite_unicode(p, save_img)
            controls.append({"image": os.path.abspath(p),
                             "x_mm": MM_W * c, "y_mm": MM_H * r, "angle_deg": 0})
            n += 1
            print(f"saved view_{n-1:02d} cell({r},{c}) mm=({MM_W*c:.0f},{MM_H*r:.0f})", flush=True)

    cap.release()
    cv2.destroyAllWindows()
    cj = os.path.join(outdir, "controls.json")
    with open(cj, "w", encoding="utf-8") as f:
        json.dump(controls, f, ensure_ascii=False, indent=2)
    print(f"saved {len(controls)} control points -> {cj}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
