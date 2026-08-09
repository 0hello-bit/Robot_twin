"""内参标定多角度采集 v3 —— 带目标格引导的 4x4 空间覆盖。

根因：旧标定视图棋盘格全在中右区域，边缘畸变未约束 → undistort 边缘错误。
本工具把画面分为 4x4 网格，用黄色目标格引导用户按顺序移动棋盘格，
已完成格显示为绿色，覆盖全部 16 格后结束。

操作：手持棋盘格（倾斜角度）放到窗口右上角黄色目标格，棋盘中心进入目标格
且位姿有变化就自动保存，然后自动切换到下一个目标格。
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
from camera_coverage_guidance import (
    GRID,
    TARGET_ORDER,
    cell_bounds,
    cell_for_centroid,
    next_target,
    target_number,
)

PATTERN = cc.CHECKERBOARD_PATTERN
MIN_DIST = 40.0
WIDTH, HEIGHT = cc.DEFAULT_WIDTH, cc.DEFAULT_HEIGHT
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)


def main():
    source = cc.get_camera_index(int(_sys.argv[1]) if len(_sys.argv) > 1 else None)
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "calibration_views_coverage")
    os.makedirs(out, exist_ok=True)
    try:
        cap, _aw, _ah = cc.open_camera(source, WIDTH, HEIGHT)
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
            cell = cell_for_centroid(centroid, WIDTH, HEIGHT)
            target = next_target(covered)
            if target is not None and cell == target:
                unique = all(
                    np.hypot(centroid[0] - c[0], centroid[1] - c[1]) > MIN_DIST
                    for _, c in kept
                )
                if unique:
                    p = os.path.join(out, f"view_{n:02d}.png")
                    ok2, buf = cv2.imencode(".png", save_img)
                    if ok2:
                        with open(p, "wb") as f:
                            f.write(buf.tobytes())
                    covered[cell[0]][cell[1]] = True
                    kept.append((cell, centroid))
                    n += 1
                    print(f"saved view_{n-1:02d}  cell({cell[0]},{cell[1]})  {n} total", flush=True)

        # Draw the 4x4 target map in the top-right corner.
        map_cell = 42
        ox, oy = WIDTH - GRID * map_cell - 24, 24
        ncov = 0
        target = next_target(covered)
        for r in range(GRID):
            for c in range(GRID):
                x0 = ox + c * map_cell
                y0 = oy + r * map_cell
                if covered[r][c]:
                    color = (0, 200, 0)
                    ncov += 1
                elif target == (r, c):
                    color = (0, 220, 255)
                else:
                    color = (120, 120, 120)
                thickness = 4 if target == (r, c) else 2
                cv2.rectangle(frame, (x0, y0), (x0 + map_cell, y0 + map_cell), color, thickness)
                cv2.putText(frame, str(target_number((r, c))), (x0 + 12, y0 + 29),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        if target is None:
            status = f"DONE {ncov}/{GRID * GRID}"
        else:
            status = f"TARGET {target_number(target)}/{GRID * GRID}  MOVE CENTER TO YELLOW"
        cv2.putText(frame, status,
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0) if target is None else (0, 220, 255), 2)
        if ret:
            cv2.circle(frame, tuple(np.round(centroid).astype(int)), 8, (255, 0, 255), -1)
            cv2.putText(frame, f"CURRENT CELL {cell[0] * GRID + cell[1] + 1}", (10, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)
        cv2.putText(frame, "Green=done  Yellow=next  ESC=stop", (10, 88),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imshow("多角度覆盖采集", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break
        if ncov == GRID * GRID:
            time.sleep(0.5)
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"collected {n} views, coverage {sum(sum(r) for r in covered)}/{GRID * GRID} -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
