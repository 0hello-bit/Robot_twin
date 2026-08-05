"""实时引导采集：4x4 覆盖地图 + 质量反馈（清晰度/平贴度），存好检测。

用法: py guided_capture.py [index] [outdir] [--grid 4] [--min-sharpness 150]

操作：纸棋盘格平贴地面，按提示放到"未覆盖"格子；质量达标自动保存该格。
窗口实时显示：
  - 右上角 4x4 覆盖地图（绿=已保存，红=未覆盖，黄=检测到但质量不达标）
  - 当前检测质量：清晰度、平贴度（行/列宽一致性）
  - 下一步提示（放哪个格子）+ 质量警告（模糊/纸没压平）
全部格子覆盖后自动结束，或按 ESC。

产出：view_NN.png（原始帧）到 outdir，供 mosaic_homography.py 拼接。
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np

import camera_common as cc

PATTERN = (9, 6)
GRID = 4
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)


def flatness(corners2):
    """平贴度：行宽/列高一致性。纸平贴地面 + 摄像头垂直 → 应接近平行四边形。

    返回 (max_dev_pct, 提示)。dev 越大越不平贴（纸翘起/倾斜）。
    """
    pts = corners2.reshape(-1, 2)
    row_w = [float(np.hypot(pts[r * 9 + 8][0] - pts[r * 9 + 0][0],
                            pts[r * 9 + 8][1] - pts[r * 9 + 0][1])) for r in range(6)]
    col_h = [float(np.hypot(pts[5 * 9 + c][0] - pts[c][0],
                            pts[5 * 9 + c][1] - pts[c][1])) for c in range(9)]
    rw = np.array(row_w); ch = np.array(col_h)
    dev_r = (rw.max() - rw.min()) / rw.mean()
    dev_c = (ch.max() - ch.min()) / ch.mean()
    dev = max(dev_r, dev_c)
    return dev, ("纸不平贴，请压平" if dev > 0.04 else "平贴 OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("index", nargs="?", type=int, default=None)
    ap.add_argument("outdir", nargs="?", default=None)
    ap.add_argument("--grid", type=int, default=GRID)
    ap.add_argument("--min-sharpness", type=float, default=150.0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    index = cc.get_camera_index(args.index)
    outdir = args.outdir or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "guided_captures")
    os.makedirs(outdir, exist_ok=True)

    cap, aw, ah = cc.open_camera(index, args.width, args.height)
    print(f"camera index {index} {aw}x{ah}, output -> {outdir}")
    cv2.namedWindow("引导采集", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("引导采集", 960, 540)

    covered = [[False] * args.grid for _ in range(args.grid)]
    n = 0
    # cell order: 优先未覆盖的格子
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        save_img = frame.copy()   # 原始帧（无网格叠加），用于保存
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        status = "未检测到棋盘格"
        color = (0, 0, 255)
        ready_cell = None
        if ret:
            sh = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            corners2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            cv2.drawChessboardCorners(frame, PATTERN, corners2, ret)
            cx = corners2.reshape(-1, 2).mean(axis=0)
            cg = min(args.grid - 1, int(cx[0] / aw * args.grid))
            rg = min(args.grid - 1, int(cx[1] / ah * args.grid))
            dev, flat_txt = flatness(corners2)

            if covered[rg][cg]:
                status = f"格子({rg},{cg})已覆盖，请移到下一个"
                color = (0, 255, 0)
            elif sh < args.min_sharpness:
                status = f"模糊(sh={sh:.0f}<{args.min_sharpness:.0f})，放稳/慢一点"
                color = (0, 165, 255)
            elif dev > 0.04:
                status = f"{flat_txt} (偏差{dev*100:.1f}%)，把纸压平"
                color = (0, 165, 255)
            else:
                ready_cell = (rg, cg)
                status = f"✓ 格子({rg},{cg})达标，按 空格 保存"
                color = (0, 255, 0)

        # 4x4 网格叠加在实时画面上（格子线 + 目标格高亮 + 坐标标注）
        cw, ch = aw // args.grid, ah // args.grid
        overlay = frame.copy()
        for r in range(1, args.grid):
            cv2.line(overlay, (r * cw, 0), (r * cw, ah), (255, 255, 255), 1)
        for c in range(1, args.grid):
            cv2.line(overlay, (0, c * ch), (aw, c * ch), (255, 255, 255), 1)
        ncov = 0
        for r in range(args.grid):
            for c in range(args.grid):
                x0, y0 = c * cw, r * ch
                if covered[r][c]:
                    ncov += 1
                    cv2.putText(overlay, f"({r},{c})", (x0 + 4, y0 + 16),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        # 目标格高亮（下一个未覆盖）
        if ncov < args.grid * args.grid:
            nxt = None
            for r in range(args.grid):
                for c in range(args.grid):
                    if not covered[r][c]:
                        nxt = (r, c); break
                if nxt: break
            x0, y0 = nxt[1] * cw, nxt[0] * ch
            cv2.rectangle(overlay, (x0 + 2, y0 + 2), (x0 + cw - 2, y0 + ch - 2),
                          (0, 0, 255), 3)
            cv2.putText(overlay, f"NEXT ({nxt[0]},{nxt[1]})", (x0 + 4, y0 + 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        frame = cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)

        # 右上角小覆盖地图
        cell = 40
        ox, oy = aw - args.grid * cell - 20, 20
        for r in range(args.grid):
            for c in range(args.grid):
                x0, y0 = ox + c * cell, oy + r * cell
                col = (0, 255, 0) if covered[r][c] else (0, 0, 255)
                cv2.rectangle(frame, (x0, y0), (x0 + cell, y0 + cell), col, 2)
        cv2.putText(frame, f"coverage {ncov}/{args.grid*args.grid}  saved {n}",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.putText(frame, status, (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        if ncov < args.grid * args.grid:
            # 提示下一个未覆盖格
            nxt = None
            for r in range(args.grid):
                for c in range(args.grid):
                    if not covered[r][c]:
                        nxt = (r, c); break
                if nxt: break
            cv2.putText(frame, f"下一步: 放 {nxt} 区域 (红格)", (10, 88),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        else:
            cv2.putText(frame, "全部覆盖完成! 按 ESC 结束", (10, 88),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow("引导采集", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27 or ncov == args.grid * args.grid:
            break
        if key == 32:   # SPACE: 手动保存当前达标格
            if ready_cell is not None:
                rg, cg = ready_cell
                if not covered[rg][cg]:
                    covered[rg][cg] = True
                    p = os.path.join(outdir, f"view_{n:02d}.png")
                    cc.imwrite_unicode(p, save_img)
                    n += 1
                    print(f"saved view_{n-1:02d} cell({rg},{cg}) — 请量 x_mm,y_mm 报给我", flush=True)
            else:
                print("not ready: 棋盘格未检测到或质量不达标（看窗口提示）", flush=True)

    cap.release()
    cv2.destroyAllWindows()
    print(f"collected {n} views, coverage {ncov}/{args.grid*args.grid} -> {outdir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
