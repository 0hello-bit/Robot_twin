# Task 4B-2 C1 Open Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the user-selected C1 geometry into one ordered open centerline from the “发” launch spur, turning right, and ending at the all-black finish marker.

**Architecture:** Keep the raw C1 mask and its cyclic graph separate from route semantics. Select only C1, skeletonize it, snap an ordered waypoint chain to the skeleton, and concatenate non-repeating graph paths between consecutive anchors. Store terminal behavior as metadata; do not modify firmware or claim real-car completion.

**Tech Stack:** Python 3.11, NumPy, OpenCV, pytest, existing `v1_twin_track_map.py` and 4B-2 evidence pipeline.

## Global Constraints

- Read first: `docs/superpowers/specs/2026-08-02-task4b2-c1-open-route-design.md`.
- Python executable: `C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe`.
- Source image: `.embeddedskills/build/v1_task4b2/track_bare.png`, exactly 1280×720.
- Selected mask components: exactly `["C1"]`; C2—C7 are excluded artifacts.
- Route is `open_traversal_on_cyclic_mask`, not `closed_loop`.
- Do not overwrite `.embeddedskills/build/v1_task4b_offline_rework/`; write new evidence to `.embeddedskills/build/v1_task4b2_c1_open_route/`.
- No MCU, ST-Link, ESP, serial, TCP, Keil, flash, reset, motor, or live-camera operation.
- Do not run Git commands; repository integration is being handled separately.
- A generated report is not acceptance. Preserve test commands, exit codes, JSON metrics, and visual evidence for Codex review.

---

### Task 1: Freeze the approved route decision as machine-readable input

**Files:**
- Create: `.embeddedskills/build/v1_task4b2_c1_open_route/route_selection.json`
- Test: `simulation/digital_twin/tests/test_v1_twin_track_map_acceptance.py`

**Interfaces:**
- Consumes: the approved design document and `track_bare.png`.
- Produces: a UTF-8 JSON route contract consumed by extraction and acceptance tests.

- [ ] **Step 1: Write a failing route-contract test**

Add a test that loads the new file and asserts the exact route semantics:

```python
def test_real_artifact_has_approved_c1_open_route_contract():
    route = _load_route_selection()
    assert route["selected_components"] == ["C1"]
    assert route["route_type"] == "open_traversal_on_cyclic_mask"
    assert route["start_semantics"] == "launch_zone_FA_enter_then_turn_right"
    assert route["terminal_marker"] == "all_black"
    assert route["after_terminal_surface"] == "all_white"
    assert route["terminal_policy"] == "cross_marker_then_stop_on_white"
    assert route["semantic_branches"] == 0
    assert route["closed_loop"] is False
    assert route["waypoints_px"] == [
        [928, 599], [929, 480], [1120, 480], [1220, 160],
        [900, 50], [500, 50], [390, 190], [185, 420],
        [390, 690], [610, 500], [760, 480], [810, 480],
    ]
```

- [ ] **Step 2: Run the single test and confirm RED**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest simulation\digital_twin\tests\test_v1_twin_track_map_acceptance.py::test_real_artifact_has_approved_c1_open_route_contract -v
```

Expected: FAIL because `route_selection.json` does not exist.

- [ ] **Step 3: Create the exact route contract**

Create UTF-8 JSON with this content:

```json
{
  "task": "4B-2-C1-open-route",
  "source": ".embeddedskills/build/v1_task4b2/track_bare.png",
  "selected_components": ["C1"],
  "route_type": "open_traversal_on_cyclic_mask",
  "start_semantics": "launch_zone_FA_enter_then_turn_right",
  "terminal_marker": "all_black",
  "after_terminal_surface": "all_white",
  "terminal_policy": "cross_marker_then_stop_on_white",
  "semantic_branches": 0,
  "closed_loop": false,
  "waypoint_snap_radius_px": 60.0,
  "waypoints_px": [[928,599],[929,480],[1120,480],[1220,160],[900,50],[500,50],[390,190],[185,420],[390,690],[610,500],[760,480],[810,480]]
}
```

> **像素纠错（2026-08-02 独立审核返工）**：发车锚点由设计初稿 `(929,700)` 修正为
> `(928,599)`。`(929,700)` 落在印刷“发”字上（非 C1 掩码），距最近 C1 骨架点
> 101px，违反 60px 吸附硬性要求；实测发车支线物理端点为 `(928,599)`（吸附 0px）。
> 本契约以 `(928,599)` 为强制值，`route_selection.json` 已同步；此纠错不改变
> “从发字支线进入后向右”的用户语义。

- [ ] **Step 4: Re-run the contract test and confirm GREEN**

Expected: one test PASS, exit code 0.

### Task 2: Add waypoint-constrained extraction with TDD

**Files:**
- Modify: `simulation/digital_twin/v1_twin/v1_twin_track_map.py`
- Modify: `simulation/digital_twin/tests/test_v1_twin_track_map.py`

**Interfaces:**
- Consumes: a 2D binary mask and ordered `(x, y)` waypoint sequence.
- Produces: `extract_waypoint_constrained_centerline(mask, waypoints_px, snap_radius_px=60.0, min_spur_length=10) -> Tuple[Tuple[float, float], ...]`.

- [ ] **Step 1: Add synthetic RED tests**

Add tests proving that the new API follows the requested side of a loop, rejects an unsnappable anchor, and never reuses an undirected edge:

```python
def test_waypoint_route_chooses_requested_side_of_loop():
    mask = _make_loop_with_start_and_finish_spurs()
    points = extract_waypoint_constrained_centerline(
        mask,
        ((50, 95), (50, 75), (80, 75), (80, 25), (20, 25), (20, 75), (45, 75)),
        snap_radius_px=8.0,
    )
    assert len(points) > 0
    waypoint_indices = _nearest_point_indices(points, ((50,95),(50,75),(80,75),(80,25),(20,25),(20,75),(45,75)))
    assert waypoint_indices == sorted(waypoint_indices)

