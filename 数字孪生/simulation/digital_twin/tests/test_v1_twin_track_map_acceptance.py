"""Acceptance tests: REAL track_bare.png under the approved C1 open route.

Task 4B-2 C1 单程开放路线：用户已冻结路线决定（只保留 C1，`发`字发车支线
进入后先向右，沿 12 锚点顺序到全黑终点标记）。本模块把 `route_selection.json`
作为唯一事实来源，对真实 track_bare.png 的最大分量（C1）调用
`extract_waypoint_constrained_centerline`，并验证生成的中心线满足开放路线
验收条件。

Algorithm-unit tests live in test_v1_twin_track_map.py on synthetic masks.
These tests validate the REAL artifact route: anchors snapped in order, no
blank-space jumps, medial-axis fidelity, open (not closed) topology, and
strict exclusion of C2—C7.

RED phase: without the frozen `route_selection.json` the contract test fails,
and without `extract_waypoint_constrained_centerline` the route cannot be built.

INPUT-EVIDENCE GATE (independent-review rework): `track_bare.png` is cropped
by the image border — the C1 mask touches the bottom edge (167 border pixels)
and 131 centerline points lie exactly on y=719. The route-algorithm gates all
pass on the cropped geometry, but the input evidence is not acceptable, so
`test_real_artifact_input_not_cropped` FAILS and the real map status is
BLOCKED_INPUT_CROPPED. Detector tests passing does NOT mean the real track
map is acceptable.
"""

from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np
import pytest

from v1_twin.v1_twin_track_map import (
    compute_border_coverage_metrics,
    compute_center_to_boundary_distance,
    extract_waypoint_constrained_centerline,
)
from v1_twin.v1_twin_calibration import HomographyTransform
from v1_twin.v1_twin_errors import V1SchemaError


# ── Test utilities ──────────────────────────────────────────────────────────

