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
from collections import deque
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


def _thin_skeleton_to_1px(skeleton: np.ndarray) -> np.ndarray:
    """将形态学骨架细化至 1px 宽度（仅移除同行相邻重复）。

    形态学骨架在偶数宽度区域可能产生 2px 宽的水平段。
    对每行中相邻的两个骨架像素，保留更靠近该行骨架中位数的像素。
    不做垂直方向细化（垂直相邻是线段的自然延伸，不应移除）。
    """
    sk = (skeleton > 0).astype(np.uint8)
    h, w = sk.shape

    for y in range(h):
        row_indices = np.where(sk[y] > 0)[0]
        if len(row_indices) <= 1:
            continue
        # 该行骨架像素的中位数
        median_x = int(np.median(row_indices))
        for i in range(len(row_indices) - 1):
            x1, x2 = row_indices[i], row_indices[i + 1]
            if x2 - x1 == 1:
                # 相邻：保留更靠近中位数的
                if abs(x1 - median_x) <= abs(x2 - median_x):
                    sk[y, x2] = 0
                else:
                    sk[y, x1] = 0

    return (sk * 255).astype(np.uint8)


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

    # 1. 提取最大掩码连通分量（避免从非赛道区域提取骨架）
    m_bin = (m > 0).astype(np.uint8)
    m_work = _extract_main_mask_region(m_bin)

    m_vis = (m_work * 255).astype(np.uint8)

    # 2. 距离变换 + 骨架化（使用 Zhang-Suen 细化，连接性更好）
    # Zhang-Suen 比形态学骨架更不易碎片化
    skeleton = _zhang_suen_thinning(m_vis)

    if not np.any(skeleton):
        return ()

    # 2b. 细化骨架至 1px 宽度（移除水平/垂直相邻重复像素）
    skeleton = _thin_skeleton_to_1px(skeleton)
    if not np.any(skeleton):
        return ()

    # 3. 基于骨架图像 8-邻接图构建连通分量并图遍历排序
    ordered = _traverse_skeleton_graph(skeleton, min_spur_length)

    # 4. 通过掩码桥接骨架间隙：合并掩码连续的相邻骨架分量
    ordered = _bridge_skeleton_gaps_via_mask(ordered, m_work, bridge_max_px=100)

    return tuple(ordered)