def test_waypoint_route_rejects_anchor_outside_snap_radius():
    mask = _make_loop_with_start_and_finish_spurs()
    with pytest.raises(ValueError, match="cannot snap waypoint"):
        extract_waypoint_constrained_centerline(mask, ((50, 95), (0, 0)), snap_radius_px=3.0)

def test_waypoint_route_has_no_repeated_undirected_edge():
    mask = _make_loop_with_start_and_finish_spurs()
    points = extract_waypoint_constrained_centerline(mask, ROUTE_WAYPOINTS, snap_radius_px=8.0)
    edges = [tuple(sorted((a, b))) for a, b in zip(points, points[1:])]
    assert len(edges) == len(set(edges))
```

- [ ] **Step 2: Run only the new tests and record RED output**

Expected: FAIL because the public extraction function is missing.

- [ ] **Step 3: Implement the minimal graph algorithm**

Implement the exact public signature:

```python
def extract_waypoint_constrained_centerline(
    mask: Any,
    waypoints_px: Sequence[Tuple[float, float]],
    snap_radius_px: float = 60.0,
    min_spur_length: int = 10,
) -> Tuple[Tuple[float, float], ...]:
    """Return one open, ordered skeleton path visiting waypoints in order."""
```

Required behavior:

1. Convert the mask to binary and keep only its largest connected component, which is C1.
2. Produce a one-pixel skeleton using the existing Zhang–Suen implementation.
3. Build an 8-neighbor graph from skeleton pixels.
4. Snap each waypoint to its nearest graph node and raise `ValueError("cannot snap waypoint ...")` when the distance exceeds `snap_radius_px`.
5. Find the shortest graph path between each consecutive pair of snapped anchors, concatenate segments while removing only their shared endpoint, and reject reuse of an undirected edge.
6. Preserve the caller’s waypoint order; do not auto-close the route and do not append points after the final anchor.

- [ ] **Step 4: Run the new tests and the complete track-map unit module**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest simulation\digital_twin\tests\test_v1_twin_track_map.py -q
```

Expected: all tests PASS, exit code 0.

### Task 3: Make the real-artifact gate consume the approved route

**Files:**
- Modify: `simulation/digital_twin/tests/test_v1_twin_track_map_acceptance.py`
- Create: `.embeddedskills/build/v1_task4b2_c1_open_route/extract_selected_route.py`

**Interfaces:**
- Consumes: `route_selection.json`, the real C1 mask, and `extract_waypoint_constrained_centerline`.
- Produces: the selected ordered pixel centerline and reusable metrics.

- [ ] **Step 1: Replace ambiguity-based acceptance with approved-route acceptance**

The acceptance helper must load `route_selection.json`, select the largest mask component only, and call:

```python
centerline_px = extract_waypoint_constrained_centerline(
    c1_mask,
    tuple(tuple(p) for p in route["waypoints_px"]),
    snap_radius_px=float(route["waypoint_snap_radius_px"]),
    min_spur_length=10,
)
```

Keep tests for blank-space jumps and medial-axis distance. Add these assertions:

```python
assert math.dist(centerline_px[0], (928, 599)) <= 60.0
assert math.dist(centerline_px[-1], (810, 480)) <= 60.0
assert max(math.dist(a, b) for a, b in zip(centerline_px, centerline_px[1:])) <= 2.0
assert all(c1_mask[int(round(y)), int(round(x))] == 1 for x, y in centerline_px)
indices = _nearest_point_indices(centerline_px, route["waypoints_px"])
assert indices == sorted(indices)
assert len(set(indices)) == len(indices)
assert math.dist(centerline_px[0], centerline_px[-1]) > 100.0
```

