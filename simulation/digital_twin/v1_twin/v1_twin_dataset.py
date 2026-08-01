"""同步数据集：pose + 遥测 时间对齐 (Task 4B-4)。

把位姿流（t_pc_ns）与遥测流（tick_ms）通过 ClockSync 映射后按
**独立时间戳**关联（§12 第四项：pc_ns ↔ mcu_tick_ms，禁止按数组下标拼合），
输出 V1SyncFrame 列表 + 匹配覆盖率 + p95 时间差。

Task 4B-4 fix（审核事实复核后）：
- coverage 只在**两流共同时间区间**内计算（排除单侧缺失段），
  coverage = 共同区间内 diff <= tolerance 的 pose 数 / 共同区间 pose 总数。
- p95 对共同区间内**全部**最近距离计算（含超出 tolerance 的失败样本），
  不得先过滤失败样本再算 p95（旧实现 `diff>tolerance` 过滤后 p95<=tolerance
  是构造性必然，属无效 gate）。
- 额外报告诊断指标：共同覆盖时长、遥测最大/p95 间隔、匹配用到的不同遥测数、
  最大复用次数、时钟拟合残差。
- 数据不足必须 INSUFFICIENT EVIDENCE（见 evaluate_sync_gate）。

不可变规则：SynchronizedRunDataset 为 frozen dataclass，只保存派生
sync_frames（引用不可变的 V1Pose/V1TelemetryFrame），不修改原始输入。
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Sequence, Tuple

import numpy as np

from v1_twin.v1_twin_schema import (
    SCHEMA_VERSION,
    V1SyncFrame,
    V1SyncQuality,
    V1TelemetryFrame,
)
from v1_twin.v1_twin_sync import ClockSync


@dataclass(frozen=True)
class SynchronizedRunDataset:
    """同步数据集：对齐后的 sync_frames + 匹配质量统计 + 诊断指标。

    只存派生数据（sync_frames），不存原始 pose/遥测流（可重算）。
    coverage/p95 定义见模块 docstring（Task 4B-4 fix）。
    """

    sync_frames: Tuple[V1SyncFrame, ...]
    coverage: float                       # 共同区间匹配覆盖率 ∈ [0,1]
    p95_time_diff_ns: float               # 全部最近距离 p95（ns，含失败样本）
    tolerance_ns: int                     # 匹配容差（ns）
    model_version: str                    # 派生数据集模型版本
    schema_version: str = SCHEMA_VERSION

    # --- Task 4B-4 fix：诊断指标 ---
    common_interval_start_ns: float = 0.0     # 共同区间起点（PC ns）
    common_interval_end_ns: float = 0.0       # 共同区间终点（PC ns）
    n_common_poses: int = 0                   # 共同区间内的 pose 数（分母）
    telemetry_interval_max_ns: float = 0.0    # 遥测最大间隔（共同区间内）
    telemetry_interval_p95_ns: float = 0.0    # 遥测 p95 间隔（共同区间内）
    n_telemetry_distinct: int = 0             # 匹配用到的不同遥测帧数
    max_telemetry_reuse: int = 0              # 单帧遥测最大复用次数
    clock_fit_residual_rms_ns: float = 0.0    # 时钟拟合残差 RMS（ns）

    @property
    def common_interval_duration_ns(self) -> float:
        return max(0.0, self.common_interval_end_ns - self.common_interval_start_ns)

    def __post_init__(self) -> None:
        if not (0.0 <= self.coverage <= 1.0):
            raise ValueError("coverage must be in [0, 1]")
        if self.p95_time_diff_ns < 0:
            raise ValueError("p95_time_diff_ns must be >= 0")
        if self.tolerance_ns < 0:
            raise ValueError("tolerance_ns must be >= 0")
        if not self.model_version:
            raise ValueError("model_version must not be empty")
        if self.n_common_poses < 0:
            raise ValueError("n_common_poses must be >= 0")
        if self.n_telemetry_distinct < 0:
            raise ValueError("n_telemetry_distinct must be >= 0")
        if self.max_telemetry_reuse < 0:
            raise ValueError("max_telemetry_reuse must be >= 0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "SynchronizedRunDataset",
            "sync_frames": [sf.to_dict() for sf in self.sync_frames],
            "coverage": self.coverage,
            "p95_time_diff_ns": self.p95_time_diff_ns,
            "tolerance_ns": self.tolerance_ns,
            "model_version": self.model_version,
            "schema_version": self.schema_version,
            "common_interval_start_ns": self.common_interval_start_ns,
            "common_interval_end_ns": self.common_interval_end_ns,
            "n_common_poses": self.n_common_poses,
            "telemetry_interval_max_ns": self.telemetry_interval_max_ns,
            "telemetry_interval_p95_ns": self.telemetry_interval_p95_ns,
            "n_telemetry_distinct": self.n_telemetry_distinct,
            "max_telemetry_reuse": self.max_telemetry_reuse,
            "clock_fit_residual_rms_ns": self.clock_fit_residual_rms_ns,
        }


def _nearest_telemetry(times, entries, pt):
    """返回 (最近遥测时间, 遥测条目, 距离) —— 独立时间戳最近邻。"""
    idx = bisect_left(times, pt)
    cand = []
    if idx < len(times):
        cand.append((times[idx], entries[idx]))
    if idx > 0:
        cand.append((times[idx - 1], entries[idx - 1]))
    best_t, best_entry = min(cand, key=lambda c: abs(c[0] - pt))
    return best_t, best_entry, abs(best_t - pt)


def build_synchronized_dataset(
    poses: Sequence[Any],
    telemetry_frames: Sequence[V1TelemetryFrame],
    clock_sync: ClockSync,
    tolerance_ns: int,
    model_version: str = "1.0.0",
) -> SynchronizedRunDataset:
    """按时间戳把位姿与遥测对齐，返回同步数据集（共同区间语义）。

    *poses*: V1Pose 序列（用 pose.t_pc_ns）。
    *telemetry_frames*: V1TelemetryFrame 序列（用 tick_ms，经 ClockSync 映射）。
    *tolerance_ns*: 匹配容差；超过则视为 MISSING（不计入 sync_frames，
        但仍计入 p95 分母）。
    """
    if not poses:
        raise ValueError("poses must not be empty")
    if not telemetry_frames:
        raise ValueError("telemetry_frames must not be empty")

    # 遥测 tick → PC ns（按时间排序，保留原始下标用于复用统计）
    entries = sorted(
        (
            float(clock_sync.tick_to_pc_ns(t.tick_ms)),
            i,
            t,
        )
        for i, t in enumerate(telemetry_frames)
    )
    times = [e[0] for e in entries]

    pose_times = [float(p.t_pc_ns) for p in poses]
    common_start = max(times[0], min(pose_times))
    common_end = min(times[-1], max(pose_times))

    sync_frames = []
    all_diffs: list = []          # 共同区间内全部最近距离（含失败样本）
    usage: Counter = Counter()    # 遥测原始下标 → 作为最近邻被使用次数
    for pose in poses:
        pt = float(pose.t_pc_ns)
        if pt < common_start or pt > common_end:
            continue              # 单侧缺失段，排除出分母
        best_t, (_, tele_idx, tele), diff = _nearest_telemetry(times, entries, pt)
        usage[tele_idx] += 1
        all_diffs.append(diff)
        if diff <= tolerance_ns:
            quality = (
                V1SyncQuality.OK
                if diff <= tolerance_ns / 2
                else V1SyncQuality.DEGRADED
            )
            sync_frames.append(V1SyncFrame(
                pose=pose, telemetry=tele, sync_quality=quality))

    n_common = len(all_diffs)
    if n_common == 0:
        coverage = 0.0
        p95 = 0.0
    else:
        coverage = len(sync_frames) / n_common
        p95 = float(np.percentile(all_diffs, 95))

    # 遥测间隔（共同区间内）
    tel_in_common = [t for t in times if common_start <= t <= common_end]
    intervals = [b - a for a, b in zip(tel_in_common, tel_in_common[1:])]
    tele_max = float(max(intervals)) if intervals else 0.0
    tele_p95 = float(np.percentile(intervals, 95)) if intervals else 0.0

    # 复用统计
    n_distinct = len(usage)
    max_reuse = max(usage.values()) if usage else 0

    # 时钟拟合残差（与拟合方式一致的残差）
    residual_rms = float(clock_sync.fit_residuals().get("rms_ns", 0.0))

    return SynchronizedRunDataset(
        sync_frames=tuple(sync_frames),
        coverage=coverage,
        p95_time_diff_ns=p95,
        tolerance_ns=int(tolerance_ns),
        model_version=model_version,
        common_interval_start_ns=float(common_start),
        common_interval_end_ns=float(common_end),
        n_common_poses=int(n_common),
        telemetry_interval_max_ns=tele_max,
        telemetry_interval_p95_ns=tele_p95,
        n_telemetry_distinct=int(n_distinct),
        max_telemetry_reuse=int(max_reuse),
        clock_fit_residual_rms_ns=float(residual_rms),
    )


# ============================================================
# Gate 评估（Task 4B-4 fix）
# ============================================================

# 最少共同区间 pose 数：少于则数据不足。
MIN_COMMON_POSES_FOR_GATE = 20
# 最少匹配用到的不同遥测数：少于则数据不足。
MIN_TELEMETRY_DISTINCT_FOR_GATE = 2
# PASS 所需覆盖率。
COVERAGE_GATE_THRESHOLD = 0.95


@dataclass(frozen=True)
class SyncGateResult:
    """4B-4 同步 gate 结果。

    verdict: "PASS" | "FAIL" | "INSUFFICIENT EVIDENCE"
    """

    verdict: str
    coverage: float
    p95_time_diff_ns: float
    tolerance_ns: int
    n_common_poses: int
    n_telemetry_distinct: int
    common_interval_duration_ns: float
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "coverage": self.coverage,
            "p95_time_diff_ns": self.p95_time_diff_ns,
            "tolerance_ns": self.tolerance_ns,
            "n_common_poses": self.n_common_poses,
            "n_telemetry_distinct": self.n_telemetry_distinct,
            "common_interval_duration_ns": self.common_interval_duration_ns,
            "reason": self.reason,
        }


def evaluate_sync_gate(
    ds: SynchronizedRunDataset,
    min_common_poses: int = MIN_COMMON_POSES_FOR_GATE,
    min_telemetry_distinct: int = MIN_TELEMETRY_DISTINCT_FOR_GATE,
) -> SyncGateResult:
    """自动验收 gate（纲领 §6e / §14 证据等级）。

    PASS: 共同区间 duration > 0 且 n_common_poses >= min 且
          n_telemetry_distinct >= min 且 coverage >= 0.95 且
          p95_time_diff_ns <= tolerance_ns。
    INSUFFICIENT EVIDENCE: 数据不足（无共同区间 / pose 数不足 /
          遥测种类不足），不得降级 PASS。
    其余为 FAIL。
    """
    duration = ds.common_interval_duration_ns
    if duration <= 0.0:
        return SyncGateResult(
            "INSUFFICIENT EVIDENCE", ds.coverage, ds.p95_time_diff_ns,
            ds.tolerance_ns, ds.n_common_poses, ds.n_telemetry_distinct,
            duration,
            "no overlapping time interval between pose and telemetry",
        )
    if ds.n_common_poses < min_common_poses:
        return SyncGateResult(
            "INSUFFICIENT EVIDENCE", ds.coverage, ds.p95_time_diff_ns,
            ds.tolerance_ns, ds.n_common_poses, ds.n_telemetry_distinct,
            duration,
            "too few poses in common interval: {0} < {1}".format(
                ds.n_common_poses, min_common_poses),
        )
    if ds.n_telemetry_distinct < min_telemetry_distinct:
        return SyncGateResult(
            "INSUFFICIENT EVIDENCE", ds.coverage, ds.p95_time_diff_ns,
            ds.tolerance_ns, ds.n_common_poses, ds.n_telemetry_distinct,
            duration,
            "too few distinct telemetry frames matched: {0} < {1}".format(
                ds.n_telemetry_distinct, min_telemetry_distinct),
        )
    if ds.coverage >= COVERAGE_GATE_THRESHOLD and ds.p95_time_diff_ns <= ds.tolerance_ns:
        return SyncGateResult(
            "PASS", ds.coverage, ds.p95_time_diff_ns, ds.tolerance_ns,
            ds.n_common_poses, ds.n_telemetry_distinct, duration,
            "coverage >= 0.95 and p95 <= tolerance",
        )
    return SyncGateResult(
        "FAIL", ds.coverage, ds.p95_time_diff_ns, ds.tolerance_ns,
        ds.n_common_poses, ds.n_telemetry_distinct, duration,
        "coverage < 0.95 or p95 > tolerance",
    )
