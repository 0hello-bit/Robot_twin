"""MCU tick → PC ns 时间映射 (Task 4B-4)。

固件事实（`程序/3. 麦轮巡线小车/User/main.c`）:
- `LOOP_DELAY_MS = 5`，`g_loop_count` 为 uint32
- `tick_ms = (uint32)(g_loop_count * LOOP_DELAY_MS)`，uint32 溢出 → 2^32 回绕

ClockSync 对 (tick_ms, pc_ns) 样本做：
1. tick 回绕展开（值突降 → +2^32）
2. 线性回归 `pc_ns = a * tick_ms + b`（最小二乘）
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

# 固件 tick 回绕模数：uint32 乘积溢出周期
TICK_MODULUS = 1 << 32


class ClockSyncError(RuntimeError):
    """ClockSync 配置/运行错误。"""


class ClockSync:
    """MCU tick_ms → PC ns 的线性映射（含 tick 回绕展开）。"""

    def __init__(self) -> None:
        self._raw: List[Tuple[int, int]] = []          # (tick_ms, pc_ns)
        self._unwrapped: List[Tuple[int, int]] = []    # (展开后 tick, pc_ns)
        self._offset: int = 0                          # 回绕累计偏移
        self._a: float | None = None
        self._b: float | None = None
        # fit_batched 使用的批次均值（tick, pc）；fit() 时为 None。
        # 用于计算与拟合方式一致的残差（诊断指标，Task 4B-4 fix）。
        self._batch_means: List[Tuple[float, float]] | None = None

    # ------------------------------------------------------------
    # 样本与展开
    # ------------------------------------------------------------
    def add_sample(self, tick_ms: int, pc_ns: int) -> None:
        """加入一个 (tick_ms, pc_ns) 观测（按时间顺序）。"""
        tick_ms = int(tick_ms)
        pc_ns = int(pc_ns)
        if self._raw and tick_ms < self._raw[-1][0]:
            # 检测到回绕（值突降）
            self._offset += TICK_MODULUS
        uw = tick_ms + self._offset
        self._raw.append((tick_ms, pc_ns))
        self._unwrapped.append((uw, pc_ns))

    def unwrapped_ticks(self) -> List[int]:
        """返回展开后的 tick 序列（单调递增）。"""
        return [t for t, _ in self._unwrapped]

    @property
    def sample_count(self) -> int:
        return len(self._unwrapped)

    # ------------------------------------------------------------
    # 拟合与映射
    # ------------------------------------------------------------
    def fit(self) -> Tuple[float, float]:
        """最小二乘拟合 pc_ns = a*tick + b。返回 (a, b)。"""
        if len(self._unwrapped) < 2:
            raise ClockSyncError(
                "ClockSync.fit requires at least 2 samples"
            )
        ts = np.array([t for t, _ in self._unwrapped], dtype=float)
        ps = np.array([p for _, p in self._unwrapped], dtype=float)
        n = len(ts)
        sx, sy = ts.sum(), ps.sum()
        sxx = float((ts * ts).sum())
        sxy = float((ts * ps).sum())
        denom = n * sxx - sx * sx
        if abs(denom) < 1e-12:
            raise ClockSyncError("ClockSync.fit degenerate samples")
        a = (n * sxy - sx * sy) / denom
        b = (sy - a * sx) / n
        self._a = float(a)
        self._b = float(b)
        self._batch_means = None   # 逐点拟合，无批次均值
        return self._a, self._b

    def fit_batched(self, batch_threshold_ns: int = 10_000_000) -> Tuple[float, float]:
        """按接收批次均值拟合（针对 ESP01S 批量投递的遥测）。

        当一批帧在极短时间内被 PC 读到（pc_recv_ns 几乎相同、但 tick 连续
        递增 20ms）时，逐点最小二乘会被"批内平 pc"扭曲。这里把 pc_recv_ns
        差距 < *batch_threshold_ns* 的连续样本合并为一批，用批次均值拟合。
        """
        if len(self._unwrapped) < 2:
            raise ClockSyncError("ClockSync.fit requires at least 2 samples")
        # 按 pc_recv_ns 分组
        batches: List[List[Tuple[int, int]]] = []
        for uw, pc in self._unwrapped:
            if batches and abs(pc - batches[-1][-1][1]) < batch_threshold_ns:
                batches[-1].append((uw, pc))
            else:
                batches.append([(uw, pc)])
        if len(batches) < 2:
            raise ClockSyncError(
                "fit_batched requires at least 2 batches")
        ts = np.array([sum(t for t, _ in b) / len(b) for b in batches], dtype=float)
        ps = np.array([sum(p for _, p in b) / len(b) for b in batches], dtype=float)
        n = len(ts)
        sx, sy = ts.sum(), ps.sum()
        sxx = float((ts * ts).sum())
        sxy = float((ts * ps).sum())
        denom = n * sxx - sx * sx
        if abs(denom) < 1e-12:
            raise ClockSyncError("fit_batched degenerate samples")
        a = (n * sxy - sx * sy) / denom
        b = (sy - a * sx) / n
        self._a = float(a)
        self._b = float(b)
        self._batch_means = [
            (float(t), float(p)) for t, p in zip(ts, ps)
        ]
        return self._a, self._b

    def params(self) -> Tuple[float, float]:
        """返回拟合参数 (a, b)。未拟合时抛错。"""
        if self._a is None or self._b is None:
            raise ClockSyncError("ClockSync not fitted; call fit() first")
        return self._a, self._b

    def tick_to_pc_ns(self, tick_ms: int) -> float:
        """把 MCU tick 映射到 PC ns（查询 tick 视作与样本同回绕时代）。"""
        if self._a is None or self._b is None:
            raise ClockSyncError("ClockSync not fitted; call fit() first")
        uw = int(tick_ms) + self._offset
        return self._a * uw + self._b

    def pc_ns_to_tick(self, pc_ns: float) -> float:
        """把 PC ns 反向映射到 MCU tick（返回浮点 ms）。"""
        if self._a is None or self._b is None:
            raise ClockSyncError("ClockSync not fitted; call fit() first")
        return (pc_ns - self._b) / self._a

    def fit_residuals(self) -> Dict[str, float]:
        """当前拟合的残差诊断（ns）。

        - fit_batched 后：对批次均值计算残差（拟合对象与拟合方式一致）。
        - fit() 后：对逐点样本计算残差。
        返回 {"rms_ns": ..., "max_ns": ..., "n": ...}。
        """
        if self._a is None or self._b is None:
            raise ClockSyncError("ClockSync not fitted; call fit() first")
        if self._batch_means is not None:
            pts = self._batch_means
        else:
            pts = [(float(t), float(p)) for t, p in self._unwrapped]
        errs = [
            abs(self._a * t + self._b - p) for t, p in pts
        ]
        if not errs:
            return {"rms_ns": 0.0, "max_ns": 0.0, "n": 0}
        arr = np.asarray(errs, dtype=float)
        return {
            "rms_ns": float(np.sqrt((arr * arr).mean())),
            "max_ns": float(arr.max()),
            "n": int(len(errs)),
        }
