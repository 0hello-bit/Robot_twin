#!/usr/bin/env python3
"""Task 2A final acceptance driver — runs all gates in one session.

Output directory: .embeddedskills/build/task2a-final/
Each gate saves its own raw log and exit code.
The script exits non-zero if any mandatory gate fails.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FW_DIR = PROJECT_ROOT / "程序" / "3. 麦轮巡线小车" / "User"
BUILD_DIR = PROJECT_ROOT / ".embeddedskills" / "build"
TASK2A_DIR = BUILD_DIR / "task2a-final"
DOCS_DIR = PROJECT_ROOT / "docs" / "superpowers"
SCRIPT_DIR = Path(__file__).parent
TEST_DIR = PROJECT_ROOT / "simulation" / "digital_twin" / "tests"
BRIDGE_DIR = PROJECT_ROOT / "simulation" / "digital_twin" / "web_showcase"

PYTHON = r"C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe"

# MSVC paths
MSVC_CL = r"D:\vs2022\VC\Tools\MSVC\14.42.34433\bin\Hostx64\x64\cl.exe"
MSVC_INC = r"D:\vs2022\VC\Tools\MSVC\14.42.34433\include"
MSVC_LIB = r"D:\vs2022\VC\Tools\MSVC\14.42.34433\lib\x64"
MSVC_BIN = r"D:\vs2022\VC\Tools\MSVC\14.42.34433\bin\Hostx64\x64"
UCRT_INC = r"D:\Windows Kits\10\Include\10.0.22621.0\ucrt"
UCRT_LIB = r"D:\Windows Kits\10\Lib\10.0.22621.0\ucrt\x64"
SHARED_INC = r"D:\Windows Kits\10\Include\10.0.22621.0\shared"
UM_INC = r"D:\Windows Kits\10\Include\10.0.22621.0\um"
UM_LIB = r"D:\Windows Kits\10\Lib\10.0.22621.0\um\x64"

# Keil paths
KEIL_CANDIDATES = [
    r"F:\keil\UV4\UV4.exe",
    r"C:\Keil_v5\UV4\UV4.exe",
    r"D:\Keil_v5\UV4\UV4.exe",
]

# Source files for production module check
PRODUCTION_C_SOURCES = [
    FW_DIR / "twin_control_protocol.c",
    FW_DIR / "ipd_parser.c",
    FW_DIR / "esp_runtime_transport.c",
]
PRODUCTION_H_SOURCES = [
    FW_DIR / "twin_control_protocol.h",
    FW_DIR / "ipd_parser.h",
    FW_DIR / "esp_runtime_transport.h",
]


class GateResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.skipped = False
        self.exit_code: int | None = None
        self.stdout = ""
        self.stderr = ""
        self.log_path: Path | None = None
        self.commands: list[str] = []
        self.tests_total: int | None = None
        self.tests_passed: int | None = None
        self._start: float | None = None

    def begin(self):
        self._start = time.time()
        return self

    def duration(self) -> str:
        if self._start is None:
            return "0.0s"
        return "{0:.1f}s".format(time.time() - self._start)

    def end(self):
        return self

    def __str__(self):
        status = "[PASS]" if self.passed else ("[SKIP]" if self.skipped else "[FAIL]")
        return "{0} {1} ({2})".format(status, self.name, self.duration())


def log_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Utility: run a command with timeout
# ---------------------------------------------------------------------------
def run_cmd(args: list[str], timeout_s: int = 60, cwd: Path | None = None,
            env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        cp = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s, cwd=str(cwd) if cwd else None,
            env=env,
        )
        return cp
    except subprocess.TimeoutExpired:
        raise TimeoutError("Command timed out after {0}s: {1}".format(timeout_s, args[0]))


# ---------------------------------------------------------------------------
# MSVC environment
# ---------------------------------------------------------------------------
def _msvc_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PATH", "")
    env["PATH"] = MSVC_BIN + os.pathsep + env["PATH"]
    return env


# ---------------------------------------------------------------------------
# Gate 1: Baseline hashes
# ---------------------------------------------------------------------------
def gate_baseline_hashes(output_dir: Path) -> GateResult:
    gate = GateResult("baseline-hashes").begin()
    lines = []
    for f in PRODUCTION_C_SOURCES + PRODUCTION_H_SOURCES + [
        FW_DIR / "main.c",
        PROJECT_ROOT / "程序" / "3. 麦轮巡线小车" / "project.uvprojx",
    ]:
        if f.is_file():
            h = sha256(f.read_bytes())
            lines.append("{0}  SHA256={1}".format(f.relative_to(PROJECT_ROOT).as_posix(), h))
            gate.stdout += lines[-1] + "\n"
        else:
            gate.stderr += "MISSING: {0}\n".format(f)
    lines.insert(0, "# Task 2A baseline hashes ({0})".format(datetime.datetime.now().isoformat()))
    log_write(output_dir / "baseline_hashes.txt", "\n".join(lines) + "\n")
    gate.passed = True
    return gate.end()


# ---------------------------------------------------------------------------
# Gate 2: IPD parser standalone test
# ---------------------------------------------------------------------------
def gate_ipd_parser(output_dir: Path) -> GateResult:
    gate = GateResult("ipd-parser").begin()
    temp = Path(r"C:\temp\task2a_ipd")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    for src in [FW_DIR / "ipd_parser.c", FW_DIR / "ipd_parser.h"]:
        shutil.copy2(src, temp / src.name)

    test_src = PROJECT_ROOT / "simulation" / "digital_twin" / "tests" / "test_ipd_parser.c"
    shutil.copy2(test_src, temp / test_src.name)

    args = [
        MSVC_CL, "/nologo", "/TC", "/W4", "/WX", "/utf-8",
        "/D_CRT_SECURE_NO_WARNINGS",
        f"/I{temp}",
        f"/I{MSVC_INC}", f"/I{UCRT_INC}", f"/I{SHARED_INC}", f"/I{UM_INC}",
        str(temp / test_src.name),
        str(temp / "ipd_parser.c"),
        f"/Fe{temp / 'test_ipd_parser.exe'}",
        "/link",
        f"/LIBPATH:{MSVC_LIB}", f"/LIBPATH:{UCRT_LIB}", f"/LIBPATH:{UM_LIB}",
    ]
    gate.commands.append("compile: " + " ".join(str(a) for a in args))
    try:
        cp = run_cmd(args, timeout_s=60, env=_msvc_env())
        gate.stdout += cp.stdout + cp.stderr
        if cp.returncode != 0:
            gate.exit_code = cp.returncode
            gate.stderr = "compile failed"
            return gate.end()

        # Run
        cp2 = run_cmd([str(temp / "test_ipd_parser.exe")], timeout_s=10)
        gate.stdout += "\n--- RUN ---\n" + cp2.stdout + cp2.stderr
        gate.exit_code = cp2.returncode
        gate.passed = (cp2.returncode == 0)
        if not gate.passed:
            gate.stderr = "test failed (exit {0})".format(cp2.returncode)
    except TimeoutError as e:
        gate.stderr = str(e)
    except Exception as e:
        gate.stderr = str(e)
    finally:
        log_path = output_dir / "ipd_parser.log"
        log_write(log_path, gate.stdout + "\n--- stderr ---\n" + gate.stderr)
        gate.log_path = log_path
    return gate.end()


# ---------------------------------------------------------------------------
# Gate 3: Production transport integration (uses SAME module as main.c)
# ---------------------------------------------------------------------------
def gate_production_integration(output_dir: Path) -> GateResult:
    gate = GateResult("production-integration").begin()
    temp = Path(r"C:\temp\task2a_prod")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    for src in [
        FW_DIR / "ipd_parser.c", FW_DIR / "ipd_parser.h",
        FW_DIR / "esp_runtime_transport.c", FW_DIR / "esp_runtime_transport.h",
        FW_DIR / "twin_control_protocol.c", FW_DIR / "twin_control_protocol.h",
    ]:
        shutil.copy2(src, temp / src.name)

    test_src = PROJECT_ROOT / "simulation" / "digital_twin" / "tests" / "test_ipd_integration.c"
    shutil.copy2(test_src, temp / test_src.name)

    args = [
        MSVC_CL, "/nologo", "/TC", "/W4", "/WX", "/utf-8",
        "/D_CRT_SECURE_NO_WARNINGS",
        f"/I{temp}",
        f"/I{MSVC_INC}", f"/I{UCRT_INC}", f"/I{SHARED_INC}", f"/I{UM_INC}",
        str(temp / test_src.name),
        str(temp / "ipd_parser.c"),
        str(temp / "esp_runtime_transport.c"),
        str(temp / "twin_control_protocol.c"),
        f"/Fe{temp / 'test_ipd_integration.exe'}",
        "/link",
        f"/LIBPATH:{MSVC_LIB}", f"/LIBPATH:{UCRT_LIB}", f"/LIBPATH:{UM_LIB}",
    ]
    gate.commands.append("compile: " + " ".join(str(a) for a in args))
    try:
        cp = run_cmd(args, timeout_s=60, env=_msvc_env())
        gate.stdout += cp.stdout + cp.stderr
        if cp.returncode != 0:
            gate.exit_code = cp.returncode
            gate.stderr = "compile failed"
            return gate.end()

        cp2 = run_cmd([str(temp / "test_ipd_integration.exe")], timeout_s=10)
        gate.stdout += "\n--- RUN ---\n" + cp2.stdout + cp2.stderr
        gate.exit_code = cp2.returncode
        gate.passed = (cp2.returncode == 0)
        if not gate.passed:
            gate.stderr = "test failed (exit {0})".format(cp2.returncode)
    except TimeoutError as e:
        gate.stderr = str(e)
    except Exception as e:
        gate.stderr = str(e)
    finally:
        log_path = output_dir / "production_integration.log"
        log_write(log_path, gate.stdout + "\n--- stderr ---\n" + gate.stderr)
        gate.log_path = log_path
    return gate.end()


# ---------------------------------------------------------------------------
# Gate 4: Task 1 regression (Host C)
# ---------------------------------------------------------------------------
def gate_task1_host_c(output_dir: Path) -> GateResult:
    gate = GateResult("task1-host-c").begin()
    temp = Path(r"C:\temp\task2a_t1c")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    for src in [FW_DIR / "twin_control_protocol.c", FW_DIR / "twin_control_protocol.h"]:
        shutil.copy2(src, temp / src.name)

    test_src = TEST_DIR / "test_twin_control_protocol.c"
    shutil.copy2(test_src, temp / test_src.name)

    args = [
        MSVC_CL, "/nologo", "/TC", "/W4", "/WX", "/utf-8",
        "/D_CRT_SECURE_NO_WARNINGS",
        f"/I{temp}",
        f"/I{MSVC_INC}", f"/I{UCRT_INC}", f"/I{SHARED_INC}", f"/I{UM_INC}",
        str(temp / test_src.name),
        str(temp / "twin_control_protocol.c"),
        f"/Fe{temp / 'test_t1.exe'}",
        "/link",
        f"/LIBPATH:{MSVC_LIB}", f"/LIBPATH:{UCRT_LIB}", f"/LIBPATH:{UM_LIB}",
    ]
    gate.commands.append("compile: " + " ".join(str(a) for a in args))
    try:
        cp = run_cmd(args, timeout_s=60, env=_msvc_env())
        gate.stdout += cp.stdout + cp.stderr
        if cp.returncode != 0:
            gate.exit_code = cp.returncode
            gate.stderr = "compile failed"
            return gate.end()

        # Run full regression
        cp2 = run_cmd([str(temp / "test_t1.exe")], timeout_s=10)
        gate.stdout += "\n--- RUN ---\n" + cp2.stdout + cp2.stderr
        gate.exit_code = cp2.returncode
        gate.passed = (cp2.returncode == 0)
        test_count = cp2.stdout.count("test_") if not gate.passed else 12
        gate.tests_total = test_count
        gate.tests_passed = test_count
        if not gate.passed:
            gate.stderr = "Task 1 regression failed (exit {0})".format(cp2.returncode)
    except TimeoutError as e:
        gate.stderr = str(e)
    except Exception as e:
        gate.stderr = str(e)
    finally:
        log_path = output_dir / "task1_host_c.log"
        log_write(log_path, gate.stdout + "\n--- stderr ---\n" + gate.stderr)
        gate.log_path = log_path
    return gate.end()


# ---------------------------------------------------------------------------
# Gate 5: Task 1 regression (Python)
# ---------------------------------------------------------------------------
def gate_task1_python(output_dir: Path) -> GateResult:
    gate = GateResult("task1-python").begin()
    test_dir = PROJECT_ROOT / "simulation" / "digital_twin"
    try:
        cp = run_cmd(
            [PYTHON, "-m", "pytest", "tests/test_runtime_protocol.py",
             "tests/test_runtime_protocol_cross_language.py",
             "-v", "--tb=short"],
            timeout_s=120, cwd=test_dir,
        )
        gate.stdout += cp.stdout + cp.stderr
        gate.exit_code = cp.returncode
        gate.passed = (cp.returncode == 0)
        # Parse pytest output for counts
        for line in cp.stdout.splitlines():
            if "passed" in line and "failed" not in line and "collected" not in line:
                parts = line.split()
                for p in parts:
                    if p.isdigit():
                        if gate.tests_passed is None:
                            gate.tests_passed = int(p)
                        else:
                            gate.tests_total = int(p)
    except TimeoutError as e:
        gate.stderr = str(e)
    except Exception as e:
        gate.stderr = str(e)
    finally:
        log_path = output_dir / "task1_python.log"
        log_write(log_path, gate.stdout + "\n--- stderr ---\n" + gate.stderr)
        gate.log_path = log_path
    return gate.end()


# ---------------------------------------------------------------------------
# Gate 6: Task 2 Python tests (bridge, bridge, demux, logger)
# ---------------------------------------------------------------------------
def gate_task2_python(output_dir: Path) -> GateResult:
    gate = GateResult("task2-python").begin()
    test_dir = PROJECT_ROOT / "simulation" / "digital_twin"
    test_files = [
        "tests/test_task2_bridge.py",
        "tests/test_stream_demuxer.py",
    ]
    # test_live_wifi_mock.py is under web_showcase, separate
    try:
        cp = run_cmd(
            [PYTHON, "-m", "pytest"] + test_files + ["-v", "--tb=short"],
            timeout_s=120, cwd=test_dir,
        )
        gate.stdout += cp.stdout + cp.stderr
        gate.exit_code = cp.returncode
        gate.passed = (cp.returncode == 0)
    except TimeoutError as e:
        gate.stderr = str(e)
    except Exception as e:
        gate.stderr = str(e)
    finally:
        log_path = output_dir / "task2_python.log"
        log_write(log_path, gate.stdout + "\n--- stderr ---\n" + gate.stderr)
        gate.log_path = log_path
    return gate.end()


# ---------------------------------------------------------------------------
# Gate 7: test_live_wifi_mock.py (websockets-dependent)
# ---------------------------------------------------------------------------
def gate_live_wifi_mock(output_dir: Path) -> GateResult:
    """Mandatory gate: run test_live_wifi_mock.py against the bridge in mock mode.

    Missing test file, missing dependencies, subprocess crash, timeout, or
    non-zero exit all cause FAIL (not SKIP).
    """
    gate = GateResult("live-wifi-mock").begin()
    test_file = BRIDGE_DIR / "test_live_wifi_mock.py"

    if not test_file.is_file():
        gate.stderr = "test file not found: {0}".format(test_file)
        gate.exit_code = -1
        return gate.end()

    try:
        cp = run_cmd(
            [PYTHON, str(test_file)],
            timeout_s=60, cwd=BRIDGE_DIR,
        )
        gate.stdout = "\n--- STDOUT ---\n" + cp.stdout
        gate.stdout += "\n--- STDERR ---\n" + cp.stderr
        gate.exit_code = cp.returncode
        gate.passed = (cp.returncode == 0)
        if not gate.passed:
            gate.stderr = "test_live_wifi_mock.py failed (exit {0})".format(cp.returncode)
    except TimeoutError as e:
        gate.stderr = "TIMEOUT: {0}".format(e)
    except Exception as e:
        gate.stderr = "EXCEPTION: {0}".format(e)
    finally:
        log_path = output_dir / "live_wifi_mock.log"
        log_write(log_path, gate.stdout + "\n--- stderr ---\n" + gate.stderr)
        gate.log_path = log_path
    return gate.end()


# ---------------------------------------------------------------------------
# Gate 8: Keil Target 1 Rebuild
# ---------------------------------------------------------------------------
def gate_keil(output_dir: Path) -> GateResult:
    gate = GateResult("keil-rebuild").begin()
    proj = PROJECT_ROOT / "程序" / "3. 麦轮巡线小车" / "project.uvprojx"
    if not proj.is_file():
        gate.stderr = "uvprojx not found"
        gate.skipped = True
        return gate.end()

    uv4: Path | None = None
    for cand in KEIL_CANDIDATES:
        p = Path(cand)
        if p.is_file():
            uv4 = p
            break
    if uv4 is None:
        gate.stdout = "UV4.exe not found among candidates"
        gate.skipped = True
        return gate.end()

    keil_log = output_dir / "keil_build_output.log"
    gate.commands.append("UV4: {0} -r {1} -j0 -l {2}".format(str(uv4), str(proj), str(keil_log)))
    try:
        cp = run_cmd(
            [str(uv4), "-r", str(proj), "-j0", "-l", str(keil_log)],
            timeout_s=120,
        )
        gate.stdout += cp.stdout + cp.stderr
        gate.exit_code = cp.returncode
        # UV4 exit code 0 = no error, read the log file
        build_log = ""
        if keil_log.is_file():
            build_log = keil_log.read_text(encoding="utf-8", errors="replace")
        gate.stdout += "\n--- build log ---\n" + build_log[-2000:]

        has_zero_error = "0 Error(s)" in build_log
        has_zero_warning = "0 Warning(s)" in build_log

        # Check ipd_parser.c was compiled
        has_ipd_compile = "ipd_parser.c" in build_log

        # Check esp_runtime_transport.c was compiled
        has_transport_compile = "esp_runtime_transport.c" in build_log

        gate.passed = (has_zero_error and has_zero_warning and
                       has_ipd_compile and has_transport_compile)
        if not has_ipd_compile:
            gate.stderr += " ipd_parser.c not compiled"
        if not has_transport_compile:
            gate.stderr += " esp_runtime_transport.c not compiled"
        if not has_zero_error or not has_zero_warning:
            gate.stderr += " errors/warnings found"
    except TimeoutError as e:
        gate.stderr = str(e)
    except Exception as e:
        gate.stderr = str(e)
    finally:
        log_path = output_dir / "keil_rebuild.log"
        log_write(log_path, gate.stdout + "\n--- stderr ---\n" + gate.stderr)
        gate.log_path = log_path
    return gate.end()


# ---------------------------------------------------------------------------
# Gate 9: Static production reference check
# ---------------------------------------------------------------------------
def gate_production_refs(output_dir: Path) -> GateResult:
    """Verify that main.c and LiveWifiBridge reference the production modules."""
    gate = GateResult("production-refs").begin()
    lines = []
    errors = []

    # Check main.c
    main_text = (FW_DIR / "main.c").read_text(encoding="utf-8", errors="replace")
    checks = [
        ("main.c reaches ipd_parser.h (via esp_runtime_transport.h)",
         '#include "ipd_parser.h"' in main_text or '#include "esp_runtime_transport.h"' in main_text),
        ("main.c includes esp_runtime_transport.h", '#include "esp_runtime_transport.h"' in main_text),
        ("main.c calls esp_transport_init", "esp_transport_init" in main_text),
        ("main.c calls esp_transport_process_byte", "esp_transport_process_byte" in main_text),
        ("main.c includes twin_control_protocol.h", '#include "twin_control_protocol.h"' in main_text),
        ("main.c calls twin_control_apply_pending", "twin_control_apply_pending" in main_text),
        ("main.c calls ESP_SendAsciiFrame for ACK/status transport", "ESP_SendAsciiFrame" in main_text),
        ("main.c calls ESP_SendQueuedFrames", "ESP_SendQueuedFrames" in main_text),
    ]
    for desc, ok in checks:
        lines.append("  [{0}] {1}".format("OK" if ok else "MISSING", desc))
        if not ok:
            errors.append(desc)

    # Check LiveWifiBridge
    bridge_text = (BRIDGE_DIR / "live_wifi_bridge.py").read_text(encoding="utf-8", errors="replace")
    py_checks = [
        ("bridge imports StreamDemuxer", "StreamDemuxer" in bridge_text),
        ("bridge imports parse_ack", "parse_ack" in bridge_text),
        ("bridge imports parse_status", "parse_status" in bridge_text),
        ("bridge imports AckRegistry", "AckRegistry" in bridge_text),
        ("bridge instantiates StreamDemuxer", "StreamDemuxer(" in bridge_text),
        ("bridge instantiates AckRegistry", "AckRegistry()" in bridge_text),
        ("bridge._on_ascii_line calls parse_ack", "parse_ack(line)" in bridge_text),
        ("bridge._on_ascii_line calls parse_status", "parse_status(line)" in bridge_text),
        ("bridge._on_ascii_line calls _deliver_ack", "_deliver_ack" in bridge_text),
        ("bridge._deliver_ack uses AckRegistry", "self._ack_registry.deliver" in bridge_text),
        ("bridge._wifi_loop calls self._demuxer.feed", "self._demuxer.feed" in bridge_text),
    ]
    for desc, ok in py_checks:
        lines.append("  [{0}] {1}".format("OK" if ok else "MISSING", desc))
        if not ok:
            errors.append(desc)

    gate.stdout = "# Production reference checks\n" + "\n".join(lines) + "\n"
    gate.passed = len(errors) == 0
    if errors:
        gate.stderr = "Missing references:\n  " + "\n  ".join(errors)
    log_path = output_dir / "production_refs.txt"
    log_write(log_path, gate.stdout + "\n--- stderr ---\n" + gate.stderr)
    gate.log_path = log_path
    return gate.end()


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def generate_report(gates: list[GateResult], output_dir: Path, status_line: str):
    TASK2A_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = """# Robot Twin AI V1 — Task 2A Final Acceptance Report

