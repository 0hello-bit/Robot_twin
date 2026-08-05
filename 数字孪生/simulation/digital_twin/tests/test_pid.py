# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulator.pid import PIDController

def test_pid_init():
    pid = PIDController(kp=0.6, ki=0.0, kd=0.15)
    assert pid.kp == 0.6
    assert pid.ki == 0.0
    assert pid.kd == 0.15

def test_pid_zero_error():
    pid = PIDController(kp=0.6, ki=0.0, kd=0.15)
    out = pid.compute(0, 0.02)
    assert out == 0.0

def test_pid_proportional():
    pid = PIDController(kp=1.0, ki=0.0, kd=0.0)
    out = pid.compute(100, 0.02)
    assert out > 0

def test_pid_reset():
    pid = PIDController(kp=0.6, ki=0.1, kd=0.15)
    pid.compute(100, 0.02)
    pid.compute(100, 0.02)
    pid.reset()
    assert pid._integral == 0.0

def test_pid_output_limits():
    pid = PIDController(kp=10.0, ki=0.0, kd=0.0, output_min=-0.5, output_max=0.5)
    out = pid.compute(1000, 0.02)
    assert -0.5 <= out <= 0.5
