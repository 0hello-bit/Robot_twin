# Camera Capture and Analysis Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple AprilTag analysis from the TCP capture loop so slow vision processing cannot reduce the number of camera frames written during a bounded run.

**Architecture:** Keep `run_sync_capture_session()` as the owner of TCP heartbeats, the 20-second deadline, camera reads, video writes, and STOP cleanup. Add one bounded `queue.Queue` and a worker thread that consumes analysis items and returns pose/diagnostic results; queue overflow drops only analysis work and is recorded per frame. Add a compact analysis summary to existing report diagnostics.

**Tech Stack:** Python 3, `threading`, `queue.Queue`, OpenCV, pytest, existing fake socket/camera/writer fixtures.

## Global Constraints

- Do not change firmware, TCP wire messages, START/STOP commands, heartbeat policy, or causal-clock sampling.
- Do not duplicate or interpolate frames to manufacture a 30 fps evidence stream.
- Preserve exactly-once STOP/socket/camera/video cleanup and bounded worker joining.
- Use `frame_index.jsonl` capture timestamps for evidence; analysis results may be incomplete or dropped.
- All regression tests must run without a real camera, car, or network connection.

---

### Task 1: Add failing worker and backpressure tests

**Files:**
- Modify: `simulation/digital_twin/tests/test_capture_sync_cleanup.py`
- Test: `simulation/digital_twin/tests/test_capture_sync_cleanup.py`

**Interfaces:**
- The tests will exercise `capture_sync_run._AnalysisWorker` with `submit(frame, frame_index, t_pc_ns)`, `drain_results()`, `stop(timeout_s)`, and `summary`.
- The session-level test will inspect `diagnostics["analysis"]`, `video_evidence["frames_written"]`, and `frame_index` records returned by `run_sync_capture_session()`.

- [ ] **Step 1: Write the worker backpressure test**

Add a test named `test_analysis_worker_drops_only_analysis_work_when_queue_is_full` with a tracker that blocks on an event. Start `_AnalysisWorker` with `queue_size=1`, submit one frame successfully, submit a second frame while the tracker is blocked, assert the second submission returns `False`, then release the tracker and stop the worker. Assert the summary reports one submitted frame and one dropped frame, and the first result retains its original frame index and timestamp.

```python
worker = capture_sync_run._AnalysisWorker(
    BlockingTracker(released), queue_size=1
)
worker.start()
assert worker.submit(object(), 7, 123456789)
assert not worker.submit(object(), 8, 123456790)
released.set()
worker.stop(timeout_s=0.5)
assert worker.summary["dropped_frames"] == 1
assert worker.drain_results()[0]["t_pc_ns"] == 123456789
```

- [ ] **Step 2: Run the focused test and verify the expected RED failure**

Run:

```powershell
python -m pytest simulation/digital_twin/tests/test_capture_sync_cleanup.py -k "analysis_worker_drops_only_analysis_work_when_queue_is_full" -q
```

Expected: collection or execution fails because `_AnalysisWorker` does not exist yet. A failure caused by a test typo must be corrected before implementation.

- [ ] **Step 3: Add the session-level slow-analysis test**

Add `test_capture_writes_frames_while_analysis_is_slow`. Use the existing fake socket and an image camera that returns frames quickly, a fake writer that records every write, and a tracker that sleeps before returning no pose. Run a short offline session with `video_writer` and `video_evidence`. Assert `outcome == "ok"`, `frames_written == len(frame_index)`, `diagnostics["analysis"]["captured_frames"] == len(frame_index)`, and `diagnostics["analysis"]["dropped_frames"] >= 1`.

- [ ] **Step 4: Run both new tests and verify they fail for the missing worker/integration behavior**

Run:

```powershell
python -m pytest simulation/digital_twin/tests/test_capture_sync_cleanup.py -k "analysis_worker or capture_writes_frames_while_analysis_is_slow" -q
```

Expected: RED before production changes.

### Task 2: Implement the bounded analysis worker

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Test: `simulation/digital_twin/tests/test_capture_sync_cleanup.py`

**Interfaces:**
- Add `_AnalysisWorker(tracker, queue_size=ANALYSIS_QUEUE_SIZE)`.
- `start()` launches one daemon thread.
- `submit(frame, frame_index, t_pc_ns)` uses `put_nowait()` and returns `True` when queued, `False` when full.
- `drain_results()` returns all currently available result dictionaries without blocking.
- `stop(timeout_s)` sets the stop event and joins at most the supplied timeout.
- `summary` exposes `submitted_frames`, `processed_frames`, `dropped_frames`, `incomplete_frames`, and `worker_errors`.

- [ ] **Step 1: Add the minimal worker implementation**

