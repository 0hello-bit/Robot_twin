"""在新 track_bare.png（C960 垂直俯拍）上点选 12 个路线锚点。

操作：按路线顺序点击（发字发车支线入口 → 沿主赛道 → 全黑终点）。
  - 左键点击: 加点
  - Backspace: 撤销最后一个
  - ESC: 保存退出
保存到 route_selection_c960.json（同 route_selection.json 结构，新坐标）。
"""
import json
import os
import sys

import cv2
import numpy as np

import camera_common as cc

# 用法: python select_waypoints.py [image_path] [out_json]
# 默认读工程 track_bare.png，输出到当前目录 route_selection_c960.json
PROJECT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
IMG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    PROJECT, "simulation", "digital_twin", "assets", "real_route",
    "track_bare.png")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "route_selection_c960.json")
DISPLAY_W, DISPLAY_H = 960, 540
MAX_POINTS = 12


def main():
    img = cc.imread_unicode(IMG)
    if img is None:
        print("FAIL: cannot decode track_bare.png")
        return 1
    h, w = img.shape[:2]
    scale = DISPLAY_W / w
    disp = cv2.resize(img, (DISPLAY_W, int(h * scale)))

    pts = []  # full-res coords

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < MAX_POINTS:
            fx, fy = int(x / scale), int(y / scale)
            pts.append([fx, fy])
            print(f"point {len(pts)}: ({fx},{fy})", flush=True)
        elif event == cv2.EVENT_LBUTTONDOWN:
            print(f"已达上限 {MAX_POINTS}，按 ESC 保存", flush=True)

    cv2.namedWindow("C960 锚点选择", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("C960 锚点选择", DISPLAY_W, DISPLAY_H)
    cv2.setMouseCallback("C960 锚点选择", on_mouse)

    while True:
        frame = disp.copy()
        for i, (fx, fy) in enumerate(pts):
            x, y = int(fx * scale), int(fy * scale)
            cv2.circle(frame, (x, y), 5, (0, 0, 255), -1)
            cv2.putText(frame, str(i + 1), (x + 6, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        cv2.putText(frame, f"anchors: {len(pts)}/12  左键加点  Backspace撤销  ESC保存退出",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow("C960 锚点选择", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            break
        if key in (8, 127):  # Backspace / Delete
            if pts:
                rm = pts.pop()
                print(f"removed ({rm[0]},{rm[1]}), now {len(pts)}", flush=True)

    cv2.destroyAllWindows()

    if len(pts) < 4:
        print(f"too few points ({len(pts)}), not saved")
        return 1

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "route_selection.json"), encoding="utf-8") as f:
        base = json.load(f)
    base["waypoints_px"] = [[int(p[0]), int(p[1])] for p in pts]
    base["source"] = IMG
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=2)
    print(f"saved {len(pts)} waypoints -> {OUT}")
    print("waypoints:", base["waypoints_px"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
