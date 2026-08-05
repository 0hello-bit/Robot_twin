#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division

import math
import unittest

import numpy as np

from pose_math import PoseFilter, apply_car_center_offset, project_points, tag_pose_from_corners


class PoseMathTests(unittest.TestCase):
    def test_homography_projection_and_tag_heading(self):
        homography = np.asarray(((0.01, 0.0, 0.0), (0.0, 0.01, 0.0), (0.0, 0.0, 1.0)))
        corners = np.asarray(((100, 100), (200, 100), (200, 200), (100, 200)))
        pose = tag_pose_from_corners(corners, homography, "top", 0)
        self.assertAlmostEqual(pose["x"], 1.5, places=6)
        self.assertAlmostEqual(pose["z"], 1.5, places=6)
        self.assertAlmostEqual(pose["yaw_deg"], 90.0, places=6)
        projected = project_points(((25, 50),), homography)
        self.assertTrue(np.allclose(projected[0], (0.25, 0.5)))

    def test_pose_filter_uses_shortest_yaw_path(self):
        pose_filter = PoseFilter(position_alpha=0.25, yaw_alpha=0.5, max_jump=2.0)
        first = pose_filter.update({"x": 0.0, "z": 0.0, "yaw_deg": 170.0})
        second = pose_filter.update({"x": 1.0, "z": 0.0, "yaw_deg": -170.0})
        self.assertEqual(first["x"], 0.0)
        self.assertAlmostEqual(second["x"], 0.25, places=6)
        self.assertAlmostEqual(abs(second["yaw_deg"]), 180.0, places=6)

    def test_jump_rejection_and_center_offset(self):
        pose_filter = PoseFilter(max_jump=0.2)
        pose_filter.update({"x": 0.0, "z": 0.0, "yaw_deg": 0.0})
        self.assertIsNone(pose_filter.update({"x": 1.0, "z": 0.0, "yaw_deg": 0.0}))
        centered = apply_car_center_offset({"x": 1.0, "z": 2.0, "yaw_deg": 90.0}, 0.1, 0.0)
        self.assertAlmostEqual(centered["x"], 1.0, places=6)
        self.assertAlmostEqual(centered["z"], 2.1, places=6)


if __name__ == "__main__":
    unittest.main()

