"""C960 实时预览：用于人工调整摄像头构图。

用法: python live_preview.py [index]   默认 index=1
窗口实时显示摄像头画面（请求 1280x720），按 ESC 关闭。
"""
import sys
import time

import cv2


import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import camera_common as cc

SOURCE = cc.get_camera_index(int(_sys.argv[1]) if len(_sys.argv) > 1 else None)
WIDTH, HEIGHT = 1280, 720


def main():
    try:
        cap, _aw, _ah = cc.open_camera(SOURCE, WIDTH, HEIGHT)
    except SystemExit as e:
        print(f"FAIL: {e}")
        return 1
    aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"C960 preview: index={SOURCE}, resolution={aw}x{ah}")
    cv2.namedWindow("C960 preview", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("C960 preview", 960, 540)
    n = 0
    while True:
        ok, frame = cap.read()
        if ok:
            cv2.imshow("C960 preview", frame)
            n += 1
        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            break
    cap.release()
    cv2.destroyAllWindows()
    print(f"preview closed after {n} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
