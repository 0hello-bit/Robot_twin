# -*- coding: utf-8 -*-
"""
checkpoint_manager.py - Model Checkpoint Manager

Saves models at regular intervals and keeps track of the best model.
Based on gym-pybullet-drones pattern.

Features:
    1. Save every N steps
    2. Keep best model (by reward)
    3. Keep last K checkpoints
    4. Auto-cleanup old checkpoints
"""

import os
import json
import time
import shutil


class CheckpointManager:
    """
    Manages model checkpoints during training.

    Saves:
        - models/checkpoint_step_N.zip  (periodic)
        - models/best_model.zip         (best reward)
        - models/checkpoint_history.json (metadata)
    """

    def __init__(self, save_dir, prefix='ppo_car',
                 save_every=10000, keep_best=3, keep_last=5):
        """
        Args:
            save_dir: Directory to save checkpoints
            prefix: Model filename prefix
            save_every: Save every N training steps
            keep_best: Number of best models to keep
            keep_last: Number of recent models to keep
        """
        self.save_dir = save_dir
        self.prefix = prefix
        self.save_every = save_every
        self.keep_best = keep_best
        self.keep_last = keep_last

        os.makedirs(save_dir, exist_ok=True)

        self._best_reward = -float('inf')
        self._best_path = None
        self._history = []
        self._history_path = os.path.join(save_dir, 'checkpoint_history.json')
        self._load_history()

    def _load_history(self):
        if os.path.exists(self._history_path):
            with open(self._history_path, 'r') as f:
                self._history = json.load(f)
                # Restore best reward
                for entry in self._history:
                    if entry.get('is_best', False):
                        if entry['reward'] > self._best_reward:
                            self._best_reward = entry['reward']
                            self._best_path = entry['path']

    def _save_history(self):
        with open(self._history_path, 'w') as f:
            json.dump(self._history, f, indent=2)

    def maybe_save(self, model, step, reward):
        """
        Save model if conditions are met.

        Args:
            model: PPO model (must have model.save(path))
            step: Current training step
            reward: Current evaluation reward

        Returns:
            dict with save info, or None if not saved
        """
        should_save = (step % self.save_every == 0) or (step == 0)
        is_best = reward > self._best_reward

        if not should_save and not is_best:
            return None

        # Build path
        if is_best:
            filename = 'best_model.zip'
            self._best_reward = reward
            self._best_path = os.path.join(self.save_dir, filename)
        else:
            filename = '%s_step_%d.zip' % (self.prefix, step)

        filepath = os.path.join(self.save_dir, filename)

        # Save model
        model.save(filepath)

        # Record in history
        entry = {
            'step': step,
            'reward': round(reward, 4),
            'path': filepath,
            'filename': filename,
            'is_best': is_best,
            'timestamp': time.time(),
        }
        self._history.append(entry)
        self._save_history()

        # Cleanup old checkpoints
        self._cleanup()

        return entry

    def _cleanup(self):
        """Remove old checkpoints, keeping best and last K."""
        if len(self._history) <= self.keep_last + self.keep_best:
            return

        # Sort by step
        sorted_entries = sorted(self._history, key=lambda x: x['step'])

        # Mark which to keep
        keep_set = set()

        # Keep best N
        by_reward = sorted(self._history, key=lambda x: x['reward'], reverse=True)
        for entry in by_reward[:self.keep_best]:
            keep_set.add(entry['path'])

        # Keep last N
        for entry in sorted_entries[-self.keep_last:]:
            keep_set.add(entry['path'])

        # Delete others
        for entry in sorted_entries:
            if entry['path'] not in keep_set:
                if os.path.exists(entry['path']):
                    try:
                        os.remove(entry['path'])
                    except OSError:
                        pass

    def get_best(self):
        """Get the best model path."""
        return self._best_path

    def get_best_reward(self):
        return self._best_reward

    def get_history(self):
        return list(self._history)

    def load_best(self):
        """Load the best model."""
        from stable_baselines3 import PPO
        if self._best_path and os.path.exists(self._best_path):
            return PPO.load(self._best_path)
        return None
