# -*- coding: utf-8 -*-
"""
floor_extractor.py - Extract floor plane from 3D scan

Finds the dominant horizontal plane (floor) from a point cloud
using RANSAC plane fitting.

Usage:
    from scanner.floor_extractor import FloorExtractor
    ext = FloorExtractor()
    floor_points, floor_normal, floor_bounds = ext.extract(points)
"""

import numpy as np


class FloorExtractor:
    """
    Extract the floor plane from a 3D point cloud.
    
    Uses RANSAC to find the largest horizontal plane.
    """

    def __init__(self, distance_threshold=0.05, min_plane_ratio=0.3,
                 vertical_normal_tolerance=0.7):
        """
        Args:
            distance_threshold: max distance from plane to be "inlier" (meters)
            min_plane_ratio: min fraction of points to qualify as floor
            vertical_normal_tolerance: how close normal must be to vertical (0-1)
        """
        self.distance_threshold = distance_threshold
        self.min_plane_ratio = min_plane_ratio
        self.vertical_tolerance = vertical_normal_tolerance

    def extract(self, points, max_iterations=1000):
        """
        Extract floor plane from point cloud.
        
        Args:
            points: Nx3 numpy array
            max_iterations: RANSAC iterations
            
        Returns:
            (floor_points, normal, bounds) or (None, None, None)
        """
        if points is None or len(points) < 10:
            return None, None, None

        best_inliers = []
        best_normal = None
        best_d = 0
        n = len(points)

        for _ in range(max_iterations):
            # Random 3 points
            idx = np.random.choice(n, 3, replace=False)
            p1, p2, p3 = points[idx[0]], points[idx[1]], points[idx[2]]

            # Normal vector
            v1 = p2 - p1
            v2 = p3 - p1
            normal = np.cross(v1, v2)
            norm_len = np.linalg.norm(normal)
            if norm_len < 1e-10:
                continue
            normal = normal / norm_len

            # Must be roughly horizontal (normal pointing up/down)
            if abs(normal[2]) < self.vertical_tolerance:
                continue

            # Distance from all points to this plane
            d = -np.dot(normal, p1)
            distances = np.abs(np.dot(points, normal) + d)
            inlier_mask = distances < self.distance_threshold
            num_inliers = np.sum(inlier_mask)

            if num_inliers > len(best_inliers):
                best_inliers = np.where(inlier_mask)[0]
                best_normal = normal
                best_d = d

        if len(best_inliers) < n * self.min_plane_ratio:
            print("[FloorExtractor] No floor found (too few inliers: %d/%d)" % (len(best_inliers), n))
            return None, None, None

        floor_points = points[best_inliers]
        bounds_min = floor_points.min(axis=0)
        bounds_max = floor_points.max(axis=0)

        # Ensure normal points up
        if best_normal[2] < 0:
            best_normal = -best_normal

        print("[FloorExtractor] Floor found:")
        print("  Points:", len(floor_points), "/", n)
        print("  Normal:", [round(x, 3) for x in best_normal])
        print("  Bounds:", [round(x, 2) for x in bounds_min],
              "->", [round(x, 2) for x in bounds_max])

        return floor_points, best_normal, (bounds_min, bounds_max)

    def project_to_2d(self, floor_points, floor_normal):
        """
        Project 3D floor points to 2D plane.
        
        Returns:
            (points_2d, transform_matrix)
        """
        if floor_points is None or len(floor_points) == 0:
            return None, None

        center = floor_points.mean(axis=0)

        # Build local coordinate system
        up = floor_normal / np.linalg.norm(floor_normal)
        if abs(up[2]) > 0.9:
            right = np.cross(up, np.array([1, 0, 0]))
        else:
            right = np.cross(up, np.array([0, 0, 1]))
        right = right / np.linalg.norm(right)
        forward = np.cross(right, up)
        forward = forward / np.linalg.norm(forward)

        # Transform matrix (3x3)
        transform = np.array([right, forward, up]).T

        # Project
        centered = floor_points - center
        points_2d = centered @ transform

        return points_2d, transform

    def extract_floor_image(self, floor_points_2d, resolution=0.005, padding=0.1):
        """
        Convert 2D floor points to a grayscale image.
        Useful for detecting track lines on the floor.
        
        Args:
            floor_points_2d: Nx3 array (only x,y used)
            resolution: meters per pixel
            padding: extra padding around bounds (meters)
            
        Returns:
            (image, origin, scale)
        """
        if floor_points_2d is None or len(floor_points_2d) == 0:
            return None, None, None

        xy = floor_points_2d[:, :2]
        xmin, ymin = xy.min(axis=0) - padding
        xmax, ymax = xy.max(axis=0) + padding

        w = int((xmax - xmin) / resolution)
        h = int((ymax - ymin) / resolution)
        w = max(1, min(w, 4096))
        h = max(1, min(h, 4096))

        image = np.zeros((h, w), dtype=np.uint8)

        # Bin points into pixels
        px = ((xy[:, 0] - xmin) / resolution).astype(int)
        py = ((xy[:, 1] - ymin) / resolution).astype(int)
        mask = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        px, py = px[mask], py[mask]
        image[py, px] = 200

        origin = np.array([xmin, ymin])
        scale = resolution
        return image, origin, scale