def _extract_main_mask_region(mask_bin: np.ndarray) -> np.ndarray:
    """从掩码中提取主赛道路径区域（最大连通分量）。

    返回仅含主分量的二值掩码（0/1）。
    若最大分量占比 ≥ 50%，则只保留最大分量；
    否则返回原掩码（可能有多条分离赛道）。
    """
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask_bin, connectivity=8
    )
    if n_labels <= 1:
        return mask_bin.copy()

    # 找出最大前景分量（label 0 是背景）
    max_area = 0
    max_label = 0
    for i in range(1, n_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area > max_area:
            max_area = area
            max_label = i

    total_fg = int(mask_bin.sum())
    if total_fg == 0:
        return mask_bin.copy()

    dominance = max_area / total_fg
    if dominance >= 0.50:
        # 最大分量占主导 → 只保留它（剔除噪声/文字/纸边）
        return (labels == max_label).astype(np.uint8)

    # 多分量 → 保留原掩码（用户可能需要选择路线）
    return mask_bin.copy()


def _zhang_suen_thinning(binary: np.ndarray) -> np.ndarray:
    """Zhang-Suen 细化算法。

    比形态学骨架更不易产生碎片化断裂。
    对掩码连续区域产生严格 1px 宽、连通的骨架。
    输入: 0/255 二值图像
    返回: 0/255 细化后骨架
    """
    img = (binary > 0).astype(np.uint8)
    h, w = img.shape

    # 预计算：只迭代前景像素附近
    while True:
        # 第一步标记
        markers1 = np.zeros((h, w), dtype=np.uint8)
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if img[y, x] == 0:
                    continue
                # 8-邻居
                p2 = img[y - 1, x]
                p3 = img[y - 1, x + 1]
                p4 = img[y, x + 1]
                p5 = img[y + 1, x + 1]
                p6 = img[y + 1, x]
                p7 = img[y + 1, x - 1]
                p8 = img[y, x - 1]
                p9 = img[y - 1, x - 1]

                neighbors = [p2, p3, p4, p5, p6, p7, p8, p9]
                A = sum(1 for i in range(8) if neighbors[i] == 0 and neighbors[(i + 1) % 8] == 1)
                B = sum(neighbors)

                if 2 <= B <= 6 and A == 1 and p2 * p4 * p6 == 0 and p4 * p6 * p8 == 0:
                    markers1[y, x] = 1

        img[markers1 > 0] = 0
        if not np.any(markers1):
            break

        # 第二步标记
        markers2 = np.zeros((h, w), dtype=np.uint8)
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if img[y, x] == 0:
                    continue
                p2 = img[y - 1, x]
                p3 = img[y - 1, x + 1]
                p4 = img[y, x + 1]
                p5 = img[y + 1, x + 1]
                p6 = img[y + 1, x]
                p7 = img[y + 1, x - 1]
                p8 = img[y, x - 1]
                p9 = img[y - 1, x - 1]

                neighbors = [p2, p3, p4, p5, p6, p7, p8, p9]
                A = sum(1 for i in range(8) if neighbors[i] == 0 and neighbors[(i + 1) % 8] == 1)
                B = sum(neighbors)

                if 2 <= B <= 6 and A == 1 and p2 * p4 * p8 == 0 and p2 * p6 * p8 == 0:
                    markers2[y, x] = 1

        img[markers2 > 0] = 0
        if not np.any(markers2):
            break

    return (img * 255).astype(np.uint8)


def _traverse_skeleton_graph(
    skeleton: np.ndarray,
    min_spur_length: int = 10,
) -> list:
    """基于骨架图像 8-邻接图构建连通分量并图遍历。

    在二值骨架图像上构建像素级邻接图（8-连通），
    找出所有连通分量，剔除短毛刺分量，然后从各分量的
    端点开始 BFS 遍历，产生有序点列。

    Args:
        skeleton: 细化后的二值骨架图像（0/255）
        min_spur_length: 小于此点数的分量作为毛刺剔除

    Returns:
        有序中心线点列 [(x, y), ...]
    """
    h, w = skeleton.shape
    binary = (skeleton > 0)

    # 收集所有骨架像素坐标并建立坐标→索引映射
    ys, xs = np.where(binary)
    n_pixels = len(ys)
    if n_pixels == 0:
        return []

    points = [(float(xs[i]), float(ys[i])) for i in range(n_pixels)]
    coord_to_idx = {f"{xs[i]},{ys[i]}": i for i in range(n_pixels)}

    # 构建 8-邻接图
    adj = [[] for _ in range(n_pixels)]
    for i in range(n_pixels):
        x, y = xs[i], ys[i]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    key = f"{nx},{ny}"
                    if key in coord_to_idx:
                        j = coord_to_idx[key]
                        adj[i].append(j)

    # BFS 找出连通分量
    visited = [False] * n_pixels
    components = []
    for i in range(n_pixels):
        if visited[i]:
            continue
        comp = []
        queue = [i]
        visited[i] = True
        while queue:
            u = queue.pop()
            comp.append(u)
            for v in adj[u]:
                if not visited[v]:
                    visited[v] = True
                    queue.append(v)
        components.append(comp)

    # 剔除短毛刺
    if len(components) > 1:
        kept = [c for c in components if len(c) >= min_spur_length]
        if not kept and components:
            kept = [components[0]]  # 至少保留最大的
        components = kept

    # 贪心排序：从最大的分量开始，每次连接最近的分量
    ordered_components = _order_components_by_proximity(components, points, adj)

    # 遍历每个分量
    ordered_all = []
    prev_last = None

    for ci, comp in enumerate(ordered_components):
        if len(comp) == 0:
            continue

        comp_set = set(comp)
        sub_adj = {u: [v for v in adj[u] if v in comp_set] for u in comp}
        degrees = {u: len(sub_adj[u]) for u in comp}
        endpoints = [u for u in comp if degrees[u] == 1]

        # 选起点：最接近上一个分量终点
        if prev_last is not None and len(endpoints) >= 1:
            plx, ply = prev_last
            start = min(endpoints, key=lambda u:
                (points[u][0] - plx)**2 + (points[u][1] - ply)**2)
        elif endpoints:
            start = endpoints[0]
        else:
            start = comp[0]

        # DFS 遍历
        visited_comp = set()
        ordered = []
        def dfs(u: int):
            visited_comp.add(u)
            ordered.append(points[u])
            for v in sub_adj[u]:
                if v not in visited_comp:
                    dfs(v)
        dfs(start)

        # 处理分支
        if len(ordered) < len(comp):
            remaining = [u for u in comp if u not in visited_comp]
            while remaining:
                best = None
                for u in remaining:
                    if any(v in visited_comp for v in sub_adj[u]):
                        best = u
                        break
                if best is None:
                    best = remaining[0]
                dfs(best)
                remaining = [u for u in comp if u not in visited_comp]

        ordered_all.extend(ordered)
        if ordered:
            prev_last = ordered[-1]

    return ordered_all


def _order_components_by_proximity(
    components: list,
    points: list,
    adj: list,
) -> list:
    """贪心排序骨架分量，使相邻分量在空间中接近。

    从最大分量开始，每次选择与当前分量最近端点距离最小的未访问分量，
    使最终拼接的点列间隙最小化。
    """
    if len(components) <= 1:
        return components[:]

    # 预计算每个分量的端点和质心
    comp_info = []
    for comp in components:
        comp_set = set(comp)
        sub_adj = {u: [v for v in adj[u] if v in comp_set] for u in comp}
        degrees = {u: len(sub_adj[u]) for u in comp}
        eps = [u for u in comp if degrees[u] == 1]
        centroid = (sum(points[u][0] for u in comp) / len(comp),
                     sum(points[u][1] for u in comp) / len(comp))
        comp_info.append({"indices": comp, "endpoints": eps, "centroid": centroid})

    ordered = [0]  # 从最大分量开始
    remaining = set(range(1, len(comp_info)))

    while remaining:
        current_idx = ordered[-1]
        current_comp = comp_info[current_idx]

        # 找最近的未访问分量
        best_dist = float("inf")
        best_idx = None
        for j in remaining:
            other_comp = comp_info[j]
            # 使用质心距离作为初始估计
            d_centroid = math.dist(current_comp["centroid"], other_comp["centroid"])
            if d_centroid < best_dist:
                # 精确检查端点距离
                for ep_i in current_comp["endpoints"]:
                    pi = points[ep_i]
                    for ep_j in other_comp["endpoints"]:
                        pj = points[ep_j]
                        d = math.dist(pi, pj)
                        if d < best_dist:
                            best_dist = d
                            best_idx = j
                # 如果没有端点，检查所有点对
                if not current_comp["endpoints"] or not other_comp["endpoints"]:
                    if d_centroid < best_dist:
                        best_dist = d_centroid
                        best_idx = j

        if best_idx is None:
            break
        ordered.append(best_idx)
        remaining.discard(best_idx)

    return [components[i] for i in ordered]


def _bridge_skeleton_gaps_via_mask(
    ordered_points: list,
    mask_bin: np.ndarray,
    bridge_max_px: float = 100.0,
    min_bridge_check_count: int = 5,
) -> list:
    """通过掩码桥接骨架间隙。

    骨架化算法可能在连续掩码区域产生微小间隙。
    检测有序点列中相邻点距离 > bridge_max_px/4 的跳跃，
    若跳跃两端之间沿直线的采样点均在掩码内，则插入桥接点。
    """
    if len(ordered_points) < 2:
        return ordered_points[:]

    h, w = mask_bin.shape

    def is_in_mask(px: float, py: float) -> bool:
        ix, iy = int(round(py)), int(round(px))
        if 0 <= ix < h and 0 <= iy < w:
            return mask_bin[ix, iy] > 0
        return False

    bridged = []
    for i, pt in enumerate(ordered_points):
        bridged.append(pt)
        if i == len(ordered_points) - 1:
            break

        nxt = ordered_points[i + 1]
        gap = math.dist(pt, nxt)

        if gap > bridge_max_px / 4.0 and gap <= bridge_max_px:
            n_samples = max(int(gap), min_bridge_check_count)
            all_in_mask = True
            bridge_pts = []
            for k in range(1, n_samples):
                t = k / n_samples
                bx = pt[0] + t * (nxt[0] - pt[0])
                by = pt[1] + t * (nxt[1] - pt[1])
                if not is_in_mask(bx, by):
                    all_in_mask = False
                    break
                bridge_pts.append((bx, by))

            if all_in_mask:
                bridged.extend(bridge_pts)

    return bridged


def _order_by_proximity(
    points: list,
    max_jump_px: float = 400.0,
) -> list:
    """按最近邻贪心排序点列，带方向动量避免 zigzag 振荡。

    跳过孤立点（最近邻居距离 > max_jump_px），从第一个有邻居的点开始。
    当遇到真正的 gap 时停止当前链，从剩余未访问点中重新开始新链。
    最终返回所有链的串联结果。

    方向动量：当链已有 ≥2 个点时，计算最近移动方向，对反向候选
    施加距离惩罚（×2），使贪心倾向于沿同一方向前进，防止在
    骨架的水平抖动处左右振荡。
    """
    if len(points) <= 1:
        return points[:]

    n = len(points)

    # 计算每个点到最近邻居的距离，用于找起始点
    nn_dists = [float("inf")] * n
    for i in range(n):
        xi, yi = points[i]
        for j in range(n):
            if i == j:
                continue
            d2 = (xi - points[j][0]) ** 2 + (yi - points[j][1]) ** 2
            if d2 < nn_dists[i]:
                nn_dists[i] = d2

    remaining = set(range(n))
    ordered_all = []

    while remaining:
        # 找有最近邻居的起始点（最近距离 <= max_jump_px）
        start = None
        min_nn = float("inf")
        for i in remaining:
            if nn_dists[i] <= max_jump_px and nn_dists[i] < min_nn:
                min_nn = nn_dists[i]
                start = i
        if start is None:
            break  # 所有剩余点都是孤立的

        # 从该点开始贪心遍历（带方向动量）
        chain = [points[start]]
        remaining.remove(start)

        while remaining:
            x, y = chain[-1]

            # 计算方向动量：最近两个点的位移
            direction_bias = (0.0, 0.0)
            if len(chain) >= 2:
                px_prev, py_prev = chain[-2]
                direction_bias = (x - px_prev, y - py_prev)

            best_idx = None
            best_score = float("inf")
            for i in remaining:
                px, py = points[i]
                d2 = (px - x) ** 2 + (py - y) ** 2
                score = d2

                # 方向动量：如果有方向历史，对反向候选施加惩罚
                if direction_bias != (0.0, 0.0):
                    ndx = px - x
                    ndy = py - y
                    dot = direction_bias[0] * ndx + direction_bias[1] * ndy
                    if dot < 0:
                        # 严格反向：惩罚 ×4
                        score *= 4.0
                    elif dot == 0:
                        # 垂直方向：轻微惩罚 ×1.5
                        score *= 1.5

                if score < best_score:
                    best_score = score
                    best_idx = i
            if best_idx is None or best_score > max_jump_px * max_jump_px:
                break
            remaining.remove(best_idx)
            chain.append(points[best_idx])

        ordered_all.extend(chain)

    return ordered_all


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
# Waypoint 约束开放路线提取 (Task 4B-2 C1 open route)
# ============================================================


def _largest_connected_component_mask(mask_bin: np.ndarray) -> np.ndarray:
    """返回掩码中最大的 8-连通前景分量（二值 0/1）。

    C1 是真实 track_bare.png 的最大分量（占前景 75.0%），本函数保证
    waypoint 约束提取只在 C1 上建图，C2—C7 被排除。
    """
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask_bin, connectivity=8
    )
    if n_labels <= 1:
        return mask_bin.copy()
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(np.argmax(areas)) + 1
    return (labels == largest).astype(np.uint8)


