#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Regression tests for calibration rollback and strict JSON reports."""

from __future__ import print_function

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from calibration.model_updater import ModelUpdater
from calibration.sim_replay_calibrator import SimReplayCalibrator


class FakePlant(object):
    def __init__(self):
        self.params = {
            "motor_gain": 0.001,
            "motor_offset": 0.0,
            "steering_K": 180.0,
            "steering_tau": 0.05,
            "velocity_damping": 0.85,
            "angular_damping": 0.8,
        }

    def get_params(self):
        return dict(self.params)

    def set_params(self, params):
        self.params = dict(params)


class ControlledUpdater(ModelUpdater):
    def __init__(self, plant, gradient):
        ModelUpdater.__init__(self, plant)
        self.test_gradient = gradient
        self.real_datasets = [[{"tick_ms": 0}]]
        self.dataset_weights = [1.0]
        self.sim_callback = lambda params: []
        self.max_iterations = 5

    def _compute_batch_error(self, params):
        return float(params["motor_gain"])

    def _compute_gradients(self, params, current_error):
        del params, current_error
        return {"motor_gain": self.test_gradient}


class CalibrationSafetyTests(unittest.TestCase):
    def test_worse_candidate_is_rolled_back(self):
        plant = FakePlant()
        updater = ControlledUpdater(plant, gradient=-1.0)
        result = updater.calibrate()
        self.assertFalse(result["successful"])
        self.assertFalse(result["converged"])
        self.assertEqual(result["stop_reason"], "no_improving_step")
        self.assertAlmostEqual(result["initial_error"], result["final_error"])
        self.assertAlmostEqual(plant.params["motor_gain"], 0.001)

    def test_better_candidate_is_kept(self):
        plant = FakePlant()
        updater = ControlledUpdater(plant, gradient=1.0)
        result = updater.calibrate()
        self.assertTrue(result["successful"])
        self.assertLess(result["final_error"], result["initial_error"])
        self.assertAlmostEqual(plant.params["motor_gain"], result["final_params"]["motor_gain"])

    def test_report_contains_no_non_finite_json_values(self):
        calibrator = object.__new__(SimReplayCalibrator)
        calibrator.calibration_result = {
            "initial_params": {"motor_offset": 0.0},
            "final_params": {"motor_offset": -0.1},
            "final_error": float("inf"),
        }
        calibrator.verification_result = {"dtw_distance": float("inf")}
        calibrator.post_verification_result = None
        calibrator.replay_data = []

        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        try:
            calibrator.save_report(path)
            with open(path, "r", encoding="utf-8") as source:
                text = source.read()
            self.assertNotIn("Infinity", text)
            decoded = json.loads(
                text,
                parse_constant=lambda value: self.fail("non-finite JSON: %s" % value),
            )
            self.assertIsNone(decoded["calibration_result"]["final_error"])
            self.assertIsNone(decoded["param_comparison"]["motor_offset"]["change_pct"])
        finally:
            os.unlink(path)

    def test_each_dataset_is_passed_to_the_simulation_callback(self):
        updater = ModelUpdater(FakePlant())
        received = []

        def callback(params, records):
            del params
            received.append(records)
            return [{"x": 0, "y": 0}]

        updater.set_sim_callback(callback)
        first = [{"id": 1}]
        second = [{"id": 2}]
        updater._run_sim_single(updater.plant.get_params(), first)
        updater._run_sim_single(updater.plant.get_params(), second)
        self.assertEqual(received, [first, second])


if __name__ == "__main__":
    unittest.main()
