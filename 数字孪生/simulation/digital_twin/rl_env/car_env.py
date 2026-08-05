# -*- coding: utf-8 -*-
"""
car_env.py - Gymnasium Standard RL Environment v3

鍏煎 Stable-Baselines3, 鏀寔:
- Curriculum tracks (Level 1-4)
- Unseen generalization test tracks
- Domain randomization
- Time-varying track drift
- Recovery bonus reward
- MODE_PID / MODE_RL / MODE_HYBRID 控制模式
"""

import math
import numpy as np
import gymnasium as gym
from gymnasium import spaces

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.map import TrackMap
from simulator.analog_sensor import AnalogSensorArray
from control_sandbox.plant_model import PlantModel

from rl_env.observation import ObservationBuilder
from rl_env.action_space import ActionEncoder
from rl_env.reward import RewardCalculator, RewardConfig
from tracks.reward_field import build_level_penalty_field, RewardFieldSystem
from tracks.curriculum_track_generator import (
    CurriculumTrackGenerator, DomainRandomizer, TimeVaryingTrack)

from control.interface_adapter import ControlAdapter


class CarEnv(gym.Env):
    """
    STM32 RL Environment v3 (Gymnasium Standard).

    observation: Box(shape=(10,), float32)
    action:      Discrete(5) or Box(shape=(2,), float32)

    control_mode: 'rl' (default) / 'pid' / 'hybrid'
    """

    metadata = {'render_modes': ['human', 'rgb_array']}

    def __init__(self, track_type='oval', action_mode='discrete',
                 max_steps=1500, dt=0.03, noise=False,
                 speed_factor=1.0, render_mode=None,
                 reward_config=None, seed=None,
                 domain_randomize=False, time_drift=False,
                 unseen_mode=False,
                 control_mode='rl', pid_kp=0.6, pid_ki=0.0, pid_kd=0.15,
                 hybrid_blend=0.5):
        super().__init__()
        self.track_type = track_type
        self.action_mode = action_mode
        self.max_steps = max_steps
        self.dt = dt
        self.noise = noise
        self.speed_factor = speed_factor
        self.render_mode = render_mode
        self.domain_randomize = domain_randomize
        self.time_drift = time_drift
        self.unseen_mode = unseen_mode
        self.control_mode = control_mode

        # Core components
        self.plant = PlantModel()
        self.analog = AnalogSensorArray(sigma=8.0, resolution=1023)
        self.obs_builder = ObservationBuilder()
        self.action_encoder = ActionEncoder(mode=action_mode, base_speed=200)
        self.reward_calc = RewardCalculator(reward_config)

        # Control adapter (PID / RL / Hybrid)
        self._adapter = ControlAdapter(
            mode=control_mode,
            base_speed=200,
            blend=hybrid_blend,
        )
        if control_mode in ('pid', 'hybrid'):
            from control.base_controller import LineFollowController
            pid_ctrl = LineFollowController(
                kp=pid_kp, ki=pid_ki, kd=pid_kd, base_speed=200)
            self._adapter.pid_controller = pid_ctrl
            self._adapter.blend = hybrid_blend

        # Track generator
        self.track_gen = CurriculumTrackGenerator(seed=seed)
        self.domain_rand = DomainRandomizer(seed)

        # Track
        self.track = None
        self._raw_track_points = None
        self._time_varying = None
        self._penalty_field = None
        self._build_track(track_type)

        # Gymnasium spaces
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(ObservationBuilder.DIMENSION,), dtype=np.float32)
        if action_mode == 'discrete':
            self.action_space = spaces.Discrete(5)
        else:
            self.action_space = spaces.Box(
                low=np.array([-1.0, 0.0], dtype=np.float32),
                high=np.array([1.0, 1.0], dtype=np.float32),
                dtype=np.float32)

        # State
        self._step_count = 0
        self._episode_reward = 0.0
        self._prev_line_error = 0.0
        self._lost_count = 0
        self._rng = np.random.RandomState(seed)
        self._track_points_cache = None
        self._track_idx = 0
        self._track_level = 1
        self._track_length = 0

    def _build_track(self, track_type):
        self.track = TrackMap()

        if track_type.startswith('curriculum_'):
            level = int(track_type.split('_')[1])
            pts = self.track_gen.get_track(level)
            self._raw_track_points = pts
            self.track.add_polyline(pts.tolist())
            self._start_pos = self.track_gen.get_start_pos()
            self._track_level = level
            self.reward_calc.set_level(level)

        elif track_type == 'unseen':
            unseen_seed = self._rng.randint(10000, 99999)
            pts = self.track_gen.get_unseen_track(unseen_seed)
            self._raw_track_points = pts
            self.track.add_polyline(pts.tolist())
            self._start_pos = self.track_gen.get_start_pos()
            self._track_level = 0
            self.reward_calc.set_level(1)

        elif track_type == 'oval':
            pts = self.track.generate_oval(400, 300, 200, 150, num_points=200)
            self.track.add_polyline(pts)
            self._start_pos = (400, 450, 0)
            self._track_level = 1

        elif track_type == 'figure8':
            pts1 = self.track.generate_oval(300, 250, 120, 80, num_points=100)
            self.track.add_polyline(pts1)
            pts2 = self.track.generate_oval(500, 250, 120, 80, num_points=100)
            self.track.add_polyline(pts2)
            self.track.add_segment(420, 250, 380, 250)
            self.track.add_segment(380, 250, 420, 250)
            self._start_pos = (300, 330, 0)
            self._track_level = 3

        elif track_type == 'random':
            pts = self._generate_random_track()
            self.track.add_polyline(pts)
            self._start_pos = (pts[0][0], pts[0][1], 0)
            self._track_level = 1

        else:
            pts = self.track.generate_oval(400, 300, 200, 150, num_points=200)
            self.track.add_polyline(pts)
            self._start_pos = (400, 450, 0)
            self._track_level = 1

        if self._raw_track_points is not None:
            self._penalty_field = build_level_penalty_field(
                self._raw_track_points, self._track_level)
        else:
            self._penalty_field = RewardFieldSystem()

        if self.time_drift and self._raw_track_points is not None:
            self._time_varying = TimeVaryingTrack(
                self._raw_track_points, drift_sigma=0.5, drift_freq=0.01)

    def _generate_random_track(self):
        n_points = 80
        cx, cy = 400, 300
        rx = self._rng.uniform(120, 220)
        ry = self._rng.uniform(80, 150)
        ox = self._rng.uniform(-50, 50)
        oy = self._rng.uniform(-30, 30)
        pts = []
        for i in range(n_points):
            t = 2 * math.pi * i / n_points
            x = cx + ox + rx * math.cos(t) + self._rng.uniform(-5, 5)
            y = cy + oy + ry * math.sin(t) + self._rng.uniform(-5, 5)
            pts.append([x, y])
        return pts

    def _apply_domain_randomization(self):
        if not self.domain_randomize:
            return
        params = self.domain_rand.sample()
        self.plant.velocity_damping = params.get(
            'friction_coeff', self.plant.velocity_damping)
        self.plant.sensor_noise_prob = params.get(
            'sensor_noise_prob', self.plant.sensor_noise_prob)
        self.plant.motor_noise_std = params.get(
            'motor_noise_std', self.plant.motor_noise_std)
        width_scale = params.get('track_width_scale', 1.0)
        if width_scale != 1.0 and hasattr(self.track, 'width'):
            self.track.width *= width_scale

    def _apply_time_drift(self):
        if self._time_varying is None:
            return
        drifted = self._time_varying.get_points(self._step_count * self.dt)
        self.track.clear()
        self.track.add_polyline(drifted.tolist())

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        if seed is not None:
            self._rng = np.random.RandomState(seed)
            self.track_gen = CurriculumTrackGenerator(seed=seed)
            self.domain_rand = DomainRandomizer(seed)

        self.track = None
        self._raw_track_points = None
        self._time_varying = None
        self._build_track(self.track_type)

        x, y, angle = self._start_pos
        self.plant.reset(x=x, y=y, angle=angle)
        self.plant.set_track(self.track)
        self.plant.noise_enabled = self.noise

        self.analog.noise_enabled = self.noise
        self.analog.sigma = 8.0
        self.obs_builder.reset()
        self.reward_calc.reset()
        self._adapter.reset()

        self._step_count = 0
        self._episode_reward = 0.0
        self._prev_line_error = 0.0
        self._lost_count = 0
        self._track_points_cache = None
        self._track_idx = 0
        self._track_length = 0

        self._apply_domain_randomization()

        obs = self.obs_builder.build(self.plant, self.analog, self.track, self.dt)
        info = {
            'position': (self.plant.x, self.plant.y),
            'track_type': self.track_type,
            'track_level': self._track_level,
        }
        return obs, info

    def step(self, action):
        # ─── Determine left/right PWM ───
        if self.control_mode == 'rl':
            left_pwm, right_pwm = self.action_encoder.encode(action)
        elif self.control_mode in ('pid', 'hybrid'):
            readings = self.analog.read(
                self.plant.x, self.plant.y, self.plant.angle, self.track)
            sensor_input = [1 if r > 512 else 0 for r in readings]
            obs = self.obs_builder.build(
                self.plant, self.analog, self.track, self.dt)
            ctrl_out = self._adapter.step(sensor_input, self.dt, obs)
            lp = (ctrl_out.left_speed + 1.0) / 2.0 * 999.0
            rp = (ctrl_out.right_speed + 1.0) / 2.0 * 999.0
            left_pwm = max(0, min(999, lp))
            right_pwm = max(0, min(999, rp))
        else:
            left_pwm, right_pwm = self.action_encoder.encode(action)

        left_pwm *= self.speed_factor
        right_pwm *= self.speed_factor
        left_pwm = max(0, min(999, left_pwm))
        right_pwm = max(0, min(999, right_pwm))

        self.plant.step(left_pwm, right_pwm, self.dt)
        self._step_count += 1

        if self._time_varying is not None and self._step_count % 30 == 0:
            self._apply_time_drift()

        obs = self.obs_builder.build(self.plant, self.analog, self.track, self.dt)

        readings = self.analog.read(
            self.plant.x, self.plant.y, self.plant.angle, self.track)
        line_error = self.analog.read_position(readings) / 3.0
        line_error = max(-1.0, min(1.0, line_error))
        speed = max(0.0, min(1.0, abs(self.plant.vx) / 300.0))
        is_lost = all(r > 800 for r in readings)

        if is_lost:
            self._lost_count += 1

        steering = (left_pwm - right_pwm) / max(left_pwm + right_pwm, 1.0)

        if self._track_points_cache is None:
            tmap = self.track
            pts_list = []
            if hasattr(tmap, 'polylines') and tmap.polylines:
                for poly in tmap.polylines:
                    pts_list.extend(poly)
            if pts_list:
                self._track_points_cache = np.array(pts_list)
                self._track_length = len(self._track_points_cache)
            else:
                self._track_points_cache = np.array([[0, 0]])
                self._track_length = 1

        if self._track_points_cache is not None and len(self._track_points_cache) > 1:
            car_pos = np.array([self.plant.x, self.plant.y])
            dists = np.linalg.norm(self._track_points_cache - car_pos, axis=1)
            self._track_idx = int(np.argmin(dists))
            track_total = len(self._track_points_cache)
        else:
            track_total = 1

        reward, breakdown = self.reward_calc.compute(
            line_error=line_error,
            line_error_rate=(line_error - self._prev_line_error) / self.dt,
            speed=speed,
            angular_velocity=self.plant.va / 180.0,
            is_lost=is_lost,
            steering=steering,
            dt=self.dt,
            track_idx=self._track_idx,
            track_total=track_total,
            left_pwm=left_pwm,
            right_pwm=right_pwm,
        )
        self._prev_line_error = line_error

        # Apply soft Gaussian penalty from reward field
        soft_penalty = self._penalty_field.evaluate(self.plant.x, self.plant.y)
        reward += soft_penalty
        breakdown['penalty_field'] = round(soft_penalty, 4)
        breakdown['total'] = round(reward, 4)

        self._episode_reward += reward

        terminated = is_lost and self._lost_count > 10
        truncated = self._step_count >= self.max_steps

        info = {
            'position': (self.plant.x, self.plant.y),
            'angle': self.plant.angle,
            'speed': speed,
            'line_error': line_error,
            'is_lost': is_lost,
            'lost_count': self._lost_count,
            'episode_reward': self._episode_reward,
            'reward_breakdown': breakdown,
            'step': self._step_count,
            'track_level': self._track_level,
            'track_progress': self._track_idx / max(track_total, 1),
            'control_mode': self.control_mode,
        }
        return obs, reward, terminated, truncated, info

    def render(self):
        if self.render_mode == 'rgb_array':
            readings = self.analog.read(
                self.plant.x, self.plant.y, self.plant.angle, self.track)
            img = np.zeros((64, 64, 3), dtype=np.uint8)
            for i, r in enumerate(readings):
                gray = int(r / 1023 * 255)
                x0 = i * 16
                img[20:44, x0:x0+16] = [gray, gray, gray]
            return img
        return None

    def close(self):
        pass

    def get_track(self):
        return self.track

    def get_plant(self):
        return self.plant

    def get_adapter(self):
        return self._adapter

    def set_rl_policy(self, policy):
        self._adapter.set_rl_policy(policy)

    def set_control_mode(self, mode, blend=None):
        self.control_mode = mode
        self._adapter.set_mode(mode)
        if blend is not None:
            self._adapter.set_blend(blend)

    def set_pid_params(self, kp=None, ki=None, kd=None):
        if self._adapter.pid_controller:
            self._adapter.pid_controller.set_pid_gains(kp, ki, kd)

