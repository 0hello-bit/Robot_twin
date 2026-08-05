"""Tests for 车顶 AprilTag 位姿跟踪 (Task 4B-3)。

先写测试后实现：模块尚不存在时应 RED。

使用 cv2.aruco.generateImageMarker 合成 36h11 ID=0 标签图验证：
- 检测返回 V1Pose 的中心（identity / scale homography）
- 空白帧返回 None
- yaw 跟随标签旋转
- confidence ∈ [0,1]、t_pc_ns 为正
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest

import cv2

from v1_twin.v1_twin_calibration import CameraCalibration, HomographyTransform
from v1_twin.v1_twin_pose_tracker import PoseTracker


def _identity_calib() -> CameraCalibration:
    return CameraCalibration(
        camera_matrix=np.eye(3),
        dist_coeffs=np.zeros(5),
        image_size=(640, 480),
        reprojection_error_rms=0.0,
        reprojection_error_p95=0.0,
    )


def _place_tag(canvas_size=(480, 640), tag_px=120, center=(260, 210),
               angle_deg=0.0) -> np.ndarray:
    """生成含 AprilTag ID=0 的画布（白色背景），标签以 center 为中心。

    旋转在 3x 大画布内进行再取中间区域，避免 warpAffine 裁切标签。
    """
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    tag = cv2.aruco.generateImageMarker(d, 0, tag_px)
    big = np.full((tag_px * 3, tag_px * 3), 255, np.uint8)
    big[tag_px:2 * tag_px, tag_px:2 * tag_px] = tag
    if angle_deg:
        m = cv2.getRotationMatrix2D(
            (big.shape[1] / 2, big.shape[0] / 2), angle_deg, 1.0)
        big = cv2.warpAffine(big, m, (big.shape[1], big.shape[0]),
                             borderValue=255)
    # 取含完整旋转后标签的中间区域
    half = int(tag_px * 0.95)
    cy, cx = big.shape[0] / 2, big.shape[1] / 2
    crop = big[int(cy - half):int(cy + half), int(cx - half):int(cx + half)]
    canvas = np.full(canvas_size, 255, np.uint8)
    x0 = int(round(center[0] - crop.shape[1] / 2))
    y0 = int(round(center[1] - crop.shape[0] / 2))
    canvas[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop
    return canvas


def test_track_identity_homography_center():
    canvas = _place_tag(center=(260, 210))
    tracker = PoseTracker(_identity_calib(), HomographyTransform(np.eye(3)))
    pose = tracker.track(canvas, t_pc_ns=1000)
    assert pose is not None
    assert pose.x_mm == pytest.approx(260.0, abs=2.0)
    assert pose.y_mm == pytest.approx(210.0, abs=2.0)


def test_track_scale_homography_center():
    canvas = _place_tag(center=(260, 210))
    scale = 0.5  # 1px -> 0.5mm
    tracker = PoseTracker(
        _identity_calib(), HomographyTransform(np.diag([scale, scale, 1.0]))
    )
    pose = tracker.track(canvas, t_pc_ns=1000)
    assert pose is not None
    assert pose.x_mm == pytest.approx(130.0, abs=1.0)
    assert pose.y_mm == pytest.approx(105.0, abs=1.0)


def test_track_returns_none_on_blank():
    canvas = np.full((480, 640), 255, np.uint8)
    tracker = PoseTracker(_identity_calib(), HomographyTransform(np.eye(3)))
    assert tracker.track(canvas) is None


def test_yaw_upright_tag_points_up_in_image():
    # 未旋转标签：印刷正上 = 车头 = 图像"上"方向 = (0, -1) -> yaw = -pi/2
    canvas = _place_tag(center=(260, 210), angle_deg=0.0)
    tracker = PoseTracker(_identity_calib(), HomographyTransform(np.eye(3)))
    pose = tracker.track(canvas, t_pc_ns=1000)
    assert pose is not None
    assert pose.yaw_rad == pytest.approx(-math.pi / 2, abs=0.15)


def test_yaw_follows_rotation():
    # 旋转 +30° 后 yaw 应相对增加约 30°（符号由实现约定决定，这里断言绝对值变化）
    canvas0 = _place_tag(center=(260, 210), angle_deg=0.0)
    canvas1 = _place_tag(center=(260, 210), angle_deg=30.0)
    tracker = PoseTracker(_identity_calib(), HomographyTransform(np.eye(3)))
    p0 = tracker.track(canvas0, t_pc_ns=1000)
    p1 = tracker.track(canvas1, t_pc_ns=1000)
    assert p0 is not None and p1 is not None
    d = p1.yaw_rad - p0.yaw_rad
    # 归一化到 (-pi, pi]
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    assert abs(abs(d) - math.radians(30.0)) < math.radians(8.0)


def test_confidence_in_unit_range():
    canvas = _place_tag(center=(260, 210))
    tracker = PoseTracker(_identity_calib(), HomographyTransform(np.eye(3)))
    pose = tracker.track(canvas, t_pc_ns=1000)
    assert pose is not None
    assert 0.0 < pose.confidence <= 1.0


def test_t_pc_ns_positive_and_defaulted():
    canvas = _place_tag(center=(260, 210))
    tracker = PoseTracker(_identity_calib(), HomographyTransform(np.eye(3)))
    pose = tracker.track(canvas)  # 不传 t_pc_ns
    assert pose is not None
    assert pose.t_pc_ns > 0
    assert pose.source == "camera"


def test_car_forward_offset_shifts_yaw():
    canvas = _place_tag(center=(260, 210), angle_deg=0.0)
    tracker = PoseTracker(
        _identity_calib(), HomographyTransform(np.eye(3)),
        car_forward_offset_rad=math.radians(90.0),
    )
    pose = tracker.track(canvas, t_pc_ns=1000)
    assert pose is not None
    # 相对未偏移时增加约 90°
    assert pose.yaw_rad == pytest.approx(-math.pi / 2 + math.pi / 2, abs=0.2)