- [ ] **Step 2: Run the real-artifact module**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest simulation\digital_twin\tests\test_v1_twin_track_map_acceptance.py -v
```

Expected: every test PASS. Any failure remains a real blocker; do not weaken thresholds or mark it expected.

> **独立审核返工补充（2026-08-02）**：验收模块新增输入证据门禁
> `test_real_artifact_input_not_cropped`——完整赛道俯视图的 C1 掩码不得接触任一
> 图像边界。当前 `track_bare.png` 因画面底边裁切（C1 掩码 167 触点、131 个中心线
> 点压在 y=719、锚点 9 吸附到 `(390,719)`），该门禁对当前真实图片 FAIL，状态为
> `BLOCKED_INPUT_CROPPED`；路线算法门禁仍全绿，但真实地图不可验收，需重新采集
> 四周留白的完整赛道俯视图。检测器测试通过 ≠ 真实轨道地图通过。

### Task 4: Generate fresh route artifacts and visual evidence

**Files:**
- Create: `.embeddedskills/build/v1_task4b2_c1_open_route/selected_route.json`
- Create: `.embeddedskills/build/v1_task4b2_c1_open_route/selected_route_centerline.npy`
- Create: `.embeddedskills/build/v1_task4b2_c1_open_route/selected_route_overlay.png`
- Create: `.embeddedskills/build/v1_task4b2_c1_open_route/metrics.json`

**Interfaces:**
- Consumes: the approved route extractor and real image.
- Produces: immutable evidence for downstream 4B-2 consumers and independent review.

- [ ] **Step 1: Generate the artifacts from a fresh run**

The overlay must show C1 in green, excluded C2—C7 in gray, the ordered centerline in red, start as a blue circle labeled `START 发`, direction arrows along the route, and the final anchor as a yellow square labeled `FINISH ALL BLACK / STOP ON WHITE`.

- [ ] **Step 2: Record metrics**

Write JSON containing at least:

```json
{
  "route_type": "open_traversal_on_cyclic_mask",
  "selected_components": ["C1"],
  "point_count": 0,
  "route_length_px": 0.0,
  "max_consecutive_jump_px": 0.0,
  "blank_space_point_count": 0,
  "repeated_edge_count": 0,
  "waypoint_count": 12,
  "waypoints_visited_in_order": true,
  "start_to_finish_distance_px": 0.0,
  "terminal_policy": "cross_marker_then_stop_on_white"
}
```

Replace numeric zero examples with measured values. Gate requirements are: `max_consecutive_jump_px <= 2.0`, `blank_space_point_count == 0`, `repeated_edge_count == 0`, and all 12 waypoints visited in order.

- [ ] **Step 3: Validate JSON and image readability**

Run Python JSON parsing on both JSON files and OpenCV decoding on the overlay. Record commands and exit codes.

### Task 5: Run regression and prepare independent-review handoff

**Files:**
- Create: `.embeddedskills/build/v1_task4b2_c1_open_route/pytest_track.log`
- Create: `.embeddedskills/build/v1_task4b2_c1_open_route/pytest_core.log`
- Create: `.embeddedskills/build/v1_task4b2_c1_open_route/handoff.md`

**Interfaces:**
- Consumes: all changes and artifacts from Tasks 1—4.
- Produces: one concise evidence-backed candidate status for Codex review.

- [ ] **Step 1: Run the track-map unit and acceptance suites together**

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest simulation\digital_twin\tests\test_v1_twin_track_map.py simulation\digital_twin\tests\test_v1_twin_track_map_acceptance.py -q
```

Expected: all PASS, exit code 0.

- [ ] **Step 2: Run the four-module core regression**

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest simulation\digital_twin\tests\test_v1_twin_camera.py simulation\digital_twin\tests\test_v1_twin_calibration.py simulation\digital_twin\tests\test_v1_twin_track_map.py simulation\digital_twin\tests\test_v1_twin_pose_tracker.py -q
```

Expected: all PASS, exit code 0; the previous independently observed baseline was 75 passing tests.

- [ ] **Step 3: Perform a scope scan**

Confirm no firmware, Keil, ESP, serial, TCP, motor, 4B-1 live-camera, or hardware files were changed. Because another agent manages Git, report exact files touched without using Git commands.

- [ ] **Step 4: Write the handoff**

The handoff must report actual commands, exit codes, test counts, measured route metrics, exact changed files, and remaining unverified facts. Final status must be `READY_FOR_CODEX_INDEPENDENT_REVIEW`, not `Task 4B-2 complete`.

## Self-review checklist

- Every approved design requirement is covered by Tasks 1, 3, or 4.
- Function name and signature are identical in implementation and tests.
- No placeholder values are allowed in generated evidence; example zeroes must be replaced by measurements.
- The plan never treats C1 as a closed loop and never treats all-white forward motion as line following.
- No hardware operation is authorized by this plan.
