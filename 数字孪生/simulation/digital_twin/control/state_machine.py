# -*- coding: utf-8 -*-
"""
state_machine.py - State machine management
Manages simulation modes.
"""

from enum import Enum, auto


class SimMode(Enum):
    """Simulation modes"""
    LINE_FOLLOW    = auto()
    STM32_COMPAT   = auto()
    MANUAL         = auto()
    REALTIME_HIL   = auto()
    REPLAY         = auto()
    REAL_WORLD     = auto()
    PAUSED         = auto()
    TRACK_RECORD   = auto()


class StateMachine:
    """Simulator state machine"""

    def __init__(self):
        self.mode = SimMode.LINE_FOLLOW
        self.prev_mode = None

    def switch_to(self, mode):
        if mode != self.mode:
            self.prev_mode = self.mode
            self.mode = mode

    def toggle_pause(self):
        if self.mode == SimMode.PAUSED:
            self.switch_to(self.prev_mode or SimMode.LINE_FOLLOW)
        else:
            self.switch_to(SimMode.PAUSED)

    def cycle_mode(self):
        modes = [SimMode.LINE_FOLLOW, SimMode.STM32_COMPAT,
                 SimMode.REALTIME_HIL, SimMode.REPLAY,
                 SimMode.REAL_WORLD, SimMode.TRACK_RECORD, SimMode.MANUAL, SimMode.PAUSED]
        idx = modes.index(self.mode) if self.mode in modes else 0
        self.switch_to(modes[(idx + 1) % len(modes)])

    def is_autonomous(self):
        return self.mode == SimMode.LINE_FOLLOW

    def is_stm32_compat(self):
        return self.mode == SimMode.STM32_COMPAT

    def is_manual(self):
        return self.mode == SimMode.MANUAL

    def is_hil(self):
        return self.mode == SimMode.REALTIME_HIL

    def is_replay(self):
        return self.mode == SimMode.REPLAY

    def is_real_world(self):
        return self.mode == SimMode.REAL_WORLD

    def is_track_record(self):
        return self.mode == SimMode.TRACK_RECORD

    def is_paused(self):
        return self.mode == SimMode.PAUSED
