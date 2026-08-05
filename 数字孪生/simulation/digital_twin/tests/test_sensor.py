# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulator.sensor import SensorArray, IRSensor
import config as cfg

def test_sensor_array_init():
    arr = SensorArray()
    assert len(arr.sensors) == cfg.NUM_SENSORS

def test_sensor_read_no_track():
    arr = SensorArray()
    from simulator.map import TrackMap
    track = TrackMap()
    readings = arr.read(track)
    assert len(readings) == 4
    assert all(r == 1 for r in readings)

def test_sensor_positions():
    from simulator.car import MecanumCar
    car = MecanumCar(100, 100, 0)
    arr = SensorArray()
    arr.update_positions(car)
    positions = arr.get_positions()
    assert len(positions) == 4
