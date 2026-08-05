"""Tests for the immutable calibration profile contract (R3 raw-pixel exploratory).

Red/Green contract tests:
- round-trip preserves pixel domain, quality, matrix and accuracy evidence;
- the formal 2 mm ground gate rejects the exploratory profile;
- strict validation rejects malformed provenance, matrices, enums and metrics;
- a forged HOLDOUT_VERIFIED_2MM profile whose p95 exceeds 2.0 mm is rejected.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from v1_twin.v1_twin_calibration_profile import (
    CalibrationProfile,
    CalibrationProfileError,
    CalibrationQuality,
    PixelDomain,
)


def _profile_dict():
    return {
        "schema_version": 1,
        "calibration_id": "c960_r3_raw_global_exploratory_v1",
        "camera": {"model": "EMEET SmartCam C960", "image_size": [1280, 720]},
        "input_domain": "RAW_PIXEL",
        "quality": "EXPLORATORY_RELATIVE_ONLY",
        "ground_transform": {
            "type": "HomographyTransform",
            "matrix": [[0.9471, -0.0043, -757.8874],
                       [-0.0096, 0.9564, -440.9269],
                       [0.0000459, 0.0000058, 1.0]],
        },
        "accuracy_evidence": {
            "scope": "GROUND_CONTROL_POINTS_ONLY",
            "stratified_holdout_p95_mm": 10.62712398475308,
            "stratified_holdout_max_mm": 10.758592939623588,
            "loo_p95_mm": 11.01137209510592,
            "loo_max_mm": 11.577187539478283,
            "evidence_class": "MODEL_ESTIMATED_NOT_PHYSICALLY_INDEPENDENT_ANGLE",
        },
        "pose_absolute_accuracy": "UNVERIFIED_TAG_HEIGHT_PARALLAX",
        "provenance": {
            "source": ".embeddedskills/build/source.json",
            "sha256": "d" * 64,
        },
    }


def test_profile_round_trip_preserves_domain_quality_matrix_and_evidence():
    profile = CalibrationProfile.from_dict(_profile_dict())
    assert profile.pixel_domain is PixelDomain.RAW_PIXEL
    assert profile.quality is CalibrationQuality.EXPLORATORY_RELATIVE_ONLY
    assert profile.image_size == (1280, 720)
    assert profile.accuracy.stratified_holdout_p95_mm == pytest.approx(10.62712398475308)
    assert CalibrationProfile.from_dict(profile.to_dict()).to_dict() == profile.to_dict()


def test_formal_ground_gate_rejects_exploratory_profile():
    profile = CalibrationProfile.from_dict(_profile_dict())
    with pytest.raises(CalibrationProfileError, match="HOLDOUT_VERIFIED_2MM"):
        profile.require_ground_holdout_verified_2mm()


def test_rejects_absolute_provenance_path():
    d = _profile_dict()
    d["provenance"]["source"] = "C:/Users/me/.embeddedskills/build/source.json"
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_parent_traversal_path():
    d = _profile_dict()
    d["provenance"]["source"] = "../outside/source.json"
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_non_hex_sha256():
    d = _profile_dict()
    d["provenance"]["sha256"] = "z" * 64
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_short_sha256():
    d = _profile_dict()
    d["provenance"]["sha256"] = "abc"
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_non_positive_image_dimensions():
    d = _profile_dict()
    d["camera"]["image_size"] = [1280, 0]
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)
    d = _profile_dict()
    d["camera"]["image_size"] = [-1, 720]
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_non_finite_homography():
    d = _profile_dict()
    d["ground_transform"]["matrix"][0][0] = float("nan")
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_singular_homography():
    d = _profile_dict()
    d["ground_transform"]["matrix"] = [[1.0, 2.0, 3.0], [2.0, 4.0, 6.0], [0.0, 0.0, 1.0]]
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_unknown_enum_values():
    d = _profile_dict()
    d["input_domain"] = "NOT_A_DOMAIN"
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)
    d = _profile_dict()
    d["quality"] = "NOT_A_QUALITY"
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_negative_accuracy_metrics():
    d = _profile_dict()
    d["accuracy_evidence"]["stratified_holdout_p95_mm"] = -1.0
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_bool_schema_version():
    d = _profile_dict()
    d["schema_version"] = True
    with pytest.raises(CalibrationProfileError, match="schema_version"):
        CalibrationProfile.from_dict(d)


def test_rejects_float_schema_version():
    d = _profile_dict()
    d["schema_version"] = 1.0
    with pytest.raises(CalibrationProfileError, match="schema_version"):
        CalibrationProfile.from_dict(d)


def test_rejects_string_schema_version():
    d = _profile_dict()
    d["schema_version"] = "1"
    with pytest.raises(CalibrationProfileError, match="schema_version"):
        CalibrationProfile.from_dict(d)


def test_rejects_float_image_dimension():
    d = _profile_dict()
    d["camera"]["image_size"] = [1280.0, 720]
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_string_image_dimension():
    d = _profile_dict()
    d["camera"]["image_size"] = ["1280", 720]
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_bool_image_dimension():
    d = _profile_dict()
    d["camera"]["image_size"] = [True, 720]
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_wrong_image_size_length():
    d = _profile_dict()
    d["camera"]["image_size"] = [1280]
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)
    d = _profile_dict()
    d["camera"]["image_size"] = [1280, 720, 1]
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_empty_camera_model():
    d = _profile_dict()
    d["camera"]["model"] = ""
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_non_string_camera_model():
    d = _profile_dict()
    d["camera"]["model"] = 123
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_empty_calibration_id():
    d = _profile_dict()
    d["calibration_id"] = ""
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_non_string_calibration_id():
    d = _profile_dict()
    d["calibration_id"] = 123
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_empty_pose_absolute_accuracy():
    d = _profile_dict()
    d["pose_absolute_accuracy"] = ""
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_non_string_pose_absolute_accuracy():
    d = _profile_dict()
    d["pose_absolute_accuracy"] = 123
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_bool_accuracy_metric():
    d = _profile_dict()
    d["accuracy_evidence"]["loo_max_mm"] = True
    with pytest.raises(CalibrationProfileError):
        CalibrationProfile.from_dict(d)


def test_rejects_forged_2mm_profile_exceeding_threshold():
    d = _profile_dict()
    d["quality"] = "HOLDOUT_VERIFIED_2MM"
    d["accuracy_evidence"]["stratified_holdout_p95_mm"] = 2.5
    with pytest.raises(CalibrationProfileError, match="p95 exceeds 2.0 mm"):
        CalibrationProfile.from_dict(d)


def test_formal_profile_below_threshold_passes_gate():
    d = _profile_dict()
    d["quality"] = "HOLDOUT_VERIFIED_2MM"
    d["accuracy_evidence"]["stratified_holdout_p95_mm"] = 1.8
    profile = CalibrationProfile.from_dict(d)
    profile.require_ground_holdout_verified_2mm()  # must not raise
