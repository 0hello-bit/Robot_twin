# -*- coding: utf-8 -*-
"""
real_car_env.py - Real STM32 Car Gymnasium Wrapper

Based on donkeycar's DonkeyRealEnv pattern.
Wraps the real STM32 mecanum car as a Gymnasium environment,
enabling the same RL code to work on both simulator and real car.

Key capabilities:
    1. Connect to real car via HC-06 Bluetooth
    2. Receive telemetry (sensors, PWM, error, PID output)
    3. Send PID parameter adjustments remotely
    4. Log data for Real-to-Sim calibration
    5. Provide Gymnasium-compatible interface

Workflow:
    # Same RL code works on both sim and real
    env = CarEnv(track_type='curriculum_1')   # simulator
    # or
    env = RealCarEnv(port='COM3')              # real car

    obs = env.reset()
    while not done:
        action = policy.predict(obs)
        obs, reward, done, info = env.step(action)

NOTE: RealCarEnv is primarily a MONITORING + CALIBRATION environment.
      For direct motor control, the STM32 firmware needs a "slave mode"
      where it accepts motor PWM commands from Python via Bluetooth.
      Currently, the real car runs its own PID controller.
      RealCarEnv monitors its behavior and adjusts parameters remotely.
"""

import time
import numpy as np
import gymnasium as gym
from gymnasium import spaces

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from real_world.serial_bridge import SerialBridge
except ImportError:
    SerialBridge = None  # 蓝牙/串口已弃用；RealCarEnv 待迁移到 wifi_bridge.WifiBridge
from real_world.telemetry_protocol import (
    TelemetryPacket, ParamPacket, ControlPacket,
    FRAME_TELEMETRY, FRAME_STATUS,
)


