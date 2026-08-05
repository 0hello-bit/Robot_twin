# CanMV K230 overhead AprilTag tracker -> UDP pose -> PC live_wifi_bridge.py
import gc
import math
import os
import socket
import time

try:
    import ujson as json
except ImportError:
    import json

import image
from media.sensor import *
from media.display import *
from media.media import *

from k230_config import *
from k230_math import PoseFilter, pose_from_corners


def load_homography():
    with open(CALIBRATION_FILE, "r") as source:
        data = json.load(source)
    return data["homography"]


sensor = None
udp_socket = None

try:
    homography = load_homography()
    destination = socket.getaddrinfo(PC_IP, PC_POSE_UDP_PORT)[0][-1]
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)

    sensor = Sensor(width=DETECT_WIDTH, height=DETECT_HEIGHT)
    sensor.reset()
    sensor.set_framesize(width=DETECT_WIDTH, height=DETECT_HEIGHT)
    sensor.set_pixformat(Sensor.GRAYSCALE)
    if PREVIEW_TO_IDE:
        Display.init(Display.VIRT, width=DETECT_WIDTH, height=DETECT_HEIGHT, fps=30)
    MediaManager.init()
    sensor.run()

    pose_filter = PoseFilter(POSITION_ALPHA, YAW_ALPHA, MAX_JUMP)
    last_send_ms = time.ticks_ms()
    last_seen_ms = last_send_ms
    sequence = 0
    print("K230 pose UDP target: %s:%d" % (PC_IP, PC_POSE_UDP_PORT))

    while True:
        os.exitpoint()
        frame = sensor.snapshot()
        selected = None
        for tag in frame.find_apriltags(families=image.TAG36H11):
            if tag.id() == TAG_ID:
                selected = tag
                break

        now_ms = time.ticks_ms()
        if selected is not None:
            if time.ticks_diff(now_ms, last_seen_ms) > 1000:
                pose_filter.reset()
            last_seen_ms = now_ms
            corners = selected.corners()
            raw_pose = pose_from_corners(corners, homography, TAG_FRONT_EDGE, TAG_YAW_OFFSET_DEG)
            quality = max(0.0, min(1.0, raw_pose["pixel_area"] / MINIMUM_PIXEL_AREA))
            raw_pose["quality"] = quality
            pose = pose_filter.update(raw_pose) if quality >= 0.7 else None
            if pose is not None and time.ticks_diff(now_ms, last_send_ms) >= SEND_INTERVAL_MS:
                packet = {
                    "type": "pose",
                    "timestamp_ms": now_ms,
                    "x": round(pose["x"], 6),
                    "z": round(pose["z"], 6),
                    "yaw_deg": round(pose["yaw_deg"], 4),
                    "quality": round(quality, 3),
                    "source": "k230",
                    "sequence": sequence,
                }
                try:
                    udp_socket.sendto(json.dumps(packet).encode(), destination)
                    sequence = (sequence + 1) & 0x7FFFFFFF
                except OSError as error:
                    print("UDP send error: %s" % error)
                last_send_ms = now_ms
            if PREVIEW_TO_IDE:
                frame.draw_rectangle(selected.rect(), color=255)
                frame.draw_cross(selected.cx(), selected.cy(), color=255)

        if PREVIEW_TO_IDE:
            Display.show_image(frame)
        gc.collect()
except KeyboardInterrupt:
    print("K230 tracker stopped")
except BaseException as error:
    print("K230 tracker error: %s" % error)
finally:
    if isinstance(sensor, Sensor):
        sensor.stop()
    if PREVIEW_TO_IDE:
        Display.deinit()
    if udp_socket is not None:
        udp_socket.close()
    os.exitpoint(os.EXITPOINT_ENABLE_SLEEP)
    time.sleep_ms(100)
    MediaManager.deinit()
