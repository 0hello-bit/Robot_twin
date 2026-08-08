"""USB 摄像头（EMEET SmartCam C960）快速探测：验证 index 2、分辨率、帧率。

输出：probe_report.txt + preview.png（当前构图预览）。
只连接摄像头，不碰小车；时间 ~3s。
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
N_FRAMES = 30
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    lines = []
    lines.append(f"=== USB Camera Probe === {time.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        cap, actual_w, actual_h = cc.open_camera(SOURCE, WIDTH, HEIGHT)
    except SystemExit as e:
        lines.append(f"FAIL: {e}")
        _write(lines)
        print("\n".join(lines))
        return 1

    fourcc_val = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc = "".join(chr((fourcc_val >> (8 * i)) & 0xFF) for i in range(4))
    driver_fps = float(cap.get(cv2.CAP_PROP_FPS))
    lines.append(f"mode: DSHOW fourcc={fourcc} driver_fps={driver_fps:.2f} res={actual_w}x{actual_h}")
    lines.append(f"after request {WIDTH}x{HEIGHT}: got {actual_w}x{actual_h}")

    # warm up a few frames (driver latency)
    for _ in range(3):
        cap.read()

    t0 = time.perf_counter()
    ts = []
    frames = []
    for i in range(N_FRAMES):
        ok, frame = cap.read()
        now = time.perf_counter_ns()
        if not ok:
            lines.append(f"frame {i}: read FAILED")
        else:
            frames.append((now, frame))
            ts.append(now)
    dt = time.perf_counter() - t0

    n_ok = len(ts)
    fps = n_ok / dt if dt > 0 else 0.0
    mono = all(ts[i] < ts[i + 1] for i in range(len(ts) - 1)) if len(ts) > 1 else True
    lines.append(f"frames ok: {n_ok}/{N_FRAMES} in {dt:.2f}s -> {fps:.1f} fps")
    lines.append(f"timestamps monotonic: {mono}")

    # content check: mean/std of first frame
    if frames:
        _, first = frames[0]
        g = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
        lines.append(f"frame mean gray: {g.mean():.1f}, std: {g.std():.1f}")

        # save preview at ~30% scale
        small = cv2.resize(first, (int(actual_w * 0.3), int(actual_h * 0.3)))
        ok_enc, buf = cv2.imencode(".png", small)
        if ok_enc:
            with open(os.path.join(OUT_DIR, "preview.png"), "wb") as f:
                f.write(buf.tobytes())
            lines.append(f"preview saved: preview.png ({actual_w}x{actual_h} scaled x0.3)")

    cap.release()
    if n_ok == 0:
        lines.append("FAIL: 0 frames read — 设备可打开但无法取帧")
        _write(lines)
        print("\n".join(lines))
        return 1
    lines.append("=== probe done ===")
    _write(lines)
    print("\n".join(lines))
    return 0


def _write(lines):
    with open(os.path.join(OUT_DIR, "probe_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
