# -*- coding: utf-8 -*-
"""
early_stopping.py - Early Stopping for RL Training

Based on gym-pybullet-drones pattern.
Monitors a metric (e.g., average reward) and stops training
when it stops improving.

Usage:
    es = EarlyStopping(patience=10, min_delta=0.01)
    for epoch in range(1000):
        reward = train_one_epoch()
        if es.step(reward):
            print("Early stopping at epoch", epoch)
            break
"""

import time


class EarlyStopping:
    """
    Early stopping with patience.

    Monitors a metric and stops when it hasn't improved
    for `patience` consecutive evaluations.

    Attributes:
        patience: Number of evaluations to wait for improvement
        min_delta: Minimum improvement required
        best_score: Best score seen so far
        counter: Current patience counter
        stopped: Whether stopping has been triggered
    """

    def __init__(self, patience=10, min_delta=0.0, mode='max'):
        """
        Args:
            patience: Stop after this many evaluations without improvement
            min_delta: Minimum change to qualify as improvement
            mode: 'max' (higher is better) or 'min' (lower is better)
        """
        self.patience = patience
        self.min_delta = min_delta
        self.mode = mode
        self.best_score = None
        self.counter = 0
        self.stopped = False
        self.best_epoch = 0
        self.history = []

    def step(self, score, epoch=0):
        """
        Record a new score and check if training should stop.

        Args:
            score: Current evaluation metric
            epoch: Current epoch number (for logging)

        Returns:
            True if training should stop, False otherwise
        """
        self.history.append({
            'epoch': epoch,
            'score': score,
            'timestamp': time.time(),
        })

        if self.best_score is None:
            self.best_score = score
            self.best_epoch = epoch
            return False

        if self.mode == 'max':
            improved = score > self.best_score + self.min_delta
        else:
            improved = score < self.best_score - self.min_delta

        if improved:
            self.best_score = score
            self.best_epoch = epoch
            self.counter = 0
        else:
            self.counter += 1

        if self.counter >= self.patience:
            self.stopped = True
            return True

        return False

    def get_info(self):
        return {
            'best_score': self.best_score,
            'best_epoch': self.best_epoch,
            'counter': self.counter,
            'patience': self.patience,
            'stopped': self.stopped,
        }


class AdaptiveEarlyStopping:
    """
    Adaptive early stopping that adjusts patience based on training phase.

    Early training: longer patience (exploration)
    Late training: shorter patience ( exploitation)
    """

    def __init__(self, base_patience=10, min_delta=0.0, phase_threshold=0.5):
        self.base_patience = base_patience
        self.min_delta = min_delta
        self.phase_threshold = phase_threshold
        self._es = EarlyStopping(patience=base_patience, min_delta=min_delta)

    def step(self, score, epoch=0, total_epochs=100):
        # Adjust patience based on training progress
        progress = epoch / max(total_epochs, 1)
        if progress < self.phase_threshold:
            # Early phase: be patient
            self._es.patience = self.base_patience * 2
        else:
            # Late phase: be strict
            self._es.patience = max(3, self.base_patience // 2)
        return self._es.step(score, epoch)

    @property
    def stopped(self):
        return self._es.stopped

    def get_info(self):
        return self._es.get_info()
