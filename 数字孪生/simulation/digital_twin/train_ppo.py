# -*- coding: utf-8 -*-
"""
train_ppo.py - PPO 训练入口

功能:
    1. 自动注册 CarEnv
    2. PPO 训练闭环
    3. Curriculum learning (自动升降级)
    4. Domain randomization
    5. 每 10k steps 保存模型
    6. 训练日志输出 (CSV)
    7. 可视化测试模式

使用:
    python train_ppo.py                  # 训练
    python train_ppo.py --test           # 可视化测试
    python train_ppo.py --total-steps 500000
"""

import os
import sys
import csv
import time
import argparse
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rl_env.car_env import CarEnv
from rl_env.curriculum import CurriculumManager, STAGES
from rl_env.domain_randomization import DomainRandomizer

# ── 路径配置 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, 'models')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')


# ══════════════════════════════════════════════════════════════
#  Curriculum PPO Trainer
# ══════════════════════════════════════════════════════════════

class CurriculumPPOTrainer:
    """
    带课程学习的 PPO 训练器。

    自动根据 episode reward 升降级赛道难度。
    """

    def __init__(self, total_steps=100000, seed=42,
                 ppo_n_steps=2048, batch_size=64, n_epochs=10,
                 eval_episodes=10, learning_rate=3e-4, ent_coef=0.01):
        self.total_steps = int(total_steps)
        if self.total_steps <= 0:
            raise ValueError("total_steps must be positive")
        self.seed = seed
        self.ppo_n_steps = max(2, int(ppo_n_steps))
        self.batch_size = max(2, min(int(batch_size), self.ppo_n_steps))
        self.n_epochs = max(1, int(n_epochs))
        self.eval_episodes = max(1, int(eval_episodes))
        self.learning_rate = learning_rate
        self.ent_coef = ent_coef

        self.curriculum = CurriculumManager()
        self.monitor = TrainingMonitor()

        # 课程配置
        self._upgrade_threshold = 300.0
        self._downgrade_threshold = -50.0
        self._level_window = 30

        # 日志
        self._csv_path = os.path.join(LOGS_DIR, 'rl_training.csv')
        self._csv_rows = []

    def train(self):
        """主训练循环"""
        from stable_baselines3 import PPO

        os.makedirs(MODELS_DIR, exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)

        print("=" * 60)
        print("  PPO Training - STM32 Car RL")
        print("=" * 60)
        print("  Total steps: {}".format(self.total_steps))
        print("  Seed: {}".format(self.seed))
        print("  PPO n_steps/batch/n_epochs: {}/{}/{}".format(
            self.ppo_n_steps, self.batch_size, self.n_epochs))
        print("  Eval episodes: {}".format(self.eval_episodes))
        print("  Models: {}".format(MODELS_DIR))
        print("  Logs: {}".format(LOGS_DIR))
        print("=" * 60)

        total_trained = 0
        level = 1
        level_rewards = []

        while total_trained < self.total_steps:
            stage = self.curriculum.get_current_stage()
            remaining = self.total_steps - total_trained
            steps_this_level = min(remaining, max(10000, self.total_steps // 10))

            print()
            print("--- Level {} | Stage: {} | Steps: {} ---".format(
                level, stage.name, steps_this_level))

            # 创建环境
            env = CarEnv(
                track_type=stage.track_type,
                action_mode='discrete',
                max_steps=stage.max_steps,
                noise=stage.noise,
                speed_factor=stage.speed_factor,
                seed=self.seed + level,
            )

            # 创建 PPO 模型
            model = PPO(
                'MlpPolicy', env,
                device='cpu',
                verbose=1,
                batch_size=self.batch_size,
                n_steps=self.ppo_n_steps,
                gamma=0.99,
                learning_rate=self.learning_rate,
                n_epochs=self.n_epochs,
                clip_range=0.2,
                ent_coef=self.ent_coef,
                seed=self.seed + level,
                tensorboard_log=None,
            )

            # 训练
            model.learn(total_timesteps=steps_this_level)
            total_trained += max(steps_this_level, self.ppo_n_steps)
            total_trained = max(total_trained, model.num_timesteps)
            print("  Timesteps trained: {}".format(total_trained))

            # 保存模型
            save_path = os.path.join(MODELS_DIR, 'ppo_car.zip')
            model.save(save_path)
            print("  Model saved: {}".format(save_path))

            # 评估当前策略
            eval_stats = self._evaluate(
                model, env, n_episodes=self.eval_episodes)
            avg_reward = eval_stats['avg_reward']
            level_rewards.append(avg_reward)

            # 记录
            self.monitor.record_episode(avg_reward, eval_stats['avg_steps'], {
                'lost_count': eval_stats['lost_episodes'],
                'avg_speed': 0,
                'completed': eval_stats['lost_episodes'] == 0})
            self._csv_rows.append({
                'total_steps': total_trained,
                'level': level,
                'stage': stage.name,
                'avg_reward': round(avg_reward, 4),
                'best_reward': round(eval_stats['best_reward'], 4),
                'worst_reward': round(eval_stats['worst_reward'], 4),
                'avg_steps': round(eval_stats['avg_steps'], 2),
                'lost_episodes': eval_stats['lost_episodes'],
                'eval_episodes': eval_stats['eval_episodes'],
                'avg_track_progress': round(eval_stats['avg_track_progress'], 4),
                'timestamp': time.time(),
            })

            print("  Eval reward avg/best/worst: {:.2f}/{:.2f}/{:.2f}".format(
                eval_stats['avg_reward'],
                eval_stats['best_reward'],
                eval_stats['worst_reward']))
            print("  Eval lost episodes: {}/{} | avg steps: {:.1f} | avg progress: {:.3f}".format(
                eval_stats['lost_episodes'],
                eval_stats['eval_episodes'],
                eval_stats['avg_steps'],
                eval_stats['avg_track_progress']))

            # 课程升降级
            if len(level_rewards) >= self._level_window:
                recent = level_rewards[-self._level_window:]
                avg_r = sum(recent) / len(recent)

                if avg_r > self._upgrade_threshold:
                    if self.curriculum.update(avg_r):
                        level += 1
                        level_rewards.clear()
                        print("  >> UPGRADED to level {}".format(level))
                elif avg_r < self._downgrade_threshold:
                    if self.curriculum._current_idx > 0:
                        self.curriculum._current_idx -= 1
                        level = max(1, level - 1)
                        level_rewards.clear()
                        print("  >> DOWNGRADED to level {}".format(level))

            env.close()

        # 最终保存
        final_path = os.path.join(MODELS_DIR, 'ppo_car_final.zip')
        model.save(final_path)
        print()
        print("Training complete. Final model: {}".format(final_path))

        # 保存日志
        self._save_csv()
        self.monitor.generate_report(os.path.join(LOGS_DIR, 'training_report.json'))
        self.monitor.print_summary()

    def _evaluate(self, model, env, n_episodes=10):
        """评估策略"""
        rewards = []
        steps = []
        lost_episodes = 0
        track_progress = []
        for i in range(n_episodes):
            obs, _ = env.reset(seed=self.seed + 1000 + i)
            total_r = 0
            step_count = 0
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, r, term, trunc, info = env.step(int(action))
                total_r += r
                step_count += 1
                done = term or trunc
            rewards.append(total_r)
            steps.append(step_count)
            if term:
                lost_episodes += 1
            track_progress.append(info.get('track_progress', 0.0))
        return {
            'avg_reward': sum(rewards) / len(rewards),
            'best_reward': max(rewards),
            'worst_reward': min(rewards),
            'avg_steps': sum(steps) / len(steps),
            'lost_episodes': lost_episodes,
            'eval_episodes': n_episodes,
            'avg_track_progress': sum(track_progress) / len(track_progress),
        }

    def _save_csv(self):
        """保存训练日志 CSV"""
        if not self._csv_rows:
            return
        with open(self._csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self._csv_rows[0].keys())
            writer.writeheader()
            writer.writerows(self._csv_rows)
        print("CSV log saved: {}".format(self._csv_path))


# ══════════════════════════════════════════════════════════════
#  训练监控 (内嵌, 避免循环导入)
# ══════════════════════════════════════════════════════════════

class TrainingMonitor:
    def __init__(self, window_size=50):
        self.window_size = window_size
        self.episodes = []
        self._start_time = time.time()

    def record_episode(self, total_reward, steps, info=None):
        record = {
            'episode': len(self.episodes),
            'reward': round(total_reward, 4),
            'steps': steps,
            'timestamp': time.time(),
        }
        if info:
            record.update(info)
        self.episodes.append(record)

    def get_stats(self):
        if not self.episodes:
            return {}
        rewards = [e['reward'] for e in self.episodes]
        return {
            'total_episodes': len(rewards),
            'avg_reward': round(sum(rewards) / len(rewards), 4),
            'best_reward': round(max(rewards), 4),
            'elapsed_s': round(time.time() - self._start_time, 1),
        }

    def generate_report(self, filepath):
        import json
        report = {'stats': self.get_stats(), 'episodes': self.episodes[-50:]}
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print("Report saved: {}".format(filepath))

    def print_summary(self):
        s = self.get_stats()
        print()
        print("=" * 50)
        print("  Training Summary")
        print("=" * 50)
        for k, v in s.items():
            print("  {}: {}".format(k, v))
        print("=" * 50)


# ══════════════════════════════════════════════════════════════
#  测试模式
# ══════════════════════════════════════════════════════════════

def run_test(model_path=None, episodes=3):
    """可视化测试模式"""
    from stable_baselines3 import PPO

    print("=" * 50)
    print("  PPO Test Mode")
    print("=" * 50)

    env = CarEnv(track_type='oval', action_mode='discrete',
                 max_steps=2000, noise=True, speed_factor=1.0)

    if model_path and os.path.exists(model_path):
        model = PPO.load(model_path)
        print("  Loaded model: {}".format(model_path))
    else:
        print("  No model found, using random policy")
        model = None

    for ep in range(episodes):
        obs, info = env.reset(seed=ep * 100)
        total_reward = 0
        steps = 0
        done = False

        print()
        print("  Episode {}/{}".format(ep + 1, episodes))

        while not done:
            if model:
                action, _ = model.predict(obs, deterministic=True)
                action = int(action)
            else:
                action = env.action_space.sample()

            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            done = terminated or truncated

        status = "COMPLETED" if not terminated else "LOST"
        print("    {} | Steps: {} | Reward: {:.2f} | Lost: {}".format(
            status, steps, total_reward, info.get('lost_count', 0)))

    env.close()
    print()
    print("=" * 50)


# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='PPO Training for STM32 Car')
    parser.add_argument('--test', action='store_true', help='Run test mode')
    parser.add_argument('--model', type=str, default=None, help='Model path for test')
    parser.add_argument('--total-steps', type=int, default=100000, help='Total training steps')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--episodes', type=int, default=3, help='Test episodes')
    parser.add_argument('--smoke', action='store_true',
                        help='Run a short PPO smoke training')
    parser.add_argument('--ppo-n-steps', type=int, default=2048,
                        help='Rollout steps per PPO update')
    parser.add_argument('--batch-size', type=int, default=64,
                        help='PPO minibatch size')
    parser.add_argument('--n-epochs', type=int, default=10,
                        help='PPO optimization epochs per update')
    parser.add_argument('--eval-episodes', type=int, default=10,
                        help='Evaluation episodes after each training chunk')
    parser.add_argument('--learning-rate', type=float, default=3e-4,
                        help='PPO learning rate')
    parser.add_argument('--ent-coef', type=float, default=0.01,
                        help='PPO entropy coefficient')
    args = parser.parse_args()

    if args.smoke:
        args.total_steps = min(args.total_steps, 512)
        args.ppo_n_steps = min(args.ppo_n_steps, 512)
        args.batch_size = min(args.batch_size, 64, args.ppo_n_steps)
        args.n_epochs = min(args.n_epochs, 4)
        args.eval_episodes = min(args.eval_episodes, 5)

    if args.test:
        run_test(model_path=args.model, episodes=args.episodes)
    else:
        trainer = CurriculumPPOTrainer(
            total_steps=args.total_steps,
            seed=args.seed,
            ppo_n_steps=args.ppo_n_steps,
            batch_size=args.batch_size,
            n_epochs=args.n_epochs,
            eval_episodes=args.eval_episodes,
            learning_rate=args.learning_rate,
            ent_coef=args.ent_coef)
        trainer.train()


if __name__ == '__main__':
    main()
