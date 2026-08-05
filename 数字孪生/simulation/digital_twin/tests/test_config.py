# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg

def test_screen_dimensions():
    assert cfg.SCREEN_WIDTH > 0
    assert cfg.SCREEN_HEIGHT > 0

def test_car_dimensions():
    assert cfg.CAR_LENGTH > 0
    assert cfg.CAR_WIDTH > 0

def test_pid_defaults():
    assert cfg.DEFAULT_KP >= 0
    assert cfg.DEFAULT_KI >= 0
    assert cfg.DEFAULT_KD >= 0

def test_sensor_config():
    assert cfg.NUM_SENSORS == 4
    assert len(cfg.SENSOR_OFFSETS) == 4