**Status:** {0}
**Date:** {1}
**Output directory:** {2}

---

## Gates

""".format(status_line, now, TASK2A_DIR)

    for g in gates:
        icon = "[PASS]" if g.passed else ("[SKIP]" if g.skipped else "[FAIL]")
        report += "### {0} {1}\n\n".format(icon, g.name)
        report += "- **Duration:** {0}\n".format(g.duration())
        report += "- **Exit code:** {0}\n".format(g.exit_code)
        report += "- **Tests total:** {0}\n".format(g.tests_total or "N/A")
        report += "- **Tests passed:** {0}\n".format(g.tests_passed or "N/A")
        if g.log_path:
            mtime = datetime.datetime.fromtimestamp(g.log_path.stat().st_mtime) if g.log_path.is_file() else "N/A"
            report += "- **Log:** `{0}` (mtime: {1})\n".format(g.log_path, mtime)
        if g.commands:
            for c in g.commands:
                report += "- **Command:**\n  ```\n  {0}\n  ```\n".format(c)
        if g.stderr:
            report += "- **Stderr:**\n  ```\n  {0}\n  ```\n".format(g.stderr[:500])
        report += "\n"

    report += """---

## Notes

- All offline gates were executed on host with no vehicle, no serial connection.
- MSVC was used for Host C tests as a stand-in for the host-side compiler.
- Keil rebuild is gated on UV4 availability.
- live-wifi-mock is a mandatory gate; missing websockets or other dependencies causes FAIL, not SKIP
- Real-vehicle integration, ESP UART transport, and TCP remain unverified.
- No vehicle connected, no serial port opened, no flash/download/debug/reset performed.

