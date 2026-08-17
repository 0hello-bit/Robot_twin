# Sync Trajectory Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, dependency-free dashboard that visualizes the real run's camera trajectory, MPU6050 heading, fused heading, frame-analysis loss, and synchronization gates without inventing an independent IMU position.

**Architecture:** A Python builder parses one evidence run and writes a compact `dashboard_data.json` plus a copy of the static HTML template into an output directory. The browser renders Canvas plots from that JSON and keeps the evidence boundary visible: camera `x/y` is the only position series, while MPU6050 contributes heading only.

**Tech Stack:** Python 3 standard library for parsing and generation, pytest for data-layer tests, native HTML/CSS/JavaScript Canvas for the dashboard, and Python's standard-library HTTP server for local serving.

## Global Constraints

- Do not derive or display a synthetic inertial `x/y` track; the captured telemetry has MPU6050 heading but no accelerometer or wheel odometry.
- Preserve `causal_sync=FAIL` and all observed thresholds in the dashboard; never turn the alignment gate into a full synchronization pass.
- Keep the implementation dependency-free in the browser and do not modify firmware, hardware, or existing evidence files.
- The new generated dashboard for the current run belongs under that run's evidence directory; the large AVI remains referenced, not copied into web assets.
- Preserve unrelated dirty worktree changes and stage only files owned by this feature.

---

### Task 1: Add the data contract tests

**Files:**
- Create: `simulation/digital_twin/tests/test_sync_dashboard_data.py`
- Test target: `tools/visualization/build_sync_dashboard.py`

**Interfaces:**
- Consumes: a temporary run directory containing `sync_report.json`, `pose.jsonl`, `telemetry.jsonl`, `fusion.jsonl`, and `frame_index.jsonl`.
- Produces: assertions for `build_dashboard_data(run_dir)` and `write_dashboard(run_dir, output_dir, template_path)`.

- [ ] **Step 1: Write the failing tests**

```python
import json
from pathlib import Path


def write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


TEST_TEMPLATE = Path("tools/visualization/sync_dashboard.html")


def make_run_fixture(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "sync_report.json").write_text(json.dumps({
        "run_id": "fixture",
        "duration_s": 1.0,
        "n_poses": 2,
        "n_telemetry": 3,
        "sync_gate_verdict": "PASS",
        "alignment_verdict": "PASS",
        "causal_sync_verdict": "FAIL",
        "video_evidence": {"frames_written": 3},
        "diagnostics": {"analysis": {
            "captured_frames": 3,
            "processed_frames": 2,
            "dropped_frames": 1,
            "incomplete_frames": 0,
        }},
        "causal_sync": {"verdict": "FAIL", "sample_count": 8},
    }), encoding="utf-8")
    write_jsonl(run_dir / "pose.jsonl", [
        {"t_pc_ns": 100, "x_mm": 1.0, "y_mm": 2.0, "yaw_rad": 0.1},
        {"t_pc_ns": 200, "x_mm": 2.0, "y_mm": 3.0, "yaw_rad": 0.2},
    ])
    write_jsonl(run_dir / "telemetry.jsonl", [
        {"pc_recv_ns": 100, "imu_yaw_rad": 0.05},
        {"pc_recv_ns": 150, "imu_yaw_rad": 0.06},
        {"pc_recv_ns": 200, "imu_yaw_rad": 0.07},
    ])
    write_jsonl(run_dir / "fusion.jsonl", [
        {"camera_timestamp_ns": 100, "camera_x_mm": 1.0,
         "camera_y_mm": 2.0, "camera_yaw_rad": 0.1,
         "imu_yaw_rad": 0.05, "fused_yaw_rad": 0.08,
         "quality": "USED_IMU"},
        {"camera_timestamp_ns": 200, "camera_x_mm": 2.0,
         "camera_y_mm": 3.0, "camera_yaw_rad": 0.2,
         "imu_yaw_rad": 0.07, "fused_yaw_rad": 0.17,
         "quality": "CAMERA_ONLY"},
    ])
    write_jsonl(run_dir / "frame_index.jsonl", [
        {"frame_index": 0, "analysis_status": "processed"},
        {"frame_index": 1, "analysis_status": "processed"},
        {"frame_index": 2, "analysis_status": "dropped"},
    ])
    return run_dir


def test_dashboard_data_preserves_evidence_boundary_and_heading_series(tmp_path):
    run_dir = make_run_fixture(tmp_path)
    data = build_dashboard_data(run_dir)

    assert data["position_comparison"]["available"] is False
    assert data["position_comparison"]["reason"]
    assert data["counts"]["video_frames_written"] == 3
    assert data["counts"]["analysis_dropped_frames"] == 1
    assert data["heading"]["series"][0]["camera_yaw_rad"] == 0.1
    assert data["gates"]["causal_sync_verdict"] == "FAIL"


def test_dashboard_builder_writes_compact_html_and_json(tmp_path):
    run_dir = make_run_fixture(tmp_path)
    output_dir = tmp_path / "dashboard"
    write_dashboard(run_dir, output_dir, template_path=TEST_TEMPLATE)

    assert (output_dir / "index.html").is_file()
    assert (output_dir / "dashboard_data.json").is_file()
```

- [ ] **Step 2: Run the focused tests to verify the expected failure**

Run: `pytest -q simulation/digital_twin/tests/test_sync_dashboard_data.py`

Expected: FAIL because `tools/visualization/build_sync_dashboard.py` does not yet exist.

### Task 2: Implement the evidence data builder

**Files:**
- Create: `tools/visualization/build_sync_dashboard.py`
- Modify: `simulation/digital_twin/tests/test_sync_dashboard_data.py` only if the fixture needs a contract-preserving correction.

