# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulator.analog_sensor import AnalogSensorArray

def test_analog_read():
    sensor = AnalogSensorArray(sigma=8.0, resolution=1023)
    from simulator.map import TrackMap
    track = TrackMap()
    pts = TrackMap.generate_oval(400, 300, 200, 120, 100)
    track.add_polyline(pts, close=True)
    readings = sensor.read(400, 300 + 120, 0, track)
    assert len(readings) == 4
    assert all(0 <= r <= 1023 for r in readings)

def test_analog_to_discrete():
    sensor = AnalogSensorArray(sigma=8.0, resolution=1023)
    readings = [100, 800, 900, 950]
    discrete = sensor.to_discrete(readings, threshold=512)
    assert discrete == [0, 1, 1, 1]

def test_read_position():
    sensor = AnalogSensorArray(sigma=8.0, resolution=1023)
    readings = [100, 200, 800, 900]
    pos = sensor.read_position(readings)
    assert -4 <= pos <= 4
