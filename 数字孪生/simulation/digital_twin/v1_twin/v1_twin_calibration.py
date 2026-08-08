"""相机内参标定 + 俯视 homography (Task 4B-2)。

Produces（纲领 §6c）：
- `CameraCalibration`: 内参矩阵、畸变系数、标定重投影误差（RMS + p95）
- `HomographyTransform`: 像素 ↔ 地面 mm 单应变换
- `detect_checkerboard`: 棋盘格内角点检测（棋盘格 15mm/格，9×6 内角点）
- `calibrate_camera`: cv2.calibrateCamera 封装，输出 CameraCalibration

Gate 阈值（§6c 自动验收）: 重投影误差 p95 ≤ max(2 pixel, 5% 黑线宽度像素)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]


MIN_CALIBRATION_VIEWS = 3


# ============================================================
# CameraCalibration
# ============================================================


@dataclass(frozen=True)
class CameraCalibration:
    """相机内参标定结果。camera_matrix 3x3，dist_coeffs 为畸变系数。"""

    camera_matrix: np.ndarray          # 3x3 内参矩阵
    dist_coeffs: np.ndarray            # 畸变系数
    image_size: Tuple[int, int]        # (width, height)
    reprojection_error_rms: float      # 总体 RMS 重投影误差（像素）
    reprojection_error_p95: float      # 逐点重投影误差 p95（像素）

    def __post_init__(self) -> None:
        if self.camera_matrix.shape != (3, 3):
            raise ValueError("camera_matrix must be 3x3")

    def undistort_point(self, x: float, y: float) -> Tuple[float, float]:
        """对像素点做畸变校正，返回校正后像素坐标。"""
        if cv2 is None:
            raise RuntimeError("OpenCV not available")
        pts = np.array([[[x, y]]], dtype=np.float32)
        out = cv2.undistortPoints(pts, self.camera_matrix, self.dist_coeffs,
                                  P=self.camera_matrix)
        return float(out[0, 0, 0]), float(out[0, 0, 1])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "CameraCalibration",
            "camera_matrix": self.camera_matrix.tolist(),
            "dist_coeffs": np.asarray(self.dist_coeffs).ravel().tolist(),
            "image_size": list(self.image_size),
            "reprojection_error_rms": self.reprojection_error_rms,
            "reprojection_error_p95": self.reprojection_error_p95,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraCalibration":
        return cls(
            camera_matrix=np.asarray(data["camera_matrix"], dtype=float),
            dist_coeffs=np.asarray(data["dist_coeffs"], dtype=float),
            image_size=tuple(data["image_size"]),
            reprojection_error_rms=float(data["reprojection_error_rms"]),
            reprojection_error_p95=float(data["reprojection_error_p95"]),
        )


def calibrate_camera(
    object_points: Sequence[Any],
    image_points: Sequence[Any],
    image_size: Tuple[int, int],
    flags: int = 0,
) -> CameraCalibration:
    """从多视角棋盘格点对应标定相机内参（cv2.calibrateCamera 封装）。

    *object_points* 与 *image_points* 为逐视图的 3D/2D 点序列。
    至少需要 MIN_CALIBRATION_VIEWS = 3 张视图（平面靶标内参可辨识下限）。
    """
    if cv2 is None:
        raise RuntimeError("OpenCV not available")
    if len(object_points) < MIN_CALIBRATION_VIEWS:
        raise ValueError(
            "至少需要 {0} 张棋盘格视图".format(MIN_CALIBRATION_VIEWS)
        )
    obj_pts = [
        np.asarray(o, dtype=np.float32).reshape(-1, 1, 3) for o in object_points
    ]
    img_pts = [
        np.asarray(i, dtype=np.float32).reshape(-1, 1, 2) for i in image_points
    ]

    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
        obj_pts, img_pts, tuple(image_size), None, None, flags=flags
    )

    # 逐点重投影误差 p95
    errors: List[float] = []
    for o, i, rv, tv in zip(obj_pts, img_pts, rvecs, tvecs):
        proj, _ = cv2.projectPoints(o, rv, tv, mtx, dist)
        errs = np.linalg.norm(proj.reshape(-1, 2) - i.reshape(-1, 2), axis=1)
        errors.extend(errs.tolist())
    p95 = float(np.percentile(errors, 95)) if errors else 0.0

    return CameraCalibration(
        camera_matrix=np.asarray(mtx, dtype=float),
        dist_coeffs=np.asarray(dist, dtype=float),
        image_size=tuple(image_size),
        reprojection_error_rms=float(ret),
        reprojection_error_p95=p95,
    )


# ============================================================
# HomographyTransform
# ============================================================


@dataclass(frozen=True)
class HomographyTransform:
    """像素 ↔ 地面 mm 单应变换（平面投影）。"""

    matrix: np.ndarray  # 3x3

    def __post_init__(self) -> None:
        if self.matrix.shape != (3, 3):
            raise ValueError("homography matrix must be 3x3")

    def pixel_to_mm(self, x: float, y: float) -> Tuple[float, float]:
        v = self.matrix @ np.array([x, y, 1.0])
        return float(v[0] / v[2]), float(v[1] / v[2])

    def mm_to_pixel(self, x: float, y: float) -> Tuple[float, float]:
        m = np.linalg.inv(self.matrix)
        v = m @ np.array([x, y, 1.0])
        return float(v[0] / v[2]), float(v[1] / v[2])

    def mm_to_pixel_batch(self, pts_mm: np.ndarray) -> np.ndarray:
        """批量 mm→像素，返回 (N, 2)。"""
        pts = np.asarray(pts_mm, dtype=float).reshape(-1, 2)
        h = np.hstack([pts, np.ones((len(pts), 1))]).T  # (3, N)
        m = np.linalg.inv(self.matrix)
        out = m @ h
        return (out[:2] / out[2]).T

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "HomographyTransform", "matrix": self.matrix.tolist()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HomographyTransform":
        return cls(matrix=np.asarray(data["matrix"], dtype=float))


def estimate_homography(
    src_px: Any, dst_mm: Any, ransac_threshold: float = 3.0
) -> HomographyTransform:
    """从像素↔mm 点对应估计单应。

    - 恰好 4 组点: 精确透视变换 (getPerspectiveTransform)
    - >4 组点: RANSAC 鲁棒估计 (findHomography)
    """
    if cv2 is None:
        raise RuntimeError("OpenCV not available")
    src = np.asarray(src_px, dtype=float).reshape(-1, 2)
    dst = np.asarray(dst_mm, dtype=float).reshape(-1, 2)
    if src.shape != dst.shape or len(src) < 4:
        raise ValueError("需要至少 4 组 像素↔mm 点对应")
    if len(src) == 4:
        # OpenCV 5.0 的 getPerspectiveTransform 要求 float32 且只返回单个矩阵
        H = cv2.getPerspectiveTransform(
            src.astype(np.float32), dst.astype(np.float32)
        )
        H = np.asarray(H, dtype=float)
    else:
        H, _ = cv2.findHomography(
            src.astype(np.float32), dst.astype(np.float32),
            cv2.RANSAC, ransac_threshold,
        )
        if H is None:
            raise ValueError("homography 估计失败（RANSAC 未收敛）")
        H = np.asarray(H, dtype=float)
    return HomographyTransform(H)


# ============================================================
# 棋盘格检测
# ============================================================


def pattern_object_points(
    pattern: Tuple[int, int], square_size_mm: float
) -> np.ndarray:
    """生成棋盘格 3D 对象点（z=0，单位 mm）。

    *pattern* 为内角点数量 (columns, rows)。
    """
    cols, rows = pattern
    obj = np.zeros((cols * rows, 3), dtype=np.float32)
    obj[:, :2] = (
        np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_size_mm
    )
    return obj


def detect_checkerboard(
    frame: Any,
    pattern_size: Tuple[int, int] = (9, 6),
    square_size_mm: float = 25.0,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """检测棋盘格内角点。

    返回 (corners_px (N,2), object_mm (N,2))，或未检测到时返回 None。
    """
    if cv2 is None:
        raise RuntimeError("OpenCV not available")
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    ret, corners = cv2.findChessboardCorners(gray, pattern_size, None)
    if not ret or corners is None:
        return None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)
    corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
    corners_px = corners.reshape(-1, 2).astype(float)
    obj = pattern_object_points(pattern_size, square_size_mm)
    return corners_px, obj[:, :2].astype(float)


# ============================================================
# Gate 评估（§6c 自动验收: p95 ≤ max(2 px, 5% 黑线宽度像素)）
# ============================================================

GATE_MAX_PIXELS = 2.0            # 固定下限 2 px
GATE_LINE_WIDTH_FRACTION = 0.05  # 黑线宽度的 5%


def gate_threshold(line_width_px: float) -> float:
    """重投影误差阈值 = max(2 px, 5% × 黑线宽度像素)。"""
    return max(GATE_MAX_PIXELS, GATE_LINE_WIDTH_FRACTION * line_width_px)


def evaluate_calibration_gate(
    calib: CameraCalibration, line_width_px: float
) -> Dict[str, Any]:
    """对照 Gate 阈值给出 PASS/FAIL。"""
    threshold = gate_threshold(line_width_px)
    p95 = calib.reprojection_error_p95
    return {
        "reprojection_error_p95": p95,
        "gate_threshold_px": threshold,
        "line_width_px": line_width_px,
        "verdict": "PASS" if p95 <= threshold else "FAIL",
    }
