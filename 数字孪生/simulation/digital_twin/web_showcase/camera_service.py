#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Single-owner camera capture and browser preview service."""

from __future__ import print_function

import base64
import os
import sys
import threading
import time

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tracking.config_io import load_config, open_camera
from tracking.pose_math import (
    PoseFilter,
    apply_car_center_offset,
    tag_pose_from_corners,
    validate_homography,
)


class CameraServiceError(RuntimeError):
    pass


class EmbeddedPoseTracker(object):
    """Detect AprilTag poses from frames already owned by SharedCameraService."""

    def __init__(self):
        self.detector = None
        self.dictionary_name = None
        self.pose_filter = None
        self.filter_signature = None
        self.last_detection = 0.0
        self.last_accepted = 0.0

    def reset(self):
        if self.pose_filter is not None:
            self.pose_filter.reset()
        self.last_detection = 0.0
        self.last_accepted = 0.0

    def _ensure_detector(self, dictionary_name):
        if self.detector is not None and self.dictionary_name == dictionary_name:
            return
        if not hasattr(cv2, "aruco"):
            raise CameraServiceError(
                "当前 OpenCV 缺少 AprilTag 识别组件，请安装 opencv-contrib-python"
            )
        dictionary_id = getattr(cv2.aruco, dictionary_name, None)
        if dictionary_id is None:
            raise CameraServiceError("未知 AprilTag 字典：%s" % dictionary_name)
        dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
        parameters = cv2.aruco.DetectorParameters()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        if hasattr(cv2.aruco, "ArucoDetector"):
            self.detector = cv2.aruco.ArucoDetector(dictionary, parameters)
        else:
            self.detector = (dictionary, parameters)
        self.dictionary_name = dictionary_name

    def _ensure_filter(self, filter_config):
        signature = (
            float(filter_config.get("position_alpha", 0.35)),
            float(filter_config.get("yaw_alpha", 0.3)),
            float(filter_config.get("max_jump", 0.35)),
        )
        if self.pose_filter is None or signature != self.filter_signature:
            self.pose_filter = PoseFilter(*signature)
            self.filter_signature = signature
            self.reset()

    def detect(self, frame, config):
        floor = config.get("floor", {})
        if not floor.get("calibrated"):
            return None
        homography = validate_homography(floor.get("homography"))
        tag = config.get("tag", {})
        dictionary_name = tag.get("dictionary", "DICT_APRILTAG_36h11")
        self._ensure_detector(dictionary_name)
        self._ensure_filter(config.get("filter", {}))

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if isinstance(self.detector, tuple):
            corners, identifiers, _rejected = cv2.aruco.detectMarkers(
                gray,
                self.detector[0],
                parameters=self.detector[1],
            )
        else:
            corners, identifiers, _rejected = self.detector.detectMarkers(gray)
        if identifiers is None:
            return None

        wanted_id = int(tag.get("id", 0))
        tag_corners = None
        for index, identifier in enumerate(np.asarray(identifiers).reshape((-1,))):
            if int(identifier) == wanted_id:
                tag_corners = np.asarray(
                    corners[index],
                    dtype=np.float64,
                ).reshape((4, 2))
                break
        if tag_corners is None:
            return None

        now = time.monotonic()
        if self.last_detection and now - self.last_detection > 1.0:
            self.pose_filter.reset()
        raw_pose = tag_pose_from_corners(
            tag_corners,
            homography,
            tag.get("front_edge", "top"),
            tag.get("yaw_offset_deg", 0.0),
        )
        raw_pose = apply_car_center_offset(
            raw_pose,
            tag.get("car_center_offset_forward", 0.0),
            tag.get("car_center_offset_right", 0.0),
        )
        minimum_area = max(1.0, float(tag.get("minimum_pixel_area", 500.0)))
        quality = max(0.0, min(1.0, raw_pose["pixel_area"] / minimum_area))
        raw_pose["quality"] = quality
        self.last_detection = now
        if quality < 0.7:
            return None

        pose = self.pose_filter.update(raw_pose)
        if pose is None and self.last_accepted and now - self.last_accepted > 1.0:
            self.pose_filter.reset()
            pose = self.pose_filter.update(raw_pose)
        if pose is None:
            return None
        self.last_accepted = now
        return {
            "timestamp_ms": int(time.time() * 1000),
            "x": float(pose["x"]),
            "z": float(pose["z"]),
            "yaw_deg": float(pose["yaw_deg"]),
            "quality": float(pose["quality"]),
            "source": "overhead-camera-service",
        }


