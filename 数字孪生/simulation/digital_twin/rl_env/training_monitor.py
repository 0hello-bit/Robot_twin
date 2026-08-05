# -*- coding: utf-8 -*-
"""
training_monitor.py - 训练监控系统

跟踪奖励曲线、丢线率、完成率等指标。
输出实验报告。
"""

import json
import os
import time
import math


class TrainingMonitor:
    """
    训练过程监控器。

    使用:
        monitor = TrainingMonitor()
        for episode in range(1000):
            # ... run episode ...
            monitor.record_episode(reward, steps, info)
        monitor.generate_report('report.json')
    """

    def __init__(self, window_size=50):
        self.window_size = window_size
        self.episodes = []
        self._start_time = time.time()

    def record_episode(self, total_reward, steps, info=None):
        """记录一个 episode"""
        record = {
            'episode': len(self.episodes),
            'reward': round(total_reward, 4),
            'steps': steps,
            'timestamp': time.time(),
        }
        if info:
            record['lost_count'] = info.get('lost_count', 0)
            record['avg_speed'] = info.get('avg_speed', 0)
            record['completed'] = info.get('completed', False)
        self.episodes.append(record)

    def get_stats(self):
        """获取当前统计"""
        if not self.episodes:
            return {}

        rewards = [e['reward'] for e in self.episodes]
        steps = [e['steps'] for e in self.episodes]
        n = len(rewards)

        # 滑动窗口均值
        window = min(self.window_size, n)
        recent_rewards = rewards[-window:]
        avg_reward = sum(recent_rewards) / len(recent_rewards)
        avg_steps = sum(steps[-window:]) / len(steps[-window:])

        # 完成率
        completed = sum(1 for e in self.episodes[-window:]
                       if e.get('completed', False))
        completion_rate = completed / max(window, 1)

        # 丢线率
        lost_episodes = sum(1 for e in self.episodes[-window:]
                           if e.get('lost_count', 0) > 0)
        loss_rate = lost_episodes / max(window, 1)

        return {
            'total_episodes': n,
            'avg_reward': round(avg_reward, 4),
            'best_reward': round(max(rewards), 4),
            'worst_reward': round(min(rewards), 4),
            'avg_steps': round(avg_steps, 1),
            'completion_rate': round(completion_rate, 4),
            'loss_rate': round(loss_rate, 4),
            'elapsed_s': round(time.time() - self._start_time, 1),
        }

    def generate_report(self, filepath):
        """生成实验报告"""
        stats = self.get_stats()

        report = {
            'stats': stats,
            'episodes': self.episodes[-100:],  # 最近 100 条
            'config': {
                'window_size': self.window_size,
            },
        }

        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print("[Monitor] Report saved:", filepath)

    def print_summary(self):
        """打印摘要"""
        stats = self.get_stats()
        print()
        print("=" * 50)
        print("  Training Monitor Summary")
        print("=" * 50)
        print("  Episodes: {}".format(stats.get('total_episodes', 0)))
        print("  Avg Reward: {:.2f}".format(stats.get('avg_reward', 0)))
        print("  Best: {:.2f}".format(stats.get('best_reward', 0)))
        print("  Avg Steps: {:.0f}".format(stats.get('avg_steps', 0)))
        print("  Completion: {:.1%}".format(stats.get('completion_rate', 0)))
        print("  Loss Rate: {:.1%}".format(stats.get('loss_rate', 0)))
        print("  Time: {:.0f}s".format(stats.get('elapsed_s', 0)))
        print("=" * 50)