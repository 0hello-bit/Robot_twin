# -*- coding: utf-8 -*-
"""
real_world_mapper.py - Real World Track Mapper

Reconstructs a track centerline from STM32 driving logs.
No RL, no PID tuning, no optimization -- pure geometry tool.

Input:  STM32 log (CSV/dict) with columns:
        tick, error, s0, s1, s2, s3, pwm_left, pwm_right

Output: numpy array (N, 2) of reconstructed track points,
        plus smoothed centerline and curvature data.
"""

import math
import numpy as np
from scipy.interpolate import make_interp_spline, splprep, splev
from scipy.ndimage import uniform_filter1d


# ================================================================
#  Constants (match your STM32 code)
# ================================================================
# PWM range on STM32: 0..999, but motor_Write clips at 650
PWM_MAX = 650.0
# Car physical parameters (pixels in sim space)
WHEEL_BASE = 50.0       # distance between left/right wheels
SENSOR_SPACING = 10.0   # distance between outer sensors
# Scale: PWM 650 -> sim velocity units
PWM_TO_VEL = 300.0             # max sim velocity (pixels/s)


# ================================================================
#  1. Log Loading
# ================================================================

def load_csv_log(filepath):
    """
    Load a CSV log file.
    
    Expected header: tick,error,s0,s1,s2,s3,pwm_left,pwm_right
    Returns: numpy structured-ish 2D array, shape (N, 8)
    """
    data = np.loadtxt(filepath, delimiter=',', skiprows=1)
    return data


def load_dict_log(records):
    """
    Convert a list of dicts (from RealDataLogger) to numpy array.
    
    Each dict must have keys:
        tick, error, s0, s1, s2, s3, pwm_left, pwm_right
    
    Returns: numpy array shape (N, 8)
    """
    rows = []
    for r in records:
        sensors = r.get('sensors', [0, 0, 0, 0])
        rows.append([
            r.get('tick', 0),
            r.get('error', 0),
            sensors[0] if len(sensors) > 0 else 0,
            sensors[1] if len(sensors) > 1 else 0,
            sensors[2] if len(sensors) > 2 else 0,
            sensors[3] if len(sensors) > 3 else 0,
            r.get('left_pwm', r.get('pwm_left', 0)),
            r.get('right_pwm', r.get('pwm_right', 0)),
        ])
    return np.array(rows, dtype=np.float64)


# ================================================================
#  2. Trajectory Reconstruction
# ================================================================

def reconstruct_trajectory(log, method='dead_reckoning'):
    """
    Reconstruct (x, y) trajectory from log data.
    
    Args:
        log: numpy array (N, 8) from load_csv_log / load_dict_log
             columns: tick, error, s0, s1, s2, s3, pwm_left, pwm_right
        method: 'dead_reckoning' or 'error_correction'
    
    Returns:
        points: numpy (N, 2) array of (x, y) positions
    """
    if method == 'error_correction':
        return _reconstruct_with_error_correction(log)
    else:
        return _reconstruct_dead_reckoning(log)


def _reconstruct_dead_reckoning(log):
    """
    Dead reckoning: integrate PWM -> velocity + heading.
    
    pwm_left / pwm_right encode differential drive:
      v_left  = pwm_left  / PWM_MAX * PWM_TO_VEL
      v_right = pwm_right / PWM_MAX * PWM_TO_VEL
      v_forward = (v_left + v_right) / 2
      omega     = (v_right - v_left) / WHEEL_BASE
    
    Then integrate:
      heading += omega * dt
      x += v_forward * cos(heading) * dt
      y += v_forward * sin(heading) * dt
    """
    n = len(log)
    points = np.zeros((n, 2))
    
    # Extract columns
    ticks = log[:, 0]
    pwm_l = log[:, 6]
    pwm_r = log[:, 7]
    
    heading = 0.0
    x, y = 0.0, 0.0
    
    for i in range(n):
        # Time delta (ticks are in ms from STM32)
        if i == 0:
            dt = 0.005  # default 5ms loop
        else:
            dt = max(ticks[i] - ticks[i - 1], 0.001) / 1000.0  # ms -> seconds
        
        # PWM -> velocity
        v_l = pwm_l[i] / PWM_MAX * PWM_TO_VEL
        v_r = pwm_r[i] / PWM_MAX * PWM_TO_VEL
        
        v_forward = (v_l + v_r) / 2.0
        omega = (v_r - v_l) / WHEEL_BASE
        
        # Integrate
        heading += omega * dt
        x += v_forward * math.cos(heading) * dt
        y += v_forward * math.sin(heading) * dt
        
        points[i] = [x, y]
    
    return points


