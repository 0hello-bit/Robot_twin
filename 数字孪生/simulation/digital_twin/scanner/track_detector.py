# -*- coding: utf-8 -*-
"""
track_detector.py - Detect black line track on floor image

Takes a floor projection image and detects the line track
(the black tape / painted line the car follows).

Usage:
    from scanner.track_detector import TrackDetector
    det = TrackDetector()
    track_points = det.detect(floor_image)
"""

import numpy as np
import cv2
import math


class TrackDetector:
    """
    Detect a line track from a floor projection image.
    
    Pipeline:
        1. Binarize (dark regions = potential track)
        2. Morphological cleanup
        3. Skeletonize to single-pixel line
        4. Trace ordered path along skeleton
        5. Smooth and resample
    """

    def __init__(self, threshold=80, min_area=100, smooth_sigma=3.0,
                 target_points=300):
        self.threshold = threshold
        self.min_area = min_area
        self.smooth_sigma = smooth_sigma
        self.target_points = target_points

    def detect(self, floor_image, origin=None, scale=0.005):
        """
        Detect track from floor image.
        
        Args:
            floor_image: grayscale HxW image (dark = track)
            origin: 2D origin offset (meters)
            scale: meters per pixel
            
        Returns:
            Nx2 array of track points in world coordinates (meters)
        """
        if floor_image is None:
            return None

        # 1. Binarize (dark = track line)
        _, binary = cv2.threshold(floor_image, self.threshold, 255,
                                  cv2.THRESH_BINARY_INV)

        # 2. Morphological cleanup
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)

        # 3. Check if track found
        if np.sum(cleaned > 0) < self.min_area:
            print("[TrackDetector] No track found (too few dark pixels)")
            return None

        # 4. Skeletonize (thin to 1-pixel line)
        skeleton = self._skeletonize(cleaned)

        # 5. Trace ordered path
        path = self._trace_path(skeleton)
        if path is None or len(path) < 10:
            print("[TrackDetector] Failed to trace path")
            return None

        # 6. Convert to world coordinates
        if origin is not None and scale is not None:
            world_points = path.astype(np.float64) * scale + origin
        else:
            world_points = path.astype(np.float64)

        # 7. Smooth
        world_points = self._smooth_path(world_points)

        # 8. Resample to target number of points
        world_points = self._resample(world_points, self.target_points)

        print("[TrackDetector] Track detected:")
        print("  Points:", len(world_points))
        if len(world_points) > 1:
            total_len = np.sum(np.linalg.norm(np.diff(world_points, axis=0), axis=1))
            print("  Length: %.2f meters" % total_len)

        return world_points

    def _skeletonize(self, binary):
        """Simple morphological skeletonization."""
        skeleton = np.zeros_like(binary)
        element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        img = binary.copy()
        while True:
            eroded = cv2.erode(img, element)
            dilated = cv2.dilate(eroded, element)
            diff = cv2.subtract(img, dilated)
            skeleton = cv2.bitwise_or(skeleton, diff)
            img = eroded.copy()
            if cv2.countNonZero(img) == 0:
                break
        return skeleton

    def _trace_path(self, skeleton):
        """Trace an ordered path along skeleton pixels."""
        points = np.argwhere(skeleton > 0)  # (row, col)
        if len(points) < 10:
            return None

        # Start from one endpoint or the leftmost point
        sorted_by_col = points[points[:, 1].argsort()]
        start = sorted_by_col[0]

        visited = set()
        path = [tuple(start)]
        visited.add(tuple(start))

        current = start
        max_iter = len(points) * 2
        for _ in range(max_iter):
            best = None
            best_dist = float('inf')
            r, c = current
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if (nr, nc) in visited:
                        continue
                    if skeleton[nr, nc] > 0 if (0 <= nr < skeleton.shape[0] and 0 <= nc < skeleton.shape[1]) else False:
                        dist = dr * dr + dc * dc
                        if dist < best_dist:
                            best_dist = dist
                            best = (nr, nc)
            if best is None:
                break
            path.append(best)
            visited.add(best)
            current = best

        if len(path) < 10:
            return None
        return np.array(path)  # (row, col)

    def _smooth_path(self, points, sigma=None):
        """Gaussian smooth the path."""
        if sigma is None:
            sigma = self.smooth_sigma
        if len(points) < 5:
            return points
        from scipy.ndimage import gaussian_filter1d
        try:
            smoothed = gaussian_filter1d(points, sigma=sigma, axis=0, mode='wrap')
            return smoothed
        except ImportError:
            # Fallback: simple moving average
            kernel = np.ones(5) / 5
            sx = np.convolve(points[:, 0], kernel, mode='same')
            sy = np.convolve(points[:, 1], kernel, mode='same')
            return np.column_stack([sx, sy])

    def _resample(self, points, n):
        """Resample path to exactly n evenly-spaced points."""
        if len(points) < 2:
            return points

        # Compute cumulative arc length
        diffs = np.diff(points, axis=0)
        seg_lengths = np.linalg.norm(diffs, axis=1)
        cum_length = np.concatenate([[0], np.cumsum(seg_lengths)])
        total_length = cum_length[-1]

        if total_length < 1e-10:
            return points

        # Evenly spaced target lengths
        target_lengths = np.linspace(0, total_length, n)

        resampled = np.zeros((n, points.shape[1]))
        for i, tl in enumerate(target_lengths):
            idx = np.searchsorted(cum_length, tl, side='right') - 1
            idx = max(0, min(idx, len(points) - 2))
            seg_len = seg_lengths[idx] if idx < len(seg_lengths) else 1e-10
            if seg_len < 1e-10:
                t = 0
            else:
                t = (tl - cum_length[idx]) / seg_len
            t = max(0, min(1, t))
            resampled[i] = points[idx] * (1 - t) + points[idx + 1] * t

        return resampled
