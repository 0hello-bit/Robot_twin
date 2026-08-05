#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Track an overhead AprilTag and publish x/z/yaw to the digital twin."""

from __future__ import print_function

import argparse
import asyncio
import json
import math
import os
import sys
import time

import cv2
import numpy as np
import websockets

from config_io import DEFAULT_CONFIG_PATH, load_config, open_camera, resolve_camera_source
from pose_math import PoseFilter, apply_car_center_offset, tag_pose_from_corners, validate_homography


WINDOW_NAME = "STM32 AprilTag tracker"


class PosePublisher(object):
    def __init__(self, url):
        self.url = url
        self.websocket = None
        self.reader_task = None
        self.last_attempt = 0.0
        self.last_error = ""

    @property
    def connected(self):
        return self.websocket is not None and not self.websocket.closed

    async def _drain_messages(self):
        try:
            async for _message in self.websocket:
                pass
        except Exception:
            pass

    async def connect(self):
        if self.connected:
            return True
        now = time.monotonic()
        if now - self.last_attempt < 1.0:
            return False
        self.last_attempt = now
        await self.close()
        try:
            self.websocket = await asyncio.wait_for(websockets.connect(self.url, max_queue=4), timeout=1.0)
            self.reader_task = asyncio.ensure_future(self._drain_messages())
            self.last_error = ""
            print("位姿接口已连接：%s" % self.url)
            return True
        except Exception as exc:
            self.websocket = None
            self.last_error = str(exc)
            return False

    async def send_pose(self, pose):
        if not await self.connect():
            return False
        payload = {
            "type": "pose",
            "timestamp_ms": int(pose["timestamp_ms"]),
            "x": round(float(pose["x"]), 6),
            "z": round(float(pose["z"]), 6),
            "yaw_deg": round(float(pose["yaw_deg"]), 4),
            "quality": round(float(pose["quality"]), 3),
        }
        try:
            await self.websocket.send(json.dumps(payload, separators=(",", ":")))
            return True
        except Exception as exc:
            self.last_error = str(exc)
            await self.close()
            return False

    async def close(self):
        if self.reader_task is not None:
            self.reader_task.cancel()
            self.reader_task = None
        if self.websocket is not None:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None


