# -*- coding: utf-8 -*-
"""
data_logger.py - 真实 STM32 数据记录器

职责:
    1. 记录串口接收的遥测数据
    2. 保存为 JSON (兼容 ExperimentLogger 格式)
    3. 支持实时统计
    4. 支持多段录制 (自动分段)
"""

from dataclasses import dataclass, field
from datetime import datetime
import time
import json
import os
from collections import deque
from typing import Optional


class RealDataLogger:
    """
    真实数据记录器。
    
    记录从 SerialBridge 接收的遥测数据，
    保存为与 ExperimentLogger 兼容的 JSON 格式。
    
    使用方式:
        logger = RealDataLogger()
        logger.start("test_01")
        
        # 在 SerialBridge 回调中调用
        logger.on_telemetry(pkt)
        
        # 停止并保存
        logger.stop()
        logger.save("data/real_test_01.json")
    """

    def __init__(self, max_history=50000):
        self.max_history = max_history
        self.history = deque(maxlen=max_history)
        self.recording = False
        self.session_name = ""
        self.start_time = 0.0
        self._last_tick_ms = 0

        # 统计
        self.total_frames = 0
        self.total_track_loss = 0
        self.max_error = 0
        self.sum_error = 0.0

    def start(self, name=None):
        """开始录制"""
        self.history.clear()
        self.recording = True
        self.start_time = time.monotonic()
        self.session_name = name or "real_{}".format(int(self.start_time))
        self.total_frames = 0
        self.total_track_loss = 0
        self.max_error = 0
        self.sum_error = 0.0
        self._last_tick_ms = 0
        print("[DataLogger] 录制开始: {}".format(self.session_name))

    def stop(self):
        """停止录制"""
        self.recording = False
        n = len(self.history)
        print("[DataLogger] 录制停止: {} 帧".format(n))

    def on_telemetry(self, pkt):
        """
        记录一个遥测帧。
        
        参数:
            pkt: TelemetryPacket
        """
        if not self.recording:
            return

        record = {
            't': round(pkt.timestamp - self.start_time, 6),
            'tick_ms': pkt.tick_ms,
            'sensors': pkt.sensors,
            'left_pwm': pkt.left_pwm,
            'right_pwm': pkt.right_pwm,
            'error': pkt.error,
            'pid_output': pkt.pid_output,
            'yaw': getattr(pkt, 'yaw', 0.0),   # MPU6050 偏航角(度), 标定/航迹推算用
        }

        self.history.append(record)
        self.total_frames += 1

        # 统计
        err = abs(pkt.error)
        if err > self.max_error:
            self.max_error = err
        self.sum_error += err
        if all(s == 0 for s in pkt.sensors):
            self.total_track_loss += 1

        self._last_tick_ms = pkt.tick_ms

    def on_status(self, pkt):
        """记录状态帧 (附加到最近的遥测帧)"""
        if not self.recording or not self.history:
            return
        last = self.history[-1]
        last['mode'] = pkt.mode
        last['lost_counter'] = pkt.lost_counter
        last['battery_mv'] = pkt.battery_mv

    def get_stats(self):
        """获取录制统计"""
        n = max(self.total_frames, 1)
        elapsed = time.monotonic() - self.start_time if self.start_time else 0
        return {
            'recording': self.recording,
            'session': self.session_name,
            'frames': self.total_frames,
            'duration_s': round(elapsed, 2),
            'avg_error': round(self.sum_error / n, 3),
            'max_error': self.max_error,
            'track_loss_pct': round(self.total_track_loss / n * 100, 1),
            'actual_hz': round(self.total_frames / max(elapsed, 0.001), 1),
        }

    def save(self, filepath):
        """
        保存录制数据为 JSON。
        
        格式与 ExperimentLogger.export_json() 兼容。
        """
        data = list(self.history)
        metrics = self._compute_metrics(data)

        result = {
            'name': self.session_name,
            'source': 'real_stm32',
            'params': {},
            'metrics': metrics,
            'data': data,
        }

        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print("[DataLogger] 已保存: {} ({} 帧)".format(filepath, len(data)))
        return filepath

    def load(self, filepath):
        """
        加载 JSON 数据文件。

        返回:
            (list[dict], bool): 数据记录列表和是否为 legacy（无 campaign_meta）
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            result = json.load(f)
        self.history.clear()
        for record in result.get('data', []):
            self.history.append(record)
        self.total_frames = len(self.history)
        is_legacy = not self.is_campaign_json(result)
        tag = "legacy" if is_legacy else "campaign"
        print("[DataLogger] 已加载: {} ({} 帧, {})".format(filepath, self.total_frames, tag))
        return list(self.history), is_legacy

    def start_campaign_run(self, campaign_id: str = "", run_id: str = "",
                           parameter_version: int = 0):
        """Start a campaign-aware recording session."""
        self.start("{0}/{1}".format(campaign_id, run_id) if campaign_id else None)
        self._campaign_id = campaign_id
        self._run_id = run_id
        self._parameter_version = parameter_version
        self._termination_reason = ""

    def set_termination_reason(self, reason: str):
        self._termination_reason = reason

    def save_campaign(self, filepath: str, additional_meta: Optional[dict] = None):
        """Save recording with campaign metadata; backward-compatible with legacy JSON."""
        data = list(self.history)
        metrics = self._compute_metrics(data)

        result = {
            'name': self.session_name,
            'source': 'real_stm32',
            'params': {},
            'metrics': metrics,
            'data': data,
            '_campaign_meta': {
                'campaign_id': getattr(self, '_campaign_id', ''),
                'run_id': getattr(self, '_run_id', ''),
                'parameter_version': getattr(self, '_parameter_version', 0),
                'termination_reason': getattr(self, '_termination_reason', ''),
                'saved_at': datetime.utcnow().isoformat() + 'Z',
            },
        }
        if additional_meta:
            result['_campaign_meta'].update(additional_meta)

        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print("[DataLogger] campaign saved: {0} ({1} frames, run={2})".format(
            filepath, len(data), getattr(self, '_run_id', '')))
        return filepath

    @staticmethod
    def is_campaign_json(data: dict) -> bool:
        """Check if loaded JSON has campaign metadata (legacy detection)."""
        return '_campaign_meta' in data

    def _compute_metrics(self, data):
        """计算与 ExperimentLogger 兼容的指标"""
        if len(data) < 10:
            return {k: 0.0 for k in [
                'avg_error', 'max_error', 'rms_error',
                'overshoot_pct', 'oscillation_freq',
                'settling_time', 'track_loss_pct', 'score',
                'data_points', 'duration']}

        errors = [abs(r['error']) for r in data]
        raw_errors = [r['error'] for r in data]

        avg_error = sum(errors) / len(errors)
        max_error = max(errors)
        rms_error = (sum(e**2 for e in raw_errors) / len(raw_errors)) ** 0.5

        track_loss = sum(1 for r in data
                         if all(s == 0 for s in r.get('sensors', [1,1,1,1])))
        track_loss_pct = track_loss / len(data) * 100

        overshoot_count = sum(1 for e in errors if e > avg_error * 2)
        overshoot_pct = overshoot_count / len(data) * 100

        zero_crossings = 0
        for i in range(1, len(raw_errors)):
            if raw_errors[i-1] * raw_errors[i] < 0:
                zero_crossings += 1
        duration = data[-1]['t'] - data[0]['t'] if len(data) > 1 else 1.0
        oscillation_freq = zero_crossings / (2.0 * max(duration, 0.001))

        settling_time = duration
        for i in range(len(raw_errors) - 10):
            if all(abs(raw_errors[j]) < 1.0
                   for j in range(i, i+10)):
                settling_time = data[i]['t'] - data[0]['t']
                break

        score = 100.0
        score -= min(40, avg_error * 8)
        score -= min(20, max_error * 2)
        score -= min(15, track_loss_pct * 1.5)
        score -= min(10, overshoot_pct * 0.5)
        score -= min(10, oscillation_freq * 2)
        score = max(0, min(100, score))

        return {
            'avg_error': round(avg_error, 3),
            'max_error': round(max_error, 3),
            'rms_error': round(rms_error, 3),
            'overshoot_pct': round(overshoot_pct, 1),
            'oscillation_freq': round(oscillation_freq, 2),
            'settling_time': round(settling_time, 3),
            'track_loss_pct': round(track_loss_pct, 1),
            'score': round(score, 1),
            'data_points': len(data),
            'duration': round(duration, 3),
        }