def _shortest_skeleton_path(adj: list, start: int, goal: int):
    """BFS 求骨架图最短路径，返回节点索引列表；不可达返回 None。"""
    if start == goal:
        return [start]
    prev = {start: None}
    dq = deque([start])
    while dq:
        u = dq.popleft()
        if u == goal:
            break
        for v in adj[u]:
            if v not in prev:
                prev[v] = u
                dq.append(v)
    if goal not in prev:
        return None
    path = [goal]
    cur = goal
    while prev[cur] is not None:
        cur = prev[cur]
        path.append(cur)
    path.reverse()
    return path


def _prune_anchorless_skeleton_fragments(
    adj: list, anchors: set, min_spur_length: int
) -> list:
    """剔除不含锚点、点数 < *min_spur_length* 的骨架碎片。

    返回保留的节点索引（原图索引，升序）。含锚点的碎片即使很短也保留，
    因此吸附结果不会丢失。
    """
    n = len(adj)
    visited = [False] * n
    keep = []
    for i in range(n):
        if visited[i]:
            continue
        comp = []
        stack = [i]
        visited[i] = True
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if not visited[v]:
                    visited[v] = True
                    stack.append(v)
        if len(comp) >= min_spur_length or any(u in anchors for u in comp):
            keep.extend(comp)
    keep.sort()
    return keep