class AprilTagDetector(object):
    def __init__(self, dictionary_name):
        dictionary_id = getattr(cv2.aruco, dictionary_name, None)
        if dictionary_id is None:
            raise ValueError("unknown OpenCV tag dictionary: %s" % dictionary_name)
        self.dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
        parameters = cv2.aruco.DetectorParameters()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.detector = cv2.aruco.ArucoDetector(self.dictionary, parameters) if hasattr(cv2.aruco, "ArucoDetector") else None
        self.parameters = parameters

    def detect(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.detector is not None:
            return self.detector.detectMarkers(gray)
        return cv2.aruco.detectMarkers(gray, self.dictionary, parameters=self.parameters)


def find_tag(corners, identifiers, wanted_id):
    if identifiers is None:
        return None
    flat_ids = np.asarray(identifiers).reshape((-1,))
    for index, identifier in enumerate(flat_ids):
        if int(identifier) == int(wanted_id):
            return np.asarray(corners[index], dtype=np.float64).reshape((4, 2))
    return None


def draw_preview(frame, corners, pose, publisher, rejected_reason=""):
    output = frame.copy()
    if corners is not None:
        polygon = np.asarray(corners, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(output, [polygon], True, (40, 220, 160), 2, cv2.LINE_AA)
        center = tuple(np.mean(corners, axis=0).astype(int))
        front = tuple(((corners[0] + corners[1]) * 0.5).astype(int))
        cv2.arrowedLine(output, center, front, (80, 220, 255), 3, cv2.LINE_AA, tipLength=0.25)
    link_text = "POSE LINK ONLINE" if publisher.connected else "POSE LINK OFFLINE"
    link_color = (80, 255, 120) if publisher.connected else (60, 160, 255)
    cv2.putText(output, link_text, (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, link_color, 2, cv2.LINE_AA)
    if pose is not None:
        text_value = "x %.3f  z %.3f  yaw %.1f  q %.2f" % (pose["x"], pose["z"], pose["yaw_deg"], pose["quality"])
        cv2.putText(output, text_value, (18, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
    elif rejected_reason:
        cv2.putText(output, rejected_reason, (18, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (60, 160, 255), 2, cv2.LINE_AA)
    cv2.putText(output, "Q quit", (18, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 220, 230), 2, cv2.LINE_AA)
    return output


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Overhead AprilTag pose tracker for the STM32 digital twin")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument("--source", default=None, help="camera index or network video URL")
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument("--probe-camera", action="store_true")
    return parser.parse_args(argv)


def probe_camera(config, source_override):
    capture = open_camera(config["camera"], source_override)
    try:
        frame = None
        for _index in range(15):
            ok, candidate = capture.read()
            if ok and candidate is not None:
                frame = candidate
        if frame is None:
            raise RuntimeError("camera opened but returned no frames")
        source = resolve_camera_source(config["camera"], source_override)
        print(json.dumps({"source": source, "width": int(frame.shape[1]), "height": int(frame.shape[0])}, sort_keys=True))
        return 0
    finally:
        capture.release()


async def run_tracker(config, source_override=None, no_preview=False):
    if not config["floor"].get("calibrated"):
        raise RuntimeError("地面坐标尚未标定，请先运行 calibrate_floor.py")
    homography = validate_homography(config["floor"].get("homography"))
    detector = AprilTagDetector(config["tag"].get("dictionary", "DICT_APRILTAG_36h11"))
    capture = open_camera(config["camera"], source_override)
    publisher = PosePublisher(config["output"].get("websocket_url", "ws://127.0.0.1:8787/live"))
    pose_filter = PoseFilter(
        config["filter"].get("position_alpha", 0.35),
        config["filter"].get("yaw_alpha", 0.3),
        config["filter"].get("max_jump", 0.35),
    )
    preview = bool(config["output"].get("preview", True)) and not no_preview
    minimum_area = max(1.0, float(config["tag"].get("minimum_pixel_area", 500.0)))
    send_interval = 1.0 / max(1.0, float(config["output"].get("send_hz", 30.0)))
    last_send = 0.0
    last_detection = 0.0
    last_accepted = 0.0
    wanted_id = int(config["tag"].get("id", 0))
    print("开始识别 AprilTag ID %d；预览窗口按 Q 退出。" % wanted_id)
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                await asyncio.sleep(0.03)
                continue
            corners, identifiers, _rejected = detector.detect(frame)
            tag_corners = find_tag(corners, identifiers, wanted_id)
            pose = None
            rejected_reason = "tag not found"
            now = time.monotonic()
            if tag_corners is not None:
                if last_detection and now - last_detection > 1.0:
                    pose_filter.reset()
                raw_pose = tag_pose_from_corners(
                    tag_corners,
                    homography,
                    config["tag"].get("front_edge", "top"),
                    config["tag"].get("yaw_offset_deg", 0.0),
                )
                raw_pose = apply_car_center_offset(
                    raw_pose,
                    config["tag"].get("car_center_offset_forward", 0.0),
                    config["tag"].get("car_center_offset_right", 0.0),
                )
                quality = max(0.0, min(1.0, raw_pose["pixel_area"] / minimum_area))
                raw_pose["quality"] = quality
                last_detection = now
                if quality >= 0.7:
                    pose = pose_filter.update(raw_pose)
                    if pose is None:
                        if last_accepted and now - last_accepted > 1.0:
                            pose_filter.reset()
                            pose = pose_filter.update(raw_pose)
                        if pose is None:
                            rejected_reason = "rejected position jump"
                    if pose is not None:
                        last_accepted = now
                else:
                    rejected_reason = "tag too small / blurred"
            if pose is not None and now - last_send >= send_interval:
                pose["timestamp_ms"] = int(time.time() * 1000)
                await publisher.send_pose(pose)
                last_send = now
            if preview:
                cv2.imshow(WINDOW_NAME, draw_preview(frame, tag_corners, pose, publisher, rejected_reason))
                if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                    break
            await asyncio.sleep(0)
    finally:
        capture.release()
        cv2.destroyAllWindows()
        await publisher.close()
    return 0


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    config = load_config(os.path.abspath(args.config))
    source_override = args.source if args.source is not None else args.camera
    if args.probe_camera:
        return probe_camera(config, source_override)
    loop = asyncio.get_event_loop()
    try:
        return loop.run_until_complete(run_tracker(config, source_override, args.no_preview))
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, ValueError) as exc:
        print("视觉定位启动失败：%s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
