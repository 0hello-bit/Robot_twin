"""旧模型隔离检查器 (Task 4B-0)。

Task 4A 判定旧数字孪生 NOT READY（data leak、参数与固件量级不符、合成数据）。
v1_twin 命名空间必须与旧路径完全隔离，否则模型筛选会被旧孪生污染。

检查分两级：
1. **源码静态扫描**（`scan_imports` / `scan_package_source`）— 确定性，不依赖
   pytest 会话状态；是本任务的自动验收主门。
2. **sys.modules 运行期诊断**（`scan_legacy_sys_modules`）— 检测当前进程已加载
   的旧模块，供审计与回归排查使用。

禁用前缀依据 Task 4A 审计 / 纲领 §11 隔离表。
"""

from __future__ import annotations

import ast
import os
import sys
from typing import Dict, List, Tuple

from v1_twin.v1_twin_errors import V1IsolationError

# 旧路径模块前缀（Task 4A / 纲领 §11 隔离表）。
# - control_sandbox: plant_model.py / pid_optimizer.py 等，搜索范围与固件不对齐
# - analysis.closed_loop_validator: data leak（real_error == sim_error）
# - calibration.sim_replay_calibrator: 同一 replay_data 做 pre/post 验证
# - config: PID 默认值与固件不匹配（Kp=0.6 vs 35.0）
LEGACY_FORBIDDEN_PREFIXES: Tuple[str, ...] = (
    "control_sandbox",
    "analysis.closed_loop_validator",
    "calibration.sim_replay_calibrator",
    "config",
)


def _matches_forbidden(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in LEGACY_FORBIDDEN_PREFIXES
    )


# ============================================================
# 源码静态扫描（主门）
# ============================================================


def scan_imports(source: str) -> List[str]:
    """静态扫描源码中的旧路径 import，返回违规模块名列表。

    基于 AST 解析，覆盖 `import x`、`import a.b as c`、`import x, y`、
    `from a.b import c` 等常见形式。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # 无法解析的源码按"不通过"处理：宁可报警也不放过违规 import。
        return ["<unparseable>"]

    violations: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches_forbidden(alias.name):
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # 仅检查绝对导入（level == 0）；相对导入在包内，不会命中顶层旧前缀。
            if node.level == 0 and node.module and _matches_forbidden(node.module):
                violations.append(node.module)
    return sorted(set(violations))


def _default_package_dir() -> str:
    """默认扫描 v1_twin 包目录（本文件所在目录）。"""
    return os.path.dirname(os.path.abspath(__file__))


def scan_package_source(package_dir: str | None = None) -> Dict[str, List[str]]:
    """扫描包目录下全部 .py 源文件，返回 {相对路径: [违规模块名]}。"""
    root = os.path.abspath(package_dir) if package_dir else _default_package_dir()
    result: Dict[str, List[str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    source = f.read()
            except OSError as exc:
                raise V1IsolationError(
                    "cannot read {0}: {1}".format(path, exc)
                ) from exc
            hits = scan_imports(source)
            if hits:
                rel = os.path.relpath(path, root).replace("\\", "/")
                result[rel] = hits
    return result


def assert_isolated(package_dir: str | None = None) -> None:
    """确认 v1_twin 包源码未引用任何旧路径；违规则抛 V1IsolationError。"""
    violations = scan_package_source(package_dir)
    if violations:
        details = "; ".join(
            "{0} -> {1}".format(rel, ",".join(names))
            for rel, names in sorted(violations.items())
        )
        raise V1IsolationError(
            "v1_twin imports legacy digital-twin module(s): " + details
        )


# ============================================================
# sys.modules 运行期诊断
# ============================================================


def scan_legacy_sys_modules() -> List[str]:
    """返回当前进程 sys.modules 中已加载的旧路径模块名（已排序去重）。"""
    return sorted(
        name for name in sys.modules if _matches_forbidden(name)
    )


def assert_no_legacy_in_sys_modules() -> None:
    """确认当前进程未加载任何旧路径模块；违规则抛 V1IsolationError。"""
    hits = scan_legacy_sys_modules()
    if hits:
        raise V1IsolationError(
            "legacy digital-twin module(s) present in sys.modules: " + ", ".join(hits)
        )
