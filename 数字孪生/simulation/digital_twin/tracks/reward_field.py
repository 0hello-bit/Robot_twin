# -*- coding: utf-8 -*-
"""
reward_field.py - Gaussian Soft Penalty Field System

Replaces hard penalties (-100) with differentiable Gaussian fields.
RL can learn gradients instead of hitting dead zones.

Core idea:
    penalty(x, y) = amplitude * exp(-dist^2 / (2 * sigma^2))

This is continuous, differentiable, and provides useful gradients.
"""

import numpy as np
import math


class GaussianPenaltyField:
    """
    A single Gaussian penalty zone centered at (cx, cy).

    penalty(x, y) = amplitude * exp(-d^2 / (2*sigma^2))
    where d = distance from (x,y) to center.
    """

    def __init__(self, cx, cy, sigma=30.0, amplitude=-10.0):
        self.cx = cx
        self.cy = cy
        self.sigma = sigma
        self.amplitude = amplitude
        self._sigma2 = 2.0 * sigma * sigma

    def evaluate(self, x, y):
        """Return penalty value at (x, y). Always <= 0."""
        dx = x - self.cx
        dy = y - self.cy
        d2 = dx * dx + dy * dy
        return self.amplitude * math.exp(-d2 / self._sigma2)

    def gradient(self, x, y):
        """Return (dPenalty/dx, dPenalty/dy) for gradient-based learning."""
        dx = x - self.cx
        dy = y - self.cy
        d2 = dx * dx + dy * dy
        exp_val = math.exp(-d2 / self._sigma2)
        g_x = self.amplitude * exp_val * (-2.0 * dx / self._sigma2)
        g_y = self.amplitude * exp_val * (-2.0 * dy / self._sigma2)
        return g_x, g_y


class PenaltyZone:
    """
    A penalty zone defined by a center point + radius.
    Uses Gaussian falloff from the edge of the zone.
    """

    def __init__(self, cx, cy, radius=20.0, sigma=15.0, amplitude=-5.0):
        self.cx = cx
        self.cy = cy
        self.radius = radius
        self.sigma = sigma
        self.amplitude = amplitude
        self._sigma2 = 2.0 * sigma * sigma

    def evaluate(self, x, y):
        """Penalty is 0 outside zone, Gaussian falloff inside."""
        dx = x - self.cx
        dy = y - self.cy
        dist = math.sqrt(dx * dx + dy * dy)
        if dist <= self.radius:
            return self.amplitude
        overflow = dist - self.radius
        return self.amplitude * math.exp(-(overflow * overflow) / self._sigma2)


class CorridorPenaltyField:
    """
    Penalty field along a polyline corridor.
    Penalty increases as the car moves away from the corridor center
    or enters forbidden regions.
    """

    def __init__(self, penalty_points, sigma=20.0, amplitude=-3.0):
        """
        Args:
            penalty_points: Nx2 array of forbidden zone centers
            sigma: Gaussian width
            amplitude: max penalty strength
        """
        self.points = np.array(penalty_points) if len(penalty_points) > 0 else np.empty((0, 2))
        self.sigma = sigma
        self.amplitude = amplitude
        self._sigma2 = 2.0 * sigma * sigma

    def evaluate(self, x, y):
        """Minimum penalty from all forbidden points."""
        if len(self.points) == 0:
            return 0.0
        dx = self.points[:, 0] - x
        dy = self.points[:, 1] - y
        d2 = dx * dx + dy * dy
        min_d2 = np.min(d2)
        return self.amplitude * math.exp(-min_d2 / self._sigma2)


class RewardFieldSystem:
    """
    Manages all penalty fields for a track.
    Called every step to compute soft penalty at car position.
    """

    def __init__(self):
        self._point_fields = []    # GaussianPenaltyField instances
        self._zone_fields = []     # PenaltyZone instances
        self._corridor_fields = [] # CorridorPenaltyField instances

    def add_point_penalty(self, cx, cy, sigma=30.0, amplitude=-10.0):
        """Add a Gaussian point penalty."""
        self._point_fields.append(GaussianPenaltyField(cx, cy, sigma, amplitude))

    def add_zone_penalty(self, cx, cy, radius=20.0, sigma=15.0, amplitude=-5.0):
        """Add a zone-based penalty."""
        self._zone_fields.append(PenaltyZone(cx, cy, radius, sigma, amplitude))

    def add_corridor_penalty(self, points, sigma=20.0, amplitude=-3.0):
        """Add a corridor penalty from point set."""
        self._corridor_fields.append(CorridorPenaltyField(points, sigma, amplitude))

    def clear(self):
        """Remove all penalty fields."""
        self._point_fields.clear()
        self._zone_fields.clear()
        self._corridor_fields.clear()

    def evaluate(self, x, y):
        """
        Compute total soft penalty at (x, y).
        Returns sum of all Gaussian penalties (always <= 0).
        """
        total = 0.0
        for f in self._point_fields:
            total += f.evaluate(x, y)
        for f in self._zone_fields:
            total += f.evaluate(x, y)
        for f in self._corridor_fields:
            total += f.evaluate(x, y)
        return total

    def get_field_count(self):
        """Return number of active penalty fields."""
        return (len(self._point_fields) +
                len(self._zone_fields) +
                len(self._corridor_fields))


def build_level_penalty_field(track_points, level, canvas_center=(400, 300)):
    """
    Build penalty fields for a given track level.

    Level 1 (ellipse): minimal penalties
    Level 2 (trefoil): soft penalties at 3 crossing zones
    Level 3 (twin loop): soft penalty at center separation zone
    Level 4 (rounded rect): minimal penalties

    Returns:
        RewardFieldSystem with configured penalties
    """
    field = RewardFieldSystem()
    pts = np.array(track_points)
    cx, cy = canvas_center

    if level == 1:
        # Ellipse: no crossings, minimal penalty
        pass

    elif level == 2:
        # Trefoil: 3 self-crossing zones
        # Find crossing points by detecting where track comes close to itself
        crossings = _find_crossing_zones(pts, threshold=25.0)
        for cross_cx, cross_cy in crossings:
            field.add_zone_penalty(
                cross_cx, cross_cy,
                radius=20.0, sigma=15.0, amplitude=-3.0
            )

    elif level == 3:
        # Twin loop: center separation zone
        # The two loops should not overlap in the center
        field.add_zone_penalty(
            cx, cy,
            radius=35.0, sigma=20.0, amplitude=-5.0
        )

    elif level == 4:
        # Rounded rectangle: no crossings
        pass

    return field


def _find_crossing_zones(points, threshold=25.0):
    """
    Find zones where the track comes close to itself (potential crossings).
    Returns list of (x, y) center points.
    """
    n = len(points)
    crossings = []
    checked = set()

    for i in range(n):
        for j in range(i + 10, n):
            if abs(i - j) < 5 or abs(i - j) > n - 5:
                continue
            dx = points[i][0] - points[j][0]
            dy = points[i][1] - points[j][1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < threshold:
                mid_x = (points[i][0] + points[j][0]) / 2.0
                mid_y = (points[i][1] + points[j][1]) / 2.0
                # Check if this zone is already found
                is_new = True
                for cx, cy in crossings:
                    if abs(mid_x - cx) < threshold and abs(mid_y - cy) < threshold:
                        is_new = False
                        break
                if is_new:
                    crossings.append((mid_x, mid_y))

    return crossings
