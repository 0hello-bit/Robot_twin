from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GUIDANCE_PATH = ROOT / "tools" / "camera_toolchain" / "camera_coverage_guidance.py"


def _load_guidance():
    spec = importlib.util.spec_from_file_location(
        "camera_coverage_guidance_under_test", GUIDANCE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_guidance_uses_four_by_four_ordered_targets():
    guidance = _load_guidance()

    assert guidance.GRID == 4
    assert len(guidance.TARGET_ORDER) == 16
    assert guidance.TARGET_ORDER[0] == (0, 0)
    assert guidance.TARGET_ORDER[-1] == (3, 3)


def test_cell_for_centroid_clamps_to_valid_grid_cells():
    guidance = _load_guidance()

    assert guidance.cell_for_centroid((240, 135), 1920, 1080) == (0, 0)
    assert guidance.cell_for_centroid((960, 540), 1920, 1080) == (2, 2)
    assert guidance.cell_for_centroid((1920, 1080), 1920, 1080) == (3, 3)


def test_next_target_skips_completed_cells_and_returns_none_when_done():
    guidance = _load_guidance()
    covered = [[False] * guidance.GRID for _ in range(guidance.GRID)]

    assert guidance.next_target(covered) == (0, 0)
    covered[0][0] = True
    assert guidance.next_target(covered) == (0, 1)

    for row, col in guidance.TARGET_ORDER:
        covered[row][col] = True
    assert guidance.next_target(covered) is None
