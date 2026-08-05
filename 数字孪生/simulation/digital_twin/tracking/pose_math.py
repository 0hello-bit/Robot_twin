#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pure pose and homography helpers, kept separate from camera I/O."""

from __future__ import division

import math

import numpy as np


def wrap_degrees(angle):
    return (float(angle) + 180.0) % 360.0 - 180.0


def angle_delta_degrees(target, current):
    return wrap_degrees(float(target) - float(current))


def smooth_angle_degrees(previous, current, alpha):
    return wrap_degrees(float(previous) + angle_delta_degrees(current, previous) * float(alpha))


def validate_homography(matrix):
    homography = np.asarray(matrix, dtype=np.float64)
    if homography.shape != (3, 3):
        raise ValueError("homography must be a 3x3 matrix")
    if not np.all(np.isfinite(homography)):
        raise ValueError("homography contains non-finite values")
    if abs(np.linalg.det(homography)) < 1e-12:
        raise ValueError("homography is singular")
    return homography


def project_points(points, homography):
    matrix = validate_homography(homography)
    source = np.asarray(points, dtype=np.float64).reshape((-1, 2))
    homogeneous = np.column_stack((source, np.ones(len(source), dtype=np.float64)))
    projected = np.dot(homogeneous, matrix.T)
    denominator = projected[:, 2]
    if np.any(np.abs(denominator) < 1e-12):
        raise ValueError("point projects to infinity")
    return projected[:, :2] / denominator[:, None]


def polygon_area(points):
    polygon = np.asarray(points, dtype=np.float64).reshape((-1, 2))
    x_values = polygon[:, 0]
    y_values = polygon[:, 1]
    return abs(float(np.dot(x_values, np.roll(y_values, 1)) - np.dot(y_values, np.roll(x_values, 1))) * 0.5)


def tag_pose_from_corners(corners_px, homography, front_edge="top", yaw_offset_deg=0.0):
    corners = np.asarray(corners_px, dtype=np.float64).reshape((4, 2))
    world = project_points(corners, homography)
    center = np.mean(world, axis=0)
    edge_indices = {
        "top": (0, 1),
        "right": (1, 2),
        "bottom": (2, 3),
        "left": (3, 0),
    }
    if front_edge not in edge_indices:
        raise ValueError("front_edge must be top, right, bottom, or left")
    first, second = edge_indices[front_edge]
    front = (world[first] + world[second]) * 0.5
    direction_x = front[0] - center[0]
    direction_z = front[1] - center[1]
    if math.hypot(direction_x, direction_z) < 1e-9:
        raise ValueError("tag direction is degenerate")
    yaw_deg = math.degrees(math.atan2(-direction_z, direction_x)) + float(yaw_offset_deg)
    return {
        "x": float(center[0]),
        "z": float(center[1]),
        "yaw_deg": wrap_degrees(yaw_deg),
        "pixel_area": polygon_area(corners),
        "world_corners": world,
    }


def apply_car_center_offset(pose, offset_forward, offset_right):
    yaw = math.radians(float(pose["yaw_deg"]))
    world_x = math.cos(yaw) * float(offset_forward) + math.sin(yaw) * float(offset_right)
    world_z = -math.sin(yaw) * float(offset_forward) + math.cos(yaw) * float(offset_right)
    result = dict(pose)
    result["x"] = float(pose["x"]) - world_x
    result["z"] = float(pose["z"]) - world_z
    return result


class PoseFilter(object):
    def __init__(self, position_alpha=0.35, yaw_alpha=0.3, max_jump=0.35):
        self.position_alpha = float(position_alpha)
        self.yaw_alpha = float(yaw_alpha)
        self.max_jump = float(max_jump)
        self.value = None

    def reset(self):
        self.value = None

    def update(self, pose):
        if self.value is None:
            self.value = dict(pose)
            return dict(self.value)
        previous = self.value
        jump = math.hypot(float(pose["x"]) - previous["x"], float(pose["z"]) - previous["z"])
        if self.max_jump > 0 and jump > self.max_jump:
            return None
        alpha_position = max(0.0, min(1.0, self.position_alpha))
        alpha_yaw = max(0.0, min(1.0, self.yaw_alpha))
        self.value = dict(pose)
        self.value["x"] = float(pose["x"]) * alpha_position + previous["x"] * (1.0 - alpha_position)
        self.value["z"] = float(pose["z"]) * alpha_position + previous["z"] * (1.0 - alpha_position)
        self.value["yaw_deg"] = smooth_angle_degrees(previous["yaw_deg"], pose["yaw_deg"], alpha_yaw)
        return dict(self.value)
