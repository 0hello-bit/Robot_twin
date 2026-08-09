"""Pure helpers for the guided checkerboard coverage overlay."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple


GRID = 4
Cell = Tuple[int, int]
TARGET_ORDER: tuple[Cell, ...] = tuple(
    (row, col) for row in range(GRID) for col in range(GRID)
)


def cell_for_centroid(
    centroid: Sequence[float], width: int, height: int, grid: int = GRID
) -> Cell:
    """Return the clamped row/column cell containing a board centroid."""
    if width <= 0 or height <= 0 or grid <= 0:
        raise ValueError("width, height, and grid must be positive")
    x, y = float(centroid[0]), float(centroid[1])
    col = max(0, min(grid - 1, int(x / width * grid)))
    row = max(0, min(grid - 1, int(y / height * grid)))
    return row, col


def cell_bounds(
    cell: Cell, width: int, height: int, grid: int = GRID
) -> tuple[int, int, int, int]:
    """Return pixel bounds (x0, y0, x1, y1) for a coverage cell."""
    row, col = cell
    if not (0 <= row < grid and 0 <= col < grid):
        raise ValueError("cell is outside the grid")
    x0 = round(col * width / grid)
    y0 = round(row * height / grid)
    x1 = round((col + 1) * width / grid)
    y1 = round((row + 1) * height / grid)
    return x0, y0, x1, y1


def next_target(
    covered: Sequence[Sequence[bool]],
    order: Iterable[Cell] = TARGET_ORDER,
) -> Optional[Cell]:
    """Return the next unvisited cell in deterministic row-major order."""
    for row, col in order:
        if not covered[row][col]:
            return row, col
    return None


def target_number(cell: Cell, order: Sequence[Cell] = TARGET_ORDER) -> int:
    """Return the one-based number shown in the overlay."""
    return order.index(cell) + 1
