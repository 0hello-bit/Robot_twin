# -*- coding: utf-8 -*-
"""
continuous_control_test.py - 离散 vs 连续传感器对比实验

测试矩阵:
    Controller:  Baseline PID / Adaptive PID
    Sensor:      Discrete (0/1) / Continuous (0~1023)
    Condition:   clean / noisy / sharp_curve / high_speed

输出:
    continuous_sensor_report.json
    continuous_sensor_summary.txt
"""

import math
import random
import json
import os
import time

from simulator.pid import PIDController
from simulator.map import TrackMap
from simulator.analog_sensor import AnalogSensorArray
from control_sandbox.plant_model import PlantModel
from control.adaptive_pid import AdaptivePID
from analysis.control_fitness import ControlFitness


# ── 赛道工厂 ──

def make_oval_track():
    track = TrackMap()
    pts = track.generate_oval(400, 300, 200, 150, num_points=200)
    track.add_polyline(pts)
    return track

def make_sharp_track():
    track = TrackMap()
    pts = track.generate_oval(300, 250, 80, 60, num_points=120)
    track.add_polyline(pts)
    return track


# ── 巡线控制器 ──

class ContinuousLineFollower:
    """支持离散/连续双模式的巡线控制器"""
    WEIGHTS = [-3.0, -1.0, 1.0, 3.0]

    def __init__(self, kp=0.6, ki=0.0, kd=0.15, base_speed=180):
        self.pid = PIDController(kp=kp, ki=ki, kd=kd)
        self.base_speed = base_speed
        self.lost_counter = 0
        self.last_position = 0

    def reset(self):
        self.pid.reset(); self.lost_counter = 0; self.last_position = 0

    def step_discrete(self, s0, s1, s2, s3, dt=0.03):
        """离散模式: 输入 0/1"""
        position = 0; black_count = 0
        if s0 == 0: position += -3; black_count += 1
        if s1 == 0: position += -1; black_count += 1
        if s2 == 0: position += +1; black_count += 1
        if s3 == 0: position += +3; black_count += 1
        return self._control(position, black_count, dt)

    def step_continuous(self, readings, analog_sensor, dt=0.03):
        """连续模式: 输入 0~1023 灰度值"""
        position = analog_sensor.read_position(readings)
        # 连续模式: 用总暗度判断是否丢线
        total_darkness = sum(max(0, analog_sensor.resolution - r) for r in readings)
        black_count = 4 if total_darkness > analog_sensor.resolution * 2 else (
            0 if total_darkness < 10 else 2)
        return self._control(position, black_count, dt)

    def _control(self, position, black_count, dt):
        if black_count == 4:
            self.lost_counter += 1
            if self.lost_counter == 1:
                self.last_position = 1 if self.last_position > 0 else -1
            if self.lost_counter > 40:
                self.last_position = -self.last_position; self.lost_counter = 0
            return (500, -500) if self.last_position > 0 else (-500, 500)
        elif black_count == 0:
            self.lost_counter = 0; return (120, 120)
        else:
            self.lost_counter = 0
            if position != 0: self.last_position = position
            pid_out = max(-1.0, min(1.0, self.pid.compute(position, dt)))
            base = self.base_speed / 999.0
            left = max(-1.0, min(1.0, base + pid_out * 0.5))
            right = max(-1.0, min(1.0, base - pid_out * 0.5))
            return (left * 999, right * 999)

    def get_pid(self):
        return self.pid


# ── 实验运行器 ──

