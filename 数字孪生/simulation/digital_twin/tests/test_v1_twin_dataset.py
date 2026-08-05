"""Tests for SynchronizedRunDataset (pose + 遥测 时间对齐) (Task 4B-4)。

先写测试后实现：模块尚不存在时应 RED。

验证：
- 时间戳关联对齐（非数组下标）
- 匹配覆盖率 / p95 时间差
- 数据集不可变、原始数据不被修改
- 使用独立时间戳（t_pc_ns ↔ mcu_tick_ms）关联（§12 第四项）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest

from v1_twin.v1_twin_schema import V1Pose, V1TelemetryFrame, V1SyncQuality
from v1_twin.v1_twin_sync import ClockSync
from v1_twin.v1_twin_dataset import (
    SynchronizedRunDataset,
    build_synchronized_dataset,
)


def _make_clock() -> ClockSync:
    cs = ClockSync()
    # pc_ns = 1_000_000 * tick + 500_000（1 tick-ms -> 1 墙钟 ms，偏移 0.5ms）
    for tick in range(0, 10_000, 20):
        cs.add_sample(tick, 1_000_000 * tick + 500_000)
    cs.fit()
    return cs


def _make_telemetry(n=100):
    """tick 0,20,...,20*(n-1)，pc_recv_ns = 映射时间 + 5ms 接收延迟。"""
    return [
        V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (0, 0, 0, 0),
                         tick, 1_000_000 * tick + 5_500_000)
        for tick in range(0, 20 * n, 20)
    ]


def _make_poses(cs, n=60, start_ms=0.0):
    """相机 30fps 位姿：t_pc_ns 每 33.3ms 一个。"""
    poses = []
    for k in range(n):
        t_pc = int(cs.tick_to_pc_ns(start_ms) + k * 33_300_000)
        poses.append(V1Pose(10.0, 20.0, 0.5, 1.0, t_pc))
    return poses


TOL_NS = 33_300_000  # max(相机周期 33.3ms, 遥测周期 20ms)


def test_build_aligns_poses_to_telemetry_by_time():
    cs = _make_clock()
    tele = _make_telemetry()
    poses = _make_poses(cs)
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    assert ds.coverage >= 0.95
    assert ds.p95_time_diff_ns <= TOL_NS
    assert len(ds.sync_frames) == int(round(ds.coverage * len(poses)))


def test_coverage_computed_over_common_interval_only():
    """Task 4B-4 fix: coverage 只在两流共同时间区间内计算。

    后段位姿（超出遥测区间）被排除出分母；共同区间内遥测密集 → 覆盖率应接近 1。
    """
    cs = _make_clock()
    tele = _make_telemetry(n=20)  # tick 0..380 → PC ~0.5..380.5ms
    poses = _make_poses(cs, n=60)  # 60 个位姿跨越 ~2s
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    # 后段位姿被排除 → 共同区间 pose 数显著小于全部 pose 数
    assert ds.n_common_poses < len(poses)
    assert ds.n_common_poses > 0
    # 共同区间内遥测 20ms 间隔，位姿 33ms → 覆盖率应接近 1
    assert ds.coverage >= 0.95


def test_coverage_less_than_one_when_telemetry_sparse():
    """共同区间内遥测稀疏（间隔 120ms > tolerance 33.3ms）→ 部分位姿无法匹配。"""
    cs = _make_clock()
    tele = [
        V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (0, 0, 0, 0),
                         tick, 1_000_000 * tick + 5_500_000)
        for tick in range(0, 2000, 120)
    ]
    poses = _make_poses(cs, n=60)
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    assert 0.0 < ds.coverage < 0.95
    # 绝大部分 pose 在共同区间内（仅最后 1-2 帧超出遥测区间）
    assert ds.n_common_poses >= len(poses) - 3
    assert ds.p95_time_diff_ns > 0


def test_alignment_uses_timestamps_not_index():
    cs = _make_clock()
    tele = _make_telemetry(n=40)      # tick 0..780ms
    poses = _make_poses(cs, n=10)     # 前 10 个位姿
    # 把遥测打乱顺序（但时间戳不变）
    import random
    random.seed(7)
    tele_shuffled = list(tele)
    random.shuffle(tele_shuffled)
    ds = build_synchronized_dataset(poses, tele_shuffled, cs, TOL_NS)
    # 仍应按时间戳正确关联（覆盖率不受顺序影响）
    assert ds.coverage >= 0.95
    # 每个 sync_frame 的 pose/telemetry 时间差在容差内
    for sf in ds.sync_frames:
        tele_pc = cs.tick_to_pc_ns(sf.telemetry.tick_ms)
        assert abs(sf.pose.t_pc_ns - tele_pc) <= TOL_NS


def test_dataset_immutable_and_input_unchanged():
    cs = _make_clock()
    tele = _make_telemetry(n=40)
    poses = _make_poses(cs, n=10)
    poses_copy = list(poses)
    tele_copy = list(tele)
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    # 原始输入未被修改
    assert poses == poses_copy
    assert tele == tele_copy
    # 数据集本身不可变
    with pytest.raises(Exception):
        ds.sync_frames = ()  # type: ignore[misc]


def test_sync_quality_ok_for_tight_match():
    cs = _make_clock()
    tele = _make_telemetry(n=40)
    poses = _make_poses(cs, n=10)
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    assert all(sf.sync_quality in (V1SyncQuality.OK, V1SyncQuality.DEGRADED)
               for sf in ds.sync_frames)


# ============================================================
# Task 4B-4 fix：诚实 gate（p95 全量最近距离 / 共同区间 / 指标）
# ============================================================

from bisect import bisect_left


def _expected_nearest_diffs(cs, poses, tele):
    """独立计算共同区间内每个 pose 的最近遥测距离（测试 ground truth）。"""
    times = sorted(cs.tick_to_pc_ns(t.tick_ms) for t in tele)
    pose_times = [float(p.t_pc_ns) for p in poses]
    common_start = max(times[0], min(pose_times))
    common_end = min(times[-1], max(pose_times))
    diffs = []
    for p in poses:
        pt = float(p.t_pc_ns)
        if pt < common_start or pt > common_end:
            continue
        idx = bisect_left(times, pt)
        cand = []
        if idx < len(times):
            cand.append(times[idx])
        if idx > 0:
            cand.append(times[idx - 1])
        best = min(cand, key=lambda t: abs(t - pt))
        diffs.append(abs(best - pt))
    return diffs


def test_p95_computed_over_all_nearest_diffs_not_filtered():
    """p95 必须对全部最近距离计算（含超出 tolerance 的失败样本），
    不能先过滤失败样本再算 p95（旧实现是构造性必然，无效 gate）。"""
    cs = _make_clock()
    tele = [
        V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (0, 0, 0, 0),
                         tick, 1_000_000 * tick + 5_500_000)
        for tick in range(0, 2000, 120)   # 稀疏：间隔 120ms
    ]
    poses = _make_poses(cs, n=60)
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    expected = _expected_nearest_diffs(cs, poses, tele)
    assert len(expected) > 0
    # 全部最近距离的 p95（含失败样本）
    exp_p95 = float(np.percentile(expected, 95))
    assert ds.p95_time_diff_ns == pytest.approx(exp_p95, rel=1e-9)
    # 失败样本存在且被计入 p95（若只统计匹配样本则 p95 必 <= tolerance）
    assert any(d > TOL_NS for d in expected)
    assert ds.p95_time_diff_ns > TOL_NS


def test_gate_verdict_pass():
    cs = _make_clock()
    tele = _make_telemetry(n=100)
    poses = _make_poses(cs, n=60)
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    from v1_twin.v1_twin_dataset import evaluate_sync_gate
    res = evaluate_sync_gate(ds)
    assert res.verdict == "PASS"


def test_gate_verdict_fail_when_sparse_telemetry():
    cs = _make_clock()
    tele = [
        V1TelemetryFrame((0, 0, 0, 0), 0.0, 0.0, (0, 0, 0, 0),
                         tick, 1_000_000 * tick + 5_500_000)
        for tick in range(0, 2000, 120)
    ]
    poses = _make_poses(cs, n=60)
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    from v1_twin.v1_twin_dataset import evaluate_sync_gate
    res = evaluate_sync_gate(ds)
    assert res.verdict == "FAIL"


def test_gate_verdict_insufficient_when_no_common_interval():
    """两流时间无交集 → 数据不足，必须 INSUFFICIENT EVIDENCE。"""
    cs = _make_clock()
    # 遥测只覆盖 tick 0..40ms；位姿从 2000ms 开始（无交集）
    tele = _make_telemetry(n=2)
    poses = _make_poses(cs, n=5, start_ms=2000.0)
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    from v1_twin.v1_twin_dataset import evaluate_sync_gate
    res = evaluate_sync_gate(ds)
    assert res.verdict == "INSUFFICIENT EVIDENCE"
    assert ds.common_interval_duration_ns == 0.0


def test_gate_verdict_insufficient_when_too_few_poses():
    cs = _make_clock()
    tele = _make_telemetry(n=100)
    poses = _make_poses(cs, n=3)   # 共同区间只有 3 个 pose
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    from v1_twin.v1_twin_dataset import evaluate_sync_gate
    res = evaluate_sync_gate(ds, min_common_poses=20)
    assert res.verdict == "INSUFFICIENT EVIDENCE"


def test_sync_metrics_distinct_telemetry_and_reuse():
    """诊断指标：匹配用到的不同遥测数、最大复用次数、遥测间隔。"""
    cs = _make_clock()
    tele = _make_telemetry(n=40)          # 20ms 间隔
    poses = _make_poses(cs, n=60)          # 33.3ms 间隔
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    # 60 个位姿，40 帧遥测，最近邻匹配 → 使用不同遥测数 > 0
    assert ds.n_telemetry_distinct >= 1
    assert ds.n_telemetry_distinct <= len(tele)
    assert ds.max_telemetry_reuse >= 1
    # 遥测间隔诊断（共同区间内）
    assert ds.telemetry_interval_max_ns > 0
    assert ds.telemetry_interval_p95_ns > 0
    # 时钟拟合残差（fit 后应已拟合）
    assert ds.clock_fit_residual_rms_ns >= 0


def test_serialization_carries_metrics():
    cs = _make_clock()
    tele = _make_telemetry(n=40)
    poses = _make_poses(cs, n=10)
    ds = build_synchronized_dataset(poses, tele, cs, TOL_NS)
    d = ds.to_dict()
    assert "common_interval_start_ns" in d
    assert "n_common_poses" in d
    assert "clock_fit_residual_rms_ns" in d
