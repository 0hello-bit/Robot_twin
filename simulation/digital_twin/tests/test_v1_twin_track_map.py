"""Tests for 赛道地图提取 (mask/centerline/width) (Task 4B-2)。

先写测试后实现：模块尚不存在时应 RED。

使用合成二值掩码验证：
- 沿行/沿列提取中心线与宽度
- 空掩码 / 过细线段处理
- 像素坐标 -> mm 转换（identity / scale homography）
- validate_track_map 一致性检查
- V1TrackMap JSON 往返（复用 4B-0 schema）
"""

from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest

from v1_twin.v1_twin_track_map import (
    TrackMapExtraction,
    edit_track_map_point,
    extract_track_map,
    load_track_map,
    replace_centerline,
    save_track_map,
    to_v1_track_map,
    validate_track_map,
)
from v1_twin.v1_twin_schema import V1TrackMap
from v1_twin.v1_twin_errors import V1SchemaError
from v1_twin.v1_twin_calibration import HomographyTransform
from v1_twin.v1_twin_schema import V1TrackMap, to_json, from_json
from v1_twin.v1_twin_errors import V1SchemaError


# ============================================================
# 提取
# ============================================================


def _vertical_line_mask(width_px=5, x_center=50, size=100):
    """垂直黑线掩码：第 x_center 列附近 width_px 宽为 1。"""
    m = np.zeros((size, size), dtype=np.uint8)
    x0 = x_center - width_px // 2
    x1 = x0 + width_px
    m[:, x0:x1] = 1
    return m


def _horizontal_line_mask(width_px=4, y_center=60, size=100):
    m = np.zeros((size, size), dtype=np.uint8)
    y0 = y_center - width_px // 2
    y1 = y0 + width_px
    m[y0:y1, :] = 1
    return m


def test_extract_vertical_line_axis0():
    m = _vertical_line_mask(width_px=5, x_center=50)
    ex = extract_track_map(m, axis=0)
    assert ex.centerline_px, "centerline should not be empty"
    assert len(ex.centerline_px) == 100  # 每行一个点
    # 每行中心线 x=50，宽 5
    for (x, y), w in zip(ex.centerline_px, ex.width_px):
        assert x == pytest.approx(50.0)
        assert w == 5
    assert ex.width_px[0] == 5


def test_extract_horizontal_line_axis1():
    m = _horizontal_line_mask(width_px=4, y_center=60)
    # y0 = 60 - 4//2 = 58，rows 58..61，中点 = (58+61)/2 = 59.5
    ex = extract_track_map(m, axis=1)
    assert len(ex.centerline_px) == 100  # 每列一个点
    for (x, y), w in zip(ex.centerline_px, ex.width_px):
        assert y == pytest.approx(59.5)
        assert w == 4


def test_extract_empty_mask():
    m = np.zeros((50, 50), dtype=np.uint8)
    ex = extract_track_map(m)
    assert ex.centerline_px == ()
    assert ex.width_px == ()


def test_extract_min_run_filters_thin_line():
    m = np.zeros((20, 20), dtype=np.uint8)
    m[:, 10:11] = 1  # 1px 宽
    ex = extract_track_map(m, min_run=2)
    assert ex.centerline_px == ()
    ex2 = extract_track_map(m, min_run=1)
    assert len(ex2.centerline_px) == 20


def test_extract_diagonal_line():
    m = np.zeros((30, 30), dtype=np.uint8)
    for i in range(30):
        m[i, i] = 1  # 对角线段
    ex = extract_track_map(m, min_run=1)
    assert len(ex.centerline_px) == 30
    xs = [p[0] for p in ex.centerline_px]
    ys = [p[1] for p in ex.centerline_px]
    assert xs == pytest.approx(ys)  # 中心线沿对角线


# ============================================================
# 像素 -> mm 转换
# ============================================================


def test_to_v1_track_map_identity_homography():
    m = _vertical_line_mask(width_px=5, x_center=50)
    ex = extract_track_map(m)
    hom = HomographyTransform(np.eye(3))
    v1 = to_v1_track_map(ex, hom)
    assert v1.width_mm == pytest.approx(5.0)
    assert v1.centerline_mm[0][0] == pytest.approx(50.0)
    assert v1.centerline_mm[0][1] == pytest.approx(0.0)
    assert len(v1.centerline_mm) == 100