def extract_waypoint_constrained_centerline(
    mask: Any,
    waypoints_px: Sequence[Tuple[float, float]],
    snap_radius_px: float = 60.0,
    min_spur_length: int = 10,
) -> Tuple[Tuple[float, float], ...]:
    """Return one open, ordered skeleton path visiting waypoints in order.

    Task 4B-2 C1 单程开放路线：只保留掩码最大连通分量（C1），Zhang-Suen
    细化得到连通骨架图，把有序锚点吸附到最近骨架节点，再在相邻锚点间取
    骨架最短路径，拼接成一条有起点、有方向、有终点的开放中心线。

    - 保留调用方锚点顺序；不自动闭合；终点后不追加任何点。
    - 拒绝复用无向边（防止折返/回绕）。
    - 任一锚点距最近骨架节点超过 *snap_radius_px* 时抛 ValueError。
    """
    m = np.asarray(mask, dtype=np.uint8)
    if m.ndim != 2:
        raise ValueError("mask must be 2D")
    if cv2 is None:
        raise RuntimeError("waypoint-constrained extraction requires cv2")
    if len(waypoints_px) < 2:
        raise ValueError("at least two waypoints are required")

    # 1. 只保留最大连通分量（= C1）
    m_bin = (m > 0).astype(np.uint8)
    c1 = _largest_connected_component_mask(m_bin)

    # 2. Zhang-Suen 细化得到连通骨架。
    #    注意不使用 _thin_skeleton_to_1px：其水平去重会破坏 8-连通性，
    #    把真实 C1 骨架打散成 188 个碎片。
    skeleton = _zhang_suen_thinning((c1 * 255).astype(np.uint8))
    ys, xs = np.where(skeleton > 0)
    if len(xs) == 0:
        raise ValueError("skeleton is empty; mask has no track pixels")

    # 3. 8-邻接骨架图
    coords = [(int(x), int(y)) for x, y in zip(xs.tolist(), ys.tolist())]
    coord_to_idx = {c: i for i, c in enumerate(coords)}
    adj = [[] for _ in coords]
    for i, (x, y) in enumerate(coords):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                j = coord_to_idx.get((x + dx, y + dy))
                if j is not None:
                    adj[i].append(j)

    # 4. 吸附每个锚点到最近骨架节点，超出半径即拒绝
    snapped = []
    for k, wp in enumerate(waypoints_px):
        wx, wy = float(wp[0]), float(wp[1])
        best = min(
            range(len(coords)),
            key=lambda i: (coords[i][0] - wx) ** 2 + (coords[i][1] - wy) ** 2,
        )
        d = math.dist(coords[best], (wx, wy))
        if d > snap_radius_px:
            raise ValueError(
                "cannot snap waypoint {0} {1} to C1 skeleton: distance "
                "{2:.1f}px exceeds snap radius {3:.1f}px".format(
                    k + 1, tuple(wp), d, snap_radius_px
                )
            )
        snapped.append(best)

    # 防御性剔除不含锚点的小碎片（连通骨架下为 no-op）
    if min_spur_length > 1:
        kept = _prune_anchorless_skeleton_fragments(
            adj, set(snapped), min_spur_length
        )
        if len(kept) < len(coords):
            coords = [coords[i] for i in kept]
            remap = {old: new for new, old in enumerate(kept)}
            snapped = [remap[i] for i in snapped]
            coord_to_idx = {c: i for i, c in enumerate(coords)}
            adj = [[] for _ in coords]
            for i, (x, y) in enumerate(coords):
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        j = coord_to_idx.get((x + dx, y + dy))
                        if j is not None:
                            adj[i].append(j)

    # 5. 相邻锚点间最短骨架路径
    segments = []
    for a, b in zip(snapped, snapped[1:]):
        path = _shortest_skeleton_path(adj, a, b)
        if path is None:
            raise ValueError(
                "no connected skeleton path between waypoint anchors "
                "{0} and {1}; C1 skeleton is fragmented".format(a + 1, b + 1)
            )
        segments.append([coords[i] for i in path])

    # 6. 拼接（丢弃共享端点），拒绝复用无向边
    route: list = []
    seen_edges: set = set()
    for seg in segments:
        start_i = 1 if (route and seg and seg[0] == route[-1]) else 0
        for pt in seg[start_i:]:
            if route:
                edge = tuple(sorted((route[-1], pt)))
                if edge in seen_edges:
                    raise ValueError(
                        "route reuses undirected edge {0}".format(edge)
                    )
                seen_edges.add(edge)
            route.append(pt)

    return tuple(route)