def _reconstruct_with_error_correction(log):
    """
    Dead reckoning + error-based lateral correction.
    
    The 'error' column represents how far the car drifted
    from the track center (positive = right, negative = left).
    
    We use this to apply a small lateral correction to the
    reconstructed path, making it closer to the true track.
    
    Correction idea:
      The error tells us the car is `error` pixels off-center.
      We shift the reconstructed point perpendicular to the
      heading by -error (to move it back toward center).
    """
    n = len(log)
    points = np.zeros((n, 2))
    
    ticks = log[:, 0]
    errors = log[:, 1]
    pwm_l = log[:, 6]
    pwm_r = log[:, 7]
    
    heading = 0.0
    x, y = 0.0, 0.0
    
    for i in range(n):
        if i == 0:
            dt = 0.005
        else:
            dt = max(ticks[i] - ticks[i - 1], 0.001) / 1000.0
        
        v_l = pwm_l[i] / PWM_MAX * PWM_TO_VEL
        v_r = pwm_r[i] / PWM_MAX * PWM_TO_VEL
        
        v_forward = (v_l + v_r) / 2.0
        omega = (v_r - v_l) / WHEEL_BASE
        
        heading += omega * dt
        x += v_forward * math.cos(heading) * dt
        y += v_forward * math.sin(heading) * dt
        
        # Lateral correction: shift perpendicular to heading
        # error > 0 means car is to the right of center
        # so we shift left (negative perpendicular direction)
        err = errors[i]
        perp_x = -math.sin(heading)
        perp_y =  math.cos(heading)
        correction_strength = 0.3  # tune this
        x += perp_x * err * correction_strength * dt * 10
        y += perp_y * err * correction_strength * dt * 10
        
        points[i] = [x, y]
    
    return points


def reconstruct_from_records(records, pwm_to_vel=PWM_TO_VEL, use_gyro=True):
    """
    直接从 RealDataLogger 的 dict 记录重建小车轨迹 (推荐用于真车 WiFi 遥测)。

    相比 reconstruct_trajectory(吃 numpy (N,8)、用 PWM 估航向),本函数:
      - 用 PC 接收时间戳 't'(秒)算 dt —— 真车 STM32 的 tick 是主循环计数,
        不是真实时间(且遥测里有 Delay),不可靠;PC 时间戳更准。
      - 优先用 MPU6050 实测 yaw(度)作航向 —— 比 PWM 差分估计准得多,
        这是装 MPU6050 的核心价值。无 yaw 时自动回退到 PWM 差分积分。

    参数:
        records:     list[dict],每条含 't','yaw','left_pwm','right_pwm'(可选 'sensors','error')
        pwm_to_vel:  PWM(0~PWM_MAX)→ 仿真速度(px/s)的标定系数,用真车实测标定
        use_gyro:    True 用 yaw 字段作航向;数据里没有 yaw 时自动回退

    返回:
        points: numpy (N,2) 轨迹(局部坐标,起点在原点)
    """
    n = len(records)
    if n == 0:
        return np.zeros((0, 2))
    points = np.zeros((n, 2))
    x = y = 0.0
    heading = 0.0
    prev_t = None
    has_gyro = use_gyro and any('yaw' in r for r in records)
    for i, r in enumerate(records):
        t = r.get('t', i * 0.05)
        dt = 0.05 if prev_t is None else max(t - prev_t, 1e-3)
        prev_t = t
        lp = float(r.get('left_pwm', 0))
        rp = float(r.get('right_pwm', 0))
        v = (lp + rp) / 2.0 / PWM_MAX * pwm_to_vel
        if has_gyro:
            heading = math.radians(float(r.get('yaw', 0.0)))
        else:
            omega = (rp - lp) / PWM_MAX * pwm_to_vel / WHEEL_BASE
            heading += omega * dt
        x += v * math.cos(heading) * dt
        y += v * math.sin(heading) * dt
        points[i] = [x, y]
    return points


# ================================================================
#  3. Trajectory Smoothing
# ================================================================