def run_experiment(ctrl, apid, sensor_mode, analog_sensor, plant,
                   track, max_ticks, dt, speed_factor=1.0):
    plant.reset(x=400, y=450, angle=0)
    plant.set_track(track)

    errors = []
    motor_history = []
    sensor_readings = []
    positions = []
    pid_outputs = []

    base_speed = ctrl.base_speed
    ctrl.base_speed = int(base_speed * speed_factor)

    for tick in range(max_ticks):
        if sensor_mode == 'discrete':
            s = plant.read_sensors()
            pos = 0
            if s[0] == 0: pos += -3
            if s[1] == 0: pos += -1
            if s[2] == 0: pos += 1
            if s[3] == 0: pos += 3
            lp, rp = ctrl.step_discrete(s[0], s[1], s[2], s[3], dt)
        else:
            readings = analog_sensor.read(plant.x, plant.y, plant.angle, track)
            pos = analog_sensor.read_position(readings)
            lp, rp = ctrl.step_continuous(readings, analog_sensor, dt)
            sensor_readings.append(readings)

        # Adaptive PID update
        if apid is not None and tick > 0:
            deriv = (pos - errors[-1]) / dt
            kp, ki, kd = apid.update(pos, deriv, dt)
            ctrl.get_pid().set_gains(kp, ki, kd)

        ns = plant.step(lp, rp, dt)
        errors.append(pos)
        motor_history.append((lp, rp))
        positions.append({'x': plant.x, 'y': plant.y, 'angle': plant.angle})
        pid_outputs.append(ctrl.pid.output)

    ctrl.base_speed = base_speed
    return {
        'errors': errors,
        'motor_history': motor_history,
        'sensor_readings': sensor_readings,
        'positions': positions,
        'pid_outputs': pid_outputs,
        'max_ticks': max_ticks,
        'dt': dt,
    }


