"""内参标定多角度采集 v2 —— 强制空间覆盖（4 角 + 4 边 + 中央）。

根因：旧标定视图棋盘格全在中右区域，边缘畸变未约束 → undistort 边缘错误。
本工具把画面分为 3x3 网格，引导用户把棋盘格放到每个格子（不同角度），
覆盖全部 9 格后结束。每个格子保存 1-2 张，共约 12-18 张。

操作：手持棋盘格（倾斜角度）放到画面不同区域，窗口右上角显示 3x3 覆盖
地图（绿=已覆盖）。每进入一个未覆盖的格子且位姿有变化就自动保存。
按 ESC 提前结束。
"""
import os
import sys
import time

import cv2
import numpy as np


import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import camera_common as cc

SOURCE = cc.get_camera_index(int(_sys.argv[1]) if len(_sys.argv) > 1 else None)
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "calibration_views_coverage")
PATTERN = (9, 6)
GRID = 3  # 3x3
MIN_DIST = 40.0
WIDTH, HEIGHT = 1280, 720
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        cap, _aw, _ah = cc.open_camera(SOURCE, WIDTH, HEIGHT)
    except SystemExit as e:
        print(f"FAIL: {e}")
        return 1
    cv2.namedWindow("多角度覆盖采集", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("多角度覆盖采集", 960, 540)

    covered = [[False] * GRID for _ in range(GRID)]
    kept = []  # (cell, centroid)
    n = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 180.0:
        ok, frame = cap.read()
        if not ok:
            continue
        save_img = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        if ret:
            corners2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            cv2.drawChessboardCorners(frame, PATTERN, corners2, ret)
            centroid = corners2.reshape(-1, 2).mean(axis=0)
            cg = min(GRID - 1, int(centroid[0] / WIDTH * GRID))
            rg = min(GRID - 1, int(centroid[1] / HEIGHT * GRID))
            if not covered[rg][cg]:
                unique = all(
                    np.hypot(centroid[0] - c[0], centroid[1] - c[1]) > MIN_DIST
                    for _, c in kept
                )
                if unique:
                    p = os.path.join(OUT, f"view_{n:02d}.png")
                    ok2, buf = cv2.imencode(".png", save_img)
                    if ok2:
                        with open(p, "wb") as f:
                            f.write(buf.tobytes())
                    covered[rg][cg] = True
                    kept.append(((rg, cg), centroid))
                    n += 1
                    print(f"saved view_{n-1:02d}  cell({rg},{cg})  {n} total", flush=True)

        # draw coverage map (top-right 3x3)
        cell = 40
        ox, oy = WIDTH - 3 * cell - 20, 20
        ncov = 0
        for r in range(GRID):
            for c in range(GRID):
                x0 = ox + c * cell
                y0 = oy + r * cell
                col = (0, 255, 0) if covered[r][c] else (0, 0, 255)
                cv2.rectangle(frame, (x0, y0), (x0 + cell, y0 + cell), col, 2)
                if covered[r][c]:
                    ncov += 1
        cv2.putText(frame, f"coverage {ncov}/9  saved {n}",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0) if ncov == 9 else (0, 0, 255), 2)
        cv2.putText(frame, "棋盘格放到红色格子(不同角度), 覆盖全9格", (10, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.putText(frame, "ESC 结束", (10, 88),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imshow("多角度覆盖采集", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break
        if ncov == 9:
            time.sleep(0.5)
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"collected {n} views, coverage {sum(sum(r) for r in covered)}/9 -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
