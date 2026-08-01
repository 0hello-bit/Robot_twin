"""Tests for 相机标定与 homography (Task 4B-2)。

先写测试后实现：模块尚不存在时应 RED。

使用合成数据（已知 homography / 已知相机矩阵 / 合成棋盘格图像）验证：
- Homography 正/反变换往返
- 从点对应估计 homography
- 相机内参标定（合成棋盘格投影）
- 棋盘格检测（合成棋盘图像）
- CameraCalibration JSON 往返
- 重投影误差 p95 满足 Gate 阈值（≤ 2 px）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest

from v1_twin.v1_twin_calibration import (
    CameraCalibration,
    HomographyTransform,
    calibrate_camera,
    detect_checkerboard,
    estimate_homography,
    evaluate_calibration_gate,
    gate_threshold,
    pattern_object_points,
)


# ============================================================
# Homography
# ============================================================

_BOARD_MM = (150.0, 105.0)  # 棋盘格 10x7 方格，每格 15mm


def test_homography_forward_inverse_round_trip():
    # 已知仿射变换: 缩放 + 平移（像素 -> mm）
    scale, tx, ty = 0.1, 20.0, -5.0  # 1px -> 0.1mm，原点偏移
    H = np.array(
        [[scale, 0.0, tx], [0.0, scale, ty], [0.0, 0.0, 1.0]],
        dtype=float,
    )
    hom = HomographyTransform(H)
    pts_px = [(0.0, 0.0), (640.0, 0.0), (0.0, 480.0), (320.0, 240.0), (123.4, 567.8)]
    for (x, y) in pts_px:
        mx, my = hom.pixel_to_mm(x, y)
        assert mx == pytest.approx(scale * x + tx)
        assert my == pytest.approx(scale * y + ty)
        bx, by = hom.mm_to_pixel(mx, my)
        assert bx == pytest.approx(x)
        assert by == pytest.approx(y)


def test_estimate_homography_from_four_corners():
    # 150x105mm 板的四个角在像素中的位置 -> mm
    px = np.array([[100.0, 100.0], [400.0, 130.0], [80.0, 330.0], [380.0, 350.0]])
    mm = np.array([[0.0, 0.0], [150.0, 0.0], [0.0, 105.0], [150.0, 105.0]])
    hom = estimate_homography(px, mm)
    for (x, y), (mx, my) in zip(px, mm):
        rx, ry = hom.pixel_to_mm(x, y)
        assert rx == pytest.approx(mx, abs=1e-6)
        assert ry == pytest.approx(my, abs=1e-6)


def test_estimate_homography_from_grid_points():
    # 用棋盘格内角点网格（9x6）估计，验证所有点往返误差 < 1mm
    pattern = (9, 6)
    obj = pattern_object_points(pattern, square_size_mm=15.0)
    # 构造一个"相机变换"：从 mm 平面经已知单应到像素
    H = np.array([[0.35, 0.02, 120.0], [-0.01, 0.33, 90.0], [0.0, 0.0, 1.0]])
    pts_mm = obj.reshape(-1, 2)
    pts_px = HomographyTransform(H).mm_to_pixel_batch(pts_mm)
    hom = estimate_homography(pts_px, pts_mm)
    for (mx, my) in pts_mm:
        rx, ry = hom.pixel_to_mm(*hom.mm_to_pixel(mx, my))
        assert rx == pytest.approx(mx, abs=1.0)
        assert ry == pytest.approx(my, abs=1.0)


def test_homography_json_round_trip():
    H = np.array([[0.1, 0.0, 5.0], [0.0, 0.1, 7.0], [0.0, 0.0, 1.0]])
    hom = HomographyTransform(H)
    restored = HomographyTransform.from_dict(hom.to_dict())
    assert np.allclose(restored.matrix, H)


# ============================================================
# 相机内参标定（合成数据）
# ============================================================


def _synthetic_checkerboard_views(n_views=10, pattern=(9, 6), square_mm=15.0,
                                  img_size=(640, 480)):
    """用已知相机矩阵生成多视角棋盘格投影（无畸变）。

    返回 (object_points, image_points)。
    """
    obj = pattern_object_points(pattern, square_size_mm=square_mm).reshape(-1, 3)
    K = np.array([[600.0, 0.0, 320.0], [0.0, 600.0, 240.0], [0.0, 0.0, 1.0]])
    dist = np.zeros((5, 1))
    object_points, image_points = [], []
    for i in range(n_views):
        rvec = np.array(
            [[0.3 + 0.1 * i], [0.2 * ((-1) ** i)], [0.15 * i]], dtype=float
        )
        tvec = np.array([[50.0 * i], [-30.0 * i], [600.0]], dtype=float)
        proj = cv2_project(obj, rvec, tvec, K, dist)
        object_points.append(obj)
        image_points.append(proj.reshape(-1, 2))
    return object_points, image_points, K


def cv2_project(obj, rvec, tvec, K, dist):
    """projectPoints 的纯 np 引用实现，避免测试依赖 cv2。"""
    import numpy as _np

    def rodrigues(rv):
        theta = _np.linalg.norm(rv)
        rv = rv.reshape(3)
        if theta < 1e-8:
            return _np.eye(3)
        k = rv / theta
        Kx = _np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        return _np.eye(3) + _np.sin(theta) * Kx + (1 - _np.cos(theta)) * (Kx @ Kx)

    R = rodrigues(rvec)
    Rt = _np.hstack([R, tvec])
    P = K @ Rt
    obj_h = _np.hstack([obj, _np.ones((obj.shape[0], 1))]).T  # (4, N)
    cam = P @ obj_h  # (3, N)
    cam = cam / cam[2]
    return cam[:2].T


def test_calibrate_camera_recovers_matrix_and_p95_small():
    obj, img, K_true = _synthetic_checkerboard_views()
    calib = calibrate_camera(obj, img, image_size=(640, 480))
    assert calib.reprojection_error_rms < 0.5
    assert calib.reprojection_error_p95 < 2.0  # Gate: ≤ max(2px, ...)
    # 恢复的内参应与真值接近（主点/焦距）
    K = calib.camera_matrix
    assert K[0, 0] == pytest.approx(600.0, rel=0.05)
    assert K[1, 1] == pytest.approx(600.0, rel=0.05)
    assert K[0, 2] == pytest.approx(320.0, abs=10.0)
    assert K[1, 2] == pytest.approx(240.0, abs=10.0)


def test_calibrate_camera_requires_sufficient_views():
    obj, img, _ = _synthetic_checkerboard_views(n_views=2)
    with pytest.raises(ValueError):
        calibrate_camera(obj, img, image_size=(640, 480))


def test_camera_calibration_json_round_trip():
    obj, img, _ = _synthetic_checkerboard_views()
    calib = calibrate_camera(obj, img, image_size=(640, 480))
    restored = CameraCalibration.from_dict(calib.to_dict())
    assert np.allclose(restored.camera_matrix, calib.camera_matrix)
    assert np.allclose(restored.dist_coeffs.ravel(), calib.dist_coeffs.ravel())
    assert restored.reprojection_error_p95 == pytest.approx(calib.reprojection_error_p95)
    assert restored.image_size == (640, 480)


# ============================================================
# 棋盘格检测（合成棋盘图像）
# ============================================================


def _draw_checkerboard(pattern=(9, 6), square_px=20):
    """绘制棋盘格图像（内角点 pattern=(9,6)，即 10x7 方格）。

    四周留白边，便于 findChessboardCorners 检测。
    """
    border = 40
    w = pattern[0] * square_px + 2 * border
    h = pattern[1] * square_px + 2 * border
    img = np.full((h, w), 255, dtype=np.uint8)
    for i in range(pattern[0] + 1):
        for j in range(pattern[1] + 1):
            if (i + j) % 2 == 0:
                x0 = border + i * square_px
                y0 = border + j * square_px
                img[y0:y0 + square_px, x0:x0 + square_px] = 0
    return img


def test_detect_checkerboard_finds_synthetic_board():
    pattern = (9, 6)
    img = _draw_checkerboard(pattern, square_px=20)
    result = detect_checkerboard(img, pattern_size=pattern, square_size_mm=15.0)
    assert result is not None
    corners_px, object_mm = result
    assert corners_px.shape == (pattern[0] * pattern[1], 2)
    assert object_mm.shape == (pattern[0] * pattern[1], 2)
    # 相邻角点间距 = 15mm
    dx = np.linalg.norm(object_mm[0] - object_mm[1])
    assert dx == pytest.approx(15.0)


def test_detect_checkerboard_returns_none_for_blank():
    img = np.full((200, 300), 128, dtype=np.uint8)
    assert detect_checkerboard(img, pattern_size=(9, 6)) is None


def test_pattern_object_points_shape_and_spacing():
    obj = pattern_object_points((9, 6), square_size_mm=15.0)
    assert obj.shape == (54, 3)
    # 相邻角点间距 15mm
    assert np.linalg.norm(obj[0, :2] - obj[1, :2]) == pytest.approx(15.0)
    # 每行 9 个内角点
    assert np.linalg.norm(obj[0, :2] - obj[9, :2]) == pytest.approx(15.0)


# ============================================================
# Gate 阈值（§6c: p95 ≤ max(2 px, 5% 黑线宽度像素)）
# ============================================================


def test_gate_threshold_lower_bound():
    # 5% × 20px = 1px < 2px → 取 2px 下限
    assert gate_threshold(20.0) == pytest.approx(2.0)
    assert gate_threshold(30.0) == pytest.approx(2.0)
    # 5% × 100px = 5px > 2px → 取 5px
    assert gate_threshold(100.0) == pytest.approx(5.0)


def test_evaluate_gate_pass_and_fail():
    calib = CameraCalibration(np.eye(3), np.zeros(5), (640, 480), 1.0, 3.5)
    # 线宽 100px → 阈值 5px → p95=3.5 PASS
    res = evaluate_calibration_gate(calib, 100.0)
    assert res["verdict"] == "PASS"
    assert res["gate_threshold_px"] == pytest.approx(5.0)
    # 线宽 20px → 阈值 2px → p95=3.5 FAIL
    assert evaluate_calibration_gate(calib, 20.0)["verdict"] == "FAIL"
