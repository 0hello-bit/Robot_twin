from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOLCHAIN_DIR = ROOT / "tools" / "camera_toolchain"
sys.path.insert(0, str(TOOLCHAIN_DIR))

import tile_auto_align  # noqa: E402
import fit_tile_controls  # noqa: E402


def test_target_axes_keep_the_full_board_inside_the_frame():
    x_targets, y_targets = tile_auto_align.safe_target_axes(
        width=1920, height=1080, inner_span_w=177, inner_span_h=111
    )

    board_square_w = 177 / (tile_auto_align.PATTERN[0] - 1)
    board_square_h = 111 / (tile_auto_align.PATTERN[1] - 1)

    assert x_targets[0] >= board_square_w
    assert y_targets[0] >= board_square_h
    assert x_targets[-1] + 177 + board_square_w <= 1920
    assert y_targets[-1] + 111 + board_square_h <= 1080
    assert x_targets[0] > 0
    assert y_targets[0] > 0


def test_overlay_window_text_is_ascii_safe():
    assert tile_auto_align.WINDOW_TITLE.isascii()
    assert tile_auto_align.PLACE_PROMPT.isascii()
    assert tile_auto_align.STATUS_PREFIX.isascii()


def test_preview_frame_explicitly_fits_a_1080p_frame():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    preview = tile_auto_align.make_preview_frame(frame, max_width=960, max_height=540)

    assert preview.shape[:2] == (540, 960)


def test_estimate_board_pose_recovers_small_in_plane_rotation():
    local = tile_auto_align.board_local_points()
    angle = np.deg2rad(4.0)
    rotation = np.array(
        [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
    )
    current = local @ rotation.T + np.array([120.0, 75.0])

    estimated_angle, tx, ty = tile_auto_align.estimate_board_pose(local, current)

    assert estimated_angle == pytest.approx(4.0, abs=1e-3)
    assert tx == pytest.approx(120.0, abs=1e-3)
    assert ty == pytest.approx(75.0, abs=1e-3)


def test_error_metrics_reports_percentile_summary():
    summary = fit_tile_controls.error_metrics([1.0, 2.0, 3.0, 4.0])

    assert summary["mean_mm"] == pytest.approx(2.5)
    assert summary["p50_mm"] == pytest.approx(2.5)
    assert summary["p95_mm"] == pytest.approx(3.85)
    assert summary["max_mm"] == pytest.approx(4.0)
