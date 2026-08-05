"""Homography 多点位采集：棋盘格平放在赛道地面多个位置，覆盖画面。

用法: python capture_homography_positions.py [index] [outdir]
操作：把 9x6 棋盘格平放在赛道一个位置（完整入画、平贴地面），按 空格 保存一帧，
然后移到下一个位置（四角+中央，尽量铺满画面），继续按空格。按 ESC 结束。

保存: pos_00.png ... pos_NN.png（原始帧，未加标记）。之后离线检测角点合并拟合 homography。
"""
import os
import sys
import time

import cv2


import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import camera_common as cc

SOURCE = cc.get_camera_index(int(_sys.argv[1]) if len(_sys.argv) > 1 else None)
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "homography_positions")
PATTERN = (9, 6)
WIDTH, HEIGHT = 1280, 720


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        cap, _aw, _ah = cc.open_camera(SOURCE, WIDTH, HEIGHT)
    except SystemExit as e:
        print(f"FAIL: {e}")
        return 1
    cv2.namedWindow("Homography 多点位采集", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Homography 多点位采集", 960, 540)

    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, _ = cv2.findChessboardCorners(gray, PATTERN, None)
        color = (0, 255, 0) if ret else (0, 0, 255)
        cv2.putText(frame, f"已存 {n} 个位置 | 按空格保存当前棋盘格位置 | ESC 结束",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        if not ret:
            cv2.putText(frame, "未检测到棋盘格: 平放赛道地面、完整入画", (10, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        else:
            cv2.putText(frame, "检测到! 按空格保存", (10, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow("Homography 多点位采集", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break
        if key == 32:   # SPACE
            if not ret:
                print("NOT detected - 未保存（先让棋盘格完整入画）", flush=True)
                continue
            p = os.path.join(OUT, f"pos_{n:02d}.png")
            ok2, buf = cv2.imencode(".png", frame)
            if ok2:
                with open(p, "wb") as f:
                    f.write(buf.tobytes())
                n += 1
                print(f"saved pos_{n-1:02d}  ({n} 个位置)", flush=True)

    cap.release()
    cv2.destroyAllWindows()
    print(f"collected {n} positions -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
