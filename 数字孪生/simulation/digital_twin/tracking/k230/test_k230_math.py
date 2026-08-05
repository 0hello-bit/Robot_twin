import unittest

from k230_math import homography_from_four_points, pose_from_corners, project_point


class K230MathTests(unittest.TestCase):
    def test_four_point_homography(self):
        image_points = ((100, 50), (500, 50), (500, 350), (100, 350))
        world_points = ((0, 0), (2, 0), (2, 1.5), (0, 1.5))
        homography = homography_from_four_points(image_points, world_points)
        self.assertAlmostEqual(project_point(homography, 300, 200)[0], 1.0, places=6)
        self.assertAlmostEqual(project_point(homography, 300, 200)[1], 0.75, places=6)
        pose = pose_from_corners(((280, 180), (320, 180), (320, 220), (280, 220)), homography)
        self.assertAlmostEqual(pose["x"], 1.0, places=6)
        self.assertAlmostEqual(pose["z"], 0.75, places=6)
        self.assertAlmostEqual(pose["yaw_deg"], 90.0, places=6)


if __name__ == "__main__":
    unittest.main()

