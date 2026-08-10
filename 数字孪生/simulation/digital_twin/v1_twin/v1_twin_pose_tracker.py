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


_ROI_PREPROCESS_MODES = (
    "blue_clahe",
    "blue_unsharp",
    "gray_clahe",
)


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
        roi_padding_px: float = 32.0,
        full_frame_fallback_scales: Sequence[float] = (2.0,),
        roi_preprocess_scales: Sequence[float] = (2.0,),
        detector_parameters: Optional[Any] = None,
        roi_detect_scales: Optional[Sequence[float]] = None,
        recovery_preprocess_modes: Sequence[str] = _ROI_PREPROCESS_MODES,
        cache_preprocessors: bool = False,
        recovery_policy: str = "production",
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
        self._fallback_scales = tuple(
            float(s) for s in full_frame_fallback_scales
        )
        self._roi_preprocess_scales = tuple(
            float(s) for s in roi_preprocess_scales
        )
        self._roi_detect_scales = (
            self._scales
            if roi_detect_scales is None
            else tuple(float(s) for s in roi_detect_scales)
        )
        if not self._roi_detect_scales:
            raise PoseTrackerError("ROI detect scales must not be empty")
        self._recovery_preprocess_modes = tuple(
            str(mode) for mode in recovery_preprocess_modes
        )
        unsupported_modes = tuple(
            mode
            for mode in self._recovery_preprocess_modes
            if mode not in _ROI_PREPROCESS_MODES
        )
        if unsupported_modes:
            raise PoseTrackerError(
                "unsupported ROI preprocess mode(s): {}".format(
                    ", ".join(unsupported_modes)
                )
            )
        self._cache_preprocessors = bool(cache_preprocessors)
        self._recovery_policy = str(recovery_policy)
        if not self._fallback_scales:
            raise PoseTrackerError("full-frame fallback scales must not be empty")
        if not self._roi_preprocess_scales:
            raise PoseTrackerError("ROI preprocess scales must not be empty")
        self._roi_padding_px = max(0.0, float(roi_padding_px))
        self._last_raw_center: Optional[np.ndarray] = None
        self._last_raw_side_px: Optional[float] = None
        self._dictionary = cv2.aruco.getPredefinedDictionary(
            cv2.aruco.DICT_APRILTAG_36h11
        )
        if detector_parameters is None:
            detector_parameters = cv2.aruco.DetectorParameters()
        self._detector = cv2.aruco.ArucoDetector(
            self._dictionary, detector_parameters
        )
        self._cached_clahe = (
            cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
            if self._cache_preprocessors
            else None
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
        roi_bounds = self._roi_bounds(gray)
        attempted_regions = []
        preprocess_modes_attempted = []
        if roi_bounds is not None:
            attempted_regions.append("roi")
            x0, y0, x1, y1 = roi_bounds
            roi_detection, roi_scale, roi_saw_markers = self._detect_region(
                gray[y0:y1, x0:x1],
                x0,
                y0,
                attempted_scales,
                rejected_candidate_counts,
                scales=self._roi_detect_scales,
            )
            saw_markers = saw_markers or roi_saw_markers
            if roi_detection is not None:
                return roi_detection, {
                    "attempted_scales": attempted_scales,
                    "matched_scale": roi_scale,
                    "tag_side_px": float(roi_detection["side_px"]),
                    "failure_reason": None,
                    "rejected_candidate_count": int(
                        sum(rejected_candidate_counts)
                    ),
                    "rejected_candidate_counts": list(
                        rejected_candidate_counts
                    ),
                    "detect_elapsed_ns": time.perf_counter_ns() - started_ns,
                    "search_mode": "roi",
                    "search_regions": ["roi"],
                    "roi_bounds": list(roi_bounds),
                    "full_frame_fallback": False,
                    "preprocess_mode": None,
                    "preprocess_modes_attempted": [],
                    "preprocess_border_px": None,
                    "recovery_policy": self._recovery_policy,
                }
            if frame.ndim == 3:
                for (
                    preprocess_mode,
                    prepared_roi,
                    prepared_offset_x,
                    prepared_offset_y,
                ) in (
                    self._roi_preprocessed_inputs(frame, roi_bounds)
                ):
                    attempted_regions.append("roi_" + preprocess_mode)
                    preprocess_modes_attempted.append(preprocess_mode)
                    preprocessed_detection, preprocessed_scale, preprocessed_saw_markers = (
                        self._detect_region(
                            prepared_roi,
                            prepared_offset_x,
                            prepared_offset_y,
                            attempted_scales,
                            rejected_candidate_counts,
                            scales=self._roi_preprocess_scales,
                        )
                    )
                    saw_markers = saw_markers or preprocessed_saw_markers
                    if preprocessed_detection is not None:
                        return preprocessed_detection, {
                            "attempted_scales": attempted_scales,
                            "matched_scale": preprocessed_scale,
                            "tag_side_px": float(
                                preprocessed_detection["side_px"]
                            ),
                            "failure_reason": None,
                            "rejected_candidate_count": int(
                                sum(rejected_candidate_counts)
                            ),
                            "rejected_candidate_counts": list(
                                rejected_candidate_counts
                            ),
                            "detect_elapsed_ns": (
                                time.perf_counter_ns() - started_ns
                            ),
                            "search_mode": "roi_preprocessed",
                            "search_regions": list(attempted_regions),
                            "roi_bounds": list(roi_bounds),
                            "full_frame_fallback": False,
                            "preprocess_mode": preprocess_mode,
                            "preprocess_modes_attempted": list(
                                preprocess_modes_attempted
                            ),
                            "preprocess_border_px": int(
                                max(16, round(self._roi_padding_px))
                            ),
                            "recovery_policy": self._recovery_policy,
                        }
        attempted_regions.append("full_frame")
        # The first frame keeps the full multi-scale probe; ROI misses use the
        # evidence-backed 2x reacquisition budget to avoid duplicate 1x/3x work.
        full_frame_scales = (
            self._scales if roi_bounds is None else self._fallback_scales
        )
        for scale in full_frame_scales:
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
                self._last_raw_center = pts.mean(axis=0)
                self._last_raw_side_px = float(
                    np.linalg.norm(pts[0] - pts[1])
                )
                pts_u = self._undistort(pts)
                center = pts_u.mean(axis=0)
                # 印刷正上 = TL - BL = corner0 - corner3
                fwd = pts_u[0] - pts_u[3]
                side = float(np.linalg.norm(pts_u[0] - pts_u[1]))
                detection = {
                    "corners": pts_u,
                    "raw_corners": pts.copy(),
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
                    "search_mode": (
                        "roi_then_full"
                        if roi_bounds is not None
                        else "full_frame"
                    ),
                    "search_regions": list(attempted_regions),
                    "roi_bounds": (
                        list(roi_bounds) if roi_bounds is not None else None
                    ),
                    "full_frame_fallback": roi_bounds is not None,
                    "preprocess_mode": None,
                    "preprocess_modes_attempted": list(
                        preprocess_modes_attempted
                    ),
                    "preprocess_border_px": None,
                    "recovery_policy": self._recovery_policy,
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
            "search_mode": (
                "roi_then_full" if roi_bounds is not None else "full_frame"
            ),
            "search_regions": list(attempted_regions),
            "roi_bounds": (
                list(roi_bounds) if roi_bounds is not None else None
            ),
            "full_frame_fallback": roi_bounds is not None,
            "preprocess_mode": None,
            "preprocess_modes_attempted": list(preprocess_modes_attempted),
            "preprocess_border_px": None,
            "recovery_policy": self._recovery_policy,
        }

    def _roi_bounds(self, gray: np.ndarray) -> Optional[tuple[int, int, int, int]]:
        """Return a bounded region around the last valid tag."""
        if self._last_raw_center is None or self._last_raw_side_px is None:
            return None
        height, width = gray.shape[:2]
        half_size = max(
            96.0,
            1.5 * max(self._last_raw_side_px, MIN_DETECT_SIDE_PX)
            + self._roi_padding_px,
        )
        center_x, center_y = self._last_raw_center
        x0 = max(0, int(math.floor(center_x - half_size)))
        y0 = max(0, int(math.floor(center_y - half_size)))
        x1 = min(width, int(math.ceil(center_x + half_size)))
        y1 = min(height, int(math.ceil(center_y + half_size)))
        if x1 <= x0 or y1 <= y0:
            return None
        return x0, y0, x1, y1

    def _roi_preprocessed_inputs(
        self,
        frame: np.ndarray,
        roi_bounds: tuple[int, int, int, int],
    ) -> tuple[tuple[str, np.ndarray, int, int], ...]:
        """Return bounded local contrast inputs after the raw ROI misses."""
        x0, y0, x1, y1 = roi_bounds
        roi = frame[y0:y1, x0:x1]
        if roi.ndim != 3 or roi.shape[2] < 3:
            return ()
        border = max(16, int(round(self._roi_padding_px)))
        roi = cv2.copyMakeBorder(
            roi,
            border,
            border,
            border,
            border,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )
        offset_x = x0 - border
        offset_y = y0 - border
        blue = None
        gray = None
        blue_blur = None
        clahe = self._cached_clahe
        prepared = []
        for mode in self._recovery_preprocess_modes:
            if mode == "blue_clahe":
                if blue is None:
                    blue = roi[:, :, 0]
                if clahe is None:
                    clahe = cv2.createCLAHE(
                        clipLimit=2.0, tileGridSize=(4, 4)
                    )
                image = clahe.apply(blue)
            elif mode == "blue_unsharp":
                if blue is None:
                    blue = roi[:, :, 0]
                if blue_blur is None:
                    blue_blur = cv2.GaussianBlur(blue, (0, 0), 1.0)
                image = cv2.addWeighted(blue, 2.0, blue_blur, -1.0, 0)
            else:  # gray_clahe
                if gray is None:
                    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                if clahe is None:
                    clahe = cv2.createCLAHE(
                        clipLimit=2.0, tileGridSize=(4, 4)
                    )
                image = clahe.apply(gray)
            prepared.append((mode, image, offset_x, offset_y))
        return tuple(prepared)

    def _detect_region(
        self,
        gray: np.ndarray,
        offset_x: int,
        offset_y: int,
        attempted_scales: list[float],
        rejected_candidate_counts: list[int],
        scales: Optional[Sequence[float]] = None,
    ) -> tuple[Optional[Dict[str, Any]], Optional[float], bool]:
        """Detect the configured target ID in one image region."""
        saw_markers = False
        active_scales = self._scales if scales is None else tuple(scales)
        for scale in active_scales:
            attempted_scales.append(float(scale))
            if scale == 1.0:
                g = gray
            else:
                g = cv2.resize(
                    gray,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_CUBIC,
                )
            corners_l, ids, rejected = self._detector.detectMarkers(g)
            rejected_count = len(rejected) if rejected is not None else 0
            rejected_candidate_counts.append(rejected_count)
            if ids is None:
                continue
            saw_markers = True
            for c, i in zip(corners_l, ids.ravel()):
                if int(i) != self._tag_id:
                    continue
                pts = np.asarray(c[0], dtype=float) / scale
                pts[:, 0] += float(offset_x)
                pts[:, 1] += float(offset_y)
                self._last_raw_center = pts.mean(axis=0)
                self._last_raw_side_px = float(
                    np.linalg.norm(pts[0] - pts[1])
                )
                pts_u = self._undistort(pts)
                center = pts_u.mean(axis=0)
                fwd = pts_u[0] - pts_u[3]
                side = float(np.linalg.norm(pts_u[0] - pts_u[1]))
                return {
                    "corners": pts_u,
                    "raw_corners": pts.copy(),
                    "center_px": center,
                    "forward_px": fwd,
                    "side_px": side,
                }, float(scale), saw_markers
        return None, None, saw_markers

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

    def track_with_diagnostics_and_geometry(
        self, frame: Any, t_pc_ns: Optional[int] = None
    ) -> tuple[Optional[V1Pose], dict, Optional[np.ndarray]]:
        """Return the decoded pose plus raw tag corners for offline observers."""
        det, diagnostics = self._detect_with_diagnostics(frame)
        if det is None:
            return None, diagnostics, None
        raw_corners = np.asarray(det["raw_corners"], dtype=float).copy()
        return self._pose_from_detection(det, t_pc_ns), diagnostics, raw_corners

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

    def project_raw_corners(self, raw_corners: Any) -> Dict[str, float]:
        """Project tracked raw pixel corners without claiming an AprilTag decode."""
        pts = np.asarray(raw_corners, dtype=float)
        if pts.shape != (4, 2) or not np.isfinite(pts).all():
            raise ValueError("raw_corners must be a finite (4, 2) array")
        pts_u = self._undistort(pts)
        center = pts_u.mean(axis=0)
        x_mm, y_mm = self._hom.pixel_to_mm(float(center[0]), float(center[1]))
        fwd = pts_u[0] - pts_u[3]
        x2, y2 = self._hom.pixel_to_mm(
            float(center[0] + fwd[0]), float(center[1] + fwd[1])
        )
        yaw = math.atan2(y2 - y_mm, x2 - x_mm) + self._offset
        side = float(np.linalg.norm(pts_u[0] - pts_u[1]))
        return {
            "x_mm": float(x_mm),
            "y_mm": float(y_mm),
            "yaw_rad": float(yaw),
            "confidence": float(self._confidence(side)),
        }

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
