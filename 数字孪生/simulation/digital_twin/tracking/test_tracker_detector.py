#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import unittest

import cv2
import numpy as np

from pose_tracker import AprilTagDetector, find_tag


class AprilTagDetectorTests(unittest.TestCase):
    def test_generated_tags_are_detected(self):
        detector = AprilTagDetector("DICT_APRILTAG_36h11")
        for tag_id in (0, 10, 11, 12, 13):
            image_path = os.path.join(os.path.dirname(__file__), "apriltag_36h11_id%d.png" % tag_id)
            encoded = np.fromfile(image_path, dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            self.assertIsNotNone(image)
            corners, identifiers, _rejected = detector.detect(image)
            tag = find_tag(corners, identifiers, tag_id)
            self.assertIsNotNone(tag)
            self.assertEqual(tag.shape, (4, 2))


if __name__ == "__main__":
    unittest.main()