# ============================================================
# 边界覆盖 / 裁切检测 (Task 4B-2 C1 open route — 独立审核返工)
# ============================================================


@dataclass(frozen=True)
class BorderCoverageMetrics:
    """赛道掩码/中心线相对图像边界的覆盖指标（裁切检测结果）。

    - mask_border_touch_count: 轨道掩码恰好落在图像边界上的去重像素数
    - route_border_point_count: 中心线恰好位于图像边界上的点数
    - route_points_within_2px_of_border: 中心线距边界 ≤ 阈值（默认 2px）的点数
    - min_route_border_clearance_px: 中心线距最近图像边界的最小距离
    - input_cropped: 掩码接触任一图像边界（完整俯视图规则，无起终点豁免）
    """

    mask_border_touch_count: int
    route_border_point_count: int
    route_points_within_2px_of_border: int
    min_route_border_clearance_px: float
    input_cropped: bool


def compute_border_coverage_metrics(
    mask: Any,
    route_points: Sequence[Tuple[float, float]],
    clearance_threshold_px: float = 2.0,
) -> BorderCoverageMetrics:
    """计算赛道掩码与中心线相对图像边界的覆盖指标，用于识别被裁切输入。

    规则（Task 4B-2 C1 完整赛道俯视图）：只要轨道掩码（C1）接触任一图像
    边界，输入即视为被裁切（``input_cropped=True``）。起点与终点在当前设计
    中都不应位于图像边界，因此不设任何起终点豁免；允许的通路是重新采集四周
    留白、包含完整赛道的新俯视图片。

    Args:
        mask: 二值轨道掩码（0/1，应传 C1 最大分量）。
        route_points: 有序中心线点列 ((x, y), ...)。
        clearance_threshold_px: “贴近边界”判定阈值（默认 2px）。

    Returns:
        BorderCoverageMetrics。
    """
    m = np.asarray(mask, dtype=np.uint8)
    if m.ndim != 2:
        raise ValueError("mask must be 2D")
    h, w = m.shape

    # 掩码边界触点：去重统计恰好落在图像边界上的轨道像素（角点只计一次）
    border_px: set = set()
    if h > 0 and w > 0:
        for x in range(w):
            if m[0, x]:
                border_px.add((0, x))
            if h > 1 and m[h - 1, x]:
                border_px.add((h - 1, x))
        if h > 1:
            for y in range(1, h - 1):
                if m[y, 0]:
                    border_px.add((y, 0))
                if m[y, w - 1]:
                    border_px.add((y, w - 1))

    route_border = 0
    route_within = 0
    min_clearance = float("inf")
    for x, y in route_points:
        xi, yi = int(round(x)), int(round(y))
        if not (0 <= xi < w and 0 <= yi < h):
            d = 0.0
        else:
            d = float(min(xi, yi, w - 1 - xi, h - 1 - yi))
        if d < min_clearance:
            min_clearance = d
        if d == 0.0:
            route_border += 1
        if d <= clearance_threshold_px:
            route_within += 1

    if not route_points:
        min_clearance = 0.0

    return BorderCoverageMetrics(
        mask_border_touch_count=len(border_px),
        route_border_point_count=route_border,
        route_points_within_2px_of_border=route_within,
        min_route_border_clearance_px=min_clearance,
        input_cropped=len(border_px) > 0,
    )


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
