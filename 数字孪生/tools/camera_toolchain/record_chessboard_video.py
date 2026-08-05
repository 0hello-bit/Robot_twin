"""录制棋盘格多角度视频（内参标定用）。

用法: py record_chessboard_video.py [index] [out.mp4] [seconds]
操作：手持 9x6 棋盘格在摄像头前**慢速**扫过全画面（4 角 + 4 边 + 中央），
并在各处变换倾角/旋转。录制 ~90s。按 ESC 提前结束。

要点：
- 移动要慢（减少运动模糊，保证角点清晰可检测）。
- 全程覆盖画面 4 角与边缘——畸变标定的关键是边缘覆盖。
- 之后用 extract_calibration_frames.py 从视频解析出标定视图。
"""
import os
import sys
import time

import cv2

import camera_common as cc

SOURCE = cc.get_camera_index(int(sys.argv[1]) if len(sys.argv) > 1 else None)
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "chessboard_calibration.mp4")
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 90.0
WIDTH, HEIGHT = 1280, 720
FPS = 30.0


def main():
    cap, aw, ah = cc.open_camera(SOURCE, WIDTH, HEIGHT)
    print(f"camera index {SOURCE}, actual {aw}x{ah}")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(OUT, fourcc, FPS, (aw, ah))
    if not out.isOpened():
        print(f"FAIL: cannot open VideoWriter -> {OUT}")
        return 1

    cv2.namedWindow("录制棋盘格视频", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("录制棋盘格视频", 960, 540)

    # Phase 1: 等待检测到棋盘格（稳定连续 15 帧 ~0.5s）后才开始录制
    print("等待棋盘格入画（绿色检测到后自动开始录制）...", flush=True)
    stable = 0
    while stable < 15:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, _ = cv2.findChessboardCorners(gray, (9, 6), None)
        stable = stable + 1 if ret else 0
        color = (0, 255, 0) if ret else (0, 0, 255)
        cv2.putText(frame, "等待棋盘格入画... 稳定检测后自动开始录制", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.imshow("录制棋盘格视频", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            cap.release(); cv2.destroyAllWindows()
            print("aborted before recording"); return 1
    print("检测到棋盘格，开始录制！", flush=True)

    # Phase 2: 录制（贴地滑动覆盖全画面）
    t0 = time.perf_counter()
    frames = 0
    while time.perf_counter() - t0 < SECONDS:
        ok, frame = cap.read()
        if not ok:
            continue
        out.write(frame)
        frames += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, _ = cv2.findChessboardCorners(gray, (9, 6), None)
        color = (0, 255, 0) if ret else (0, 0, 255)
        cv2.putText(frame, f"录制中 {time.perf_counter()-t0:.0f}/{SECONDS:.0f}s  检测到棋盘格={bool(ret)}",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.putText(frame, "贴地滑动扫过全画面(4角+4边)+变换角度  ESC结束",
                    (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.imshow("录制棋盘格视频", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break

    out.release()
    cap.release()
    cv2.destroyAllWindows()
    print(f"recorded {frames} frames -> {OUT} ({frames/FPS:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
