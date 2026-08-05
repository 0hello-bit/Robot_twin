#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Interactive four-point floor-plane calibration for the overhead camera."""

from __future__ import print_function

import argparse
import os
import sys

import cv2
import numpy as np

from config_io import DEFAULT_CONFIG_PATH, load_config, open_camera, save_config


WINDOW_NAME = "STM32 floor calibration"
POINT_NAMES = ("origin (0,0)", "x corner", "opposite corner", "z corner")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Four-point overhead camera floor calibration")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument("--source", default=None, help="camera index or network video URL")
    parser.add_argument("--width", type=float, default=None, help="measured floor width along +x")
    parser.add_argument("--height", type=float, default=None, help="measured floor height along +z")
    parser.add_argument("--image", default="", help="calibrate from a saved image instead of a camera")
    return parser.parse_args(argv)


def draw_overlay(frame, points, width, height):
    output = frame.copy()
    for index, point in enumerate(points):
        cv2.circle(output, point, 7, (40, 220, 160), -1, cv2.LINE_AA)
        cv2.putText(output, str(index + 1), (point[0] + 9, point[1] - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 220, 160), 2, cv2.LINE_AA)
    if len(points) > 1:
        cv2.polylines(output, [np.asarray(points, dtype=np.int32)], len(points) == 4, (255, 190, 60), 2, cv2.LINE_AA)
    instruction = "Click: origin -> X corner -> opposite -> Z corner"
    cv2.putText(output, instruction, (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.66, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(output, "R reset | SPACE recapture | S save | Q quit | floor %.3f x %.3f" % (width, height), (18, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2, cv2.LINE_AA)
    if len(points) < 4:
        cv2.putText(output, "Next: %s" % POINT_NAMES[len(points)], (18, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (80, 220, 255), 2, cv2.LINE_AA)
    else:
        cv2.putText(output, "Four points ready - press S to save", (18, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (80, 255, 120), 2, cv2.LINE_AA)
    return output


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    config_path = os.path.abspath(args.config)
    config = load_config(config_path)
    width = float(args.width if args.width is not None else config["floor"].get("width", 2.0))
    height = float(args.height if args.height is not None else config["floor"].get("height", 1.5))
    if width <= 0 or height <= 0:
        raise ValueError("floor width and height must be positive")

    capture = None
    if args.image:
        encoded = np.fromfile(os.path.abspath(args.image), dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("cannot read image: %s" % args.image)
    else:
        source_override = args.source if args.source is not None else args.camera
        capture = open_camera(config["camera"], source_override)
        frame = None
        ok = False
        for _index in range(15):
            ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            raise RuntimeError("camera opened but did not return a frame")

    points = []

    def on_mouse(event, x_value, y_value, flags, user_data):
        del flags, user_data
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((int(x_value), int(y_value)))

    print("依次点击：原点、X轴端点、对角点、Z轴端点。按 S 保存，R 重置，Q 退出。")
    print("地面尺寸：%.3f x %.3f（单位由你决定，后续必须保持一致）" % (width, height))
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WINDOW_NAME, on_mouse)
    saved = False
    try:
        while True:
            cv2.imshow(WINDOW_NAME, draw_overlay(frame, points, width, height))
            key = cv2.waitKey(20) & 0xFF
            try:
                window_closed = (
                    cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
                )
            except cv2.error:
                window_closed = True
            if window_closed:
                break
            if key in (ord("q"), 27):
                break
            if key == ord("r"):
                del points[:]
            if key == ord(" ") and capture is not None:
                ok, next_frame = capture.read()
                if ok and next_frame is not None:
                    frame = next_frame
                    del points[:]
            if key == ord("s") and len(points) == 4:
                source = np.asarray(points, dtype=np.float32)
                destination = np.asarray(((0.0, 0.0), (width, 0.0), (width, height), (0.0, height)), dtype=np.float32)
                homography = cv2.getPerspectiveTransform(source, destination)
                config["floor"]["calibrated"] = True
                config["floor"]["width"] = width
                config["floor"]["height"] = height
                config["floor"]["homography"] = homography.tolist()
                config["floor"]["image_points"] = [list(point) for point in points]
                if args.camera is not None:
                    config["camera"]["mode"] = "device"
                    config["camera"]["index"] = int(args.camera)
                if args.source is not None:
                    source_value = str(args.source).strip()
                    if source_value.isdigit():
                        config["camera"]["mode"] = "device"
                        config["camera"]["index"] = int(source_value)
                        config["camera"]["stream_url"] = ""
                    else:
                        config["camera"]["mode"] = "stream"
                        config["camera"]["stream_url"] = source_value
                save_config(config_path, config)
                print("标定已保存：%s" % config_path)
                saved = True
                break
    finally:
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
