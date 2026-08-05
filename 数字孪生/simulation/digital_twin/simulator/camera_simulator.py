# -*- coding: utf-8 -*-
"""
camera_simulator.py - Virtual K230 Camera

Simulates what a K230 AI camera would see when mounted on the car.
Uses perspective projection to render a 3D-like view from 2D track data.

Camera specs (K230 typical):
    Resolution: 320x240 (or 640x480)
    FOV: ~60 degrees horizontal
    Mounting: front of car, pointing forward, slight downward tilt

How it works:
    1. Car position + angle defines camera pose
    2. Track points ahead of car are projected into camera frame
    3. Perspective transform creates the "camera image"
    4. OpenCV processes the image for line detection

No new dependencies: uses only numpy + opencv.
"""

import numpy as np
import cv2
import math


class VirtualK230Camera:
    """
    Virtual camera simulating K230 on the car.

    Renders a perspective view of the track from the car's viewpoint.
    Output is a grayscale image like what K230 would capture.
    """

    def __init__(self, resolution=(320, 240), fov_deg=60,
                 mount_height=30, tilt_deg=25,
                 view_distance=200):
        """
        Args:
            resolution: (width, height) output image size
            fov_deg: horizontal field of view in degrees
            mount_height: camera height above ground (pixels in 2D world)
            tilt_deg: downward tilt angle in degrees
            view_distance: how far ahead to render (pixels)
        """
        self.width, self.height = resolution
        self.fov = math.radians(fov_deg)
        self.mount_height = mount_height
        self.tilt = math.radians(tilt_deg)
        self.view_distance = view_distance

        # Pre-compute projection matrix
        self._init_projection()

    def _init_projection(self):
        """Initialize the perspective projection parameters."""
        # Camera intrinsic-like parameters (simplified)
        self.focal_length = (self.width / 2) / math.tan(self.fov / 2)

        # Ground plane to camera projection
        # Simulates a camera looking forward and slightly down
        self.half_fov_x = self.fov / 2
        self.half_fov_y = math.atan((self.height / 2) / self.focal_length)

    def render(self, car_x, car_y, car_angle, track_points):
        """
        Render what the camera sees.

        Args:
            car_x, car_y: car position in 2D world
            car_angle: car heading in degrees (0 = right, 90 = down)
            track_points: Nx2 array of track centerline points

        Returns:
            image: grayscale image (height, width) uint8
                   White background, black track line
        """
        # Create blank white image
        image = np.ones((self.height, self.width), dtype=np.uint8) * 240

        # Transform track points to camera-relative coordinates
        cam_points = self._world_to_camera(
            car_x, car_y, car_angle, track_points)

        # Project to image space
        img_points = self._project_to_image(cam_points)

        # Draw track line on image
        if len(img_points) > 1:
            # Sort by depth (far to near) for proper rendering
            valid = img_points[img_points[:, 2] > 0]
            if len(valid) > 1:
                # Sort by z (depth)
                sorted_idx = np.argsort(-valid[:, 2])
                sorted_pts = valid[sorted_idx]

                # Draw track as thick line
                pts_2d = sorted_pts[:, :2].astype(np.int32)
                for i in range(len(pts_2d) - 1):
                    p1 = tuple(pts_2d[i])
                    p2 = tuple(pts_2d[i + 1])
                    # Thicker when closer
                    depth = sorted_pts[i, 2]
                    thickness = max(1, int(8 * self.view_distance / max(depth, 1)))
                    thickness = min(thickness, 12)
                    cv2.line(image, p1, p2, (30, 30, 30), thickness)

                # Add anti-aliasing blur
                image = cv2.GaussianBlur(image, (3, 3), 0.5)

        return image

    def _world_to_camera(self, car_x, car_y, car_angle, track_points):
        """
        Transform world coordinates to camera-relative coordinates.

        Camera frame:
            X = right
            Y = down
            Z = forward (into the scene)
        """
        theta = math.radians(car_angle)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        dx = track_points[:, 0] - car_x
        dy = track_points[:, 1] - car_y

        # Forward = car heading direction (Z in camera frame)
        forward = dx * cos_t + dy * sin_t
        # Right = perpendicular to heading (X in camera frame)
        right = -dx * sin_t + dy * cos_t

        # Only keep points ahead of the car
        mask = (forward > 5) & (forward < self.view_distance)

        points_3d = np.zeros((len(track_points), 3))
        points_3d[:, 0] = right          # X = right
        points_3d[:, 1] = -self.mount_height  # Y = below camera (ground)
        points_3d[:, 2] = forward        # Z = forward

        points_3d[~mask] = [0, 0, -1]
        return points_3d

    def _project_to_image(self, points_3d):
        """
        Project 3D camera-space points to 2D image coordinates.

        Uses pinhole camera model (simplified).
        """
        img_points = np.zeros((len(points_3d), 3))  # x, y, z(depth)

        for i in range(len(points_3d)):
            x, y, z = points_3d[i]

            if z <= 0:
                img_points[i] = [self.width // 2, self.height, -1]
                continue

            # Perspective projection
            img_x = (x * self.focal_length / z) + self.width / 2
            img_y = (y * self.focal_length / z) + self.height / 2

            # Check if within image bounds
            if 0 <= img_x < self.width and 0 <= img_y < self.height:
                img_points[i] = [img_x, img_y, z]
            else:
                img_points[i] = [img_x, img_y, -1]  # mark out of bounds

        return img_points

    def detect_line(self, image):
        """
        Detect the track line in the camera image.
        Simulates K230's line detection algorithm.

        Args:
            image: grayscale camera image

        Returns:
            dict with detection results:
                - line_detected: bool
                - line_position: x position of line center (0~width)
                - line_angle: angle of line in image (degrees)
                - confidence: detection confidence (0~1)
                - mask: binary mask of detected line
        """
        # Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(image, (5, 5), 0)

        # Adaptive threshold to find dark line on light background
        _, binary = cv2.threshold(blurred, 0, 255,
                                   cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Morphological cleanup
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)

        # Find contours
        contours, _ = cv2.findContours(
            cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return {
                'line_detected': False,
                'line_position': self.width / 2,
                'line_angle': 0.0,
                'confidence': 0.0,
                'mask': cleaned,
            }

        # Find the largest contour (likely the track line)
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)

        if area < 50:  # too small, probably noise
            return {
                'line_detected': False,
                'line_position': self.width / 2,
                'line_angle': 0.0,
                'confidence': 0.0,
                'mask': cleaned,
            }

        # Compute line properties
        M = cv2.moments(largest)
        if M['m00'] > 0:
            cx = M['m10'] / M['m00']  # centroid x
            cy = M['m01'] / M['m00']  # centroid y
        else:
            cx = self.width / 2
            cy = self.height / 2

        # Fit line to get angle
        vx, vy, x0, y0 = cv2.fitLine(
            largest, cv2.DIST_L2, 0, 0.01, 0.01).flatten()
        angle = math.degrees(math.atan2(vx, vy))

        # Confidence based on area and position
        max_area = self.width * self.height * 0.3  # 30% of image
        confidence = min(1.0, area / max_area)

        # Normalize line position to [-1, 1] (center = 0)
        line_pos_normalized = (cx - self.width / 2) / (self.width / 2)

        return {
            'line_detected': True,
            'line_position': cx,
            'line_position_normalized': line_pos_normalized,
            'line_angle': angle,
            'confidence': confidence,
            'mask': cleaned,
        }

    def render_with_overlay(self, car_x, car_y, car_angle, track_points):
        """Render camera view with detection overlay (for visualization)."""
        image = self.render(car_x, car_y, car_angle, track_points)
        detection = self.detect_line(image)

        # Create color overlay
        overlay = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        if detection['line_detected']:
            # Draw detected line center
            cx = int(detection['line_position'])
            cv2.circle(overlay, (cx, self.height // 2), 5, (0, 0, 255), -1)

            # Draw crosshair at center
            cv2.line(overlay, (self.width // 2 - 10, self.height // 2),
                     (self.width // 2 + 10, self.height // 2), (255, 0, 0), 1)
            cv2.line(overlay, (self.width // 2, self.height // 2 - 10),
                     (self.width // 2, self.height // 2 + 10), (255, 0, 0), 1)

            # Draw detection info
            cv2.putText(overlay, "POS: %.2f" % detection['line_position_normalized'],
                        (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            cv2.putText(overlay, "CONF: %.2f" % detection['confidence'],
                        (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            cv2.putText(overlay, "ANGLE: %.1f" % detection['line_angle'],
                        (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        else:
            cv2.putText(overlay, "NO LINE DETECTED",
                        (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

        return overlay, detection


# ================================================================
#  Quick test
# ================================================================

if __name__ == '__main__':
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from simulator.map import TrackMap

    print("=== Virtual K230 Camera Test ===")

    # Create a simple oval track
    track = TrackMap()
    pts = TrackMap.generate_oval(400, 300, 200, 120, 100)
    track.add_polyline(pts, close=True)
    track_points = np.array(pts)

    # Create camera
    cam = VirtualK230Camera(resolution=(320, 240), fov_deg=60)

    # Simulate car at different positions
    test_cases = [
        (400, 420, 0, "straight"),
        (600, 300, 90, "right_curve"),
        (400, 180, 180, "back_straight"),
        (200, 300, 270, "left_curve"),
    ]

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets",
    )
    os.makedirs(output_dir, exist_ok=True)

    for x, y, angle, name in test_cases:
        image = cam.render(x, y, angle, track_points)
        overlay, detection = cam.render_with_overlay(
            x, y, angle, track_points)

        # Save images
        cv2.imwrite(os.path.join(output_dir, 'k230_%s_raw.png' % name), image)
        cv2.imwrite(os.path.join(output_dir, 'k230_%s_overlay.png' % name), overlay)

        print("  %s: detected=%s pos=%.2f conf=%.2f" % (
            name, detection['line_detected'],
            detection.get('line_position_normalized', 0),
            detection['confidence']))

    print("Images saved to assets/")
    print("Test complete!")