Import `queue`, define `ANALYSIS_QUEUE_SIZE = 8` and `ANALYSIS_JOIN_TIMEOUT_S = 1.0`, and implement `_AnalysisWorker`. Each result dictionary must include `frame_index`, `t_pc_ns`, `pose`, `diagnostics`, `frame`, and either `analysis_status="processed"` or `analysis_status="error"`. Catch worker exceptions and return them as `analysis_error`; never send network data from the worker.

- [ ] **Step 2: Run the worker tests and verify GREEN**

Run:

```powershell
python -m pytest simulation/digital_twin/tests/test_capture_sync_cleanup.py -k "analysis_worker_drops_only_analysis_work_when_queue_is_full" -q
```

Expected: PASS with the queue-full result and original timestamp assertions satisfied.

- [ ] **Step 3: Keep worker shutdown bounded**

When `stop()` returns, report `worker_alive` and count queued items that never produced results as `incomplete_frames`. Do not block indefinitely on a tracker call.

- [ ] **Step 4: Re-run the worker tests**

Run:

```powershell
python -m pytest simulation/digital_twin/tests/test_capture_sync_cleanup.py -k "analysis_worker" -q
```

Expected: PASS with no real hardware access.

### Task 3: Integrate the worker into capture and evidence reporting

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Modify: `simulation/digital_twin/tests/test_capture_sync_cleanup.py`
- Modify: `simulation/digital_twin/tests/test_capture_sync_report.py`

**Interfaces:**
- The session thread continues to own `cap.read()`, `video_writer.write()`, heartbeats, deadline, and `cleanup_session()`.
- Each successfully read frame receives `t_pc_ns` before video writing and `analysis_status="queued"` or `"dropped"`.
- `_AnalysisWorker` results update the matching frame record and append poses in capture-time order.
- Reports expose `diagnostics["analysis"]` in both normal and failure reports.

- [ ] **Step 1: Replace inline tracker calls with queue submission**

In the capture loop, keep dimension checks and video writes on the session thread. Submit the frame only after a successful write. Drain results non-blocking after each capture iteration. Remove direct calls to `tracker.track()` and `tracker.track_with_diagnostics()` from the session thread.

- [ ] **Step 2: Preserve failure-frame behavior from worker results**

When a completed result has no pose and includes a failure reason, call `_maybe_save_failure_frame()` in the session thread using the returned frame and update the original frame record. Worker exceptions must update `analysis_error` and not change the primary capture outcome unless video/camera/control already failed.

- [ ] **Step 3: Stop control first, then bound worker cleanup**

At the existing collection deadline, leave the loop and invoke the existing cleanup path so STOP is sent without waiting for analysis. Signal and join the analysis worker in the session `finally` path, drain completed results, mark unresolved queued records `analysis_status="incomplete"`, and sort poses by `t_pc_ns` before returning.

- [ ] **Step 4: Add the analysis summary to normal and failure reports**

Include the worker summary under `report["diagnostics"]["analysis"]` while retaining `video_evidence.frames_written` as the authoritative count of written frames. Add report assertions for the summary without changing alignment or causal-sync verdict rules.

- [ ] **Step 5: Run the focused capture and report tests**

Run:

```powershell
python -m pytest simulation/digital_twin/tests/test_capture_sync_cleanup.py simulation/digital_twin/tests/test_capture_sync_report.py -q
```

Expected: PASS, including existing START/STOP, writer failure, cleanup idempotence, and report-boundary tests.

### Task 4: Full verification and review checkpoint

**Files:**
- Verify: `tools/camera_toolchain/capture_sync_run.py`
- Verify: `simulation/digital_twin/tests/test_capture_sync_cleanup.py`
- Verify: `simulation/digital_twin/tests/test_capture_sync_report.py`
- Verify: `docs/superpowers/specs/2026-08-17-camera-capture-analysis-decoupling-design.md`

- [ ] **Step 1: Run all related digital-twin tests**

Run:

```powershell
python -m pytest simulation/digital_twin/tests/test_capture_sync_cleanup.py simulation/digital_twin/tests/test_capture_sync_report.py simulation/digital_twin/tests/test_causal_clock_capture_policy.py -q
```

Expected: zero failures and no hardware connection attempts.

- [ ] **Step 2: Run syntax and diff checks**

Run:

```powershell
python -m py_compile tools/camera_toolchain/capture_sync_run.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Review evidence boundaries**

Confirm the patch does not alter firmware, TCP framing, START/STOP bytes, causal-clock policy, calibration claims, or physical-motion verdict semantics. Confirm queue drops are visible and never counted as captured-video loss.

- [ ] **Step 4: Commit the implementation**

```powershell
git add tools/camera_toolchain/capture_sync_run.py simulation/digital_twin/tests/test_capture_sync_cleanup.py simulation/digital_twin/tests/test_capture_sync_report.py
git commit -m "fix: decouple camera capture from pose analysis"
```

Do not stage unrelated pre-existing worktree changes.