class RealCarEnv(gym.Env):
    """
    Gymnasium environment for real STM32 mecanum car.

    Observation space (matches CarEnv simulator):
        [s0, s1, s2, s3, error_norm, pid_norm, left_norm, right_norm, tick_norm, lost_flag]

    Action space:
        Discrete(5) - same as simulator (LEFT/SLIGHT_LEFT/STRAIGHT/SLIGHT_RIGHT/RIGHT)

    NOTE: In the current firmware, the real car runs its own PID.
          This env monitors behavior and can adjust PID parameters remotely.
          Direct motor control requires firmware "slave mode" (future work).
    """

    metadata = {'render_modes': ['human', 'rgb_array']}

    def __init__(self, port=None, baudrate=115200, timeout=2.0,
                 max_steps=3000, render_mode=None,
                 auto_detect=True):
        super().__init__()

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.max_steps = max_steps
        self.render_mode = render_mode

        # Serial bridge
        self.bridge = SerialBridge(baudrate=baudrate)
        self._connected = False

        # Auto-detect port if not specified
        if port is None and auto_detect:
            detected, is_bt = self.bridge.auto_detect_port()
            if detected:
                self.port = detected
                print("[RealCarEnv] Auto-detected port: %s (BT=%s)" % (detected, is_bt))

        # Observation space (10D, matches CarEnv)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(10,), dtype=np.float32)

        # Action space (5 discrete, matches CarEnv)
        self.action_space = spaces.Discrete(5)

        # State
        self._step_count = 0
        self._episode_reward = 0.0
        self._latest_telemetry = None
        self._latest_status = None
        self._data_log = []
        self._prev_sensors = [1, 1, 1, 1]
        self._prev_error = 0.0
        self._lost_count = 0
        self._start_time = 0.0

        # Action mapping (same as simulator)
        self._action_map = {
            0: (-1.0, 0.7),    # LEFT
            1: (-0.5, 0.85),   # SLIGHT_LEFT
            2: (0.0, 1.0),     # STRAIGHT
            3: (0.5, 0.85),    # SLIGHT_RIGHT
            4: (1.0, 0.7),     # RIGHT
        }

        # Callbacks
        self.bridge.on_telemetry(self._on_telemetry)
        self.bridge.on_status(self._on_status)

    def connect(self):
        """Connect to the real car via Bluetooth."""
        if self._connected:
            return True

        if self.port is None:
            print("[RealCarEnv] No port specified and auto-detect failed")
            return False

        ok = self.bridge.connect(self.port, self.baudrate)
        if ok:
            self._connected = True
            self.bridge.start()
            print("[RealCarEnv] Connected to %s" % self.port)
            # Wait for first telemetry
            time.sleep(0.5)
            return True
        return False

    def disconnect(self):
        """Disconnect from the real car."""
        self.bridge.stop()
        self._connected = False
        print("[RealCarEnv] Disconnected")

    def reset(self, seed=None, options=None):
        """Reset the environment.

        NOTE: Real car cannot be "reset" like a simulator.
        This resets the internal state and waits for fresh telemetry.
        User must physically place the car on the track.
        """
        super().reset(seed=seed)

        self._step_count = 0
        self._episode_reward = 0.0
        self._data_log.clear()
        self._prev_sensors = [1, 1, 1, 1]
        self._prev_error = 0.0
        self._lost_count = 0
        self._start_time = time.monotonic()

        # Wait for telemetry
        if self._connected:
            self.bridge.flush()
            time.sleep(0.2)

        obs = self._get_observation()
        info = {'status': 'waiting_for_telemetry'}
        return obs, info

    def step(self, action):
        """Execute one step.

        NOTE: In current firmware, the car runs its own PID.
        This step:
            1. Logs the current telemetry
            2. Computes observation from latest sensor data
            3. Computes reward based on tracking quality
            4. Optionally sends PID parameter adjustments

        For direct motor control, firmware needs "slave mode".
        """
        self._step_count += 1

        # Wait for fresh telemetry
        if self._connected:
            self.bridge.flush()
            time.sleep(0.02)  # ~50Hz

        # Get observation
        obs = self._get_observation()

        # Compute reward
        reward, breakdown = self._compute_reward()

        # Log data
        self._data_log.append({
            'step': self._step_count,
            'time': time.monotonic() - self._start_time,
            'action': int(action),
            'sensors': list(self._prev_sensors),
            'error': self._prev_error,
            'reward': reward,
            'telemetry': self._latest_telemetry.to_dict() if self._latest_telemetry else None,
            'status': self._latest_status.to_dict() if self._latest_status else None,
        })

        self._episode_reward += reward

        # Check termination
        is_lost = all(s == 1 for s in self._prev_sensors)
        if is_lost:
            self._lost_count += 1
        else:
            self._lost_count = max(0, self._lost_count - 1)

        terminated = self._lost_count > 50  # lost for too long
        truncated = self._step_count >= self.max_steps

        info = {
            'step': self._step_count,
            'episode_reward': self._episode_reward,
            'sensors': list(self._prev_sensors),
            'error': self._prev_error,
            'is_lost': is_lost,
            'lost_count': self._lost_count,
            'reward_breakdown': breakdown,
            'telemetry': self._latest_telemetry.to_dict() if self._latest_telemetry else None,
            'status': self._latest_status.to_dict() if self._latest_status else None,
        }

        return obs, reward, terminated, truncated, info

    def close(self):
        """Clean up."""
        self.disconnect()

    # ================================================================
    #  Remote PID adjustment
    # ================================================================

    def set_pid_params(self, kp=None, ki=None, kd=None, base_speed=None):
        """Send PID parameters to the real car via Bluetooth.

        Args:
            kp: Proportional gain (None = don't change)
            ki: Integral gain (None = don't change)
            kd: Derivative gain (None = don't change)
            base_speed: Base PWM speed (None = don't change)
        """
        if not self._connected:
            print("[RealCarEnv] Not connected, cannot set PID")
            return False

        # Get current values as defaults
        kp_val = kp if kp is not None else 0.6
        ki_val = ki if ki is not None else 0.0
        kd_val = kd if kd is not None else 0.15
        bs_val = base_speed if base_speed is not None else 180

        pkt = ParamPacket(kp=kp_val, ki=ki_val, kd=kd_val, base_speed=bs_val)
        self.bridge.send_command(pkt.to_csv())
        print("[RealCarEnv] PID sent: Kp=%.3f Ki=%.3f Kd=%.3f Base=%d" % (
            kp_val, ki_val, kd_val, bs_val))
        return True

    def set_mode(self, mode_override):
        """Send mode override to the real car.

        Args:
            mode_override: 0=normal, 1=force line follow, 2=stop
        """
        if not self._connected:
            return False

        pkt = ControlPacket(mode_override=mode_override)
        self.bridge.send_command(pkt.to_csv())
        return True

    def stop_car(self):
        """Emergency stop the real car."""
        return self.set_mode(2)

    # ================================================================
    #  Data export for calibration
    # ================================================================

    def get_data_log(self):
        """Get the logged data from this episode."""
        return list(self._data_log)

    def get_calibration_data(self):
        """Convert logged data to calibration-compatible format.

        Returns list of dicts matching the format expected by
        calibration_loop.py and model_updater.py.
        """
        cal_data = []
        for entry in self._data_log:
            tel = entry.get('telemetry')
            if tel is None:
                continue
            cal_data.append({
                't': entry['time'],
                'sensors': tel.get('sensors', [1, 1, 1, 1]),
                'left_pwm': tel.get('left_pwm', 0),
                'right_pwm': tel.get('right_pwm', 0),
                'error': tel.get('error', 0),
                'pid_output': tel.get('pid_output', 0),
                'tick_ms': tel.get('tick_ms', 0),
            })
        return cal_data

    def save_data_log(self, filepath):
        """Save logged data to JSON file."""
        import json
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self._data_log, f, indent=2, ensure_ascii=False)
        print("[RealCarEnv] Data saved: %s (%d records)" % (filepath, len(self._data_log)))

    # ================================================================
    #  Internal methods
    # ================================================================

    def _on_telemetry(self, packet):
        """Callback for telemetry packets."""
        self._latest_telemetry = packet

    def _on_status(self, packet):
        """Callback for status packets."""
        self._latest_status = packet

    def _get_observation(self):
        """Build observation from latest telemetry.

        Returns 10D observation matching CarEnv simulator format:
        [s0, s1, s2, s3, error_norm, pid_norm, left_norm, right_norm, tick_norm, lost_flag]
        """
        tel = self._latest_telemetry

        if tel is None:
            # No telemetry yet, return zeros
            return np.zeros(10, dtype=np.float32)

        sensors = [tel.s0, tel.s1, tel.s2, tel.s3]
        self._prev_sensors = sensors

        # Normalize error to [-1, 1]
        error_norm = max(-1.0, min(1.0, tel.error / 1024.0))
        self._prev_error = error_norm

        # Normalize PID output to [-1, 1]
        pid_norm = max(-1.0, min(1.0, tel.pid_output / 1024.0))

        # Normalize motor PWM to [0, 1]
        left_norm = tel.left_pwm / 999.0
        right_norm = tel.right_pwm / 999.0

        # Normalize tick to [0, 1] (assuming max 10 seconds = 10000ms)
        tick_norm = min(1.0, tel.tick_ms / 10000.0)

        # Lost flag
        lost_flag = 1.0 if all(s == 1 for s in sensors) else 0.0

        obs = np.array([
            sensors[0], sensors[1], sensors[2], sensors[3],
            error_norm, pid_norm,
            left_norm, right_norm,
            tick_norm, lost_flag,
        ], dtype=np.float32)

        return obs

    def _compute_reward(self):
        """Compute reward from current telemetry state.

        Simple reward: positive for staying on line, negative for losing.
        """
        sensors = self._prev_sensors
        error = self._prev_error

        black_count = sum(1 for s in sensors if s == 0)

        breakdown = {}

        # Tracking reward: error smaller = better
        tracking = 1.0 - abs(error)
        breakdown['tracking'] = round(tracking, 4)

        # Center reward
        center = max(0.0, 1.0 - abs(error) * 2.0)
        breakdown['center'] = round(center, 4)

        # Lost penalty
        penalty_lost = -5.0 if black_count == 0 else 0.0
        breakdown['penalty_lost'] = round(penalty_lost, 4)

        # Recovery bonus
        recovery = 0.0
        if hasattr(self, '_was_lost') and self._was_lost and black_count > 0:
            recovery = 3.0
        self._was_lost = (black_count == 0)
        breakdown['recovery'] = round(recovery, 4)

        total = sum(breakdown.values())
        breakdown['total'] = round(total, 4)

        return total, breakdown

    def get_info(self):
        """Get current environment info."""
        return {
            'connected': self._connected,
            'port': self.port,
            'steps': self._step_count,
            'episode_reward': self._episode_reward,
            'data_log_size': len(self._data_log),
            'latest_telemetry': self._latest_telemetry.to_dict() if self._latest_telemetry else None,
            'latest_status': self._latest_status.to_dict() if self._latest_status else None,
            'bridge_stats': self.bridge.get_stats() if self._connected else None,
        }


# ================================================================
#  Quick test
# ================================================================

if __name__ == '__main__':
    print("=== RealCarEnv Quick Test ===")
    print("This requires a real STM32 car connected via HC-06 Bluetooth.")
    print()
    print("Usage:")
    print("  env = RealCarEnv(port='COM3')")
    print("  obs, info = env.reset()")
    print("  for _ in range(100):")
    print("      obs, reward, term, trunc, info = env.step(2)  # STRAIGHT")
    print("      print(info['sensors'], info['error'])")
    print("  env.save_data_log('real_data.json')")
    print("  cal = env.get_calibration_data()")
    print("  # Use cal with calibration_loop.py")