def test_to_v1_track_map_scale_homography():
    m = _vertical_line_mask(width_px=5, x_center=50)
    ex = extract_track_map(m)
    scale = 0.1  # 1px -> 0.1mm
    hom = HomographyTransform(np.diag([scale, scale, 1.0]))
    v1 = to_v1_track_map(ex, hom)
    assert v1.width_mm == pytest.approx(0.5)
    assert v1.centerline_mm[0][0] == pytest.approx(5.0)


def test_to_v1_track_map_mask_is_binary_nested():
    m = _vertical_line_mask(width_px=5, x_center=50)
    ex = extract_track_map(m)
    hom = HomographyTransform(np.eye(3))
    v1 = to_v1_track_map(ex, hom)
    assert isinstance(v1.mask, tuple)
    assert isinstance(v1.mask[0], tuple)
    assert set(v1.mask[0]) <= {0, 1}


# ============================================================
# validate
# ============================================================


def test_validate_passes_on_valid_map():
    m = _vertical_line_mask(width_px=5, x_center=50)
    ex = extract_track_map(m)
    v1 = to_v1_track_map(ex, HomographyTransform(np.eye(3)))
    validate_track_map(v1)  # 不应抛异常
    validate_track_map(v1, max_centerline_jump_mm=10.0)


def test_validate_empty_centerline_raises():
    v1 = V1TrackMap(
        mask=((0, 1), (1, 0)),
        centerline_mm=(),
        width_mm=5.0,
    )
    with pytest.raises(V1SchemaError):
        validate_track_map(v1)


def test_validate_jump_detected():
    v1 = V1TrackMap(
        mask=((0, 1), (1, 0)),
        centerline_mm=((0.0, 0.0), (100.0, 0.0)),  # 跳变 100mm
        width_mm=5.0,
    )
    with pytest.raises(V1SchemaError):
        validate_track_map(v1, max_centerline_jump_mm=10.0)
    # 不给阈值时不检查跳变
    validate_track_map(v1)


# ============================================================
# schema 往返（复用 4B-0）
# ============================================================


def test_track_map_schema_json_round_trip():
    m = _vertical_line_mask(width_px=5, x_center=10, size=20)
    ex = extract_track_map(m)
    v1 = to_v1_track_map(ex, HomographyTransform(np.eye(3)))
    restored = from_json(to_json(v1), V1TrackMap)
    assert restored == v1
    assert restored.width_mm == pytest.approx(v1.width_mm)


# ============================================================
# 轨道地图持久化与编辑接口（用户可后续修改轨道）
# ============================================================


def _sample_map():
    mask = ((0, 0, 0, 0), (0, 1, 1, 0), (0, 1, 1, 0), (0, 0, 0, 0))
    center = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    return V1TrackMap(mask=mask, centerline_mm=center, width_mm=4.0)


def test_save_load_track_map_round_trip(tmp_path):
    v1 = _sample_map()
    path = str(tmp_path / "track_map.json")
    save_track_map(v1, path)
    loaded = load_track_map(path)
    assert loaded == v1
    assert loaded.centerline_mm == v1.centerline_mm
    assert loaded.width_mm == pytest.approx(v1.width_mm)


def test_edit_track_map_point(tmp_path):
    v1 = _sample_map()
    edited = edit_track_map_point(v1, index=2, x_mm=5.0, y_mm=7.0)
    assert edited.centerline_mm[2] == (5.0, 7.0)
    # 其余点不变
    assert edited.centerline_mm[0] == (0.0, 0.0)
    assert edited.centerline_mm[1] == (1.0, 0.0)
    assert edited.centerline_mm[3] == (0.0, 1.0)
    # 原对象不可变
    assert v1.centerline_mm[2] == (1.0, 1.0)


def test_edit_track_map_point_out_of_range():
    v1 = _sample_map()
    with pytest.raises(IndexError):
        edit_track_map_point(v1, index=99, x_mm=0.0, y_mm=0.0)


def test_edit_track_map_point_invalid_value():
    v1 = _sample_map()
    with pytest.raises(V1SchemaError):
        edit_track_map_point(v1, index=0, x_mm=float("nan"), y_mm=0.0)


def test_replace_centerline():
    v1 = _sample_map()
    new_center = ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0))
    edited = replace_centerline(v1, new_center)
    assert edited.centerline_mm == tuple(new_center)
    assert edited.width_mm == pytest.approx(v1.width_mm)
    with pytest.raises(V1SchemaError):
        replace_centerline(v1, ())


# ============================================================
# 中心线拓扑与几何验证测试 (Task 4B-2 Reacceptance — RED → GREEN)
# ============================================================


