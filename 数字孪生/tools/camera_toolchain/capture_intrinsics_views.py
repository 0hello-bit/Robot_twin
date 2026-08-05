"""棋盘格多角度采集（相机内参标定用）。带实时窗口显示检测进度。

用法: python capture_intrinsics_views.py [index] [outdir]
用户手持 9x6 棋盘格在摄像头前缓慢转动（倾斜/旋转/远近），脚本自动保存
位姿互异（角点质心距离>MIN_DIST）的视图，最多 MAX_VIEWS 张。
按 ESC 可提前结束。全部保存后窗口自动关闭。
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
    os.path.dirname(os.path.abspath(__file__)), "calibration_views")
PATTERN = (9, 6)
MAX_VIEWS = 15
MIN_DIST = 50.0        # 角点质心至少移动 50px 才算新位姿
MIN_GAP_S = 1.5        # 相邻视图至少间隔 1.5s，强制换位姿
TOTAL_S = 150.0        # 总时长放宽到 150s
WIDTH, HEIGHT = 1280, 720

CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        cap, _aw, _ah = cc.open_camera(SOURCE, WIDTH, HEIGHT)
    except SystemExit as e:
        print(f"FAIL: {e}")
        return 1
    cv2.namedWindow("棋盘格多角度采集", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("棋盘格多角度采集", 960, 540)

    kept = []  # (centroid_px, path, save_tick)
    t0 = time.perf_counter()
    while len(kept) < MAX_VIEWS and (time.perf_counter() - t0) < TOTAL_S:
        ok, frame = cap.read()
        if not ok:
            continue
        save_img = frame.copy()   # 原始帧（无标记），用于保存；frame 用于显示
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        if ret:
            corners2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            cv2.drawChessboardCorners(frame, PATTERN, corners2, ret)
            now = time.perf_counter()
            centroid = corners2.reshape(-1, 2).mean(axis=0)
            unique = True
            for c, _, tsv in kept:
                if np.hypot(centroid[0] - c[0], centroid[1] - c[1]) <= MIN_DIST:
                    unique = False
                    break
                if (now - tsv) < MIN_GAP_S:   # 距上一视图不足间隔也判非唯一
                    unique = False
                    break
            if unique:
                p = os.path.join(OUT, f"view_{len(kept):02d}.png")
                ok2, buf = cv2.imencode(".png", save_img)
                if ok2:
                    with open(p, "wb") as f:
                        f.write(buf.tobytes())
                kept.append((centroid, p, now))
                print(f"DETECTED + saved view_{len(kept)-1:02d}  ({len(kept)}/{MAX_VIEWS})",
                      flush=True)
        color = (0, 255, 0) if ret else (0, 0, 255)
        cv2.putText(frame,
                    f"views: {len(kept)}/{MAX_VIEWS}  - 缓慢转动棋盘格(倾斜/旋转/远近)",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.putText(frame, "每张换一个明显角度，间隔约 2 秒", (10, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(frame, "按 ESC 结束", (10, 88),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imshow("棋盘格多角度采集", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"collected {len(kept)} views -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
