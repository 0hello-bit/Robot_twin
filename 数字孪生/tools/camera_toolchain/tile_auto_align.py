"""棋盘格自动对齐放置（R3 控制点，工具检测"严丝合缝"，无需人眼/尺子）。

原理：棋盘格 120x75mm。工具用角点检测实时测量棋盘格左上内角位置，
与目标格原点对齐（亚像素级）。对齐稳定 N 帧后**自动保存**，无需按空格。

mm 坐标 = 目标格索引 × 棋盘格尺寸（120*col, 75*row），假设网格物理连续。

用法: py tile_auto_align.py [index] [outdir] [--tolerance 6]

操作：
  1. 先把棋盘格平放画面任意处 → 量尺寸。
  2. 网格（棋盘格等大连续平铺）生成，红色=当前目标格原点。
  3. 把棋盘格滑到红色目标附近，工具检测到角点对齐（稳定 ~0.4s）→ 自动保存并跳下一格。
  4. ESC 结束。
产出: view_NN.png + controls.json。
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

import camera_common as cc

PATTERN = (9, 6)
SQUARE_MM = cc.GROUND_CHECKERBOARD_SQUARE_MM
MM_W = 8 * SQUARE_MM   # 120
MM_H = 5 * SQUARE_MM   # 75
CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)
STABLE_FRAMES = 12   # 对齐稳定帧数
WINDOW_TITLE = "Tile Auto Align"
PLACE_PROMPT = "Place checkerboard flat in view (measure size)"
STATUS_PREFIX = "saved"
PREVIEW_WIDTH = 960
PREVIEW_HEIGHT = 540


def make_preview_frame(frame, max_width=PREVIEW_WIDTH, max_height=PREVIEW_HEIGHT):
    """Resize a frame for display without changing the saved source frame."""
    if frame is None or frame.size == 0:
        raise ValueError("frame must contain pixels")
    if max_width <= 0 or max_height <= 0:
        raise ValueError("preview bounds must be positive")

    height, width = frame.shape[:2]
    scale = min(max_width / width, max_height / height, 1.0)
    if scale == 1.0:
        return frame
    target_size = (
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    )
    return cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)


def safe_target_axes(width, height, inner_span_w, inner_span_h):
    """Return board origins that keep one outer square inside each edge."""
    values = (width, height, inner_span_w, inner_span_h)
    if any(value <= 0 for value in values):
        raise ValueError("frame and checkerboard spans must be positive")

    margin_w = int(math.ceil(inner_span_w / (PATTERN[0] - 1)))
    margin_h = int(math.ceil(inner_span_h / (PATTERN[1] - 1)))

    def build_axis(frame_span, board_span, margin):
        max_origin = frame_span - board_span - margin
        if max_origin < margin:
            raise ValueError("checkerboard does not fit with the required margin")
        count = int(math.floor((max_origin - margin) / board_span)) + 1
        return [int(round(margin + index * board_span)) for index in range(count)]

    return (
        build_axis(width, inner_span_w, margin_w),
        build_axis(height, inner_span_h, margin_h),
    )


def board_local_points(square_mm=SQUARE_MM):
    """Return checkerboard inner-corner coordinates in board-local mm."""
    cols, rows = PATTERN
    points = np.zeros((cols * rows, 2), dtype=np.float64)
    points[:, 0] = (np.arange(cols * rows) % cols) * square_mm
    points[:, 1] = (np.arange(cols * rows) // cols) * square_mm
    return points


def _fit_rigid_pose(local_points, ground_points):
    local = np.asarray(local_points, dtype=np.float64).reshape(-1, 2)
    ground = np.asarray(ground_points, dtype=np.float64).reshape(-1, 2)
    if local.shape != ground.shape or len(local) < 3:
        raise ValueError("rigid pose needs matching board point sets")

    local_center = local.mean(axis=0)
    ground_center = ground.mean(axis=0)
    covariance = (local - local_center).T @ (ground - ground_center)
    u, _, vt = np.linalg.svd(covariance)
    row_rotation = u @ vt
    if np.linalg.det(row_rotation) < 0:
        u[:, -1] *= -1
        row_rotation = u @ vt
    rotation = row_rotation.T
    translation = ground_center - rotation @ local_center
    angle_deg = np.degrees(np.arctan2(rotation[1, 0], rotation[0, 0]))
    return float(angle_deg), float(translation[0]), float(translation[1])


def estimate_board_pose(reference_corners, current_corners):
    """Estimate current board angle and translation in the first-view plane."""
    reference = np.asarray(reference_corners, dtype=np.float64).reshape(-1, 2)
    current = np.asarray(current_corners, dtype=np.float64).reshape(-1, 2)
    local = board_local_points()
    expected_shape = local.shape
    if reference.shape != expected_shape or current.shape != expected_shape:
        raise ValueError("checkerboard corner count does not match PATTERN")

    reference_to_pixel, _ = cv2.findHomography(
        local.astype(np.float32), reference.astype(np.float32), 0
    )
    if reference_to_pixel is None or not np.all(np.isfinite(reference_to_pixel)):
        raise ValueError("could not fit the reference board plane")

    pixel_to_reference = np.linalg.inv(reference_to_pixel)
    current_ground = cv2.perspectiveTransform(
        current.astype(np.float32).reshape(-1, 1, 2),
        pixel_to_reference.astype(np.float64),
    ).reshape(-1, 2)
    return _fit_rigid_pose(local, current_ground)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("index", nargs="?", type=int, default=None)
    ap.add_argument("outdir", nargs="?", default=None)
    ap.add_argument("--tolerance", type=float, default=6.0)
    ap.add_argument("--width", type=int, default=cc.DEFAULT_WIDTH)
    ap.add_argument("--height", type=int, default=cc.DEFAULT_HEIGHT)
    args = ap.parse_args()

    index = cc.get_camera_index(args.index)
    outdir = args.outdir or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "tile_auto_controls")
    os.makedirs(outdir, exist_ok=True)
    cap, aw, ah = cc.open_camera(index, args.width, args.height)
    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_TITLE, PREVIEW_WIDTH, PREVIEW_HEIGHT)

    # Phase 1: 量棋盘格图像尺寸
    print(f"{PLACE_PROMPT}...", flush=True)
    tw = th = None
    while tw is None:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        if ret:
            c2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            pts = c2.reshape(-1, 2)
            tw = int(np.hypot(pts[0][0] - pts[8][0], pts[0][1] - pts[8][1]))
            th = int(np.hypot(pts[0][0] - pts[45][0], pts[0][1] - pts[45][1]))
            print(f"Checkerboard size: {tw}x{th}px", flush=True)
        cv2.putText(frame, PLACE_PROMPT, (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imshow(WINDOW_TITLE, make_preview_frame(frame))
        if cv2.waitKey(1) & 0xFF == 27:
            cap.release(); cv2.destroyAllWindows(); return 1

    # Keep the full checkerboard visible while retaining one-board-span steps.
    x_targets, y_targets = safe_target_axes(aw, ah, tw, th)
    cols = len(x_targets)
    rows = len(y_targets)
    total = cols * rows
    # 目标顺序：行优先
    targets = [(r, c) for r in range(rows) for c in range(cols)]
    print(f"Grid {cols}x{rows}={total} cells, tolerance {args.tolerance}px", flush=True)

    controls = []
    n = 0
    ti = 0   # 当前目标索引
    stable = 0
    reference_corners = None
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        save_img = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        tl_corner = None
        board_corners = None
        if ret:
            c2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            cv2.drawChessboardCorners(frame, PATTERN, c2, ret)
            board_corners = c2.reshape(-1, 2)
            tl_corner = board_corners[0]   # 棋盘格左上内角

        # 当前目标格原点（像素）
        tr, tc = targets[ti] if ti < total else (None, None)
        tx, ty = x_targets[tc], y_targets[tr]

        # 对齐检测
        captured = False
        if tl_corner is not None and tr is not None:
            d = float(np.hypot(tl_corner[0] - tx, tl_corner[1] - ty))
            if d <= args.tolerance:
                stable += 1
                if stable >= STABLE_FRAMES:
                    if n == 0:
                        reference_corners = board_corners.copy()
                        angle_deg = 0.0
                    else:
                        try:
                            angle_deg, _, _ = estimate_board_pose(
                                reference_corners, board_corners
                            )
                        except (TypeError, ValueError) as exc:
                            print(f"angle estimation failed: {exc}; point not saved",
                                  flush=True)
                            stable = 0
                            continue
                    p = os.path.join(outdir, f"view_{n:02d}.png")
                    cc.imwrite_unicode(p, save_img)
                    controls.append({"image": os.path.abspath(p),
                                     "x_mm": MM_W * tc, "y_mm": MM_H * tr, "angle_deg": 0})
                    n += 1
                    controls[-1]["angle_deg"] = round(angle_deg, 6)
                    print(f"AUTO saved view_{n-1:02d} cell({tr},{tc}) "
                          f"mm=({MM_W*tc:.0f},{MM_H*tr:.0f}) angle={angle_deg:+.3f}deg",
                          flush=True)
                    stable = 0
                    ti += 1
                    captured = True
            else:
                stable = 0

        # 绘制
        for r in range(rows):
            for c in range(cols):
                x0, y0 = x_targets[c], y_targets[r]
                cv2.rectangle(frame, (x0, y0), (x0 + tw, y0 + th), (100, 100, 100), 1)
        if tr is not None:
            cv2.rectangle(frame, (tx, ty), (tx + tw, ty + th), (0, 0, 255), 2)
            cv2.circle(frame, (int(tx), int(ty)), 4, (0, 0, 255), -1)
            cv2.putText(frame, f"NEXT({tr},{tc}) mm=({MM_W*tc:.0f},{MM_H*tr:.0f}) align {stable}/{STABLE_FRAMES}",
                        (tx + 4, ty - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        if tl_corner is not None:
            cv2.circle(frame, (int(tl_corner[0]), int(tl_corner[1])), 5, (255, 0, 0), -1)
        cv2.putText(frame, f"{STATUS_PREFIX} {n}/{total}  move board origin to red target  ESC exit",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow(WINDOW_TITLE, make_preview_frame(frame))
        key = cv2.waitKey(1) & 0xFF
        if key == 27 or ti >= total:
            break

    cap.release()
    cv2.destroyAllWindows()
    cj = os.path.join(outdir, "controls.json")
    with open(cj, "w", encoding="utf-8") as f:
        json.dump(controls, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(controls)} control points -> {cj}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
