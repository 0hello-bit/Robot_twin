"""把摄像头当前画面降采样成 ASCII 亮度图 + 存全分辨率帧，便于无图像渲染时审查构图。

用法: python preview_ascii.py
输出: preview_full.png（全分辨率帧，用户自行打开）+ stdout ASCII 网格。
ASCII 网格 80 列 x 45 行：'#'暗 / '.'亮，中等用 0-9 步进。
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
COLS, ROWS = 80, 45
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ASCII ramp: 最暗->最亮
RAMP = "#@%+=:-. "  # 9 级


def main():
    try:
        cap, _aw, _ah = cc.open_camera(SOURCE, WIDTH, HEIGHT)
    except SystemExit as e:
        print(f"FAIL: {e}")
        return 1
    for _ in range(5):
        cap.read()  # warm up
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print("FAIL: frame read")
        return 1

    h, w = frame.shape[:2]
    print(f"frame: {w}x{h}")

    # save full-res frame for the user
    ok_enc, buf = cv2.imencode(".png", frame)
    if ok_enc:
        with open(os.path.join(OUT_DIR, "preview_full.png"), "wb") as f:
            f.write(buf.tobytes())
        print(f"saved preview_full.png ({w}x{h})")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # per-cell mean luminance
    cell_h, cell_w = h // ROWS, w // COLS
    grid = np.zeros((ROWS, COLS), dtype=np.float32)
    for r in range(ROWS):
        for c in range(COLS):
            block = gray[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w]
            grid[r, c] = block.mean()

    # normalize to [0,1] using observed min/max for contrast
    vmin, vmax = grid.min(), grid.max()
    span = (vmax - vmin) or 1.0
    norm = (grid - vmin) / span

    print(f"luma min={vmin:.0f} max={vmax:.0f} mean={gray.mean():.0f}")
    print("--- top row = frame top, left col = frame left ---")
    for r in range(ROWS):
        line = ""
        for c in range(COLS):
            v = norm[r, c]
            idx = min(len(RAMP) - 1, int(v * (len(RAMP) - 1)))
            line += RAMP[idx]
        print(line)

    # simple edge/dark-structure hint: fraction of very dark cells (track candidates)
    dark_frac = float((norm < 0.35).mean())
    print(f"dark-cell fraction (norm<0.35): {dark_frac:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
