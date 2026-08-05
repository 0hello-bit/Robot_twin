# Run this on CanMV K230 with four fixed AprilTag 36h11 markers.
import gc
import os
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
from k230_math import homography_from_four_points


sensor = None
sample_centers = {}

try:
    sensor = Sensor(width=DETECT_WIDTH, height=DETECT_HEIGHT)
    sensor.reset()
    sensor.set_framesize(width=DETECT_WIDTH, height=DETECT_HEIGHT)
    sensor.set_pixformat(Sensor.GRAYSCALE)
    if PREVIEW_TO_IDE:
        Display.init(Display.VIRT, width=DETECT_WIDTH, height=DETECT_HEIGHT, fps=30)
    MediaManager.init()
    sensor.run()

    print("Place calibration tags %s and keep them still." % (CALIBRATION_TAG_IDS,))
    print("Waiting for 30 complete frames...")
    complete_frames = 0
    while complete_frames < 30:
        os.exitpoint()
        frame = sensor.snapshot()
        detected = {}
        for tag in frame.find_apriltags(families=image.TAG36H11):
            if tag.id() in CALIBRATION_TAG_IDS:
                detected[tag.id()] = (tag.cx(), tag.cy())
                frame.draw_rectangle(tag.rect(), color=255)
                frame.draw_cross(tag.cx(), tag.cy(), color=255)
        if all(tag_id in detected for tag_id in CALIBRATION_TAG_IDS):
            complete_frames += 1
            for tag_id in CALIBRATION_TAG_IDS:
                sample_centers.setdefault(tag_id, []).append(detected[tag_id])
            print("calibration frame %d/30" % complete_frames)
        if PREVIEW_TO_IDE:
            Display.show_image(frame)
        gc.collect()

    image_points = []
    for tag_id in CALIBRATION_TAG_IDS:
        samples = sample_centers[tag_id]
        image_points.append((
            sum(point[0] for point in samples) / float(len(samples)),
            sum(point[1] for point in samples) / float(len(samples)),
        ))
    world_points = (
        (0.0, 0.0),
        (FLOOR_WIDTH, 0.0),
        (FLOOR_WIDTH, FLOOR_HEIGHT),
        (0.0, FLOOR_HEIGHT),
    )
    homography = homography_from_four_points(image_points, world_points)
    with open(CALIBRATION_FILE, "w") as output:
        json.dump({
            "image_points": image_points,
            "world_points": world_points,
            "homography": homography,
        }, output)
    print("Saved floor calibration to %s" % CALIBRATION_FILE)
except KeyboardInterrupt:
    print("Calibration cancelled")
except BaseException as error:
    print("Calibration error: %s" % error)
finally:
    if isinstance(sensor, Sensor):
        sensor.stop()
    if PREVIEW_TO_IDE:
        Display.deinit()
    os.exitpoint(os.EXITPOINT_ENABLE_SLEEP)
    time.sleep_ms(100)
    MediaManager.deinit()