**Interfaces:**
- `build_dashboard_data(run_dir: Path) -> dict`: parse and normalize one run.
- `write_dashboard(run_dir: Path, output_dir: Path, template_path: Path | None = None) -> Path`: write `dashboard_data.json`, copy the template as `index.html`, and return the output directory.
- CLI: `python tools/visualization/build_sync_dashboard.py --run-dir <run> --output-dir <dir>`.

- [ ] **Step 1: Implement strict JSONL readers and required-file validation**

Read `sync_report.json`, `pose.jsonl`, `telemetry.jsonl`, `fusion.jsonl`, and `frame_index.jsonl`; raise a readable `ValueError` for malformed records and a `FileNotFoundError` for missing required files. Keep optional fields absent rather than zero-filled.

- [ ] **Step 2: Implement timestamp normalization and derived heading metrics**

Use the first available fusion/camera timestamp as `t0_ns`; expose relative `t_s` values. Compute wrapped camera-versus-IMU heading residuals with `atan2(sin(delta), cos(delta))`, and compute p95 over finite samples. Preserve each fusion record's `quality`, `imu_gap_ns`, and `fused_yaw_rad`.

- [ ] **Step 3: Implement explicit position availability and gate summaries**

Emit `position_comparison.available = false` with an explanatory reason when no independent inertial `x/y` exists. Copy observed video/analysis counts, alignment values, causal-clock values, verdicts, and policy thresholds from the report without changing them.

- [ ] **Step 4: Implement the CLI writer**

Write UTF-8 JSON with stable indentation, copy `tools/visualization/sync_dashboard.html` to `index.html`, and print the absolute output path plus counts. Do not copy the AVI.

- [ ] **Step 5: Run the focused tests to verify the green result**

Run: `pytest -q simulation/digital_twin/tests/test_sync_dashboard_data.py`

Expected: all data-builder tests pass.

### Task 3: Build the responsive measurement dashboard

**Files:**
- Create: `tools/visualization/sync_dashboard.html`

**Interfaces:**
- Consumes: sibling `dashboard_data.json` loaded with `fetch`.
- Produces: responsive local dashboard with canvas plots, text summaries, and visible evidence limitations.

- [ ] **Step 1: Add semantic layout and evidence rail**

Create a header with run id and verdict, a fixed evidence rail for alignment/causal-clock/position-boundary status, and responsive sections for trajectory, heading, capture health, and event details.

- [ ] **Step 2: Add the trajectory and heading Canvas renderers**

Render camera `x/y` in millimetres with quality-colored points. Render camera, IMU, and fused heading on a shared relative-time axis; include a text summary beneath each canvas for accessibility and no-canvas fallback.

- [ ] **Step 3: Add capture-health and gate presentation**

Show video frames written, analysis processed/dropped, telemetry count, alignment p95, causal-clock RTT/residual/uncertainty, and exact verdict labels. Display an explicit unavailable state for independent IMU position comparison.

- [ ] **Step 4: Add responsive/focus/reduced-motion styling**

Use the measurement-console palette from the design spec, stable canvas dimensions, keyboard-visible focus, mobile single-column layout, and no animation dependency for core information.

### Task 4: Generate and inspect the real-run dashboard

**Files:**
- Generate: `docs/evidence/v1_b3_camera_capture_analysis_decoupled_20260817/c260817013638536/dashboard/index.html`
- Generate: `docs/evidence/v1_b3_camera_capture_analysis_decoupled_20260817/c260817013638536/dashboard/dashboard_data.json`

**Interfaces:**
- Consumes: the immutable run artifacts already captured.
- Produces: a browser-ready dashboard for the user to inspect.

- [ ] **Step 1: Build the dashboard from the real run**

Run: `python tools/visualization/build_sync_dashboard.py --run-dir docs/evidence/v1_b3_camera_capture_analysis_decoupled_20260817/c260817013638536 --output-dir docs/evidence/v1_b3_camera_capture_analysis_decoupled_20260817/c260817013638536/dashboard`

- [ ] **Step 2: Validate generated data against the report**

Run: `python -c "import json; from pathlib import Path; out=Path('docs/evidence/v1_b3_camera_capture_analysis_decoupled_20260817/c260817013638536/dashboard'); data=json.loads((out/'dashboard_data.json').read_text(encoding='utf-8')); report=json.loads((out.parent/'sync_report.json').read_text(encoding='utf-8')); assert data['counts']['video_frames_written'] == report['video_evidence']['frames_written']; assert data['position_comparison']['available'] is False; assert data['gates']['alignment_verdict'] == report['alignment_verdict']; assert data['gates']['causal_sync_verdict'] == report['causal_sync_verdict']"`.

- [ ] **Step 3: Serve the dashboard locally**

Run a standard-library HTTP server from the generated dashboard directory on the first free local port in the `8765`-`8775` range and report the URL.

### Task 5: Verify and review

**Files:**
- No source changes expected.

- [ ] **Step 1: Run focused Python tests and syntax checks**

Run: `pytest -q simulation/digital_twin/tests/test_sync_dashboard_data.py`

Run: `python -m py_compile tools/visualization/build_sync_dashboard.py`

- [ ] **Step 2: Inspect the rendered page at desktop and mobile sizes**

Use the available local browser automation to load the served URL, capture one desktop and one mobile screenshot, verify both Canvas elements have non-zero pixels, and check that the evidence rail does not overlap the plots.

- [ ] **Step 3: Run a final diff check**

Run: `git diff --check`; confirm only the dashboard source, test, design/plan files, and generated dashboard outputs are attributable to this task. Do not stage unrelated dirty files.
