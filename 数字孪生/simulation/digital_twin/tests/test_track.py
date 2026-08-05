# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulator.map import TrackMap

def test_oval_generation():
    pts = TrackMap.generate_oval(400, 300, 200, 120, 100)
    assert len(pts) == 100

def test_track_add_polyline():
    track = TrackMap()
    pts = TrackMap.generate_oval(400, 300, 200, 120, 100)
    track.add_polyline(pts, close=True)
    assert len(track.segments) > 0

def test_point_on_track():
    track = TrackMap()
    pts = TrackMap.generate_oval(400, 300, 200, 120, 100)
    track.add_polyline(pts, close=True)
    on = track.is_point_on_track(400, 300 + 120)
    assert on == True

def test_distance_to_track():
    track = TrackMap()
    pts = TrackMap.generate_oval(400, 300, 200, 120, 100)
    track.add_polyline(pts, close=True)
    d = track.get_distance_to_track(400, 300)
    assert d >= 0
