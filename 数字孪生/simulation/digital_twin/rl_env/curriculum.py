# -*- coding: utf-8 -*-
"""
curriculum.py - 课程学习系统

按难度递进训练: 简单赛道 → 复杂赛道 → 噪声环境。
"""


class CurriculumStage:
    """单个课程阶段"""
    def __init__(self, name, track_type, noise, speed_factor,
                 max_steps, description=''):
        self.name = name
        self.track_type = track_type
        self.noise = noise
        self.speed_factor = speed_factor
        self.max_steps = max_steps
        self.description = description


# ── 预定义课程 ──

STAGES = {
    'easy': CurriculumStage(
        'easy', 'curriculum_1', False, 0.8, 500,
        'Level 1: ellipse + mild curvature noise'),
    'medium': CurriculumStage(
        'medium', 'curriculum_2', True, 1.0, 1000,
        'Level 2: sine wave + varying amplitude'),
    'hard': CurriculumStage(
        'hard', 'curriculum_3', True, 1.0, 1500,
        'Level 3: figure-8 + cross intersection'),
    'expert': CurriculumStage(
        'expert', 'curriculum_4', True, 1.2, 2000,
        'Level 4: hybrid (straight + sharp + spiral + spline)'),
}


class CurriculumManager:
    """
    课程学习管理器。

    根据训练进度自动切换赛道难度。

    使用:
        cm = CurriculumManager()
        stage = cm.get_current_stage()
        # stage.track_type, stage.noise, ...
        cm.update(episode_reward)
    """

    def __init__(self, stages=None):
        self._stages = stages or list(STAGES.values())
        self._current_idx = 0
        self._episode_rewards = []
        self._promotion_threshold = 300.0
        self._patience = 20
        self._window = 50

    def get_current_stage(self):
        return self._stages[min(self._current_idx, len(self._stages) - 1)]

    def update(self, episode_reward):
        self._episode_rewards.append(episode_reward)

        if len(self._episode_rewards) < self._patience:
            return False

        recent = self._episode_rewards[-self._window:]
        avg = sum(recent) / len(recent)

        if avg >= self._promotion_threshold and self._current_idx < len(self._stages) - 1:
            self._current_idx += 1
            return True
        return False

    def get_progress(self):
        n = len(self._stages)
        return {
            'current_stage': self._current_idx,
            'total_stages': n,
            'stage_name': self.get_current_stage().name,
            'progress_pct': round(self._current_idx / max(n - 1, 1) * 100, 1),
            'episodes': len(self._episode_rewards),
        }

    def reset(self):
        self._current_idx = 0
        self._episode_rewards.clear()