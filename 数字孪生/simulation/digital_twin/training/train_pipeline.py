# -*- coding: utf-8 -*-
"""
train_pipeline.py - Unified Training Pipeline

Integrates:
    - EarlyStopping
    - CheckpointManager
    - CurvePlotter
    - CurriculumManager
    - DomainRandomization
    - ManifestStore (data logging)

Based on donkeycar + gym-pybullet-drones best practices.

Usage:
    python -m training.train_pipeline                    # Full training
    python -m training.train_pipeline --test             # Test mode
    python -m training.train_pipeline --total-steps 500000
    python -m training.train_pipeline --resume models/ppo_car.zip
"""

import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rl_env.car_env import CarEnv
from rl_env.curriculum import CurriculumManager, STAGES
from training.early_stopping import EarlyStopping
from training.checkpoint_manager import CheckpointManager
from training.curve_plotter import CurvePlotter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, 'models')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')


class TrainPipeline:
    """
    Unified training pipeline with production features.

    Features:
        1. Curriculum learning (auto level-up/down)
        2. Early stopping (patience-based)
        3. Checkpoint management (save best + periodic)
        4. Training curve plotting
        5. Domain randomization
        6. Comprehensive logging
    """

    def __init__(self, total_steps=100000, seed=42,
                 save_every=10000, eval_every=5000,
                 patience=15, resume_path=None):
        """
        Args:
            total_steps: Total training steps
            seed: Random seed
            save_every: Save checkpoint every N steps
            eval_every: Evaluate policy every N steps
            patience: Early stopping patience
            resume_path: Path to resume training from
        """
        self.total_steps = total_steps
        self.seed = seed
        self.save_every = save_every
        self.eval_every = eval_every
        self.resume_path = resume_path

        # Components
        self.curriculum = CurriculumManager()
        self.early_stop = EarlyStopping(
            patience=patience, min_delta=1.0, mode='max')
        self.checkpoint = CheckpointManager(
            save_dir=MODELS_DIR, prefix='ppo_car',
            save_every=save_every, keep_best=3, keep_last=5)
        self.plotter = CurvePlotter(log_dir=LOGS_DIR, window_size=30)

        # State
        self._total_trained = 0
        self._current_level = 1
        self._level_rewards = []
        self._upgrade_threshold = 300.0
        self._downgrade_threshold = -50.0

    def train(self):
        """Main training loop."""
        from stable_baselines3 import PPO

        os.makedirs(MODELS_DIR, exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)

        print("=" * 60)
        print("  PPO Training Pipeline - STM32 Car RL")
        print("=" * 60)
        print("  Total steps: %d" % self.total_steps)
        print("  Seed: %d" % self.seed)
        print("  Save every: %d steps" % self.save_every)
        print("  Eval every: %d steps" % self.eval_every)
        print("  Early stop patience: %d" % self.early_stop.patience)
        if self.resume_path:
            print("  Resume from: %s" % self.resume_path)
        print("=" * 60)

        # Load or create model
        model = None
        if self.resume_path and os.path.exists(self.resume_path):
            model = PPO.load(self.resume_path)
            print("  Resumed from: %s" % self.resume_path)

        level = self._current_level
        stage = self.curriculum.get_current_stage()

        while self._total_trained < self.total_steps:
            remaining = self.total_steps - self._total_trained
            steps_this_level = min(remaining, max(10000, self.total_steps // 10))

            print()
            print("--- Level %d | Stage: %s | Steps: %d ---" % (
                level, stage.name, steps_this_level))

            # Create environment
            env = CarEnv(
                track_type=stage.track_type,
                action_mode='discrete',
                max_steps=stage.max_steps,
                noise=stage.noise,
                speed_factor=stage.speed_factor,
                seed=self.seed + level,
            )

            # Create or update model
            if model is None:
                model = PPO(
                    'MlpPolicy', env,
                    device='cpu',
                    verbose=1,
                    batch_size=64,
                    n_steps=2048,
                    gamma=0.99,
                    learning_rate=3e-4,
                    n_epochs=10,
                    clip_range=0.2,
                    ent_coef=0.01,
                    seed=self.seed + level,
                )
            else:
                # Re-setup model with new env
                model.set_env(env)

            # Train
            model.learn(total_timesteps=steps_this_level)
            self._total_trained += steps_this_level

            # Evaluate
            avg_reward = self._evaluate(model, env, n_episodes=10)
            self._level_rewards.append(avg_reward)

            # Record
            success = avg_reward > 100
            self.plotter.add_episode(
                reward=avg_reward,
                steps=self._total_trained,
                level=level,
                success=success)

            # Checkpoint
            entry = self.checkpoint.maybe_save(
                model, self._total_trained, avg_reward)
            if entry:
                print("  Saved: %s (reward=%.2f)" % (
                    entry['filename'], entry['reward']))

            # Early stopping check
            if self.early_stop.step(avg_reward, self._total_trained):
                print()
                print("  *** EARLY STOPPING ***")
                print("  Best reward: %.2f at step %d" % (
                    self.early_stop.best_score,
                    self.early_stop.best_epoch))
                break

            # Curriculum adjustment
            level = self._adjust_curriculum(avg_reward, level)
            stage = self.curriculum.get_current_stage()

            env.close()

        # Final results
        self._print_summary()
        self.plotter.plot_all()
        self.plotter.export_json()

        return model

    def _evaluate(self, model, env, n_episodes=10):
        """Evaluate policy and return average reward."""
        rewards = []
        for i in range(n_episodes):
            obs, _ = env.reset(seed=i * 100)
            total_reward = 0
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, _ = env.step(int(action))
                total_reward += reward
                done = terminated or truncated
            rewards.append(total_reward)
        avg = sum(rewards) / len(rewards)
        print("  Eval: avg=%.2f best=%.2f worst=%.2f" % (
            avg, max(rewards), min(rewards)))
        return avg

    def _adjust_curriculum(self, avg_reward, current_level):
        """Adjust curriculum level based on performance."""
        if avg_reward > self._upgrade_threshold and current_level < 4:
            new_level = current_level + 1
            print("  LEVEL UP: %d -> %d (reward=%.2f)" % (
                current_level, new_level, avg_reward))
            return new_level
        elif avg_reward < self._downgrade_threshold and current_level > 1:
            new_level = current_level - 1
            print("  LEVEL DOWN: %d -> %d (reward=%.2f)" % (
                current_level, new_level, avg_reward))
            return new_level
        return current_level

    def _print_summary(self):
        """Print training summary."""
        stats = self.plotter.get_stats()
        print()
        print("=" * 60)
        print("  Training Complete")
        print("=" * 60)
        for k, v in stats.items():
            print("  %s: %s" % (k, v))
        print("  Best checkpoint: %s" % self.checkpoint.get_best())
        print("  Early stop: %s" % self.early_stop.get_info())
        print("=" * 60)


def run_test(model_path=None, episodes=3):
    """Visualization test mode."""
    print("=" * 50)
    print("  PPO Test Mode")
    print("=" * 50)

    env = CarEnv(track_type='oval', action_mode='discrete',
                 max_steps=2000, noise=True, speed_factor=1.0)

    model = None
    if model_path and os.path.exists(model_path):
        from stable_baselines3 import PPO
        model = PPO.load(model_path)
        print("  Loaded: %s" % model_path)
    else:
        print("  No model, using random policy")

    for ep in range(episodes):
        obs, _ = env.reset(seed=ep * 100)
        total_reward = 0
        steps = 0
        done = False

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
        print("  Ep %d: %s | Steps=%d | Reward=%.2f" % (
            ep + 1, status, steps, total_reward))

    env.close()


def main():
    parser = argparse.ArgumentParser(
        description='PPO Training Pipeline for STM32 Car')
    parser.add_argument('--test', action='store_true',
                        help='Run visualization test')
    parser.add_argument('--model', type=str, default=None,
                        help='Model path for test or resume')
    parser.add_argument('--total-steps', type=int, default=100000,
                        help='Total training steps')
    parser.add_argument('--seed', type=int, default=42,
                        help='Random seed')
    parser.add_argument('--save-every', type=int, default=10000,
                        help='Save checkpoint every N steps')
    parser.add_argument('--patience', type=int, default=15,
                        help='Early stopping patience')
    parser.add_argument('--resume', type=str, default=None,
                        help='Resume from checkpoint')
    args = parser.parse_args()

    if args.test:
        run_test(model_path=args.model)
    else:
        pipeline = TrainPipeline(
            total_steps=args.total_steps,
            seed=args.seed,
            save_every=args.save_every,
            patience=args.patience,
            resume_path=args.resume,
        )
        pipeline.train()


if __name__ == '__main__':
    main()
