"""C960 实时垂直度调节：检测地面棋盘格，量化摄像头是否垂直正对地面。

用法: python perpendicularity_preview.py [index]   默认 index=1
棋盘格 9x6（15mm/格）平放赛道地面、完整入画。
窗口实时显示：
  - 棋盘格网格叠加
  - 纵横比（理想 1.60 = 120mm/75mm 物理纵横比）
  - px/mm 各向异性（理想 1.00）
  - 俯仰/横滚方向提示（哪端更近）
当「垂直 OK」出现即表示镜头平面已平行地面。按 ESC 关闭。
"""
import sys
import time

import cv2
import numpy as np


import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_sys.path.insert(0, _HERE)
_sys.path.insert(0, _os.path.abspath(_os.path.join(_HERE, "..", "..", "simulation", "digital_twin")))
import camera_common as cc

SOURCE = cc.get_camera_index(int(_sys.argv[1]) if len(_sys.argv) > 1 else None)
PATTERN = cc.CHECKERBOARD_PATTERN
SQUARE_MM = cc.CHECKERBOARD_SQUARE_MM
MM_W = 8 * SQUARE_MM          # 200mm
MM_H = 5 * SQUARE_MM          # 125mm
TARGET_ASPECT = MM_W / MM_H   # 1.60

CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)


def _local_scale_ratio(M, px, py):
    """homography 在 (px,py) 的局部 Jacobian 奇异值比（旋转无关；理想 1.0）。"""
    a, b, c = M[0]; d, e, f = M[1]; g, h, i = M[2]
    w_ = g * px + h * py + i
    n_ = a * px + b * py + c
    m_ = d * px + e * py + f
    Jxx = (a * w_ - n_ * g) / w_ ** 2
    Jxy = (b * w_ - n_ * h) / w_ ** 2
    Jyx = (d * w_ - m_ * g) / w_ ** 2
    Jyy = (e * w_ - m_ * h) / w_ ** 2
    J = np.array([[Jxx, Jxy], [Jyx, Jyy]])
    sv = np.linalg.svd(J, compute_uv=False)
    return float(sv[0] / sv[1])


def analyze(corners, frame_size=(cc.DEFAULT_WIDTH, cc.DEFAULT_HEIGHT)):
    """返回 (中心ratio, 角部最大偏差, 方向提示)。

    权威判据 = homography 局部 Jacobian 奇异值比（旋转无关）：
    - 中心 ≈ 1.0 → 摄像头垂直。
    - 角部也 ≈ 1.0 → 垂直 + undistort 正确 = 全图映射均匀（mm 级精度）。
    注意：不要用图像四角 mm 跨度比（对旋转敏感，会误报倾斜）。
    """
    from v1_twin.v1_twin_calibration import estimate_homography
    pts = corners.reshape(-1, 2)
    obj = np.zeros((54, 2), dtype=np.float32)
    obj[:, 0] = (np.arange(54) % 9) * SQUARE_MM
    obj[:, 1] = (np.arange(54) // 9) * SQUARE_MM
    try:
        H = estimate_homography(pts, obj, ransac_threshold=3.0)
        M = H.matrix
    except Exception:
        return 0.0, 99.0, "homography 拟合失败", ""
    w, h = frame_size
    cx = pts.mean(axis=0)
    center_ratio = _local_scale_ratio(M, cx[0], cx[1])
    corners = [(0.25 * w, 0.25 * h), (0.75 * w, 0.25 * h),
               (0.25 * w, 0.75 * h), (0.75 * w, 0.75 * h)]
    corner_ratios = [_local_scale_ratio(M, x, y) for x, y in corners]
    max_dev = max(abs(r - 1.0) for r in corner_ratios)
    # 方向提示：中心到角落的比例梯度方向
    pitch, roll = "俯仰: 平行", "横滚: 平行"
    tl, tr, bl, br = corner_ratios
    if abs(tl - bl) > 0.04 or abs(tr - br) > 0.04:
        pitch = "俯仰: 上下角比例不一致 → 微调俯仰"
    if abs(tl - tr) > 0.04 or abs(bl - br) > 0.04:
        roll = "横滚: 左右角比例不一致 → 微调横滚"
    return center_ratio, max_dev, pitch, roll


def main():
    try:
        cap, _aw, _ah = cc.open_camera(
            SOURCE, cc.DEFAULT_WIDTH, cc.DEFAULT_HEIGHT
        )
    except SystemExit as e:
        print(f"FAIL: {e}")
        return 1
    cv2.namedWindow("垂直度调节 (ESC 关闭)", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("垂直度调节 (ESC 关闭)", 960, 540)
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, PATTERN, None)
        color = (0, 0, 255)
        if ret:
            corners2 = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), CRITERIA)
            cv2.drawChessboardCorners(frame, PATTERN, corners2, ret)
            center_ratio, max_dev, pitch, roll = analyze(
                corners2, (cc.DEFAULT_WIDTH, cc.DEFAULT_HEIGHT)
            )
            ok_flag = abs(center_ratio - 1.0) < 0.03 and max_dev < 0.06
            color = (0, 255, 0) if ok_flag else (0, 165, 255)
            status = "垂直 OK ✓ (全图均匀)" if ok_flag else "微调摄像头趋近 1.0"
            cv2.putText(frame, status, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            cv2.putText(frame, f"中心 ratio {center_ratio:.3f} (理想1.00) | 角部偏差 {max_dev:.3f} (<0.06)",
                        (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            cv2.putText(frame, pitch, (10, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            cv2.putText(frame, roll, (10, 112), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        else:
            cv2.putText(frame, "未检测到棋盘格: 请把 9x6 棋盘格平放赛道中央、完整入画",
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.putText(frame, "按 ESC 关闭", (10, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imshow("垂直度调节 (ESC 关闭)", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break
    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