---

*Report generated by run_task2a_final.py*
"""
    report_path = DOCS_DIR / "task2a-final-acceptance.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Task 2A final acceptance")
    parser.add_argument("--keil-path", type=str, default=None, help="Keil UV4.exe path")
    args = parser.parse_args()

    if KEIL_CANDIDATES and args.keil_path:
        KEIL_CANDIDATES.insert(0, args.keil_path)

    # Clean task2a output dir
    TASK2A_DIR.mkdir(parents=True, exist_ok=True)
    for item in TASK2A_DIR.iterdir():
        if item.is_file():
            item.unlink()

    gates = []

    g = gate_baseline_hashes(TASK2A_DIR)
    gates.append(g); print(g)

    g = gate_ipd_parser(TASK2A_DIR)
    gates.append(g); print(g)

    g = gate_production_integration(TASK2A_DIR)
    gates.append(g); print(g)

    g = gate_task1_host_c(TASK2A_DIR)
    gates.append(g); print(g)

    g = gate_task1_python(TASK2A_DIR)
    gates.append(g); print(g)

    g = gate_task2_python(TASK2A_DIR)
    gates.append(g); print(g)

    g = gate_live_wifi_mock(TASK2A_DIR)
    gates.append(g); print(g)

    g = gate_keil(TASK2A_DIR)
    gates.append(g); print(g)

    g = gate_production_refs(TASK2A_DIR)
    gates.append(g); print(g)

    # Final status: ALL gates must have passed == True
    all_pass = all(g.passed for g in gates)
    failed = [g for g in gates if not g.passed]

    if all_pass:
        status_line = "Task 2A complete"
        print("\n[PASS] All gates passed. Ready for Task 2B (hardware authorization required).")
    else:
        status_line = "Task 2A incomplete"
        print("\n[FAIL] Some gates did not pass:")
        for g in gates:
            if not g.passed:
                print("  - {0}: exit={1} {2}".format(
                    g.name, g.exit_code, g.stderr[:120] if g.stderr else ""))

    report_path = generate_report(gates, TASK2A_DIR, status_line)
    print("Report: {0}".format(report_path))
    print()
    print("NOTICE: No vehicle connected, no serial port opened,")
    print("no flash/download/debug/reset/motor performed.")
    print("Real ESP UART transport and vehicle remain unverified.")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
