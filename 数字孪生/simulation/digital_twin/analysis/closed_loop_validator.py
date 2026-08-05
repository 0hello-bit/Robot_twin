# -*- coding: utf-8 -*-
"""
closed_loop_validator.py - 闭环验证系统

职责:
    1. 回放真实 PWM 数据到仿真器
    2. 同步仿真轨迹与真实轨迹
    3. 自动对比误差
    4. 输出 mismatch 分析报告

使用方式:
    validator = ClosedLoopValidator(sim_engine)
    validator.load_real_data('data/hil_session.json')
    result = validator.validate()
    validator.save_report('data/validation_report.json')
"""

import json
import math
import os
import time

from analysis.model_error import ModelErrorEvaluator


class ClosedLoopValidator:
    """
    闭环验证器。

    工作流程:
        1. 加载真实遥测数据 (含 PWM 指令)
        2. 将 PWM 指令输入仿真器
        3. 仿真器产生虚拟轨迹
        4. 对比虚拟轨迹 vs 真实轨迹
        5. 输出误差报告
    """

    def __init__(self):
        self.real_data = []
        self.sim_trajectory = []
        self.validation_result = None

    def load_real_data(self, filepath):
        """
        加载真实遥测数据。

        支持格式:
            - DataLogger JSON
            - ExperimentLogger JSON
            - 原始 telemetry 列表
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        # 兼容多种格式
        if isinstance(raw, list):
            self.real_data = raw
        elif isinstance(raw, dict):
            self.real_data = raw.get('data', [])
        else:
            self.real_data = []

        print("[Validator] Loaded {} records from {}".format(
            len(self.real_data), filepath))

    def load_real_data_direct(self, records):
        """直接加载数据列表"""
        self.real_data = records

    def validate_with_sim(self, sim_class, sim_config=None):
        """
        使用仿真器执行闭环验证。

        参数:
            sim_class:   仿真器类 (可实例化)
            sim_config:  仿真配置参数

        返回:
            dict: 验证结果
        """
        if not self.real_data:
            return {'error': 'no real data loaded'}

        # 实例化仿真器
        sim = sim_class() if sim_config is None else sim_class(**sim_config)

        self.sim_trajectory = []

        for i, rec in enumerate(self.real_data):
            # 提取 PWM 指令
            left_pwm = rec.get('left_pwm', 0)
            right_pwm = rec.get('right_pwm', 0)

            # 归一化到 [-1, 1]
            left_n = left_pwm / 999.0
            right_n = right_pwm / 999.0

            # 输入到仿真器
            sim.set_motor_command(left_n, right_n)
            sim.step()

            # 记录仿真状态
            state = sim.get_state()
            state['t'] = rec.get('t', i * 0.03)
            self.sim_trajectory.append(state)

        # 对比
        evaluator = ModelErrorEvaluator()
        evaluator.set_real_data(self.real_data)
        evaluator.set_sim_data(self.sim_trajectory)
        result = evaluator.evaluate()

        # 附加验证信息
        result['method'] = 'closed_loop'
        result['real_records'] = len(self.real_data)
        result['sim_records'] = len(self.sim_trajectory)

        self.validation_result = result
        return result

    def validate_open_loop(self, motor_model=None, steering_model=None,
                           latency_model=None):
        """
        开环验证: 不使用仿真器, 直接用模型预测。

        适用于没有完整仿真环境时的快速验证。

        参数:
            motor_model:    PWM→速度模型
            steering_model: 转向模型
            latency_model:  延迟模型

        返回:
            dict: 验证结果
        """
        if not self.real_data:
            return {'error': 'no real data loaded'}

        self.sim_trajectory = []

        # 简单运动学模拟
        x, y, angle = 0.0, 0.0, 0.0
        vx, vy, va = 0.0, 0.0, 0.0

        for i, rec in enumerate(self.real_data):
            dt = 0.03  # 30ms 控制周期
            left_pwm = rec.get('left_pwm', 0)
            right_pwm = rec.get('right_pwm', 0)

            # PWM → 速度
            if motor_model:
                left_v = motor_model.predict(left_pwm)
                right_v = motor_model.predict(right_pwm)
            else:
                left_v = left_pwm / 999.0
                right_v = right_pwm / 999.0

            # 差速 → 角速度
            delta = left_v - right_v
            if steering_model:
                if hasattr(steering_model, 'predict'):
                    omega = steering_model.predict(delta, i * dt, dt)
                elif hasattr(steering_model, 'update'):
                    omega = steering_model.update(delta, dt)
                else:
                    omega = delta * 180.0
            else:
                omega = delta * 180.0

            # 延迟
            if latency_model:
                delay_steps = int(latency_model.total_latency_ms / (dt * 1000))
                if i >= delay_steps:
                    left_v_delayed = self.real_data[i - delay_steps].get('left_pwm', 0) / 999.0
                    right_v_delayed = self.real_data[i - delay_steps].get('right_pwm', 0) / 999.0
                else:
                    left_v_delayed = left_v
                    right_v_delayed = right_v
            else:
                left_v_delayed = left_v
                right_v_delayed = right_v

            # 运动学
            avg_v = (left_v_delayed + right_v_delayed) / 2.0
            rad = math.radians(angle)
            x += avg_v * math.cos(rad) * dt * 100
            y += avg_v * math.sin(rad) * dt * 100
            angle += omega * dt
            angle %= 360

            self.sim_trajectory.append({
                't': rec.get('t', i * dt),
                'car_x': x, 'car_y': y, 'car_angle': angle,
                'left_pwm': left_pwm, 'right_pwm': right_pwm,
                'sensors': [1, 1, 1, 1],
                'error': rec.get('error', 0),
            })

        # 对比
        evaluator = ModelErrorEvaluator()
        evaluator.set_real_data(self.real_data)
        evaluator.set_sim_data(self.sim_trajectory)
        result = evaluator.evaluate()
        result['method'] = 'open_loop'

        self.validation_result = result
        return result

    def get_mismatch_heatmap(self):
        """
        生成 mismatch 热力图数据。

        返回:
            list[dict]: 每个时间点的误差值
        """
        if not self.real_data or not self.sim_trajectory:
            return []

        heatmap = []
        for r, s in zip(self.real_data, self.sim_trajectory):
            rx = r.get('car_x', 0)
            ry = r.get('car_y', 0)
            sx = s.get('car_x', 0)
            sy = s.get('car_y', 0)
            err = math.sqrt((rx - sx)**2 + (ry - sy)**2)

            heatmap.append({
                't': r.get('t', 0),
                'x': rx, 'y': ry,
                'error': round(err, 3),
                'real_error': r.get('error', 0),
                'sim_error': s.get('error', 0),
            })

        return heatmap

    def save_report(self, filepath):
        """保存验证报告"""
        if self.validation_result is None:
            return

        report = {
            'validation': self.validation_result,
            'heatmap': self.get_mismatch_heatmap()[:100],  # 前100点
            'timestamp': time.time(),
        }

        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print("[Validator] Report saved: {}".format(filepath))

    def print_summary(self):
        """打印验证摘要"""
        if self.validation_result is None:
            print("No validation result")
            return

        r = self.validation_result
        print("\n" + "=" * 55)
        print("  Closed-Loop Validation Report")
        print("=" * 55)
        print("  Trust Score:   {:.1f} / 100".format(r.get('trust_score', 0)))
        print("  Method:        {}".format(r.get('method', '?')))
        print("  Samples:       {}".format(r.get('n_samples', 0)))

        traj = r.get('trajectory', {})
        print("\n  Trajectory:")
        print("    RMSE:  {:.2f} px".format(traj.get('rmse', 0)))
        print("    MAE:   {:.2f} px".format(traj.get('mae', 0)))
        print("    Max:   {:.2f} px".format(traj.get('max', 0)))

        sensor = r.get('sensor_match', {})
        print("\n  Sensor Match:  {:.1f}%".format(sensor.get('match_pct', 0)))

        pid = r.get('pid_trend', {})
        print("  PID Corr:      {:.4f}".format(pid.get('correlation', 0)))
        print("  Dir Match:     {:.1f}%".format(
            pid.get('direction_match_pct', 0)))

        turn = r.get('turning', {})
        print("  Angular RMSE:  {:.2f}".format(turn.get('angular_rmse', 0)))
        print("=" * 55)