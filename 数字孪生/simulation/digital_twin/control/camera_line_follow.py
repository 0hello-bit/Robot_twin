# -*- coding: utf-8 -*-
"""
camera_line_follow.py - Camera-based Line Following Controller

Simulates what K230 would do:
    1. Capture image from virtual camera
    2. Detect line position using OpenCV
    3. Compute steering error
    4. PID control to follow the line

This is the controller that would run on K230 in the real car.
Here we run it in simulation to test before deploying.
"""

import math
from simulator.camera_simulator import VirtualK230Camera
from simulator.pid import PIDController


class CameraLineFollower:
    """
    Camera-based line following controller.

    Mirrors what K230 + OpenCV would do on the real car:
        camera -> image -> detect line -> PID -> motor

    Usage:
        ctrl = CameraLineFollower()
        motors = ctrl.step(car_x, car_y, car_angle, track_points, dt)
    """

    def __init__(self, camera=None, kp=0.6, ki=0.0, kd=0.15,
                 base_speed=200, camera_config=None):
        """
        Args:
            camera: VirtualK230Camera instance (created if None)
            kp, ki, kd: PID parameters
            base_speed: base PWM speed
            camera_config: dict of camera parameters
        """
        if camera is not None:
            self.camera = camera
        else:
            cfg = camera_config or {}
            self.camera = VirtualK230Camera(
                resolution=cfg.get('resolution', (320, 240)),
                fov_deg=cfg.get('fov_deg', 60),
                mount_height=cfg.get('mount_height', 30),
                tilt_deg=cfg.get('tilt_deg', 25),
                view_distance=cfg.get('view_distance', 200),
            )

        self.pid = PIDController()
        self.pid.set_gains(kp, ki, kd)
        self.base_speed = base_speed

        # State
        self.last_error = 0.0
        self.line_detected = False
        self.confidence = 0.0
        self.error_normalized = 0.0
        self.image = None
        self.detection = None

    def step(self, car_x, car_y, car_angle, track_points, dt):
        """
        Run one control step.

        Args:
            car_x, car_y: car position
            car_angle: car heading (degrees)
            track_points: Nx2 track centerline
            dt: time step

        Returns:
            (left_pwm, right_pwm) in range [0, 999]
        """
        # 1. Render camera view
        self.image = self.camera.render(car_x, car_y, car_angle, track_points)

        # 2. Detect line
        self.detection = self.camera.detect_line(self.image)
        self.line_detected = self.detection['line_detected']
        self.confidence = self.detection['confidence']

        # 3. Get error
        if self.line_detected:
            # line_position_normalized: -1 (left) to +1 (right), 0 = center
            self.error_normalized = self.detection['line_position_normalized']
            self._lost_frames = 0
        else:
            # Line lost: search by turning in last known error direction
            self._lost_frames = getattr(self, '_lost_frames', 0) + 1
            if abs(self.last_error) > 0.05:
                # Turn toward last known line direction (maintain search)
                self.error_normalized = self.last_error
            else:
                # No prior direction: sweep right then left
                sweep = math.sin(self._lost_frames * 0.3) * 0.8
                self.error_normalized = sweep

        self.last_error = self.error_normalized

        # 4. PID control
        # Error is in [-1, 1], we need to scale it for PID
        error_scaled = self.error_normalized * 1024.0  # match IR sensor scale
        pid_output = self.pid.compute(error_scaled, dt)
        pid_output = max(-1.0, min(1.0, pid_output))

        # 5. Convert to motor PWM (same as IR line follower)
        base = self.base_speed / 999.0
        left = base + pid_output * 0.5
        right = base - pid_output * 0.5

        # Clamp
        left = max(0.0, min(1.0, left))
        right = max(0.0, min(1.0, right))

        left_pwm = int(left * 999)
        right_pwm = int(right * 999)

        return left_pwm, right_pwm

    def step_normalized(self, car_x, car_y, car_angle, track_points, dt):
        """Return normalized motor commands (-1 ~ 1)."""
        left_pwm, right_pwm = self.step(
            car_x, car_y, car_angle, track_points, dt)
        left = (left_pwm / 999.0) * 2.0 - 1.0
        right = (right_pwm / 999.0) * 2.0 - 1.0
        return left, right

    def set_pid_gains(self, kp=None, ki=None, kd=None):
        self.pid.set_gains(kp, ki, kd)

    def reset(self):
        self.pid.reset()
        self.last_error = 0.0
        self.line_detected = False

    def get_debug_info(self):
        return {
            'line_detected': self.line_detected,
            'confidence': self.confidence,
            'error_normalized': self.error_normalized,
            'pid_output': self.pid.output_smooth if hasattr(self.pid, 'output_smooth') else 0,
        }

