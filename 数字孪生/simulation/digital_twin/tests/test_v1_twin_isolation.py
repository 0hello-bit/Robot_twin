"""Tests for 旧模型隔离检查器 (Task 4B-0)。

先写测试后实现：模块尚不存在时应 RED。

Task 4A 判定旧数字孪生 NOT READY（data leak、参数与固件量级不符、合成数据）。
v1_twin 命名空间必须与旧路径完全隔离。本测试验证隔离检查器能：
- 静态扫描检测源码中的旧路径 import（确定性，不依赖 pytest 会话状态）
- 确认 v1_twin 包自身不引用任何旧路径
- 运行期检测 sys.modules 中的旧模块（诊断用途）

旧路径前缀（LEGACY_FORBIDDEN_PREFIXES）依据 Task 4A / 纲领 §11 隔离表。
"""

from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from v1_twin import v1_twin_isolation as iso
from v1_twin.v1_twin_errors import V1IsolationError


# ============================================================
# 旧路径 import 片段（Task 4A / 纲领 §11）
# ============================================================

# 每个片段映射到其应当被检测出的完整违规模块路径（含父包前缀）
LEGACY_SNIPPETS = {
    "control_sandbox": (
        "control_sandbox.plant_model",
        "from control_sandbox.plant_model import PlantModel\n",
    ),
    "config": ("config", "import config as cfg\n"),
    "closed_loop_validator": (
        "analysis.closed_loop_validator",
        "from analysis.closed_loop_validator import validate_open_loop\n",
    ),
    "sim_replay_calibrator": (
        "calibration.sim_replay_calibrator",
        "from calibration.sim_replay_calibrator import SimReplayCalibrator\n",
    ),
}


# ============================================================
# 静态源码扫描
# ============================================================


def test_scan_imports_detects_each_legacy_prefix():
    for label, (expected, snippet) in LEGACY_SNIPPETS.items():
        hits = iso.scan_imports(snippet)
        assert expected in hits, (
            "missing detection for legacy prefix {0}: got {1}".format(label, hits)
        )


def test_scan_imports_handles_alias_and_multi_import():
    source = (
        "import control_sandbox.pid_optimizer as po\n"
        "import os, sys\n"
        "from config import DEFAULT_KP\n"
    )
    hits = iso.scan_imports(source)
    assert "control_sandbox.pid_optimizer" in hits
    assert "config" in hits


def test_scan_imports_ignores_benign_imports():
    source = (
        "import json\n"
        "import math\n"
        "from dataclasses import dataclass\n"
        "from v1_twin.v1_twin_errors import V1SchemaError\n"
        "from v1_twin.v1_twin_schema import V1Pose\n"
    )
    assert iso.scan_imports(source) == []


# ============================================================
# v1_twin 包整体隔离（主门）
# ============================================================


def test_scan_package_source_returns_empty_for_v1_twin():
    assert iso.scan_package_source() == {}


def test_assert_isolated_passes_for_v1_twin_package():
    # 不应抛 V1IsolationError
    iso.assert_isolated()


def test_assert_isolated_raises_on_violating_package(tmp_path):
    (tmp_path / "bad_module.py").write_text(
        "import config\n", encoding="utf-8"
    )
    with pytest.raises(V1IsolationError):
        iso.assert_isolated(package_dir=str(tmp_path))


def test_scan_imports_handles_deep_prefix():
    # `calibration.sim_replay_calibrator` 是 `calibration` 的深层子模块，
    # 但 `calibration` 整体不在禁用前缀内 —— 只禁确切的旧路径。
    source = "from calibration.sim_replay_calibrator import SimReplayCalibrator\n"
    hits = iso.scan_imports(source)
    assert any(h == "calibration.sim_replay_calibrator" for h in hits)


# ============================================================
# sys.modules 运行期诊断
# ============================================================


def test_scan_legacy_sys_modules_detects_injected_module(monkeypatch):
    fake = types.ModuleType("control_sandbox")
    monkeypatch.setitem(sys.modules, "control_sandbox", fake)
    hits = iso.scan_legacy_sys_modules()
    assert "control_sandbox" in hits


def test_assert_no_legacy_in_sys_modules_raises_when_present(monkeypatch):
    fake = types.ModuleType("config")
    monkeypatch.setitem(sys.modules, "config", fake)
    with pytest.raises(V1IsolationError):
        iso.assert_no_legacy_in_sys_modules()