class SharedCameraService(object):
    def __init__(self, config_path):
        self.config_path = config_path
        self.capture = None
        self.thread = None
        self.lock = threading.Lock()
        self.running = False
        self.latest = None
        self.frame_id = 0
        self.last_frame_time = 0.0
        self.last_error = ""

    def start(self):
        if self.running and self.thread is not None and self.thread.is_alive():
            return self.status()
        self.stop()
        config = load_config(self.config_path)
        try:
            self.capture = open_camera(config["camera"])
        except Exception as exc:
            self.last_error = "无法打开摄像头：%s" % exc
            raise CameraServiceError(self.last_error)
        self.running = True
        self.last_error = ""
        self.thread = threading.Thread(
            target=self._capture_loop,
            name="TwinTrackCamera",
            daemon=True,
        )
        self.thread.start()
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            if self.snapshot() is not None:
                return self.status()
            if self.last_error:
                break
            time.sleep(0.04)
        self.stop()
        raise CameraServiceError(
            self.last_error or "摄像头已打开，但没有返回有效画面"
        )

    def _capture_loop(self):
        failures = 0
        while self.running:
            try:
                ok, frame = self.capture.read()
            except Exception as exc:
                ok = False
                frame = None
                self.last_error = "读取摄像头失败：%s" % exc
            if ok and frame is not None:
                with self.lock:
                    self.latest = frame
                    self.frame_id += 1
                    self.last_frame_time = time.time()
                failures = 0
            else:
                failures += 1
                if failures >= 30:
                    self.last_error = "摄像头连续30帧读取失败"
                    self.running = False
                    break
                time.sleep(0.03)
        capture = self.capture
        self.capture = None
        if capture is not None:
            capture.release()

    def stop(self):
        self.running = False
        capture = self.capture
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass
        thread = self.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self.thread = None
        self.capture = None
        with self.lock:
            self.latest = None

    def snapshot(self):
        with self.lock:
            return None if self.latest is None else self.latest.copy()

    def status(self):
        frame = self.snapshot()
        return {
            "running": bool(
                self.running
                and self.thread is not None
                and self.thread.is_alive()
            ),
            "frame_id": self.frame_id,
            "width": int(frame.shape[1]) if frame is not None else None,
            "height": int(frame.shape[0]) if frame is not None else None,
            "last_frame_age_ms": int(
                max(0.0, time.time() - self.last_frame_time) * 1000
            ) if self.last_frame_time else None,
            "error": self.last_error,
        }

    @staticmethod
    def encode_frame(frame, max_width=960, quality=72, points=None):
        if frame is None:
            raise CameraServiceError("没有可用的摄像头画面")
        output = frame.copy()
        if points:
            for index, point in enumerate(points):
                x_value = int(round(float(point[0])))
                y_value = int(round(float(point[1])))
                cv2.circle(
                    output,
                    (x_value, y_value),
                    8,
                    (40, 220, 160),
                    -1,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    output,
                    str(index + 1),
                    (x_value + 10, y_value - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (40, 220, 160),
                    2,
                    cv2.LINE_AA,
                )
            if len(points) > 1:
                cv2.polylines(
                    output,
                    [np.asarray(points, dtype=np.int32)],
                    len(points) == 4,
                    (255, 190, 60),
                    2,
                    cv2.LINE_AA,
                )
        height, width = output.shape[:2]
        if width > max_width:
            scale = max_width / float(width)
            output = cv2.resize(
                output,
                (max_width, max(1, int(round(height * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        ok, encoded = cv2.imencode(
            ".jpg",
            output,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)],
        )
        if not ok:
            raise CameraServiceError("摄像头预览编码失败")
        return {
            "mime": "image/jpeg",
            "data_url": "data:image/jpeg;base64,"
            + base64.b64encode(encoded.tobytes()).decode("ascii"),
            "source_width": int(width),
            "source_height": int(height),
            "preview_width": int(output.shape[1]),
            "preview_height": int(output.shape[0]),
        }


def calibration_homography(normalized_points, frame_shape, width_m, height_m):
    if len(normalized_points) != 4:
        raise CameraServiceError("地面标定必须恰好包含4个点")
    frame_height, frame_width = frame_shape[:2]
    image_points = []
    for point in normalized_points:
        x_value = float(point[0])
        y_value = float(point[1])
        if not (0.0 <= x_value <= 1.0 and 0.0 <= y_value <= 1.0):
            raise CameraServiceError("标定点超出了摄像头画面")
        image_points.append((
            x_value * frame_width,
            y_value * frame_height,
        ))
    source = np.asarray(image_points, dtype=np.float32)
    polygon = source.reshape((-1, 1, 2))
    minimum_area = float(frame_width * frame_height) * 0.02
    if (
        not cv2.isContourConvex(polygon)
        or abs(float(cv2.contourArea(polygon))) < minimum_area
    ):
        raise CameraServiceError(
            "四个标定点必须按顺序围成足够大的凸四边形"
        )
    destination = np.asarray(
        (
            (0.0, 0.0),
            (float(width_m), 0.0),
            (float(width_m), float(height_m)),
            (0.0, float(height_m)),
        ),
        dtype=np.float32,
    )
    homography = cv2.getPerspectiveTransform(source, destination)
    if not np.isfinite(homography).all() or abs(np.linalg.det(homography)) < 1e-12:
        raise CameraServiceError("标定点排列无效，请重新选择四个角点")
    return image_points, homography.tolist()
