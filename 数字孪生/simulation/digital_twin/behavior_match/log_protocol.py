# -*- coding: utf-8 -*-
"""
log_protocol.py - 统一日志协议

仿真端和 STM32 真实端使用完全相同的日志格式。
支持 CSV 文件读写 + 实时流解析。

日志格式 (每行一条):
  tick, error, s0, s1, s2, s3, pwm_left, pwm_right, state

其中:
  tick:       控制周期序号 (从 0 开始)
  error:      加权偏差 (position, 整数)
  s0~s3:      传感器状态 (0=黑线, 1=白底)
  pwm_left:   左轮 PWM (0~999)
  pwm_right:  右轮 PWM (0~999)
  state:      控制状态 (forward/turn_left/turn_right/lost)
"""

import os
import csv


LOG_HEADER = ['tick', 'error', 's0', 's1', 's2', 's3',
              'pwm_left', 'pwm_right', 'state']


def control_state_to_name(black_count, position):
    if black_count == 4:
        return 'lost'
    elif black_count == 0:
        return 'forward'
    elif -1 <= position <= 1:
        return 'forward'
    elif position < 0:
        return 'turn_left'
    else:
        return 'turn_right'


def pwm_from_normalized(left_norm, right_norm):
    lp = max(0, min(999, int((left_norm + 1.0) / 2.0 * 999)))
    rp = max(0, min(999, int((right_norm + 1.0) / 2.0 * 999)))
    return lp, rp


def log_entry(tick, ctrl_out):
    state = control_state_to_name(
        sum(1 for s in ctrl_out.sensor_reading if s == 0),
        ctrl_out.error)
    lp, rp = pwm_from_normalized(ctrl_out.left_speed, ctrl_out.right_speed)
    return {
        'tick': tick,
        'error': int(ctrl_out.error),
        's0': ctrl_out.sensor_reading[0] if len(ctrl_out.sensor_reading) > 0 else 1,
        's1': ctrl_out.sensor_reading[1] if len(ctrl_out.sensor_reading) > 1 else 1,
        's2': ctrl_out.sensor_reading[2] if len(ctrl_out.sensor_reading) > 2 else 1,
        's3': ctrl_out.sensor_reading[3] if len(ctrl_out.sensor_reading) > 3 else 1,
        'pwm_left': lp,
        'pwm_right': rp,
        'state': state,
    }


def save_log(entries, filepath):
    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=LOG_HEADER)
        writer.writeheader()
        for e in entries:
            writer.writerow(e)


def load_log(filepath):
    entries = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = {}
            for k in LOG_HEADER:
                if k in ('tick', 'error', 's0', 's1', 's2', 's3',
                         'pwm_left', 'pwm_right'):
                    entry[k] = int(row[k])
                else:
                    entry[k] = row[k]
            entries.append(entry)
    return entries