def _ring_mask(outer_r=40, inner_r=25, size=100):
    """合成环形赛道掩码（闭环，无分支）。"""
    m = np.zeros((size, size), dtype=np.uint8)
    cy, cx = size / 2.0, size / 2.0
    for y in range(size):
        for x in range(size):
            d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            if inner_r <= d <= outer_r:
                m[y, x] = 1
    return m


def _curved_line_mask(size=100, line_width=10):
    """合成弯曲路径掩码（无分支，非闭环）。"""
    m = np.zeros((size, size), dtype=np.uint8)
    for y in range(10, size - 10):
        cx = int(size / 2 + 15 * math.sin(y / 8.0))
        x0 = max(0, cx - line_width // 2)
        x1 = min(size, cx + line_width // 2)
        m[y, x0:x1] = 1
    return m


def _branched_mask(size=100):
    """合成有分支的掩码：主竖线 + 一条水平分支。"""
    m = np.zeros((size, size), dtype=np.uint8)
    m[:, 48:52] = 1        # 主竖线
    m[48:52, 30:52] = 1    # 向左分支
    return m


def _mask_with_spur(size=100):
    """合成带短毛刺的掩码：主竖线 + 短突起。"""
    m = np.zeros((size, size), dtype=np.uint8)
    m[:, 45:55] = 1        # 主轨道 宽10
    m[30:35, 55:58] = 1    # 3px 宽短毛刺
    return m


# 中心到边界距离测试

def test_center_to_boundary_computes_distance():
    """RED: compute_center_to_boundary_distance 不存在时应 ImportError。"""
    from v1_twin.v1_twin_track_map import compute_center_to_boundary_distance

    mask = _ring_mask()
    # 环中轴在半径 32.5 处，点 (50, 17.5) ≈ 在环掩码内部
    # 距离 = 32.5 - 25 = 7.5（到内边界）或 40 - 32.5 = 7.5（到外边界）
    distances = compute_center_to_boundary_distance(
        ((50.0, 50.0 + 32.5),), mask  # (50, 82.5) 在环中轴上
    )
    assert len(distances) == 1
    assert 5.0 <= distances[0] <= 12.0, f"distance={distances[0]:.2f}"


def test_center_to_boundary_edge_point_rejected():
    """RED: 贴边点应被识别为"不在中心"。"""
    from v1_twin.v1_twin_track_map import compute_center_to_boundary_distance

    mask = _ring_mask()
    # 点在环外边界附近
    distances = compute_center_to_boundary_distance(
        ((10.0, 50.0),), mask
    )
    # 贴边点到边界的距离应很小
    assert distances[0] < 3.0, "贴边点应有很小的边界距离"


# 中心线连续性测试

def test_validate_centerline_continuity_passes_smooth():
    """RED: 连续点列应通过连续性检查。"""
    from v1_twin.v1_twin_track_map import validate_centerline_continuity

    points = tuple((float(i), float(i)) for i in range(100))
    # 应不抛异常
    validate_centerline_continuity(points, max_jump=5.0)


def test_validate_centerline_continuity_detects_jump():
    """RED: 跨越空白区域的跳变应被检测。"""
    from v1_twin.v1_twin_track_map import validate_centerline_continuity

    points = ((0.0, 0.0), (1.0, 0.0), (100.0, 0.0), (101.0, 0.0))
    with pytest.raises(V1SchemaError, match="jump"):
        validate_centerline_continuity(points, max_jump=5.0)


def test_validate_centerline_continuity_empty():
    """RED: 空点列不抛异常（无跳变可检）。"""
    from v1_twin.v1_twin_track_map import validate_centerline_continuity
    validate_centerline_continuity((), max_jump=5.0)  # 不应抛异常


# 短毛刺检测/剔除测试

def test_prune_short_spurs_detects_spur():
    """毛刺剔除法：隔离的小组件（< min_branch_length）应被删除。"""
    from v1_twin.v1_twin_track_map import prune_short_spurs

    # 主路径：密集点列
    main = tuple((float(i), 0.0) for i in range(0, 100))
    # 毛刺：孤立的小组件（3 个点，远离主路径）
    spur = ((200.0, 0.0), (201.0, 0.0), (202.0, 0.0))
    all_points = main + spur
    pruned = prune_short_spurs(all_points, min_branch_length=5)
    # 毛刺组件应被剔除
    for sp in spur:
        assert sp not in pruned, f"毛刺点 {sp} 应被剔除"
    # 主路径应全部保留
    assert len(pruned) == 100


def test_prune_short_spurs_preserves_main_path():
    """RED: 主路径应被保留。"""
    from v1_twin.v1_twin_track_map import prune_short_spurs

    centerline = tuple((float(i), 0.0) for i in range(20))
    pruned = prune_short_spurs(centerline, min_branch_length=3)
    assert len(pruned) == 20


# 拓扑分析测试

def test_compute_centerline_topology_simple_path():
    """RED: compute_centerline_topology 不存在时应 ImportError。"""
    from v1_twin.v1_twin_track_map import compute_centerline_topology

    points = tuple((float(i), 0.0) for i in range(10))
    topo = compute_centerline_topology(points, connection_radius=1.5)
    assert topo["component_count"] == 1
    assert len(topo["endpoints"]) == 2  # 起点 + 终点
    assert len(topo["branch_nodes"]) == 0


def test_compute_centerline_topology_branched():
    """RED: 分支拓扑应被检测。"""
    from v1_twin.v1_twin_track_map import compute_centerline_topology

    # 主竖线 + 分支
    main = tuple((50.0, float(y)) for y in range(0, 30))
    branch = ((50.0, 15.0), (30.0, 15.0), (10.0, 15.0))  # 从 (50,15) 分叉
    points = main + branch
    topo = compute_centerline_topology(points, connection_radius=2.0)
    assert topo["component_count"] >= 1
    # 分支点 (50,15) 连接到 3 个点 (上、下、左)
    assert len(topo["branch_nodes"]) >= 1


def test_compute_centerline_topology_closed_loop():
    """RED: 闭环应无端点。"""
    from v1_twin.v1_twin_track_map import compute_centerline_topology
    import math as _math

    # 小圆环点列（间距 ≈ 1.0，不重复首尾）
    n = 20
    radius = 3.0  # 小半径，相邻点间距 ≈ 2*pi*3/20 ≈ 0.94
    points = tuple(
        (10.0 + radius * _math.cos(2 * _math.pi * i / n),
         10.0 + radius * _math.sin(2 * _math.pi * i / n))
        for i in range(n)
    )

    topo = compute_centerline_topology(points, connection_radius=1.5)
    assert topo["component_count"] == 1, f"应 1 个组件，实际 {topo['component_count']}"
    assert len(topo["endpoints"]) == 0, f"闭环应无端点，实际 {len(topo['endpoints'])}"
    assert len(topo["branch_nodes"]) == 0, f"闭环应无分支节点，实际 {len(topo['branch_nodes'])}"


# 中轴中心线提取测试

def test_extract_medial_centerline_ring():
    """RED: extract_medial_centerline 不存在时应 ImportError。"""
    from v1_twin.v1_twin_track_map import extract_medial_centerline

    mask = _ring_mask()
    centerline = extract_medial_centerline(mask)
    assert len(centerline) > 0, "环掩码应有中心线"
    # 所有点应在掩码内部
    for x, y in centerline:
        xi, yi = int(round(y)), int(round(x))
        assert 0 <= xi < mask.shape[0] and 0 <= yi < mask.shape[1]
        assert mask[xi, yi] == 1, f"点 ({x:.1f}, {y:.1f}) 不在掩码内"


def test_extract_medial_centerline_curved():
    """RED: 弯曲路径应有连续中心线。"""
    from v1_twin.v1_twin_track_map import extract_medial_centerline

    mask = _curved_line_mask()
    centerline = extract_medial_centerline(mask)
    assert len(centerline) >= 10, "弯曲路径应有足够中心线点"


def test_extract_medial_centerline_empty_mask():
    """RED: 空掩码应返回空中心线。"""
    from v1_twin.v1_twin_track_map import extract_medial_centerline

    mask = np.zeros((50, 50), dtype=np.uint8)
    centerline = extract_medial_centerline(mask)
    assert len(centerline) == 0


def test_extract_medial_centerline_thin_line():
    """RED: 细线 (3px) 应有单像素宽中心线。"""
    from v1_twin.v1_twin_track_map import extract_medial_centerline

    mask = np.zeros((50, 50), dtype=np.uint8)
    mask[:, 25:28] = 1  # 3px 宽竖线
    centerline = extract_medial_centerline(mask)
    assert len(centerline) > 0
    # 中心线 x 坐标应接近 26（中间列）
    xs = [p[0] for p in centerline]
    mean_x = sum(xs) / len(xs)
    assert 25.5 <= mean_x <= 27.5, f"中心线 x 均值 {mean_x:.2f} 不在 25.5-27.5"
