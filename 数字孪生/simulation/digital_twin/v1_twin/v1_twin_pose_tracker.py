"""车顶 AprilTag 二维位姿跟踪 (Task 4B-3)。

检测车顶 AprilTag 36h11 ID=0，用地面单应把标签中心投影到地面 mm 得到
x/y，用标签"印刷正上"方向（默认=车头）投影得到 yaw。输出 V1Pose。

约定：
- 检测角点序（OpenCV aruco）: [TL, TR, BR, BL]
- 标签"印刷正上" = corner0 - corner3（TL 相对 BL 的方向）默认指向车头，
  可用 ``car_forward_offset_rad`` 调整固定偏转。

注意（已知限制）: 标签在车顶高于地面，单应把标签像素按地面平面投影，
存在视差偏移（对 yaw 无影响，对 x/y 有小量偏移）。V1 接受该限制。
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional, Sequence

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from v1_twin.v1_twin_schema import V1Pose
from v1_twin.v1_twin_calibration import CameraCalibration, HomographyTransform

MIN_GOOD_SIDE_PX = 30.0   # 该尺寸以上 confidence=1.0
MIN_DETECT_SIDE_PX = 15.0  # 该尺寸以下 confidence 下限


class PoseTrackerError(RuntimeError):
    """PoseTracker 配置/运行错误。"""


class PoseTracker:
    """车顶 AprilTag 36h11 检测 + 地面单应投影，输出 V1Pose。"""

    def __init__(
        self,
        calib: CameraCalibration,
        homography: HomographyTransform,
        tag_id: int = 0,
        tag_size_mm: float = 35.0,
        car_forward_offset_rad: float = 0.0,
        detect_scales: Sequence[float] = (1.0, 2.0, 3.0),
    ) -> None:
        """初始化。

        *calib*: CameraCalibration（用于角点去畸变）。
        *homography*: HomographyTransform（像素↔地面 mm）。
        *tag_id*: 目标标签 ID（默认 0）。
        *tag_size_mm*: 标签黑区边长 mm（参考值，当前实现不用于投影）。
        *car_forward_offset_rad*: 标签"印刷正上"到车头方向的固定偏转。
        *detect_scales*: 检测前放大倍率序列，逐个尝试直到解码成功。
            小标签（约 <60px）在原始尺度常解码失败，放大 2-3 倍可显著
            提高检测率（真机实测 1×:5% -> 1/2/3×:99%）。
        """
        if cv2 is None:
            raise PoseTrackerError("OpenCV (cv2) not importable")
        self._calib = calib
        self._hom = homography
        self._tag_id = int(tag_id)
        self._tag_size_mm = float(tag_size_mm)
        self._offset = float(car_forward_offset_rad)
        self._scales = tuple(float(s) for s in detect_scales)
        self._dictionary = cv2.aruco.getPredefinedDictionary(
            cv2.aruco.DICT_APRILTAG_36h11
        )
        self._detector = cv2.aruco.ArucoDetector(
            self._dictionary, cv2.aruco.DetectorParameters()
        )

    # ------------------------------------------------------------
    # 检测
    # ------------------------------------------------------------
    def detect(self, frame: Any) -> Optional[Dict[str, Any]]:
        """检测目标标签，返回角点信息或 None。

        依次尝试各放大倍率，第一个解码成功即返回。
        返回 dict: corners(去畸变后 (4,2)), center_px, forward_px, side_px。
        """
        detection, _ = self._detect_with_diagnostics(frame)
        return detection

    def _detect_with_diagnostics(
        self, frame: Any
    ) -> tuple[Optional[Dict[str, Any]], dict]:
        started_ns = time.perf_counter_ns()
        attempted_scales = []
        rejected_candidate_counts = []
        saw_markers = False
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        for scale in self._scales:
            attempted_scales.append(float(scale))
            if scale == 1.0:
                g = gray
            else:
                g = cv2.resize(gray, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_CUBIC)
            corners_l, ids, rejected = self._detector.detectMarkers(g)
            rejected_count = len(rejected) if rejected is not None else 0
            rejected_candidate_counts.append(rejected_count)
            if ids is None:
                continue
            saw_markers = True
            for c, i in zip(corners_l, ids.ravel()):
                if int(i) != self._tag_id:
                    continue
                pts = np.asarray(c[0], dtype=float) / scale  # 原始尺度
                pts_u = self._undistort(pts)
                center = pts_u.mean(axis=0)
                # 印刷正上 = TL - BL = corner0 - corner3
                fwd = pts_u[0] - pts_u[3]
                side = float(np.linalg.norm(pts_u[0] - pts_u[1]))
                detection = {
                    "corners": pts_u,
                    "center_px": center,
                    "forward_px": fwd,
                    "side_px": side,
                }
                return detection, {
                    "attempted_scales": attempted_scales,
                    "matched_scale": float(scale),
                    "tag_side_px": float(side),
                    "failure_reason": None,
                    "rejected_candidate_count": int(
                        sum(rejected_candidate_counts)
                    ),
                    "rejected_candidate_counts": list(
                        rejected_candidate_counts
                    ),
                    "detect_elapsed_ns": time.perf_counter_ns() - started_ns,
                }
        return None, {
            "attempted_scales": attempted_scales,
            "matched_scale": None,
            "tag_side_px": None,
            "failure_reason": (
                "target_tag_not_found"
                if saw_markers
                else (
                    "candidates_rejected"
                    if sum(rejected_candidate_counts) > 0
                    else "no_markers"
                )
            ),
            "rejected_candidate_count": int(sum(rejected_candidate_counts)),
            "rejected_candidate_counts": list(rejected_candidate_counts),
            "detect_elapsed_ns": time.perf_counter_ns() - started_ns,
        }

    def track(
        self, frame: Any, t_pc_ns: Optional[int] = None
    ) -> Optional[V1Pose]:
        """检测标签，返回 V1Pose；未检测到返回 None。

        *t_pc_ns*: 相机帧的 PC monotonic 时间戳（ns）。**强烈建议显式传入**：
        在 `cap.read()` 成功返回后**立即**记录 `time.monotonic_ns()`，再传给
        本方法（Task 4B-4 fix，事实 #10）。缺省时本方法在检测结束后才打
        `time.monotonic_ns()`，与相机帧实际采集时刻存在处理延迟，同步精度较差。
        """
        det = self.detect(frame)
        if det is None:
            return None
        return self._pose_from_detection(det, t_pc_ns)

    def track_with_diagnostics(
        self, frame: Any, t_pc_ns: Optional[int] = None
    ) -> tuple[Optional[V1Pose], dict]:
        """Track one frame and return bounded detector diagnostics."""
        det, diagnostics = self._detect_with_diagnostics(frame)
        if det is None:
            return None, diagnostics
        return self._pose_from_detection(det, t_pc_ns), diagnostics

    def _pose_from_detection(
        self, det: Dict[str, Any], t_pc_ns: Optional[int]
    ) -> V1Pose:
        cx, cy = det["center_px"]
        x_mm, y_mm = self._hom.pixel_to_mm(cx, cy)
        fx, fy = det["forward_px"]
        x2, y2 = self._hom.pixel_to_mm(cx + fx, cy + fy)
        yaw = math.atan2(y2 - y_mm, x2 - x_mm) + self._offset
        conf = self._confidence(det["side_px"])
        if t_pc_ns is None:
            # V1Pose schema 规定 t_pc_ns 为 PC **monotonic** clock；
            # 不能用 perf_counter_ns（Windows 上二者 epoch 相差 ~17s，
            # 会导致 4B-4 与遥测 pc_recv_ns(monotonic) 对齐失败）。
            t_pc_ns = time.monotonic_ns()
        return V1Pose(
            x_mm=x_mm, y_mm=y_mm, yaw_rad=yaw,
            confidence=conf, t_pc_ns=int(t_pc_ns), source="camera",
        )

    # ------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------
    def _undistort(self, pts: np.ndarray) -> np.ndarray:
        """用内参对像素点去畸变（返回与原图同尺度的坐标）。"""
        inp = pts.reshape(-1, 1, 2).astype(np.float32)
        out = cv2.undistortPoints(
            inp, self._calib.camera_matrix, self._calib.dist_coeffs,
            P=self._calib.camera_matrix,
        )
        return out.reshape(-1, 2).astype(float)

    def _confidence(self, side_px: float) -> float:
        """基于标签尺寸的置信度（>=30px → 1.0，线性衰减到 0.2）。"""
        if side_px >= MIN_GOOD_SIDE_PX:
            return 1.0
        if side_px <= MIN_DETECT_SIDE_PX:
            return 0.2
        span = MIN_GOOD_SIDE_PX - MIN_DETECT_SIDE_PX
        return 0.2 + 0.8 * (side_px - MIN_DETECT_SIDE_PX) / span
