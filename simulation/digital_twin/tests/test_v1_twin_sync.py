"""Tests for ClockSync (MCU tick → PC ns 映射) (Task 4B-4)。

先写测试后实现：模块尚不存在时应 RED。

验证：
- MCU tick 回绕（uint32 溢出）展开
- 线性回归恢复 tick→PC ns 映射
- 正/反向映射往返
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from v1_twin.v1_twin_sync import ClockSync, TICK_MODULUS


def test_tick_modulus_is_uint32():
    assert TICK_MODULUS == 1 << 32


def test_add_sample_unwraps_wrapped_tick():
    cs = ClockSync()
    # 100ms, 200ms, 300ms, 然后回绕到 50ms（+2^32）
    cs.add_sample(100, 1_000_000_000)
    cs.add_sample(200, 2_000_000_000)
    cs.add_sample(300, 3_000_000_000)
    cs.add_sample(50, 4_000_000_000)  # 回绕
    uw = cs.unwrapped_ticks()
    assert uw == [100, 200, 300, TICK_MODULUS + 50]
    # 展开后严格递增
    assert all(b > a for a, b in zip(uw, uw[1:]))


def test_linear_regression_recovers_mapping():
    cs = ClockSync()
    # pc_ns = 1_000_000 * tick + 500_000 (每 ms 对应 1ms 墙钟，偏移 0.5ms)
    for tick in range(0, 10_000, 20):
        cs.add_sample(tick, 1_000_000 * tick + 500_000)
    cs.fit()
    a, b = cs.params()
    assert a == pytest.approx(1_000_000, rel=1e-6)
    assert b == pytest.approx(500_000, rel=1e-3)


def test_tick_to_pc_ns_and_back():
    cs = ClockSync()
    for tick in range(0, 5_000, 20):
        cs.add_sample(tick, 2_000_000 * tick + 1_000)
    cs.fit()
    pc = cs.tick_to_pc_ns(1234)
    assert pc == pytest.approx(2_000_000 * 1234 + 1_000, rel=1e-6)
    tick_back = cs.pc_ns_to_tick(pc)
    assert tick_back == pytest.approx(1234, rel=1e-6)


def test_fit_requires_at_least_two_samples():
    cs = ClockSync()
    cs.add_sample(100, 1_000_000)
    with pytest.raises(RuntimeError):
        cs.fit()


def test_no_wrap_sequence_unwrapped_unchanged():
    cs = ClockSync()
    for tick in (0, 20, 40, 60, 80):
        cs.add_sample(tick, tick * 1_000_000)
    assert cs.unwrapped_ticks() == [0, 20, 40, 60, 80]


def test_fit_batched_recovers_mapping_under_batched_delivery():
    """模拟 ESP01S 批量投递：批内各帧 PC 接收时间近似相同（同一 recv 集群），
    源 tick 每帧递增 20ms；批与批之间按真实交付节奏推进。

    数据真实表达“批内接收时间近似相同、源 tick 递增”：
    - 批内 6 帧 tick 相隔 20ms，但 pc 只差亚毫秒（同一 burst 到达）
    - 批间隔 = true_a × batch_tick_span = 120ms（实时交付，仅突发打包）

    fit_batched 用批次均值拟合，必须恢复真实速率斜率 a≈1e6，
    且拟合线必须穿过每个批次均值（一致性，而非强行对齐错误期望）。
    注意：批内平 pc 使 intercept 吸收批内 mean-tick 偏移，因此只断言
    a（速率）与批次均值一致性，不断言某个具体 b。
    """
    cs = ClockSync()
    true_a, true_b = 1_000_000, 500_000
    delivery_delay_ns = 30_000_000          # 固定投递延迟 30ms
    batch_tick_span = 120                   # 每批覆盖 120ms tick（6 帧 × 20ms）
    batch_means = []                        # [(mean_tick, mean_pc)]
    for start_tick in range(0, 10_000, batch_tick_span):
        base_pc = true_a * start_tick + true_b + delivery_delay_ns
        ticks, pcs = [], []
        for j in range(6):
            tick = start_tick + j * 20
            # 批内接收时间近似相同：仅亚毫秒抖动（< fit_batched 阈值 10ms）
            pc = base_pc + (j % 2) * 100_000
            cs.add_sample(tick, pc)
            ticks.append(tick)
            pcs.append(pc)
        batch_means.append((sum(ticks) / len(ticks), sum(pcs) / len(pcs)))
    cs.fit_batched()
    a, _ = cs.params()
    # 速率斜率恢复（真实时钟速率）
    assert a == pytest.approx(true_a, rel=1e-3)
    # 拟合映射与每个批次均值一致
    for mt, mp in batch_means:
        assert cs.tick_to_pc_ns(mt) == pytest.approx(mp, rel=1e-3)


def test_fit_still_works_when_no_batching():
    """无批量投递（帧逐个到达，pc 间隔反映真实节奏）时 fit() 正常。"""
    cs = ClockSync()
    true_a, true_b = 1_000_000, 500_000
    for tick in range(0, 5_000, 20):
        cs.add_sample(tick, true_a * tick + true_b)
    cs.fit()
    a, b = cs.params()
    assert a == pytest.approx(true_a, rel=1e-6)
    assert b == pytest.approx(true_b, rel=1e-3)