def smooth_trajectory(points, method='moving_average', **kwargs):
    """
    Smooth a noisy trajectory.
    
    Args:
        points: numpy (N, 2)
        method: 'moving_average' or 'bspline'
    
    Returns:
        smoothed: numpy (M, 2) -- M may differ from N for bspline
    """
    if len(points) < 3:
        return points.copy()
    
    if method == 'bspline':
        return _smooth_bspline(points, **kwargs)
    else:
        return _smooth_moving_average(points, **kwargs)


def _smooth_moving_average(points, window=11):
    """
    Moving average smoothing.
    Preserves number of points.
    """
    window = max(3, window)
    if window % 2 == 0:
        window += 1
    
    smoothed = np.zeros_like(points)
    smoothed[:, 0] = uniform_filter1d(points[:, 0], size=window)
    smoothed[:, 1] = uniform_filter1d(points[:, 1], size=window)
    return smoothed


def _smooth_bspline(points, smooth_factor=0.5, num_output=None):
    """
    B-spline smoothing.
    
    Args:
        smooth_factor: 0 = interpolation, higher = more smoothing
        num_output: number of output points (default: same as input)
    
    Returns:
        smoothed points (M, 2)
    """
    if num_output is None:
        num_output = len(points)
    
    # Remove duplicate consecutive points
    diffs = np.diff(points, axis=0)
    dists = np.linalg.norm(diffs, axis=1)
    mask = np.ones(len(points), dtype=bool)
    mask[1:] = dists > 1e-6
    clean = points[mask]
    
    if len(clean) < 4:
        return points.copy()
    
    try:
        # Fit B-spline
        tck, u = splprep([clean[:, 0], clean[:, 1]],
                         s=smooth_factor * len(clean),
                         per=True)  # per=True for closed track
        
        # Evaluate at uniform parameter values
        u_new = np.linspace(0, 1, num_output)
        smooth_x, smooth_y = splev(u_new, tck)
        return np.column_stack([smooth_x, smooth_y])
    except Exception:
        # Fallback to moving average
        return _smooth_moving_average(points)


# ================================================================
#  4. Curvature Estimation
# ================================================================

def estimate_curvature(points):
    """
    Estimate curvature at each point using the Menger curvature formula.
    
    For three consecutive points p0, p1, p2:
      curvature = 2 * |cross(v1, v2)| / (|v1| * |v2| * |v1+v2|)
    
    For a closed track, wraps around.
    
    Returns:
        curvatures: numpy (N,) array, values in [0, inf)
                    0 = straight, large = sharp turn
    """
    n = len(points)
    if n < 3:
        return np.zeros(n)
    
    curvatures = np.zeros(n)
    
    for i in range(n):
        p0 = points[(i - 1) % n]
        p1 = points[i]
        p2 = points[(i + 1) % n]
        
        v1 = p1 - p0
        v2 = p2 - p1
        
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        len1 = np.linalg.norm(v1)
        len2 = np.linalg.norm(v2)
        
        if len1 > 1e-6 and len2 > 1e-6:
            sin_angle = cross / (len1 * len2)
            curvatures[i] = abs(sin_angle) * 2.0 / (len1 + len2 + 1e-8)
        else:
            curvatures[i] = 0.0
    
    return curvatures


def compute_path_length(points):
    """Total path length of the trajectory."""
    diffs = np.diff(points, axis=0)
    return np.sum(np.linalg.norm(diffs, axis=1))


# ================================================================
#  5. Resampling
# ================================================================

def resample_track(points, num_points=200):
    """
    Resample track to uniform arc-length spacing.
    
    Args:
        points: (N, 2) array
        num_points: desired number of output points
    
    Returns:
        resampled: (num_points, 2) array
    """
    if len(points) < 2:
        return points.copy()
    
    # Compute cumulative arc length
    diffs = np.diff(points, axis=0)
    seg_lengths = np.linalg.norm(diffs, axis=1)
    cum_len = np.zeros(len(points))
    cum_len[1:] = np.cumsum(seg_lengths)
    total_len = cum_len[-1]
    
    if total_len < 1e-6:
        return np.tile(points[0], (num_points, 1))
    
    # Uniform parameter values
    uniform_len = np.linspace(0, total_len, num_points, endpoint=False)
    
    # Interpolate x and y separately
    resampled_x = np.interp(uniform_len, cum_len, points[:, 0])
    resampled_y = np.interp(uniform_len, cum_len, points[:, 1])
    
    return np.column_stack([resampled_x, resampled_y])


# ================================================================
#  6. Export
# ================================================================

