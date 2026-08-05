# -*- coding: utf-8 -*-
"""
curve_plotter.py - Training Curve Plotter

Generates training visualization plots:
    1. Reward curve (with moving average)
    2. Loss curve
    3. Success rate over time
    4. Combined dashboard

Based on gym-pybullet-drones training monitoring pattern.

Usage:
    plotter = CurvePlotter('logs/')
    plotter.add_episode(reward=150.2, loss=0.05, success=True)
    plotter.plot_all()
"""

import os
import json
import time


class CurvePlotter:
    """
    Training curve visualization.

    Collects training metrics and generates plots.
    Falls back to text-based output if matplotlib unavailable.
    """

    def __init__(self, log_dir, window_size=50):
        self.log_dir = log_dir
        self.window_size = window_size
        self.episodes = []
        self._csv_path = os.path.join(log_dir, 'training_curves.csv')

        os.makedirs(log_dir, exist_ok=True)

    def add_episode(self, reward, loss=None, success=None,
                    steps=0, level=1, extra=None):
        """Record one episode's metrics."""
        entry = {
            'episode': len(self.episodes),
            'reward': reward,
            'loss': loss,
            'success': success,
            'steps': steps,
            'level': level,
            'timestamp': time.time(),
        }
        if extra:
            entry.update(extra)
        self.episodes.append(entry)

        # Append to CSV
        write_header = not os.path.exists(self._csv_path)
        with open(self._csv_path, 'a', encoding='utf-8') as f:
            if write_header:
                f.write('episode,reward,loss,success,steps,level\n')
            f.write('{},{},{},{},{},{}\n'.format(
                entry['episode'],
                round(reward, 4),
                loss if loss is not None else '',
                success if success is not None else '',
                steps, level))

    def _moving_average(self, data, window):
        """Compute moving average."""
        if len(data) < window:
            return data
        result = []
        for i in range(len(data)):
            start = max(0, i - window + 1)
            result.append(sum(data[start:i+1]) / (i - start + 1))
        return result

    def plot_all(self, save_path=None):
        """Generate all plots.

        Args:
            save_path: Path to save the combined plot.
                      If None, uses log_dir/training_curves.png
        """
        if not self.episodes:
            print("[CurvePlotter] No episodes to plot")
            return

        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt

            fig, axes = plt.subplots(2, 2, figsize=(14, 10))
            fig.suptitle('Training Dashboard', fontsize=14)

            rewards = [e['reward'] for e in self.episodes]
            episodes = [e['episode'] for e in self.episodes]

            # 1. Reward curve
            ax = axes[0][0]
            ax.plot(episodes, rewards, 'b-', alpha=0.3, label='Raw')
            if len(rewards) >= self.window_size:
                ma = self._moving_average(rewards, self.window_size)
                ax.plot(episodes, ma, 'r-', linewidth=2,
                        label='MA(%d)' % self.window_size)
            ax.set_title('Reward Curve')
            ax.set_xlabel('Episode')
            ax.set_ylabel('Reward')
            ax.legend()
            ax.grid(True, alpha=0.3)

            # 2. Success rate
            ax = axes[0][1]
            successes = [e.get('success', False) for e in self.episodes]
            if len(successes) >= self.window_size:
                success_rate = self._moving_average(
                    [1.0 if s else 0.0 for s in successes], self.window_size)
                ax.plot(episodes, success_rate, 'g-', linewidth=2)
            ax.set_title('Success Rate')
            ax.set_xlabel('Episode')
            ax.set_ylabel('Rate')
            ax.set_ylim(-0.05, 1.05)
            ax.grid(True, alpha=0.3)

            # 3. Loss curve
            ax = axes[1][0]
            losses = [e.get('loss') for e in self.episodes]
            valid_losses = [(e['episode'], l) for e, l in zip(self.episodes, losses)
                           if l is not None]
            if valid_losses:
                lx, ly = zip(*valid_losses)
                ax.plot(lx, ly, 'm-', alpha=0.5)
            ax.set_title('Loss Curve')
            ax.set_xlabel('Episode')
            ax.set_ylabel('Loss')
            ax.grid(True, alpha=0.3)

            # 4. Level distribution
            ax = axes[1][1]
            levels = [e.get('level', 1) for e in self.episodes]
            if levels:
                level_counts = {}
                for l in levels:
                    level_counts[l] = level_counts.get(l, 0) + 1
                bars = ax.bar(
                    [str(k) for k in sorted(level_counts.keys())],
                    [level_counts[k] for k in sorted(level_counts.keys())],
                    color='steelblue')
            ax.set_title('Level Distribution')
            ax.set_xlabel('Level')
            ax.set_ylabel('Episodes')
            ax.grid(True, alpha=0.3)

            plt.tight_layout()

            if save_path is None:
                save_path = os.path.join(self.log_dir, 'training_curves.png')
            fig.savefig(save_path, dpi=100, bbox_inches='tight')
            plt.close(fig)
            print("[CurvePlotter] Saved: %s" % save_path)

        except ImportError:
            print("[CurvePlotter] matplotlib not available, using text output")
            self._print_summary()

    def _print_summary(self):
        """Text-based summary when matplotlib unavailable."""
        if not self.episodes:
            return
        rewards = [e['reward'] for e in self.episodes]
        print()
        print("=" * 50)
        print("  Training Summary")
        print("=" * 50)
        print("  Episodes: %d" % len(rewards))
        print("  Avg Reward: %.2f" % (sum(rewards) / len(rewards)))
        print("  Best Reward: %.2f" % max(rewards))
        print("  Last 10 Avg: %.2f" % (sum(rewards[-10:]) / max(len(rewards[-10:]), 1)))
        print("=" * 50)

    def export_json(self, filepath=None):
        """Export all data as JSON."""
        if filepath is None:
            filepath = os.path.join(self.log_dir, 'training_data.json')
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.episodes, f, indent=2, ensure_ascii=False)
        print("[CurvePlotter] Data exported: %s" % filepath)

    def get_stats(self):
        """Get training statistics."""
        if not self.episodes:
            return {}
        rewards = [e['reward'] for e in self.episodes]
        successes = [e.get('success', False) for e in self.episodes]
        return {
            'total_episodes': len(rewards),
            'avg_reward': round(sum(rewards) / len(rewards), 2),
            'best_reward': round(max(rewards), 2),
            'last_10_avg': round(sum(rewards[-10:]) / max(len(rewards[-10:]), 1), 2),
            'success_rate': round(sum(1 for s in successes if s) / len(successes), 2),
        }