def compute_metrics(exp):
    e = exp['errors']; m = exp['motor_history']; n = len(e)
    if n == 0: return {}

    ae = [abs(x) for x in e]
    mean_e = sum(ae) / n; max_e = max(ae)

    zc = sum(1 for i in range(1, n) if e[i-1] * e[i] < 0)
    osc = zc / max(n, 1) * 2

    em = sum(e) / n
    ev = sum((x - em)**2 for x in e) / n

    # Settle time
    th = 0.5; st = n; sw = max(n // 5, 10)
    for i in range(n - sw, -1, -1):
        if all(abs(x) <= th for x in e[i:i+sw]): st = i
        else: break

    # PWM smoothness
    pc = [(abs(m[i][0]-m[i-1][0]) + abs(m[i][1]-m[i-1][1])) / 2.0
          for i in range(1, n)]
    mpc = sum(pc) / max(len(pc), 1)

    # PID smoothness
    po = exp['pid_outputs']
    pid_changes = [abs(po[i] - po[i-1]) for i in range(1, len(po))]
    mpid = sum(pid_changes) / max(len(pid_changes), 1)

    # Lost line
    if exp['sensor_readings']:
        # Continuous: "lost" = all readings > 800
        lc = sum(1 for sr in exp['sensor_readings'] if all(r > 800 for r in sr))
    else:
        lc = sum(1 for sr in exp['sensor_readings'] if all(r == 1 for r in sr)) if False else 0
    lp = lc / max(n, 1) * 100

    return {
        'mean_error': round(mean_e, 4),
        'max_error': round(max_e, 4),
        'osc_freq': round(osc, 4),
        'error_variance': round(ev, 4),
        'settle_time_s': round(st * exp['dt'], 3),
        'mean_pwm_change': round(mpc, 2),
        'mean_pid_change': round(mpid, 4),
        'lost_pct': round(lp, 2),
        'n_steps': n,
    }


# ── 主实验 ──

class ContinuousControlTest:
    def __init__(self, kp=0.6, ki=0.0, kd=0.15):
        self.kp = kp; self.ki = ki; self.kd = kd
        self.fitness = ControlFitness()

    def run_all(self, seeds=3, max_ticks=1500, dt=0.03):
        analog = AnalogSensorArray(sigma=8.0, resolution=1023)
        plant = PlantModel()

        scenarios = [
            ('oval_clean', make_oval_track, False, 1.0),
            ('oval_noisy', make_oval_track, True, 1.0),
            ('sharp_clean', make_sharp_track, False, 1.0),
            ('high_speed', make_oval_track, False, 1.5),
        ]

        all_results = {}

        for scenario_name, track_fn, noise, speed in scenarios:
            track = track_fn()
            analog.noise_enabled = noise

            scenario_data = {}
            for controller_type in ['baseline', 'adaptive']:
                for sensor_mode in ['discrete', 'continuous']:
                    key = '{}_{}_{}'.format(scenario_name, controller_type, sensor_mode)
                    runs = []

                    for si in range(seeds):
                        seed = si * 1000 + hash(key) % 1000
                        random.seed(seed)

                        ctrl = ContinuousLineFollower(
                            kp=self.kp, ki=self.ki, kd=self.kd)
                        apid = AdaptivePID(
                            kp=self.kp, ki=self.ki, kd=self.kd
                        ) if controller_type == 'adaptive' else None

                        exp = run_experiment(
                            ctrl, apid, sensor_mode, analog, plant,
                            track, max_ticks, dt, speed)

                        metrics = compute_metrics(exp)
                        runs.append({'seed': seed, 'metrics': metrics})

                    # 汇总
                    ml = [r['metrics'] for r in runs if r['metrics']]
                    if ml:
                        avg = {}
                        for k in ml[0]:
                            vs = [m[k] for m in ml]
                            avg[k] = round(sum(vs) / len(vs), 4)
                        # Std for key metrics
                        for k in ['mean_error', 'error_variance', 'mean_pwm_change']:
                            vs = [m[k] for m in ml]
                            mv = sum(vs) / len(vs)
                            sv = math.sqrt(sum((v-mv)**2 for v in vs)/max(len(vs)-1,1))
                            avg[k+'_std'] = round(sv, 4)
                    else:
                        avg = {}

                    scenario_data[key] = {
                        'controller': controller_type,
                        'sensor': sensor_mode,
                        'scenario': scenario_name,
                        'avg_metrics': avg,
                        'n_runs': len(runs),
                    }

            all_results[scenario_name] = scenario_data

        return all_results

    def analyze(self, results):
        """分析: 离散 vs 连续, baseline vs adaptive"""
        comparisons = []

        for scenario, data in results.items():
            keys = list(data.keys())
            # 找对应的 4 组
            for ctrl in ['baseline', 'adaptive']:
                dk = [k for k in keys if data[k]['controller'] == ctrl
                      and data[k]['sensor'] == 'discrete']
                ck = [k for k in keys if data[k]['controller'] == ctrl
                      and data[k]['sensor'] == 'continuous']
                if dk and ck:
                    d = data[dk[0]]['avg_metrics']
                    c = data[ck[0]]['avg_metrics']
                    if d and c:
                        comparisons.append({
                            'scenario': scenario,
                            'controller': ctrl,
                            'discrete_mean_error': d.get('mean_error', 0),
                            'continuous_mean_error': c.get('mean_error', 0),
                            'error_improvement_pct': round(
                                (d.get('mean_error',1) - c.get('mean_error',1))
                                / max(d.get('mean_error',1), 0.001) * 100, 2),
                            'discrete_osc': d.get('osc_freq', 0),
                            'continuous_osc': c.get('osc_freq', 0),
                            'discrete_pwm': d.get('mean_pwm_change', 0),
                            'continuous_pwm': c.get('mean_pwm_change', 0),
                            'discrete_pid_smooth': d.get('mean_pid_change', 0),
                            'continuous_pid_smooth': c.get('mean_pid_change', 0),
                        })

        # Baseline vs Adaptive (continuous mode)
        ctrl_compare = []
        for scenario, data in results.items():
            bk = [k for k in data if data[k]['controller'] == 'baseline'
                  and data[k]['sensor'] == 'continuous']
            ak = [k for k in data if data[k]['controller'] == 'adaptive'
                  and data[k]['sensor'] == 'continuous']
            if bk and ak:
                b = data[bk[0]]['avg_metrics']
                a = data[ak[0]]['avg_metrics']
                if b and a:
                    ctrl_compare.append({
                        'scenario': scenario,
                        'baseline_error': b.get('mean_error', 0),
                        'adaptive_error': a.get('mean_error', 0),
                        'improvement_pct': round(
                            (b.get('mean_error',1) - a.get('mean_error',1))
                            / max(b.get('mean_error',1), 0.001) * 100, 2),
                        'baseline_osc': b.get('osc_freq', 0),
                        'adaptive_osc': a.get('osc_freq', 0),
                    })

        return {
            'sensor_comparison': comparisons,
            'controller_comparison': ctrl_compare,
        }

    def generate_summary(self, results, analysis):
        """生成 summary.txt 内容"""
        lines = []
        lines.append("=" * 60)
        lines.append("  Continuous Sensor System Evaluation Report")
        lines.append("=" * 60)
        lines.append("")

        # 1. Sensor comparison
        lines.append("## 1. Discrete vs Continuous Sensor")
        lines.append("")
        sc = analysis.get('sensor_comparison', [])
        for c in sc:
            lines.append("  [{}] {}:".format(c['scenario'], c['controller']))
            lines.append("    Error: discrete={:.3f} continuous={:.3f} (improvement: {:+.1f}%)".format(
                c['discrete_mean_error'], c['continuous_mean_error'],
                c['error_improvement_pct']))
            lines.append("    Osc:   discrete={:.3f} continuous={:.3f}".format(
                c['discrete_osc'], c['continuous_osc']))
            lines.append("    PWM:   discrete={:.1f} continuous={:.1f}".format(
                c['discrete_pwm'], c['continuous_pwm']))
            lines.append("")

        # 2. Controller comparison (continuous mode)
        lines.append("## 2. Baseline vs Adaptive (Continuous Sensor)")
        lines.append("")
        cc = analysis.get('controller_comparison', [])
        for c in cc:
            lines.append("  [{}]:".format(c['scenario']))
            lines.append("    Error: baseline={:.3f} adaptive={:.3f} (improvement: {:+.1f}%)".format(
                c['baseline_error'], c['adaptive_error'], c['improvement_pct']))
            lines.append("    Osc:   baseline={:.3f} adaptive={:.3f}".format(
                c['baseline_osc'], c['adaptive_osc']))
            lines.append("")

        # 3. Key findings
        lines.append("## 3. Key Findings")
        lines.append("")

        if sc:
            avg_improve = sum(c['error_improvement_pct'] for c in sc) / len(sc)
            better_count = sum(1 for c in sc if c['error_improvement_pct'] > 0)
            lines.append("  - Continuous sensor improves error by {:.1f}% on average".format(avg_improve))
            lines.append("  - Better in {}/{} scenarios".format(better_count, len(sc)))

        if cc:
            avg_ctrl = sum(c['improvement_pct'] for c in cc) / len(cc)
            lines.append("  - Adaptive PID improves by {:.1f}% on average (continuous mode)".format(avg_ctrl))

        lines.append("")
        lines.append("## 4. Conclusions")
        lines.append("")
        lines.append("  1. Continuous observation: {} advantage".format(
            "YES - shows" if sc and sum(c['error_improvement_pct'] for c in sc) > 0 else "MARGINAL"))
        lines.append("  2. Observation bottleneck: {}".format(
            "RESOLVED" if sc and max(c['error_improvement_pct'] for c in sc) > 5 else "STILL PRESENT"))
        lines.append("  3. Adaptive PID benefit: {}".format(
            "EMERGING" if cc and max(c['improvement_pct'] for c in cc) > 1 else "MINIMAL"))
        lines.append("  4. RL readiness: {}".format(
            "YES - continuous state space" if sc else "NO"))
        lines.append("  5. Next priority: {}".format(
            "Tune sigma / sensor resolution" if sc and max(c['error_improvement_pct'] for c in sc) < 5
            else "Proceed with adaptive PID refinement"))
        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)

    def save_all(self, results, analysis, summary_text,
                 report_path, summary_path):
        """保存所有输出"""
        os.makedirs(os.path.dirname(report_path) or '.', exist_ok=True)

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({'results': results, 'analysis': analysis},
                      f, indent=2, ensure_ascii=False, default=str)

        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(summary_text)

        print("[Test] Saved: {}".format(report_path))
        print("[Test] Saved: {}".format(summary_path))