def export_track(points, filepath,
                 smoothed=None, curvature=None, metadata=None):
    """
    Export reconstructed track to .npy file.
    
    The .npy file contains a dict with:
      - 'track_points': (N, 2) raw reconstructed points
      - 'smoothed': (M, 2) smoothed centerline
      - 'curvature': (M,) curvature at each smoothed point
      - 'metadata': dict with reconstruction info
    
    Args:
        points: raw reconstructed (N, 2)
        filepath: output path (e.g. 'tracks/real_reconstructed_track.npy')
        smoothed: smoothed (M, 2) or None
        curvature: (M,) or None
        metadata: dict or None
    """
    if smoothed is None:
        smoothed = points
    if curvature is None:
        curvature = estimate_curvature(smoothed)
    if metadata is None:
        metadata = {}
    
    metadata['n_raw_points'] = len(points)
    metadata['n_smooth_points'] = len(smoothed)
    metadata['path_length'] = float(compute_path_length(smoothed))
    metadata['max_curvature'] = float(np.max(curvature)) if len(curvature) > 0 else 0.0
    metadata['avg_curvature'] = float(np.mean(curvature)) if len(curvature) > 0 else 0.0
    
    export_data = {
        'track_points': points,
        'smoothed': smoothed,
        'curvature': curvature,
        'metadata': metadata,
    }
    
    import os
    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
    np.save(filepath, export_data, allow_pickle=True)
    print("[RealWorldMapper] Exported: {}".format(filepath))
    print("  Raw points: {}".format(len(points)))
    print("  Smoothed:   {}".format(len(smoothed)))
    print("  Path length: {:.1f}".format(metadata['path_length']))
    print("  Max curvature: {:.4f}".format(metadata['max_curvature']))
    return filepath


def load_track(filepath):
    """
    Load a previously exported track .npy file.
    
    Returns dict with keys: track_points, smoothed, curvature, metadata
    """
    data = np.load(filepath, allow_pickle=True).item()
    return data


# ================================================================
#  7. Full Pipeline
# ================================================================

def map_real_track(log, method='dead_reckoning',
                   smooth_method='bspline',
                   num_output_points=200,
                   output_path=None):
    """
    Full pipeline: log -> trajectory -> smooth -> curvature -> export.
    
    Args:
        log: numpy (N, 8) array or list of dicts
        method: 'dead_reckoning' or 'error_correction'
        smooth_method: 'bspline' or 'moving_average'
        num_output_points: number of points in output track
        output_path: where to save .npy (None = don't save)
    
    Returns:
        dict with:
          'raw_points': (N, 2)
          'smoothed': (M, 2)
          'curvature': (M,)
          'metadata': dict
    """
    # Convert dict log to numpy if needed
    if isinstance(log, list):
        log = load_dict_log(log)
    
    print("[RealWorldMapper] Input log: {} rows".format(len(log)))
    
    # Step 1: Reconstruct trajectory
    raw = reconstruct_trajectory(log, method=method)
    print("[RealWorldMapper] Raw trajectory: {} points".format(len(raw)))
    
    # Step 2: Resample to uniform spacing
    raw_resampled = resample_track(raw, num_points=max(num_output_points * 2, 400))
    
    # Step 3: Smooth
    smoothed = smooth_trajectory(raw_resampled, method=smooth_method)
    print("[RealWorldMapper] Smoothed: {} points".format(len(smoothed)))
    
    # Step 4: Resample to final count
    smoothed = resample_track(smoothed, num_points=num_output_points)
    
    # Step 5: Curvature
    curv = estimate_curvature(smoothed)
    
    # Step 6: Metadata
    metadata = {
        'method': method,
        'smooth_method': smooth_method,
        'input_rows': len(log),
        'track_length': float(compute_path_length(smoothed)),
    }
    
    # Step 7: Export
    if output_path:
        export_track(raw, output_path,
                     smoothed=smoothed, curvature=curv,
                     metadata=metadata)
    
    return {
        'raw_points': raw,
        'smoothed': smoothed,
        'curvature': curv,
        'metadata': metadata,
    }


# ================================================================
#  8. Demo / CLI
# ================================================================

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python real_world_mapper.py <log.csv> [output.npy]")
        print("")
        print("CSV format: tick,error,s0,s1,s2,s3,pwm_left,pwm_right")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'real_reconstructed_track.npy'
    
    log = load_csv_log(csv_path)
    result = map_real_track(log, output_path=out_path)
    
    print("\nDone! Track saved to:", out_path)
