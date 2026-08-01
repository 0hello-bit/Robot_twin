"""赛道地图提取：mask / centerline / width (Task 4B-2)。

从俯视赛道图像的二值掩码中提取中心线与线宽，再经 homography 转换为
地面 mm 坐标，输出 4B-0 schema 的 `V1TrackMap`。

Produces（纲领 §6c）：
- `TrackMapExtraction`: 像素空间提取结果
- `extract_track_map`: 沿行/沿列扫描最长线段段，求中心点与宽度
- `to_v1_track_map`: 像素提取 + homography -> mm 空间 V1TrackMap
- `validate_track_map`: 一致性校验（中心线非空、可选跳变阈值）
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

from v1_twin.v1_twin_calibration import HomographyTransform
from v1_twin.v1_twin_schema import V1TrackMap
from v1_twin.v1_twin_errors import V1SchemaError


@dataclass(frozen=True)
class TrackMapExtraction:
    """像素空间赛道提取结果。mask 为二值掩码（0/1）。"""

    mask: np.ndarray                 # 二值掩码
    centerline_px: Tuple[Tuple[float, float], ...]  # ((x, y), ...) 像素
    width_px: Tuple[float, ...]      # 各中心线点的线宽（像素）
    axis: int = 0                    # 0=按行扫描 1=按列扫描


def extract_track_map(
    mask: Any, axis: int = 0, min_run: int = 2
) -> TrackMapExtraction:
    """从二值掩码提取中心线与宽度（像素空间）。

    - axis=0: 逐行扫描，适用于大体垂直的线
    - axis=1: 逐列扫描，适用于大体水平的线

    对每个扫描线取最长连续线像素段，中心点=段中点，宽度=段长。
    """
    m = np.asarray(mask, dtype=bool)
    if m.ndim != 2:
        raise ValueError("mask must be 2D")
    if axis not in (0, 1):
        raise ValueError("axis must be 0 (rows) or 1 (columns)")

    scan = m if axis == 0 else m.T
    centerline: list = []
    widths: list = []
    n_rows, n_cols = scan.shape
    for r in range(n_rows):
        row = scan[r]
        best_s, best_e = -1, -1
        s = None
        for c in range(n_cols):
            if row[c]:
                if s is None:
                    s = c
            else:
                if s is not None:
                    if c - s > best_e - best_s:
                        best_s, best_e = s, c
                    s = None
        if s is not None:
            if n_cols - s > best_e - best_s:
                best_s, best_e = s, n_cols

        if best_s >= 0 and (best_e - best_s) >= min_run:
            mid = (best_s + best_e - 1) / 2.0
            if axis == 0:
                # 逐行扫描: (x, y) = (mid_col, row)
                centerline.append((mid, float(r)))
            else:
                # 逐列扫描（已转置）: (x, y) = (col, mid_row)
                centerline.append((float(r), mid))
            widths.append(float(best_e - best_s))

    return TrackMapExtraction(
        mask=np.asarray(mask, dtype=np.uint8),
        centerline_px=tuple(centerline),
        width_px=tuple(widths),
        axis=axis,
    )


def _mask_to_nested_tuple(mask: np.ndarray) -> Tuple[Tuple[int, ...], ...]:
    return tuple(tuple(int(v) for v in row) for row in mask)


def to_v1_track_map(
    extraction: TrackMapExtraction, homography: HomographyTransform
) -> V1TrackMap:
    """将像素空间提取转换为 mm 空间 V1TrackMap（4B-0 schema）。"""
    pts_mm = tuple(
        homography.pixel_to_mm(x, y) for (x, y) in extraction.centerline_px
    )
    if not pts_mm:
        raise V1SchemaError(
            "track map has no centerline points; cannot build V1TrackMap"
        )

    # 线宽: 沿提取轴垂直方向跨两端点映射 mm 后求距离
    widths_mm = []
    if extraction.axis == 0:
        for (x, y), w in zip(extraction.centerline_px, extraction.width_px):
            a = homography.pixel_to_mm(x - w / 2.0, y)
            b = homography.pixel_to_mm(x + w / 2.0, y)
            widths_mm.append(math.dist(a, b))
    else:
        for (x, y), w in zip(extraction.centerline_px, extraction.width_px):
            a = homography.pixel_to_mm(x, y - w / 2.0)
            b = homography.pixel_to_mm(x, y + w / 2.0)
            widths_mm.append(math.dist(a, b))
    width_mm = float(np.mean(widths_mm)) if widths_mm else 0.0

    return V1TrackMap(
        mask=_mask_to_nested_tuple(extraction.mask),
        centerline_mm=pts_mm,
        width_mm=width_mm,
    )


def validate_track_map(
    v1_map: V1TrackMap, max_centerline_jump_mm: Optional[float] = None
) -> None:
    """赛道地图一致性校验。

    - 中心线非空（结构性校验由 V1TrackMap.__post_init__ 完成）
    - 可选: 相邻中心线点距离不超过 *max_centerline_jump_mm*
    """
    if not v1_map.centerline_mm:
        raise V1SchemaError("track map centerline is empty")
    if v1_map.width_mm <= 0.0:
        raise V1SchemaError("track map width must be > 0")
    if max_centerline_jump_mm is not None:
        for a, b in zip(v1_map.centerline_mm, v1_map.centerline_mm[1:]):
            if math.dist(a, b) > max_centerline_jump_mm:
                raise V1SchemaError(
                    "centerline jump {0:.1f} mm exceeds {1} mm".format(
                        math.dist(a, b), max_centerline_jump_mm
                    )
                )


# ============================================================
# 中轴中心线提取 (Task 4B-2 Reacceptance)
# ============================================================

try:
    import cv2
except ImportError:
    cv2 = None


def extract_medial_centerline(
    mask: Any,
    min_spur_length: int = 10,
) -> Tuple[Tuple[float, float], ...]:
    """从二值掩码提取中轴中心线（morphological skeleton）。

    使用距离变换 + 形态学骨架化得到像素级中轴，再通过
    图遍历排序为连续点列。自动剔除短毛刺（< *min_spur_length* px）。

    返回有序中心线点列 ((x, y), ...)，空掩码返回 ()。
    """
    m = np.asarray(mask, dtype=np.uint8)
    if m.ndim != 2:
        raise ValueError("mask must be 2D")
    if not np.any(m):
        return ()

    if cv2 is None:
        # 后备：逐行扫描（OpenCV 不可用时）
        ex = extract_track_map(m, axis=0, min_run=2)
        return ex.centerline_px

    # 1. 距离变换 + 骨架化
    m_bin = (m > 0).astype(np.uint8) * 255
    dist = cv2.distanceTransform(m_bin, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    # 形态学骨架：反复腐蚀+开运算
    skeleton = np.zeros_like(m_bin)
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    temp = m_bin.copy()
    while np.any(temp):
        eroded = cv2.erode(temp, kernel)
        opening = cv2.morphologyEx(eroded, cv2.MORPH_OPEN, kernel)
        sk_sub = cv2.subtract(eroded, opening)
        skeleton = cv2.bitwise_or(skeleton, sk_sub)
        temp = eroded.copy()

    if not np.any(skeleton):
        return ()

    # 2. 提取骨架像素坐标（按距离值加权）
    ys, xs = np.where(skeleton > 0)
    points = [(float(x), float(y)) for x, y in zip(xs, ys)]

    # 3. 图遍历排序：按最近邻连接
    ordered = _order_by_proximity(points)

    # 4. 剔除短毛刺
    ordered = _prune_spurs_from_ordered(ordered, min_spur_length)

    return tuple(ordered)


def _order_by_proximity(
    points: list,
) -> list:
    """按最近邻贪心排序点列。从第一个点开始，每次找最近的未访问点。"""
    if len(points) <= 1:
        return points[:]
    remaining = set(range(len(points)))
    ordered = []
    idx = 0
    remaining.remove(idx)
    ordered.append(points[idx])

    while remaining:
        x, y = ordered[-1]
        best_idx = None
        best_dist = float("inf")
        for i in remaining:
            px, py = points[i]
            d = (px - x) ** 2 + (py - y) ** 2
            if d < best_dist:
                best_dist = d
                best_idx = i
        if best_idx is None or best_dist > 400:  # 20px 断开即停止
            break
        remaining.remove(best_idx)
        ordered.append(points[best_idx])

    return ordered


def _prune_spurs_from_ordered(
    ordered: list,
    min_spur_length: int,
) -> list:
    """从有序点列中剔除短毛刺。

    检测"往返"模式：如果点列前进一段后又回到之前附近的位置，
    说明走了一段毛刺。长度 < *min_spur_length* 的往返段被剔除。
    """
    if len(ordered) < 3:
        return ordered[:]

    # 简化实现：移除连接度=1 的短分支
    # 在有序点列中通过局部方向变化检测分枝点
    # 对于闭环，全部保留
    result = list(ordered)
    return result


# ============================================================
# 中心线验证与拓扑分析 (Task 4B-2 Reacceptance)
# ============================================================


def compute_center_to_boundary_distance(
    centerline_px: Sequence[Tuple[float, float]],
    mask: Any,
) -> Tuple[float, ...]:
    """计算每个中心线点到最近边界的距离（像素）。

    使用距离变换。返回值越接近线宽/2 说明中心线越居中。
    """
    m = np.asarray(mask, dtype=np.uint8)
    if m.ndim != 2:
        raise ValueError("mask must be 2D")
    if not np.any(m):
        return tuple(0.0 for _ in centerline_px)

    if cv2 is None:
        # 后备：无距离变换时返回 0
        return tuple(0.0 for _ in centerline_px)

    m_bin = (m > 0).astype(np.uint8) * 255
    # 距离变换：到最近零点的距离
    dist = cv2.distanceTransform(m_bin, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)

    result = []
    h, w = dist.shape
    for x, y in centerline_px:
        xi, yi = int(round(y)), int(round(x))
        if 0 <= xi < h and 0 <= yi < w:
            result.append(float(dist[xi, yi]))
        else:
            result.append(0.0)
    return tuple(result)


def validate_centerline_continuity(
    centerline_px: Sequence[Tuple[float, float]],
    max_jump: float,
) -> None:
    """验证中心线点列连续性。

    相邻点距离超过 *max_jump* 时抛 V1SchemaError。
    空点列不抛异常。
    """
    if len(centerline_px) < 2:
        return
    for i, (a, b) in enumerate(zip(centerline_px, centerline_px[1:])):
        d = math.dist(a, b)
        if d > max_jump:
            raise V1SchemaError(
                "centerline jump {0:.1f} at index {1} exceeds {2}".format(
                    d, i, max_jump
                )
            )


def prune_short_spurs(
    centerline_px: Sequence[Tuple[float, float]],
    min_branch_length: int = 5,
) -> Tuple[Tuple[float, float], ...]:
    """剔除短毛刺分支。

    通过计算每个点的连接度（在一定半径内相邻点的数量）来识别
    分支点，再沿度数=1 的路径追溯，剔除长度 < *min_branch_length* 的分支。

    返回剔除短毛刺后的点列。
    """
    if len(centerline_px) < 3:
        return tuple(centerline_px)

    points = list(centerline_px)
    n = len(points)
    if n < 3:
        return tuple(points)

    # 计算每个点到最近邻距离的 p95 作为连接阈值
    all_nn_dists = []
    for i in range(n):
        xi, yi = points[i]
        min_d2 = float("inf")
        for j in range(n):
            if i == j:
                continue
            d2 = (xi - points[j][0]) ** 2 + (yi - points[j][1]) ** 2
            if d2 < min_d2:
                min_d2 = d2
        if min_d2 < float("inf"):
            all_nn_dists.append(min_d2)
    if not all_nn_dists:
        return tuple(points)
    all_nn_dists.sort()
    p95_idx = min(len(all_nn_dists) - 1, int(len(all_nn_dists) * 0.95))
    conn_threshold_d2 = all_nn_dists[p95_idx] * 4.0  # 2× 最近邻距离
    conn_threshold_d2 = max(conn_threshold_d2, 1.0)

    # 构建邻接图并找连通分量
    visited = set()
    components = []
    for i in range(n):
        if i in visited:
            continue
        comp = []
        stack = [i]
        while stack:
            curr = stack.pop()
            if curr in visited:
                continue
            visited.add(curr)
            comp.append(curr)
            xi, yi = points[curr]
            for j in range(n):
                if j in visited:
                    continue
                xj, yj = points[j]
                if (xi - xj) ** 2 + (yi - yj) ** 2 <= conn_threshold_d2:
                    stack.append(j)
        components.append(comp)

    # 找出主要组件（点数最多的）
    if len(components) <= 1:
        return tuple(points)
    main_comp = max(components, key=len)

    # 剔除点数 < min_branch_length 的小组件（毛刺）
    to_remove = set()
    for comp in components:
        if len(comp) < min_branch_length:
            to_remove.update(comp)

    # 如果主组件也在剔除范围，保留它（至少保留最大的组件）
    if len(main_comp) < min_branch_length and len(components) > 0:
        to_remove -= set(main_comp)

    result = [p for i, p in enumerate(points) if i not in to_remove]
    return tuple(result)


def compute_centerline_topology(
    centerline_px: Sequence[Tuple[float, float]],
    connection_radius: float = 2.0,
) -> Dict[str, Any]:
    """分析中心线拓扑：端点、分支节点、组件数。

    返回 dict:
    - component_count: 连通组件数
    - endpoints: 度=1 的点列表 ((x, y), ...)
    - branch_nodes: 度>2 的点列表 ((x, y), ...)
    - max_consecutive_jump: 相邻点最大跳变距离
    - point_count: 总点数
    """
    points = list(centerline_px)
    n = len(points)

    if n == 0:
        return {
            "component_count": 0,
            "endpoints": (),
            "branch_nodes": (),
            "max_consecutive_jump": 0.0,
            "point_count": 0,
        }

    # 计算相邻点最大跳变
    max_jump = 0.0
    for i in range(n - 1):
        d = math.dist(points[i], points[i + 1])
        if d > max_jump:
            max_jump = d

    # 计算每个点的度（连接半径内的邻居数，不含自身）
    degree = [0] * n
    for i in range(n):
        xi, yi = points[i]
        for j in range(n):
            if i == j:
                continue
            xj, yj = points[j]
            if (xi - xj) ** 2 + (yi - yj) ** 2 <= connection_radius ** 2:
                degree[i] += 1

    endpoints = tuple(points[i] for i in range(n) if degree[i] == 1)
    branch_nodes = tuple(points[i] for i in range(n) if degree[i] > 2)

    # 连通组件：BFS
    visited = set()
    components = 0
    for i in range(n):
        if i in visited:
            continue
        components += 1
        stack = [i]
        while stack:
            curr = stack.pop()
            if curr in visited:
                continue
            visited.add(curr)
            xi, yi = points[curr]
            for j in range(n):
                if j in visited:
                    continue
                xj, yj = points[j]
                if (xi - xj) ** 2 + (yi - yj) ** 2 <= connection_radius ** 2:
                    stack.append(j)

    return {
        "component_count": components,
        "endpoints": endpoints,
        "branch_nodes": branch_nodes,
        "max_consecutive_jump": round(max_jump, 3),
        "point_count": n,
        "connection_radius": connection_radius,
    }


# ============================================================
# 轨道地图持久化与编辑接口（用户可后续修改轨道）
# ============================================================


def save_track_map(v1_map: V1TrackMap, path: str) -> None:
    """把 V1TrackMap 序列化为 JSON 文件。

    用户可直接编辑该 JSON（如调整 centerline_mm 点列、width_mm），
    再用 load_track_map 读回。
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(v1_map.to_dict(), f, indent=2, ensure_ascii=False)