def _imread_unicode(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        data = f.read()
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Cannot decode: {path}")
    return img


def _load_route_selection():
    """Load the approved C1 open-route contract JSON (Task 4B-2 C1, C960 重验收).

    2026-08-03: track_bare.png 重采为 C960 垂直俯拍（新坐标），锚点在
    `docs/evidence/v1_task4b2_c1_c960_reacceptance/route_selection_c960.json`
    作为当前 C960 像素坐标契约。
    语义契约（C1 / 发车支线 / 12 锚点 / 全黑终点）不变，仅像素坐标随新帧更新。

    Returns the parsed dict, or None when the contract file is absent so the
    RED→GREEN contract test can report a clean failure.
    """
    project = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    path = os.path.join(
        project, "docs", "evidence", "v1_task4b2_c1_c960_reacceptance",
        "route_selection_c960.json",
    )
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_real_artifact_has_approved_c1_open_route_contract():
    """GATE: the frozen user decision must exist and carry the exact semantics.

    The portable C960 contract is the single source of truth consumed by the
    waypoint-constrained extractor and by the real-artifact acceptance gate.
    """
    route = _load_route_selection()
    assert route is not None, (
        "route_selection.json missing — the approved C1 open-route decision "
        "must be frozen before any acceptance run"
    )
    assert route["selected_components"] == ["C1"]
    assert route["route_type"] == "open_traversal_on_cyclic_mask"
    assert route["start_semantics"] == "launch_zone_FA_enter_then_turn_right"
    assert route["terminal_marker"] == "all_black"
    assert route["after_terminal_surface"] == "all_white"
    assert route["terminal_policy"] == "cross_marker_then_stop_on_white"
    assert route["semantic_branches"] == 0
    assert route["closed_loop"] is False
    assert route["waypoints_px"] == [
        [817, 558], [813, 457], [997, 453], [1062, 373],
        [1056, 146], [980, 86], [440, 97], [376, 264],
        [196, 425], [386, 645], [568, 452], [714, 458],
    ]


def _load_real_artifact():
    """Load the real track_bare.png mask and homography.

    Returns (mask_bin, homography_matrix, otsu_thresh) or skips if the files
    are missing.  mask_bin is the full cleaned binary mask (all components).
    """
    project = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    artifact_dir = os.path.join(
        project, "simulation", "digital_twin", "assets", "real_route")
    img_path = os.path.join(artifact_dir, "track_bare.png")
    homo_path = os.path.join(artifact_dir, "homography.json")

    if not os.path.exists(img_path):
        pytest.skip(f"Real artifact image not found: {img_path}")
    if not os.path.exists(homo_path):
        pytest.skip(f"Real homography not found: {homo_path}")

    img = _imread_unicode(img_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    otsu_thresh, mask_raw = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_clean = cv2.morphologyEx(mask_raw, cv2.MORPH_OPEN, kernel, iterations=1)
    mask_clean = cv2.morphologyEx(mask_clean, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask_bin = (mask_clean > 0).astype(np.uint8)

    with open(homo_path, "r") as f:
        homo_data = json.load(f)
    H = np.array(homo_data["homography"]["matrix"])

    return mask_bin, H, otsu_thresh


def _load_c1_mask(mask_bin: np.ndarray, waypoints_px, snap_radius: float) -> np.ndarray:
    """Extract C1 = 含锚点最多的连通分量（C960 重验收）。

    2026-08-03: 新 track_bare.png 背景有暗桌面/阴影，最大连通分量（旧实现）
    未必是赛道；用户沿赛道选定的锚点唯一标识赛道分量。向后兼容：锚点在
    最大分量内时结果与旧 largest_component 一致。
    """
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask_bin, connectivity=8
    )
    if n_labels <= 1:
        return mask_bin.copy()
    from collections import Counter
    votes: Counter = Counter()
    h, w = mask_bin.shape
    for (x, y) in waypoints_px:
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < w and 0 <= yi < h and labels[yi, xi] > 0:
            votes[int(labels[yi, xi])] += 1
            continue
        best, best_d = 0, snap_radius
        for c in range(1, n_labels):
            if stats[c, cv2.CC_STAT_AREA] < 4:
                continue
            cx = stats[c, cv2.CC_STAT_LEFT] + stats[c, cv2.CC_STAT_WIDTH] // 2
            cy = stats[c, cv2.CC_STAT_TOP] + stats[c, cv2.CC_STAT_HEIGHT] // 2
            d = math.hypot(cx - x, cy - y)
            if d < best_d:
                best, best_d = c, d
        if best > 0:
            votes[best] += 1
    if votes:
        chosen = votes.most_common(1)[0][0]
        return (labels == chosen).astype(np.uint8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(np.argmax(areas)) + 1
    return (labels == largest).astype(np.uint8)


def _extract_approved_centerline():
    """Run the approved-route pipeline on the real artifact.

    Returns (centerline_px, c1_mask, route).  The centerline is the ordered
    open point sequence produced by `extract_waypoint_constrained_centerline`
    from the frozen `route_selection.json` waypoints.
    """
    route = _load_route_selection()
    if route is None:
        pytest.skip("route_selection.json missing")
    mask_bin, H, _ = _load_real_artifact()
    c1_mask = _load_c1_mask(
        mask_bin, route["waypoints_px"], float(route["waypoint_snap_radius_px"])
    )
    centerline_px = extract_waypoint_constrained_centerline(
        c1_mask,
        tuple(tuple(p) for p in route["waypoints_px"]),
        snap_radius_px=float(route["waypoint_snap_radius_px"]),
        min_spur_length=10,
    )
    return centerline_px, c1_mask, route


def _nearest_point_indices(points, waypoints):
    """对每个 waypoint 返回其最近中心线点的索引（列表）。"""
    return [
        min(range(len(points)), key=lambda i: math.dist(points[i], wp))
        for wp in waypoints
    ]


# ── Approved-route acceptance gates ─────────────────────────────────────────


def test_real_artifact_c1_open_route_snaps_anchors_in_order():
    """GATE: 12 锚点按序出现，起点/终点落在锚点半径内，且不是闭环。

    RED until the approved route can be extracted from the real C1 mask.
    """
    centerline_px, c1_mask, route = _extract_approved_centerline()
    assert len(centerline_px) > 0, "approved route must not be empty"

    start_wp = tuple(route["waypoints_px"][0])
    finish_wp = tuple(route["waypoints_px"][-1])

    # 起点靠近发车锚点、终点位于全黑标记
    assert math.dist(centerline_px[0], start_wp) <= 60.0, (
        f"route start {centerline_px[0]} not within 60px of launch anchor {start_wp}"
    )
    assert math.dist(centerline_px[-1], finish_wp) <= 60.0, (
        f"route finish {centerline_px[-1]} not within 60px of finish anchor {finish_wp}"
    )

    # 12 个锚点按序且不重复
    indices = _nearest_point_indices(centerline_px, route["waypoints_px"])
    assert indices == sorted(indices), f"waypoints out of order: {indices}"
    assert len(set(indices)) == len(indices), f"waypoint indices not unique: {indices}"

    # 开放路线：起点到终点直线距离显著大于 0（非闭环）
    assert math.dist(centerline_px[0], centerline_px[-1]) > 100.0, (
        "start and finish are nearly coincident — route looks closed"
    )

    # 进入主赛道后先向右：锚点 2 -> 锚点 3 方向 dx > 0
    p2 = min(centerline_px, key=lambda p: math.dist(p, tuple(route["waypoints_px"][1])))
    p3 = min(centerline_px, key=lambda p: math.dist(p, tuple(route["waypoints_px"][2])))
    dx, dy = p3[0] - p2[0], p3[1] - p2[1]
    assert dx > 0, f"first turn after joining main track is not rightward (dx={dx:.1f})"
    assert abs(dy) <= abs(dx) + 1e-6, (
        f"first direction not predominantly rightward (dx={dx:.1f}, dy={dy:.1f})"
    )


def test_real_artifact_c1_open_route_no_blank_space_jumps():
    """GATE: 中心线连续、逐点跳变 ≤ 2px，且全部落在 C1 掩码内。

    No consecutive points may jump across blank space or leave the C1 mask.
    """
    centerline_px, c1_mask, route = _extract_approved_centerline()
    assert len(centerline_px) >= 2

    max_jump = max(
        math.dist(a, b) for a, b in zip(centerline_px, centerline_px[1:])
    )
    assert max_jump <= 2.0, (
        f"max consecutive jump {max_jump:.2f}px exceeds 2.0px — centerline "
        f"crosses blank space"
    )

    bad = [
        p for p in centerline_px
        if c1_mask[int(round(p[1])), int(round(p[0]))] != 1
    ]
    assert not bad, f"{len(bad)} centerline points lie outside the C1 mask"


def test_real_artifact_c1_open_route_is_medial():
    """GATE: 中心线贴近中轴，不贴边（min boundary distance ≥ 2px）。"""
    centerline_px, c1_mask, route = _extract_approved_centerline()
    assert len(centerline_px) > 0

    dists = compute_center_to_boundary_distance(centerline_px, c1_mask)
    nonzero = [d for d in dists if d > 0]
    assert nonzero, "all centerline points have zero boundary distance"

    min_dist = min(nonzero)
    median_dist = sorted(nonzero)[len(nonzero) // 2]

    assert min_dist >= 2.0, (
        f"centerline has contour-hugging points: min boundary distance "
        f"{min_dist:.1f}px"
    )
    estimated_width = median_dist * 2
    assert 5.0 <= estimated_width <= 50.0, (
        f"suspicious line width estimate {estimated_width:.0f}px "
        f"(median boundary distance {median_dist:.1f}px)"
    )


def test_real_artifact_c1_route_uses_only_c1():
    """GATE: 中心线只使用 C1，C2—C7 不进入路线。

    路线全部像素都必须在 C1（最大分量）掩码内；C2—C7 是与 C1 不相交的
    次要组件，因此绝无路线点落在其中。
    """
    centerline_px, c1_mask, route = _extract_approved_centerline()
    assert route["selected_components"] == ["C1"]
    assert len(centerline_px) > 0

    for x, y in centerline_px:
        row, col = int(round(y)), int(round(x))
        assert c1_mask[row, col] == 1, (
            f"route point ({x:.1f}, {y:.1f}) is not inside C1"
        )

    # C1 之外的任何前景像素都不应被路线占用（排除 C2—C7 语义）。
    mask_bin, H, _ = _load_real_artifact()
    not_c1 = (mask_bin > 0) & (c1_mask == 0)
    if np.any(not_c1):
        route_on_not_c1 = [
            p for p in centerline_px
            if not_c1[int(round(p[1])), int(round(p[0]))]
        ]
        assert not route_on_not_c1, (
            f"{len(route_on_not_c1)} route points fall on non-C1 components"
        )


def test_real_artifact_input_not_cropped():
    """INPUT-EVIDENCE GATE: 完整赛道俯视图必须四周留白、不接触图像边界。

    独立审核发现 track_bare.png 被画面底边裁切：C1 掩码接触底边 167 触点，
    131 个中心线点直接压在 y=719（左侧下弯被裁）。起点与终点在当前设计中
    都不应位于图像边界，故不设豁免。本测试对当前真实图片 FAIL，真实地图
    状态为 BLOCKED_INPUT_CROPPED——算法检测测试通过 ≠ 真实轨道地图通过。
    """
    centerline_px, c1_mask, route = _extract_approved_centerline()
    border = compute_border_coverage_metrics(c1_mask, centerline_px)
    assert border.input_cropped is False, (
        "input_cropped=True: track_bare.png is cropped by the image border "
        "(mask_border_touch_count=%d, route_border_point_count=%d, "
        "min_route_border_clearance_px=%.1f). The real track map is NOT "
        "acceptable; status=BLOCKED_INPUT_CROPPED. "
        "Re-capture a full track top view with margin on all sides."
        % (
            border.mask_border_touch_count,
            border.route_border_point_count,
            border.min_route_border_clearance_px,
        )
    )
    assert border.mask_border_touch_count == 0
    assert border.route_border_point_count == 0
    assert border.min_route_border_clearance_px > 2.0
