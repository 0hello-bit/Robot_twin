"""Task 1 mutation proof drive — temporary copy, single-anchor mutant, MSVC compile & run.

Each mutation creates a clean directory, verifies the anchor appears exactly once,
compiles clean and mutant variants with MSVC, runs each against the named killer
selector, and records all evidence (hashes, diff, compile log, run log, exit codes).

Usage:
    python run_task1_mutation_proof.py [--output-dir <dir>]
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Project paths (relative to this script's location)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]  # scripts/digital_twin/simulation -> project root
FW_DIR = PROJECT_ROOT / "程序" / "3. 麦轮巡线小车" / "User"
PRODUCTION_SOURCE = FW_DIR / "twin_control_protocol.c"
PRODUCTION_HEADER = FW_DIR / "twin_control_protocol.h"
TEST_SOURCE = (
    PROJECT_ROOT
    / "simulation"
    / "digital_twin"
    / "tests"
    / "test_twin_control_protocol.c"
)

# ---------------------------------------------------------------------------
# MSVC toolchain (discovered once)
# ---------------------------------------------------------------------------
MSVC_CL: Path | None = None
MSVC_INCLUDE: Path | None = None
UCRT_INCLUDE: Path | None = None
SHARED_INCLUDE: Path | None = None
UM_INCLUDE: Path | None = None
MSVC_LIB: Path | None = None
UCRT_LIB: Path | None = None
UM_LIB: Path | None = None


def _find_msvc() -> tuple[Path, ...] | None:
    """Locate MSVC cl.exe and the SDK include/lib paths."""
    candidates = [
        Path(r"D:\vs2022\VC\Tools\MSVC\14.42.34433\bin\Hostx64\x64\cl.exe"),
    ]
    for c in candidates:
        if c.is_file():
            msvc_root = c.parents[3]  # up 4 levels: .../MSVC/14.xx.xxxxx/
            inc = msvc_root / "include"
            lib = msvc_root / "lib" / "x64"
            ucrt_inc = Path(r"D:\Windows Kits\10\Include\10.0.22621.0\ucrt")
            shared_inc = Path(r"D:\Windows Kits\10\Include\10.0.22621.0\shared")
            um_inc = Path(r"D:\Windows Kits\10\Include\10.0.22621.0\um")
            ucrt_lib = Path(r"D:\Windows Kits\10\Lib\10.0.22621.0\ucrt\x64")
            um_lib = Path(r"D:\Windows Kits\10\Lib\10.0.22621.0\um\x64")
            if inc.is_dir() and ucrt_inc.is_dir() and lib.is_dir():
                return (c, inc, ucrt_inc, shared_inc, um_inc, lib, ucrt_lib, um_lib)
    return None


def _ensure_msvc() -> None:
    global MSVC_CL, MSVC_INCLUDE, UCRT_INCLUDE, SHARED_INCLUDE, UM_INCLUDE
    global MSVC_LIB, UCRT_LIB, UM_LIB
    if MSVC_CL is not None:
        return
    found = _find_msvc()
    if found is None:
        print("FATAL: MSVC cl.exe not found. Checked:", file=sys.stderr)
        for c in [r"D:\vs2022\VC\Tools\MSVC\14.42.34433\bin\Hostx64\x64\cl.exe"]:
            print(f"  {c}", file=sys.stderr)
        sys.exit(2)
    (MSVC_CL, MSVC_INCLUDE, UCRT_INCLUDE, SHARED_INCLUDE, UM_INCLUDE,
     MSVC_LIB, UCRT_LIB, UM_LIB) = found
    print(f"[setup] MSVC: {MSVC_CL}")
    print(f"[setup] inc: {MSVC_INCLUDE}")
    print(f"[setup] ucrt: {UCRT_INCLUDE}")


def _sha256(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def _anchor_count(content: str, anchor: str) -> int:
    return content.count(anchor)


# ---------------------------------------------------------------------------
# Mutation definitions
# ---------------------------------------------------------------------------
MUTATIONS = {
    "bounds": {
        "label": "Remove parse_speed() maximum check",
        "killer": "bounds",
        "file": PRODUCTION_SOURCE,
        "anchor": (
            '    if (*end != \'\\0\' || parsed < TWIN_CONTROL_SPEED_MIN ||\n'
            '        parsed > TWIN_CONTROL_SPEED_MAX) return 0U;'
        ),
        "replacement": (
            '    if (*end != \'\\0\' || parsed < TWIN_CONTROL_SPEED_MIN) return 0U;'
        ),
    },
    "step": {
        "label": "Make exceeds_float_step() use >= instead of >",
        "killer": "step",
        "file": PRODUCTION_SOURCE,
        "anchor": (
            '    return (difference > maximum_step || difference < -maximum_step) ? 1U : 0U;'
        ),
        "replacement": (
            '    return (difference >= maximum_step || difference <= -maximum_step) ? 1U : 0U;'
        ),
    },
    "null_byte": {
        "label": "Remove byte < 0x20 reject in receive_byte()",
        "killer": "nul",
        "file": PRODUCTION_SOURCE,
        "anchor": (
            '    if (byte < 0x20U || byte > 0x7EU) {\n'
            '        g_line_overflow = 1U;\n'
            '        return 0U;\n'
            '    }'
        ),
        "replacement": (
            '    if (byte > 0x7EU) {\n'
            '        g_line_overflow = 1U;\n'
            '        return 0U;\n'
            '    }'
        ),
    },
    "rollback": {
        "label": "Remove g_restore_baseline branch in apply_pending()",
        "killer": "rollback",
        "file": PRODUCTION_SOURCE,
        "anchor": (
            '    if (g_restore_baseline) {\n'
            '        if (g_has_pending_params) {\n'
            '            make_result(result, 0U, g_pending_params.campaign_id,\n'
            '                        g_pending_params.version, g_rollback_reason);\n'
            '        }\n'
            '        *active = *baseline;\n'
            '        g_last_speed_max = baseline->speed_max;\n'
            '        g_last_kp = baseline->kp;\n'
            '        g_last_ki = baseline->ki;\n'
            '        g_last_kd = baseline->kd;\n'
            '        g_has_pending_params = 0U;\n'
            '        g_restore_baseline = 0U;\n'
            '        g_rollback_reason = 0;\n'
            '        return 1U;\n'
            '    }'
        ),
        "replacement": (
            '    if (0) { /* mutation: rollback disabled */\n'
            '        if (g_has_pending_params) {\n'
            '            make_result(result, 0U, g_pending_params.campaign_id,\n'
            '                        g_pending_params.version, g_rollback_reason);\n'
            '        }\n'
            '        *active = *baseline;\n'
            '        g_last_speed_max = baseline->speed_max;\n'
            '        g_last_kp = baseline->kp;\n'
            '        g_last_ki = baseline->ki;\n'
            '        g_last_kd = baseline->kd;\n'
            '        g_has_pending_params = 0U;\n'
            '        g_restore_baseline = 0U;\n'
            '        g_rollback_reason = 0;\n'
            '        return 1U;\n'
            '    }'
        ),
    },
    "start": {
        "label": "Remove !g_restore_baseline guard on START",
        "killer": "start",
        "file": PRODUCTION_SOURCE,
        "anchor": (
            '    } else if (strcmp(fields[3], "START") == 0 && !g_restore_baseline) {'
        ),
        "replacement": (
            '    } else if (strcmp(fields[3], "START") == 0) {'
        ),
    },
}

# ---------------------------------------------------------------------------
# Compile and run helpers
# ---------------------------------------------------------------------------
_COMPILE_ARGS = [
    "/nologo",
    "/TC",
    "/W4",
    "/WX",
    "/source-charset:utf-8",
    "/D_CRT_SECURE_NO_WARNINGS",
]


def _cl_exe() -> str:
    _ensure_msvc()
    return str(MSVC_CL)


def _include_args() -> list[str]:
    _ensure_msvc()
    return [
        f'/I"{MSVC_INCLUDE}"',
        f'/I"{UCRT_INCLUDE}"',
        f'/I"{SHARED_INCLUDE}"',
        f'/I"{UM_INCLUDE}"',
    ]


def _link_args() -> list[str]:
    _ensure_msvc()
    return [
        "/link",
        f'/LIBPATH:"{MSVC_LIB}"',
        f'/LIBPATH:"{UCRT_LIB}"',
        f'/LIBPATH:"{UM_LIB}"',
    ]


# ---------------------------------------------------------------------------
# Build system temp base (pure ASCII path to avoid cmd.exe encoding issues)
# ---------------------------------------------------------------------------
_TEMP_BASE = Path(r"C:\temp\mutation_proof")


def _compile(work_dir: Path, exe_name: str, sources: list[Path]) -> subprocess.CompletedProcess:
    """Compile sources into an exe in work_dir, return completed process."""
    _ensure_msvc()
    args = [str(MSVC_CL), "/nologo", "/TC", "/W4", "/WX", "/source-charset:utf-8",
            "/D_CRT_SECURE_NO_WARNINGS",
            f'/I{MSVC_INCLUDE}', f'/I{UCRT_INCLUDE}',
            f'/I{SHARED_INCLUDE}', f'/I{UM_INCLUDE}']
    args.extend([str(s) for s in sources])
    args.append(f'/Fe{work_dir / exe_name}')
    args.extend(['/link', f'/LIBPATH:{MSVC_LIB}', f'/LIBPATH:{UCRT_LIB}', f'/LIBPATH:{UM_LIB}'])
    log_msg = f"cl compile {' '.join(str(s) for s in sources)} -> {exe_name}"
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="mbcs",
        errors="replace",
        cwd=work_dir,
    )


def _run_test(work_dir: Path, exe_name: str, selector: str) -> subprocess.CompletedProcess:
    """Run the test exe with the given selector."""
    return subprocess.run(
        [str(work_dir / exe_name), selector],
        capture_output=True,
        text=True,
        encoding="ascii",
        errors="replace",
        cwd=work_dir,
    )


# ---------------------------------------------------------------------------
# Single mutation proof
# ---------------------------------------------------------------------------
def _proof_one(
    mutation_name: str,
    config: dict,
    work_dir: Path,
    clean_dir: Path,
) -> dict:
    label = config["label"]
    anchor = config["anchor"]
    killer = config["killer"]
    source_to_mutate = config["file"]

    result = {
        "name": mutation_name,
        "label": label,
        "killer": killer,
        "ok": False,
        "errors": [],
        "clean_sha": "",
        "mutant_sha": "",
        "anchor_count": 0,
        "clean_compile_ok": False,
        "clean_run_ok": False,
        "clean_exit_code": -1,
        "clean_stdout": "",
        "clean_compile_log": "",
        "mutant_compile_ok": False,
        "mutant_run_ok": False,
        "mutant_exit_code": -1,
        "mutant_stdout": "",
        "mutant_compile_log": "",
        "diff": "",
    }

    print(f"\n{'=' * 60}")
    print(f"[{mutation_name}] {label}")
    print(f"[{mutation_name}] anchor check + clean compile -> clean run ; "
          f"mutant compile -> mutant run")

    # ---- anchor verification ----
    source_content = source_to_mutate.read_text(encoding="utf-8")
    n = _anchor_count(source_content, anchor)
    result["anchor_count"] = n
    if n != 1:
        msg = f"anchor appears {n} times, expected 1"
        result["errors"].append(msg)
        print(f"[{mutation_name}] FAIL: {msg}")
        return result

    # ---- clean compile ----
    clean_exe = f"clean_{mutation_name}.exe"
    cp = _compile(clean_dir, clean_exe, [
        clean_dir / "twin_control_protocol.c",
        clean_dir / "test_twin_control_protocol.c",
    ])
    result["clean_compile_ok"] = cp.returncode == 0
    result["clean_compile_log"] = cp.stdout + cp.stderr
    if not result["clean_compile_ok"]:
        result["errors"].append("clean compile failed")
        print(f"[{mutation_name}] FAIL: clean compile failed")
        return result
    print(f"[{mutation_name}] clean compile OK")

    # ---- clean run ----
    cp = _run_test(clean_dir, clean_exe, killer)
    result["clean_exit_code"] = cp.returncode
    result["clean_stdout"] = cp.stdout
    result["clean_run_ok"] = cp.returncode == 0
    if not result["clean_run_ok"]:
        msg = f"clean run exit {cp.returncode}, expected 0:\n{cp.stdout[:200]}"
        result["errors"].append(msg)
        print(f"[{mutation_name}] FAIL: {msg}")
        return result
    print(f"[{mutation_name}] clean run OK (exit 0)")

    # ---- create mutant ----
    mutant_content = source_content.replace(anchor, config["replacement"], 1)
    mutant_file = work_dir / "twin_control_protocol.c"
    mutant_file.write_text(mutant_content, encoding="utf-8")
    # Also copy header and test source to work_dir for compilation
    shutil.copy2(clean_dir / "twin_control_protocol.h", work_dir / "twin_control_protocol.h")
    shutil.copy2(clean_dir / "test_twin_control_protocol.c", work_dir / "test_twin_control_protocol.c")
    result["mutant_sha"] = _sha256(mutant_file)
    result["clean_sha"] = _sha256(clean_dir / "twin_control_protocol.c")
    result["diff"] = "\n".join(
        difflib.unified_diff(
            (clean_dir / "twin_control_protocol.c").read_text(encoding="utf-8").splitlines(),
            mutant_content.splitlines(),
            fromfile="clean/twin_control_protocol.c",
            tofile="mutant/twin_control_protocol.c",
            lineterm="",
        )
    )

    # ---- mutant compile ----
    mutant_exe = f"mutant_{mutation_name}.exe"
    cp = _compile(work_dir, mutant_exe, [
        work_dir / "twin_control_protocol.c",
        work_dir / "test_twin_control_protocol.c",
    ])
    result["mutant_compile_ok"] = cp.returncode == 0
    result["mutant_compile_log"] = cp.stdout + cp.stderr
    if not result["mutant_compile_ok"]:
        compile_log = cp.stdout + cp.stderr
        result["errors"].append(f"mutant compile failed (not killed):\n{compile_log[:300]}")
        print(f"[{mutation_name}] FAIL: mutant compile failed")
        print(f"  compile output: {compile_log[:500]}")
        return result
    print(f"[{mutation_name}] mutant compile OK")

    # ---- mutant run ----
    cp = _run_test(work_dir, mutant_exe, killer)
    result["mutant_exit_code"] = cp.returncode
    result["mutant_stdout"] = cp.stdout
    result["mutant_run_ok"] = cp.returncode != 0
    if cp.returncode == 0:
        msg = f"mutant run exit 0 (not killed), expected != 0"
        result["errors"].append(msg)
        print(f"[{mutation_name}] FAIL: {msg}")
        return result
    print(f"[{mutation_name}] mutant killed (exit {cp.returncode})")

    # ---- passed ----
    result["ok"] = True
    print(f"[{mutation_name}] PASS")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Task 1 mutation proof: clean vs single-anchor mutant for 5 gates"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / ".embeddedskills" / "build" / "task1-final",
        help="Output directory for logs and working directories",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[main] output: {output_dir}")

    # Verify production source exists
    if not PRODUCTION_SOURCE.is_file():
        print(f"FATAL: production source not found: {PRODUCTION_SOURCE}", file=sys.stderr)
        return 1
    if not TEST_SOURCE.is_file():
        print(f"FATAL: test source not found: {TEST_SOURCE}", file=sys.stderr)
        return 1

    _ensure_msvc()

    # Clean and recreate temp base
    if _TEMP_BASE.exists():
        shutil.rmtree(_TEMP_BASE)
    _TEMP_BASE.mkdir(parents=True, exist_ok=True)

    all_ok = True
    all_results = []

    for name, cfg in MUTATIONS.items():
        # Use ASCII-only temp paths for compilation
        clean_dir = _TEMP_BASE / name / "clean"
        clean_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PRODUCTION_SOURCE, clean_dir / "twin_control_protocol.c")
        shutil.copy2(PRODUCTION_HEADER, clean_dir / "twin_control_protocol.h")
        shutil.copy2(TEST_SOURCE, clean_dir / "test_twin_control_protocol.c")

        mutation_dir = _TEMP_BASE / name / "mutant"
        mutation_dir.mkdir(parents=True, exist_ok=True)

        res = _proof_one(name, cfg, mutation_dir, clean_dir)
        all_results.append(res)
        if not res["ok"]:
            all_ok = False

    # ---- summary ----
    print(f"\n{'=' * 60}")
    print("MUTATION PROOF SUMMARY")
    print(f"{'=' * 60}")
    for r in all_results:
        status = "PASS" if r["ok"] else "FAIL"
        print(f"  [{status}] {r['name']}: {r['label']}")
        if not r["ok"]:
            for e in r["errors"]:
                print(f"         {e}")

    # Write per-mutation detail files + summary manifest
    manifest_path = output_dir / "mutation_proof_manifest.txt"
    with open(manifest_path, "w", encoding="ascii") as f:
        for r in all_results:
            # Summary line
            f.write("mutation_name={name}\n".format(name=r['name']))
            f.write("status={s}\n".format(s='PASS' if r['ok'] else 'FAIL'))
            f.write("label={l}\n".format(l=r['label']))
            f.write("killer={k}\n".format(k=r['killer']))
            f.write("anchor_count={c}\n".format(c=r['anchor_count']))
            f.write("clean_sha256={h}\n".format(h=r.get('clean_sha', '')))
            f.write("mutant_sha256={h}\n".format(h=r.get('mutant_sha', '')))
            f.write("clean_compile_ok={v}\n".format(v=r['clean_compile_ok']))
            f.write("clean_exit_code={v}\n".format(v=r['clean_exit_code']))
            f.write("mutant_compile_ok={v}\n".format(v=r['mutant_compile_ok']))
            f.write("mutant_exit_code={v}\n".format(v=r['mutant_exit_code']))
            f.write("ok={v}\n".format(v=r['ok']))
            f.write("---\n")

            # Per-mutation detail file
            detail_path = output_dir / "mutation_{name}_detail.txt".format(name=r['name'])
            detail = [
                "mutation_name={name}".format(name=r['name']),
                "label={l}".format(l=r['label']),
                "killer={k}".format(k=r['killer']),
                "anchor_count={c}".format(c=r['anchor_count']),
                "",
                "--- clean sha256 ---",
                r.get('clean_sha', ''),
                "--- mutant sha256 ---",
                r.get('mutant_sha', ''),
                "",
                "--- diff ---",
                r.get('diff', ''),
                "",
                "--- clean compile log ---",
                r.get('clean_compile_log', ''),
                "",
                "--- clean run stdout ---",
                r.get('clean_stdout', ''),
                "",
                "--- mutant compile log ---",
                r.get('mutant_compile_log', ''),
                "",
                "--- mutant run stdout ---",
                r.get('mutant_stdout', ''),
                "",
            ]
            with open(detail_path, "w", encoding="utf-8") as df:
                df.write("\n".join(detail) + "\n")

    print(f"\n[main] manifest: {manifest_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
