# -*- coding: utf-8 -*-
"""
sandbox_runner.py - 控制参数沙盒运行器

职责:
    1. 接收 PID 参数
    2. 运行闭环仿真 (控制器 + 物理模型)
    3. 输出完整轨迹 + 评分

数据流:
    PID参数 → ControllerEmulator → PlantModel → 轨迹 → 评分
"""

import math
import json
import os
import time

from control_sandbox.controller_emulator import SimpleController, AdvancedController
from control_sandbox.plant_model import PlantModel
from analysis.control_fitness import ControlFitness


class SandboxRunner:
    """
    控制参数沙盒运行器。

    使用方式:
        runner = SandboxRunner()
        result = runner.run(kp=8, kd=3, max_ticks=3000)
        print(result['fitness']['grade'])
    """

    def __init__(self, algorithm='simple', model_dir=None):
        """
        参数:
            algorithm: 'simple' 或 'advanced'
            model_dir: calibration/models/ 路径
        """
        self.algorithm = algorithm
        self.model_dir = model_dir
        self.plant = PlantModel(model_dir)
        self.fitness = ControlFitness()

    def run(self, max_ticks=3000, dt=0.03, noise=False, **pid_params):
        """
        运行闭环仿真。

        参数:
            max_ticks: 最大仿真步数
            dt:        时间步长 (s)
            noise:     是否启用噪声
            **pid_params: PID 参数

        返回:
            dict: {
                'trajectory': [...],
                'fitness': {...},
                'statistics': {...},
            }
        """
        # ── 创建控制器 ──
        if self.algorithm == 'simple':
            ctrl = SimpleController()
        else:
            ctrl = AdvancedController(pid_params)

        # ── 重置物理模型 ──
        self.plant.reset()
        self.plant.noise_enabled = noise

        # ── 运行仿真 ──
        trajectory = []
        sensor_history = []
        motor_history = []

        for tick in range(max_ticks):
            # 读取传感器
            sensors = self.plant.read_sensors()
            s0, s1, s2, s3 = sensors

            # 控制器输出
            left_pwm, right_pwm = ctrl.step(s0, s1, s2, s3)

            # 物理模型更新
            new_sensors = self.plant.step(left_pwm, right_pwm, dt)

            # 记录
            state = self.plant.get_state_dict()
            state['t'] = tick * dt
            state['tick'] = tick
            state['sensors'] = new_sensors
            state['left_pwm'] = left_pwm
            state['right_pwm'] = right_pwm
            state['black_count'] = sum(1 for s in new_sensors if s == 0)

            trajectory.append(state)
            sensor_history.append(new_sensors)
            motor_history.append((left_pwm, right_pwm))

        # ── 评分 ──
        fitness_result = self.fitness.evaluate(
            trajectory, sensor_history, motor_history)

        return {
            'trajectory': trajectory,
            'fitness': fitness_result,
            'algorithm': self.algorithm,
            'pid_params': pid_params,
            'max_ticks': max_ticks,
            'dt': dt,
        }

    def run_comparison(self, param_sets, max_ticks=3000, dt=0.03):
        """
        批量对比多组 PID 参数。

        参数:
            param_sets: list of dict, 每个 dict 是一组参数

        返回:
            list of dict: 每组参数的仿真结果
        """
        results = []
        for i, params in enumerate(param_sets):
            result = self.run(max_ticks=max_ticks, dt=dt, **params)
            result['param_index'] = i
            results.append(result)
            print("  [{}/{}] grade={} score={:.1f}".format(
                i + 1, len(param_sets),
                result['fitness']['grade'],
                result['fitness']['score']))
        return results

    def save_result(self, result, filepath):
        """保存仿真结果"""
        # 不保存完整轨迹 (太大), 只保存统计
        save_data = {
            'algorithm': result['algorithm'],
            'pid_params': result['pid_params'],
            'fitness': result['fitness'],
            'max_ticks': result['max_ticks'],
            'dt': result['dt'],
            'trajectory_length': len(result['trajectory']),
            'timestamp': time.time(),
        }
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        print("[Sandbox] Saved: {}".format(filepath))