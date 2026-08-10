# B3 R1 Full-Frame Recovery Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit, evidence-labelled R1 grayscale `1x` recovery profile while preserving the current production observation path as the default.

**Architecture:** Reuse the existing `PoseTracker` and capture lifecycle. Add a small profile resolver and pass only the selected full-frame fallback scale to the existing tracker constructor. Record the selected profile in capture evidence; do not add a parallel detector or transport.

**Tech Stack:** Python 3.11, OpenCV, pytest, existing `capture_sync_run.py` and `v1_twin` interfaces.

## Global Constraints

- Default profile remains the current production behavior: full-frame fallback `(2.0,)`.
- R1 profile is `r1_gray1x`: full-frame fallback `(1.0,)`; all other tracker settings remain unchanged.
- Unknown profiles fail before opening camera or TCP resources.
- Offline tests never open camera, TCP, firmware, motor, or debugger resources.
- The B3 real acceptance contract remains detection ratio `>=0.95`, maximum pose gap `<=2.0` frames, and detector p95 `<=33.333333 ms`.
- Do not claim the R1 profile improves the real car until a matched authorized A/B capture passes the contract.

### Task 1: Add failing profile tests

**Files:**
- Create: `simulation/digital_twin/tests/test_capture_observation_profile.py`
- Read-only dependency: `tools/camera_toolchain/capture_sync_run.py`

**Interfaces:**
- Tests will import `OBSERVATION_PROFILES`, `resolve_observation_profile`, and `create_pose_tracker`.

- [ ] **Step 1: Write the failing tests**

```python
def test_production_profile_keeps_existing_fallback():
    profile = resolve_observation_profile("production")
    assert profile["name"] == "production"
    assert profile["full_frame_fallback_scales"] == (2.0,)


def test_r1_profile_changes_only_full_frame_fallback():
    profile = resolve_observation_profile("r1_gray1x")
    assert profile["name"] == "r1_gray1x"
    assert profile["full_frame_fallback_scales"] == (1.0,)


def test_unknown_profile_is_rejected_before_capture():
    with pytest.raises(ValueError, match="unsupported observation profile"):
        resolve_observation_profile("unknown")
```

- [ ] **Step 2: Run the focused test and verify the expected RED failure**

Run:

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_capture_observation_profile.py
```

Expected: import failure because the profile resolver does not exist yet.

### Task 2: Implement profile resolution and tracker wiring

**Files:**
- Modify: `tools/camera_toolchain/capture_sync_run.py`
- Test: `simulation/digital_twin/tests/test_capture_observation_profile.py`

- [ ] **Step 1: Add the two profile definitions and resolver**

Use immutable dictionaries/tuples and raise `ValueError` for any name outside
`production` and `r1_gray1x`.

- [ ] **Step 2: Add `create_pose_tracker(calib, hom, observation_profile)`**

The factory must call the existing `PoseTracker` constructor with
`tag_id=0`, `detect_scales=(1.0, 2.0, 3.0)`, and only the selected
`full_frame_fallback_scales` changed.

- [ ] **Step 3: Add `--observation-profile` with default `production`**

Resolve the profile before camera/TCP setup. A bad profile must return a
configuration error without opening either resource.

- [ ] **Step 4: Add profile metadata to derived capture evidence**

Pass the profile name/config through the existing report-building boundary;
do not create a second report format or alter the raw session lifecycle.

- [ ] **Step 5: Run the focused tests and verify GREEN**

```text
py -3.11 -m pytest -q simulation/digital_twin/tests/test_capture_observation_profile.py simulation/digital_twin/tests/test_capture_sync_cleanup.py
```

Expected: all selected tests pass.

### Task 3: Offline verification and handoff

**Files:**
- Modify only if needed: `docs/agent-context/handoffs/2026-08-10-b3-offline-dynamic-static-analysis.md`
- Existing evidence: `docs/evidence/v1_b3_r1_gray_fallback_screening_20260810_c260810042912843/report.json`

- [ ] **Step 1: Run the full relevant regression**

```text
py -3.11 -m pytest -q --ignore=archive simulation/digital_twin/tests
py -3.11 -m compileall -q simulation/digital_twin tools
git diff --check
```

- [ ] **Step 2: Record the offline result**

Record that the current four-thumbnail screen found `2/4` for gray `1x` and
`0/4` for gray `2x`, classify this as candidate evidence only, and state that
no hardware was accessed.

- [ ] **Step 3: Stop before hardware**

The next interface is an explicitly authorized matched A/B real capture:
production first, then `r1_gray1x`, same start pose/direction/lighting and
same run duration. Do not flash firmware or run either profile until the user
authorizes the test.
