from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest

from v1_twin.v1_twin_vehicle_geometry import (
    DEFAULT_VEHICLE_BODY_PROFILE_PATH,
    VehicleBodyProfile,
    VehicleBodyRectangle,
    derive_vehicle_body_rectangle,
    load_default_vehicle_body_profile,
)


PROFILE_DATA = {
    "profile_id": "vehicle_body_visual_seed_v1",
    "schema_version": "1.0.0",
    "length_mm": 190.0,
    "width_mm": 140.0,
    "tag_to_center_forward_mm": 55.0,
    "tag_to_center_left_mm": 0.0,
    "source": "APRILTAG_RIGID_BODY_OFFSET",
    "validation_status": "HEURISTIC_UNVERIFIED",
    "calibration_status": "INITIAL_VIDEO_SEED",
    "coordinate_frame": "relative_plane_mm",
}


def test_zero_yaw_uses_tag_center_and_orders_corners_front_to_rear():
    rectangle = derive_vehicle_body_rectangle(
        {"x_mm": 100.0, "y_mm": 200.0, "yaw_rad": 0.0, "confidence": 0.8},
        VehicleBodyProfile.from_dict(PROFILE_DATA),
    )

    assert (rectangle.center_x_mm, rectangle.center_y_mm) == (155.0, 200.0)
    assert rectangle.corners_mm == (
        (250.0, 270.0),
        (250.0, 130.0),
        (60.0, 130.0),
        (60.0, 270.0),
    )


def test_ninety_degree_yaw_rotates_forward_offset_and_corner_order():
    rectangle = derive_vehicle_body_rectangle(
        {"x_mm": 100.0, "y_mm": 200.0, "yaw_rad": math.pi / 2, "confidence": 1.0},
        VehicleBodyProfile.from_dict(PROFILE_DATA),
    )

    assert rectangle.center_x_mm == pytest.approx(100.0)
    assert rectangle.center_y_mm == pytest.approx(255.0)
    assert rectangle.corners_mm == tuple(
        pytest.approx(point)
        for point in ((30.0, 350.0), (170.0, 350.0), (170.0, 160.0), (30.0, 160.0))
    )


def test_tag_corners_are_preserved_and_absence_is_null():
    profile = VehicleBodyProfile.from_dict(PROFILE_DATA)
    corners = ((1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0))
    with_corners = derive_vehicle_body_rectangle(
        {"x_mm": 0, "y_mm": 0, "yaw_rad": 0, "confidence": 0.5},
        profile,
        tag_corners_px=corners,
    )
    without_corners = derive_vehicle_body_rectangle(
        {"x_mm": 0, "y_mm": 0, "yaw_rad": 0, "confidence": 0.5}, profile
    )

    assert with_corners.to_dict()["tag_corners_px"] == [list(p) for p in corners]
    assert without_corners.to_dict()["tag_corners_px"] is None


@pytest.mark.parametrize(
    "field,value",
    [("length_mm", 0.0), ("length_mm", -1.0), ("width_mm", 0.0),
     ("width_mm", float("inf")), ("tag_to_center_forward_mm", float("nan")),
     ("tag_to_center_left_mm", float("-inf"))],
)
def test_profile_rejects_invalid_geometry(field, value):
    with pytest.raises(ValueError):
        VehicleBodyProfile.from_dict({**PROFILE_DATA, field: value})


def test_profile_and_rectangle_json_round_trip_preserves_values_and_metadata():
    profile = VehicleBodyProfile.from_dict(PROFILE_DATA)
    profile_round_trip = VehicleBodyProfile.from_dict(
        json.loads(json.dumps(profile.to_dict()))
    )
    rectangle = derive_vehicle_body_rectangle(
        {"x_mm": 100, "y_mm": 200, "yaw_rad": 0.25, "confidence": 0.75},
        profile_round_trip,
        tag_corners_px=((1, 2), (3, 4), (5, 6), (7, 8)),
    )
    rectangle_round_trip = VehicleBodyRectangle.from_dict(
        json.loads(json.dumps(rectangle.to_dict()))
    )

    assert profile_round_trip == profile
    assert rectangle_round_trip == rectangle


def test_default_profile_is_the_versioned_visual_seed():
    profile = load_default_vehicle_body_profile()

    assert DEFAULT_VEHICLE_BODY_PROFILE_PATH.is_file()
    assert profile.profile_id == "vehicle_body_visual_seed_v1"
    assert profile.source_run_id == "c260817013638536"
    assert "not absolute measurement" in profile.note
