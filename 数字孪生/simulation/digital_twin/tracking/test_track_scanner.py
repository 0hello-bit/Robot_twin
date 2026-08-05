#!/usr/bin/env python
# -*- coding: utf-8 -*-

import math
import unittest

import cv2
import numpy as np

from track_scanner import TrackScanError, extract_track_map


class TrackScannerTests(unittest.TestCase):
    @staticmethod
    def _config(calibrated=True):
        return {
            "floor": {
                "calibrated": calibrated,
                "width": 2.0,
                "height": 1.5,
                "homography": [
                    [2.0 / 1000.0, 0.0, 0.0],
                    [0.0, 1.5 / 750.0, 0.0],
                    [0.0, 0.0, 1.0],
                ],
            }
        }

    def test_extracts_closed_ellipse_in_metric_coordinates(self):
        frame = np.full((750, 1000, 3), 238, dtype=np.uint8)
        cv2.ellipse(frame, (500, 375), (350, 235), 0, 0, 360, (15, 15, 15), 30)
        payload, preview = extract_track_map(frame, self._config())

        self.assertTrue(payload["track"]["closed"])
        self.assertEqual(len(payload["track"]["points"]), 180)
        self.assertAlmostEqual(payload["track"]["width_m"], 0.06, delta=0.02)
        expected_length = math.pi * (
            3 * (0.7 + 0.47)
            - math.sqrt((3 * 0.7 + 0.47) * (0.7 + 3 * 0.47))
        )
        self.assertAlmostEqual(
            payload["track"]["length_m"],
            expected_length,
            delta=0.25,
        )
        self.assertGreater(payload["detection"]["quality"], 0.7)
        self.assertEqual(preview.shape[:2], (750, 1000))

    def test_rejects_uncalibrated_floor(self):
        frame = np.full((100, 100, 3), 255, dtype=np.uint8)
        with self.assertRaisesRegex(TrackScanError, "尚未标定"):
            extract_track_map(frame, self._config(calibrated=False))

    def test_rejects_non_loop_blob(self):
        frame = np.full((750, 1000, 3), 240, dtype=np.uint8)
        cv2.rectangle(frame, (200, 330), (800, 420), (10, 10, 10), -1)
        with self.assertRaisesRegex(TrackScanError, "没有识别到闭合"):
            extract_track_map(frame, self._config())


if __name__ == "__main__":
    unittest.main()
