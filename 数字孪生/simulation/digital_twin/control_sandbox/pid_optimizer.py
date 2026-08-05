# -*- coding: utf-8 -*-
"""
pid_optimizer.py - PID 参数安全优化器 (v2)

v2 升级:
    - 安全约束: 稳定性 / 超调 / 现实可行性
    - 基于已校准模型的参数搜索
    - 约束优化: 不只找最优, 还要找"安全最优"
"""

import random
import time
from control_sandbox.sandbox_runner import SandboxRunner


class PidOptimizer:
    """
    PID 参数安全优化器 (v2)。

    安全约束:
        1. 稳定性: score >= 60 (Grade B+)
        2. 超调: max_error < 6 (不丢线)
        3. 丢线率: lost_pct < 5%
        4. 收敛: converging == True
    """

    def __init__(self, algorithm='simple', model_dir=None):
        self.runner = SandboxRunner(algorithm=algorithm, model_dir=model_dir)
        self.results = []
        self.safe_results = []  # 满足安全约束的结果

    def grid_search(self, kp_range=(1, 20), kd_range=(0, 10),
                    ki_range=(0, 0), step_kp=2, step_kd=1,
                    max_ticks=2000, dt=0.03, safety_only=True):
        """
        安全网格搜索。

        参数:
            safety_only: True=只返回满足安全约束的结果

        返回:
            dict: best_safe, best_overall, all_results
        """
        kps = list(range(kp_range[0], kp_range[1] + 1, step_kp))
        kds = list(range(kd_range[0], kd_range[1] + 1, step_kd))
        kis = list(range(ki_range[0], ki_range[1] + 1, max(1, ki_range[1]))) or [0]

        total = len(kps) * len(kds) * len(kis)
        print("[Optimizer] Grid search: {} combos".format(total))

        all_results = []
        best_overall = {'score': -1}
        best_safe = {'score': -1}

        idx = 0
        for kp in kps:
            for kd in kds:
                for ki in kis:
                    idx += 1
                    params = {'kp': kp, 'ki': ki, 'kd': kd}
                    result = self.runner.run(max_ticks=max_ticks, dt=dt, **params)
                    f = result['fitness']

                    entry = {
                        'params': params,
                        'score': f['score'],
                        'grade': f['grade'],
                        'metrics': f['metrics'],
                        'is_safe': self._check_safety(f),
                    }
                    all_results.append(entry)

                    if f['score'] > best_overall.get('score', -1):
                        best_overall = entry

                    if entry['is_safe'] and f['score'] > best_safe.get('score', -1):
                        best_safe = entry

                    if idx % 20 == 0:
                        print("  [{}/{}] best={} ({:.1f}) safe={} ({:.1f})".format(
                            idx, total,
                            best_overall['grade'], best_overall['score'],
                            best_safe.get('grade', '-'), best_safe.get('score', -1)))

        self.results = all_results
        self.safe_results = [r for r in all_results if r['is_safe']]

        return {
            'best_safe': best_safe if best_safe['score'] >= 0 else None,
            'best_overall': best_overall,
            'total_tested': total,
            'n_safe': len(self.safe_results),
            'all_results': sorted(all_results, key=lambda x: -x['score']),
        }

    def random_search(self, n_trials=50, max_ticks=2000, dt=0.03,
                      kp_range=(1, 20), kd_range=(0, 10), ki_range=(0, 2)):
        """安全随机搜索"""
        print("[Optimizer] Random search: {} trials".format(n_trials))

        all_results = []
        best_safe = {'score': -1}

        for i in range(n_trials):
            kp = random.randint(kp_range[0], kp_range[1])
            kd = random.randint(kd_range[0], kd_range[1])
            ki = random.randint(ki_range[0], ki_range[1])

            params = {'kp': kp, 'ki': ki, 'kd': kd}
            result = self.runner.run(max_ticks=max_ticks, dt=dt, **params)
            f = result['fitness']

            entry = {
                'params': params,
                'score': f['score'],
                'grade': f['grade'],
                'metrics': f['metrics'],
                'is_safe': self._check_safety(f),
            }
            all_results.append(entry)

            if entry['is_safe'] and f['score'] > best_safe.get('score', -1):
                best_safe = entry

            if (i + 1) % 10 == 0:
                print("  [{}/{}] safe={} ({:.1f})".format(
                    i + 1, n_trials,
                    best_safe.get('grade', '-'), best_safe.get('score', -1)))

        self.safe_results = [r for r in all_results if r['is_safe']]

        return {
            'best_safe': best_safe if best_safe['score'] >= 0 else None,
            'total_tested': n_trials,
            'n_safe': len(self.safe_results),
            'all_results': sorted(all_results, key=lambda x: -x['score']),
        }

    def quick_evaluate(self, kp, ki=0, kd=0, max_ticks=2000):
        """快速评估单组参数"""
        result = self.runner.run(max_ticks=max_ticks, kp=kp, ki=ki, kd=kd)
        f = result['fitness']
        return {
            'score': f['score'],
            'grade': f['grade'],
            'is_safe': self._check_safety(f),
            'metrics': f['metrics'],
        }

    def _check_safety(self, fitness):
        """
        安全约束检查。

        必须同时满足:
            1. score >= 60 (Grade B+)
            2. lost_pct < 5%
            3. diverging == False
            4. max_error < 8
        """
        m = fitness.get('metrics', {})
        return (fitness.get('score', 0) >= 60 and
                m.get('lost_pct', 100) < 5 and
                not m.get('diverging', True) and
                m.get('max_error', 999) < 8)

    def get_recommendation(self):
        """获取推荐参数 (安全约束下的最优)"""
        if self.safe_results:
            best = max(self.safe_results, key=lambda x: x['score'])
            return {
                'params': best['params'],
                'score': best['score'],
                'grade': best['grade'],
                'confidence': 'SAFE',
            }
        elif self.results:
            best = max(self.results, key=lambda x: x['score'])
            return {
                'params': best['params'],
                'score': best['score'],
                'grade': best['grade'],
                'confidence': 'UNSAFE',
            }
        return None