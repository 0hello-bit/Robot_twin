# -*- coding: utf-8 -*-
"""
domain_randomization.py - 域随机化

随机化仿真参数, 提高 Sim2Real 能力。
"""

import random
import copy


class DomainRandomizer:
    """
    域随机化器。

    每次 reset() 时随机化 PlantModel 参数,
    使 RL 策略对参数变化具有鲁棒性。

    使用:
        dr = DomainRandomizer()
        dr.randomize(plant)
    """

    # 参数范围 (min, max) 相对于默认值的比例
    PARAM_RANGES = {
        'motor_gain':           (0.7, 1.3),
        'motor_offset':         (-0.05, 0.05),
        'steering_K':           (0.8, 1.2),
        'steering_tau':         (0.7, 1.3),
        'velocity_damping':     (0.9, 1.1),
        'angular_damping':      (0.9, 1.1),
        'sensor_noise_prob':    (0.0, 0.1),
        'motor_noise_std':      (0.0, 0.08),
        'position_noise_std':   (0.0, 2.0),
    }

    def __init__(self, enabled=True, seed=None):
        self.enabled = enabled
        self._rng = random.Random(seed)
        self._original_params = None

    def capture_original(self, plant):
        """保存 PlantModel 原始参数"""
        self._original_params = plant.get_params()

    def randomize(self, plant):
        """
        随机化 PlantModel 参数。

        参数:
            plant: PlantModel 实例
        """
        if not self.enabled:
            return

        if self._original_params is None:
            self.capture_original(plant)

        params = copy.deepcopy(self._original_params)

        for key, (lo_ratio, hi_ratio) in self.PARAM_RANGES.items():
            if key in params:
                original = params[key]
                factor = self._rng.uniform(lo_ratio, hi_ratio)
                params[key] = original * factor

        plant.set_params(params)

    def restore(self, plant):
        """恢复原始参数"""
        if self._original_params is not None:
            plant.set_params(self._original_params)

    def get_randomized_info(self):
        """获取当前随机化信息"""
        return {
            'enabled': self.enabled,
            'param_ranges': self.PARAM_RANGES,
        }