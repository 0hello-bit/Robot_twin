# -*- coding: utf-8 -*-
"""
replay_compare.py - 真实 vs 仿真数据对比分析

职责:
    1. 对齐两组数据的时间轴
    2. 计算传感器/PWM/误差的逐帧差异
    3. 生成差异报告
    4. 建议仿真参数修正方向
"""

import math


class ReplayComparison:
    """
    回放数据对比。
    
    对比真实 STM32 数据与仿真数据，
    量化差异并提供参数修正建议。
    
    使用方式:
        cmp = ReplayComparison()
        cmp.load_real("data/real_test.json")
        cmp.load_sim("data/sim_test.json")
        report = cmp.analyze()
        print(report)
    """

    def __init__(self):
        self.real_data = []
        self.sim_data = []
        self._aligned = []

    def load_real(self, data_list):
        """加载真实数据 (list of dict)"""
        self.real_data = data_list

    def load_sim(self, data_list):
        """加载仿真数据 (list of dict)"""
        self.sim_data = data_list

    def load_from_engine(self, real_engine, sim_engine):
        """从 ReplayEngine 加载数据"""
        self.real_data = [self._frame_to_dict(f) for f in real_engine.frames]
        self.sim_data = [self._frame_to_dict(f) for f in sim_engine.frames]

    @staticmethod
    def _frame_to_dict(frame):
        return {
            't': frame.t,
            'sensors': frame.sensors,
            'left_pwm': frame.left_pwm,
            'right_pwm': frame.right_pwm,
            'error': frame.error,
            'pid_output': frame.pid_output,
            'x': frame.car_x,
            'y': frame.car_y,
            'angle': frame.car_angle,
        }

    def analyze(self):
        """
        执行完整对比分析。
        
        返回:
            dict: {
                'summary': 摘要,
                'sensor_accuracy': 传感器匹配度,
                'pwm_diff': PWM 差异统计,
                'error_diff': 误差差异统计,
                'timing_diff': 时序差异,
                'suggestions': 参数修正建议,
            }
        """
        if not self.real_data or not self.sim_data:
            return {'error': '数据不足'}

        # 时间对齐
        self._align_by_time()

        result = {
            'summary': self._summary(),
            'sensor_accuracy': self._sensor_accuracy(),
            'pwm_diff': self._pwm_diff(),
            'error_diff': self._error_diff(),
            'timing_diff': self._timing_diff(),
            'suggestions': self._generate_suggestions(),
        }
        return result

    def _align_by_time(self):
        """按时间戳对齐两组数据"""
        self._aligned = []
        sim_idx = 0

        for real_pkt in self.real_data:
            real_t = real_pkt['t']
            # 在仿真数据中找到最接近的帧
            best_idx = sim_idx
            best_diff = float('inf')
            for i in range(max(0, sim_idx - 5),
                           min(len(self.sim_data), sim_idx + 10)):
                diff = abs(self.sim_data[i]['t'] - real_t)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i
            sim_idx = best_idx

            self._aligned.append({
                'real': real_pkt,
                'sim': self.sim_data[sim_idx] if sim_idx < len(self.sim_data) else None,
                'time_diff': best_diff,
            })

    def _summary(self):
        """生成摘要"""
        n = len(self._aligned)
        if n == 0:
            return "无对齐数据"

        avg_time_diff = sum(a['time_diff'] for a in self._aligned) / n
        sensor_match = sum(
            1 for a in self._aligned
            if a['sim'] and a['real']['sensors'] == a['sim']['sensors']
        ) / n * 100

        return {
            'aligned_frames': n,
            'avg_time_offset_ms': round(avg_time_diff * 1000, 2),
            'sensor_match_pct': round(sensor_match, 1),
            'real_duration_s': round(self.real_data[-1]['t'] - self.real_data[0]['t'], 2),
            'sim_duration_s': round(self.sim_data[-1]['t'] - self.sim_data[0]['t'], 2),
        }

    def _sensor_accuracy(self):
        """逐传感器匹配度"""
        counts = [0, 0, 0, 0]
        total = max(len(self._aligned), 1)

        for a in self._aligned:
            if a['sim'] is None:
                continue
            real_s = a['real']['sensors']
            sim_s = a['sim']['sensors']
            for i in range(min(4, len(real_s), len(sim_s))):
                if real_s[i] == sim_s[i]:
                    counts[i] += 1

        return {
            'S{}_match'.format(i): round(counts[i] / total * 100, 1)
            for i in range(4)
        }

    def _pwm_diff(self):
        """PWM 输出差异"""
        left_diffs = []
        right_diffs = []

        for a in self._aligned:
            if a['sim'] is None:
                continue
            left_diffs.append(abs(
                a['real']['left_pwm'] - a['sim']['left_pwm']))
            right_diffs.append(abs(
                a['real']['right_pwm'] - a['sim']['right_pwm']))

        if not left_diffs:
            return {}

        return {
            'left_avg_diff': round(sum(left_diffs) / len(left_diffs), 1),
            'left_max_diff': round(max(left_diffs), 1),
            'right_avg_diff': round(sum(right_diffs) / len(right_diffs), 1),
            'right_max_diff': round(max(right_diffs), 1),
        }

    def _error_diff(self):
        """误差差异"""
        diffs = []
        for a in self._aligned:
            if a['sim'] is None:
                continue
            diffs.append(abs(a['real']['error'] - a['sim']['error']))

        if not diffs:
            return {}

        return {
            'avg_error_diff': round(sum(diffs) / len(diffs), 3),
            'max_error_diff': round(max(diffs), 3),
        }

    def _timing_diff(self):
        """时序差异分析"""
        if not self.real_data or not self.sim_data:
            return {}

        real_dt = []
        sim_dt = []
        for i in range(1, len(self.real_data)):
            real_dt.append(self.real_data[i]['t'] - self.real_data[i-1]['t'])
        for i in range(1, len(self.sim_data)):
            sim_dt.append(self.sim_data[i]['t'] - self.sim_data[i-1]['t'])

        return {
            'real_avg_dt_ms': round(
                (sum(real_dt) / max(len(real_dt), 1)) * 1000, 2),
            'sim_avg_dt_ms': round(
                (sum(sim_dt) / max(len(sim_dt), 1)) * 1000, 2),
            'real_hz': round(
                len(self.real_data) / max(
                    self.real_data[-1]['t'] - self.real_data[0]['t'], 0.001), 1),
            'sim_hz': round(
                len(self.sim_data) / max(
                    self.sim_data[-1]['t'] - self.sim_data[0]['t'], 0.001), 1),
        }

    def _generate_suggestions(self):
        """
        基于差异分析生成参数修正建议。
        
        返回:
            list[str]: 建议列表
        """
        suggestions = []
        pwm_diff = self._pwm_diff()
        sensor_acc = self._sensor_accuracy()
        timing = self._timing_diff()

        # PWM 差异大 → 电机模型需要调整
        avg_left = pwm_diff.get('left_avg_diff', 0)
        avg_right = pwm_diff.get('right_avg_diff', 0)
        if avg_left > 50 or avg_right > 50:
            suggestions.append(
                "PWM 差异较大 (L={:.0f}, R={:.0f}): "
                "建议调整电机响应时间常数 (MOTOR_RESPONSE_TAU)".format(
                    avg_left, avg_right))

        # 传感器匹配低 → 传感器模型需要调整
        for i in range(4):
            key = 'S{}_match'.format(i)
            if sensor_acc.get(key, 100) < 80:
                suggestions.append(
                    "传感器 S{} 匹配度低 ({:.0f}%): "
                    "建议调整传感器检测半径或赛道宽度".format(
                        i, sensor_acc[key]))

        # 时序差异 → 控制频率需要调整
        real_hz = timing.get('real_hz', 50)
        sim_hz = timing.get('sim_hz', 50)
        if abs(real_hz - sim_hz) > 5:
            suggestions.append(
                "控制频率差异: 真实 {:.0f}Hz vs 仿真 {:.0f}Hz: "
                "建议调整仿真器控制频率".format(real_hz, sim_hz))

        if not suggestions:
            suggestions.append("各项指标匹配良好, 无需调整")

        return suggestions

    def get_report_text(self):
        """生成可读的文本报告"""
        report = self.analyze()
        lines = []
        lines.append("=" * 50)
        lines.append("  真实 vs 仿真 对比报告")
        lines.append("=" * 50)

        s = report.get('summary', {})
        lines.append("")
        lines.append("[摘要]")
        lines.append("  对齐帧数: {}".format(s.get('aligned_frames', 0)))
        lines.append("  时间偏移: {:.1f}ms".format(
            s.get('avg_time_offset_ms', 0)))
        lines.append("  传感器匹配: {:.1f}%".format(
            s.get('sensor_match_pct', 0)))

        sa = report.get('sensor_accuracy', {})
        lines.append("")
        lines.append("[传感器匹配度]")
        for i in range(4):
            key = 'S{}_match'.format(i)
            lines.append("  S{}: {:.1f}%".format(i, sa.get(key, 0)))

        pw = report.get('pwm_diff', {})
        if pw:
            lines.append("")
            lines.append("[PWM 差异]")
            lines.append("  左轮: avg={:.0f}  max={:.0f}".format(
                pw.get('left_avg_diff', 0), pw.get('left_max_diff', 0)))
            lines.append("  右轮: avg={:.0f}  max={:.0f}".format(
                pw.get('right_avg_diff', 0), pw.get('right_max_diff', 0)))

        sg = report.get('suggestions', [])
        if sg:
            lines.append("")
            lines.append("[修正建议]")
            for s in sg:
                lines.append("  - " + s)

        lines.append("")
        lines.append("=" * 50)
        return "\n".join(lines)
