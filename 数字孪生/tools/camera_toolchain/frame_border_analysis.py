"""检查当前画面里"暗结构"是否贴边/被裁切（对应 4B-2 input_cropped 问题）。

方法：把灰度阈值化得到"暗区域"（赛道黑线候选），统计：
  - 暗像素是否触到上下左右四边（触边 count）
  - 暗区域包围盒与四周留白（px）
注意：这不是赛道识别，只是构图 sanity check。场景里有深色桌面/物体也会被判为暗，
结论只用于判断"画面四周是否留白、底边是否有内容顶到边"。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "simulation", "digital_twin"))

import cv2
import numpy as np


import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import camera_common as cc

SOURCE = cc.get_camera_index(int(_sys.argv[1]) if len(_sys.argv) > 1 else None)
WIDTH, HEIGHT = cc.DEFAULT_WIDTH, cc.DEFAULT_HEIGHT
THRESH = 80      # 灰度 < 80 视为暗
EDGE = 2         # 距边缘 <=2px 视为贴边
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    try:
        cap, _aw, _ah = cc.open_camera(SOURCE, WIDTH, HEIGHT)
    except SystemExit as e:
        print(f"FAIL: {e}")
        return 1
    for _ in range(5):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print("FAIL: frame read")
        return 1

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    dark = gray < THRESH

    h, w = dark.shape
    ys, xs = np.nonzero(dark)
    n_dark = int(len(ys))
    total = h * w
    print(f"frame {w}x{h}; dark(<{THRESH}) pixels: {n_dark} ({100*n_dark/total:.2f}%)")

    # border touch
    touches = {}
    touches['top']    = int((ys < EDGE).sum())
    touches['bottom'] = int((ys >= h - EDGE).sum())
    touches['left']   = int((xs < EDGE).sum())
    touches['right']  = int((xs >= w - EDGE).sum())
    print("dark pixels within 2px of each edge:")
    for k, v in touches.items():
        print(f"  {k:6s}: {v}")

    # bounding box + margin
    if n_dark:
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        print(f"dark bbox: y[{y0},{y1}] x[{x0},{x1}]")
        print(f"margins (px)  top={y0}  bottom={h-1-y1}  left={x0}  right={w-1-x1}")
        # if any dark pixel within 2px of border -> crop risk
        crop_risk = any(touches.values())
        print(f"border-touch count total: {sum(touches.values())}")
        print(f"CROP RISK: {'YES - 暗内容贴边，构图需调整' if crop_risk else 'no - 四周有暗区留白'}")

    # 把暗掩码叠加保存便于用户核对
    overlay = frame.copy()
    overlay[dark] = (0, 0, 255)
    ok_enc, buf = cv2.imencode(".png", overlay)
    if ok_enc:
        with open(os.path.join(OUT_DIR, "dark_overlay.png"), "wb") as f:
            f.write(buf.tobytes())
        print("saved dark_overlay.png (dark->red, for visual check)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