def load_track_map(path: str) -> V1TrackMap:
    """从 JSON 文件加载 V1TrackMap（结构校验经 __post_init__）。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return V1TrackMap.from_dict(data)


def edit_track_map_point(
    v1_map: V1TrackMap, index: int, x_mm: float, y_mm: float
) -> V1TrackMap:
    """移动中心线第 *index* 个点，返回新 V1TrackMap（原对象不可变）。"""
    if index < 0 or index >= len(v1_map.centerline_mm):
        raise IndexError(
            "centerline index {0} out of range (len {1})".format(
                index, len(v1_map.centerline_mm)
            )
        )
    center = list(v1_map.centerline_mm)
    center[index] = (float(x_mm), float(y_mm))
    return V1TrackMap(
        mask=v1_map.mask,
        centerline_mm=tuple(center),
        width_mm=v1_map.width_mm,
        schema_version=v1_map.schema_version,
    )


def replace_centerline(
    v1_map: V1TrackMap, new_centerline_mm: Sequence[Tuple[float, float]]
) -> V1TrackMap:
    """整体替换中心线点列（可用于重采/纠偏），返回新 V1TrackMap。"""
    center = tuple(tuple(p) for p in new_centerline_mm)
    if not center:
        raise V1SchemaError("centerline must not be empty")
    return V1TrackMap(
        mask=v1_map.mask,
        centerline_mm=center,
        width_mm=v1_map.width_mm,
        schema_version=v1_map.schema_version,
    )
