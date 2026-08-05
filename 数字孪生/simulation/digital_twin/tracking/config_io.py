#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Configuration and camera helpers for the overhead tracker."""

from __future__ import print_function

import json
import os
import sys

import cv2


DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker_config.json")


def load_config(path=DEFAULT_CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    for section in ("camera", "tag", "floor", "filter", "output"):
        if section not in config or not isinstance(config[section], dict):
            raise ValueError("missing config section: %s" % section)
    return config


def save_config(path, config):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def resolve_camera_source(camera_config, source_override=None):
    if source_override is not None:
        value = str(source_override).strip()
        if value.isdigit():
            return int(value)
        if value:
            return value
    if camera_config.get("mode") == "stream":
        stream_url = str(camera_config.get("stream_url", "")).strip()
        if not stream_url:
            raise ValueError("camera mode is stream but stream_url is empty")
        return stream_url
    return int(camera_config.get("index", 0))


def open_camera(camera_config, source_override=None):
    source = resolve_camera_source(camera_config, source_override)
    is_device = isinstance(source, int)
    backend = cv2.CAP_DSHOW if is_device and sys.platform.startswith("win") else cv2.CAP_ANY
    capture = cv2.VideoCapture(source, backend)
    if not capture.isOpened() and backend != cv2.CAP_ANY:
        capture.release()
        capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError("cannot open camera source %s" % source)
    width = int(camera_config.get("width", 1280))
    height = int(camera_config.get("height", 720))
    fps = float(camera_config.get("fps", 30))
    if is_device:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_FPS, fps)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture
