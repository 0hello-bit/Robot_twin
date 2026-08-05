# Handoff — Task 4B-2 C1 Open Route（独立审核返工，单程开放路线，纯离线）

## Task ID / 状态

- **Task:** 4B-2 C1 — 单程开放路线返工（从“发”字发车支线进入，先向右，沿 12 锚点到全黑终点）
- **最终状态：`BLOCKED_INPUT_CROPPED`**（不可宣布 Task 4B-2 complete）
- **Route type:** `open_traversal_on_cyclic_mask`（底层 C1 掩码可含环形几何，交付的是有起点、方向、终点的开放有序中心线）
- **Session:** 2026-08-02，纯离线 4B-2 返工，未接触任何硬件/固件；未运行 Git 命令

---

## 一句话结论（审核者必读）

**路线算法正确且检测测试全绿，但真实输入 `track_bare.png` 被画面底边裁切——
左侧下弯被截断、131 个中心线点直接压在 y=719。因此真实轨道地图不可验收，
状态为 `BLOCKED_INPUT_CROPPED`。检测器测试通过 ≠ 真实轨道地图通过。**

---

## 用户已确认路线决定（不可更改，已实现）

- 只保留 C1；C2—C7 全部排除。
- 从“发”字发车支线进入，到主赛道后先向右。
- 12 锚点按序走完整条路线。
- 终点为全黑标记；标记后是全白，路线在终点结束，不把全白直行描述成持续巡线。
- `terminal_policy = cross_marker_then_stop_on_white`，`closed_loop = false`，`semantic_branches = 0`。
- 本次返工未回退路线算法，未降低任何已有门槛（max jump、空白点、重复边、锚点顺序、中轴）。

---

## 真实输入被裁切（独立审核已核实，本次实测确认）

真实 `track_bare.png` 为 1280×720。实测边界覆盖指标（`metrics.json`，非占位值）：

| 指标 | 实测值 |
|------|--------|
| `mask_border_touch_count` | **167**（C1 掩码落在底边 y=719 的去重像素数） |
| `route_border_point_count` | **131**（中心线点恰好压在 y=719，x=333..463） |
| `route_points_within_2px_of_border` | **135** |
| `min_route_border_clearance_px` | **0.0** |
| `input_cropped` | **true** |
| `gates_pass` | **false** |
| `status` | **`BLOCKED_INPUT_CROPPED`** |

锚点 9 吸附到 `(390,719)`，证明左侧下弯被画面底边裁切。规则：完整赛道俯视图的
C1 掩码只要接触任一图像边界即判定输入被裁切；起点与终点在当前设计中都不应位于
图像边界，**不设任何豁免**。当前路线指标仍全部满足（`point_count=2859`、
`max_consecutive_jump_px=1.414 ≤ 2.0`、`blank_space_point_count=0`、
`repeated_edge_count=0`、12 锚点按序、`start→finish=168.29px > 100px`），
但输入不完整，不得报告为可用。

---

## 本次返工修改的文件（无 Git 命令，按文件系统记录）

| 文件 | 变更 |
|------|------|
| `simulation/digital_twin/v1_twin/v1_twin_track_map.py` | 新增 `BorderCoverageMetrics` dataclass 与 `compute_border_coverage_metrics(mask, route_points, clearance_threshold_px=2.0)`：输出 5 项边界覆盖指标 + `input_cropped`（可复用生产/验收逻辑） |
| `simulation/digital_twin/tests/test_v1_twin_track_map.py` | 新增 4 个边界覆盖单元测试（RED→GREEN，见 `border_gate_red_output.txt` / `border_gate_green_output.txt`）；合成裁切掩码 `_make_cropped_bottom_track_mask`、干净掩码 `_make_clean_margined_track_mask` |
| `simulation/digital_twin/tests/test_v1_twin_track_map_acceptance.py` | 新增输入证据门禁 `test_real_artifact_input_not_cropped`（对当前真实图片 FAIL）；模块 docstring 说明阻塞 |
| `.embeddedskills/build/v1_task4b2_c1_open_route/extract_selected_route.py` | 集成 `compute_border_coverage_metrics`；`metrics.json` 写入 5 项边界指标 + `input_cropped` + `status`；`gates_pass` 要求 `input_cropped==False`；overlay 增加底部裁切红色条带与 `BLOCKED: TRACK CROPPED` 粗体红字；**最终收尾：新增退出码契约**（证据文件总先完整写出；`gates_pass==true`→0，`BLOCKED_INPUT_CROPPED`→2，`BLOCKED_ROUTE_METRICS`→3；非零=门禁阻塞非脚本崩溃） |
| `docs/superpowers/specs/2026-08-02-task4b2-c1-open-route-design.md` | 发车锚点 `(929,700)→(928,599)` 像素纠错说明；验收条件新增输入完整性（边界裁切）条款 |
| `docs/superpowers/plans/2026-08-02-task4b2-c1-open-route.md` | 契约与测试断言 `(929,700)→(928,599)` 同步 + 纠错说明；Task 3 增加裁切门禁说明；**最终收尾：Task 3 断言代码块约第 199 行同步为 `(928, 599)`**（全文件确认 `(929,700)` 仅保留在"像素纠错"历史说明中，不再作有效断言/契约值） |
| `.embeddedskills/build/v1_task4b2_c1_open_route/`（证据目录） | 重新生成 `metrics.json` / `selected_route.json` / `selected_route_centerline.npy` / `selected_route_overlay.png`（含裁切标注）；新增 `border_gate_red_output.txt`、`border_gate_green_output.txt`、`pytest_track_rework.log`、`pytest_core_rework.log`、`pytest_acceptance_rework.log`、`_verify_border_facts.py`（真实指标实测）、`_scratch_cropped_mask.py`（合成掩码验证） |

未改动：固件、Keil 工程、ESP/串口/TCP、电机、摄像头、4B-1 长测、任何硬件文件。
未运行任何 Git 命令（仅文件系统复制/读写）。

**历史证据保留（返工前副本，未覆盖）**：
`handoff_pre_rework_2026-08-02.md`（旧状态 `READY_FOR_CODEX_INDEPENDENT_REVIEW`）、
`metrics_pre_rework_2026-08-02.json`（旧 `gates_pass=true`）。
说明：旧的 `selected_route_overlay.png`（80514B，无裁切标注）在重新生成时被新版
（87118B，含 BLOCKED 标注）覆盖，旧 overlay 图像本身不可恢复；其对应的旧状态由
上述 metrics/handoff 副本记录。`selected_route_centerline_pre_rework.npy` 为旧
中心线副本（本返工未改路线算法，2859 点与新版一致）。

---

## 测试命令 / 数量 / 退出码

| 步骤 | 命令 | 结果 | 退出码 |
|------|------|------|--------|
| 边界检测 RED | `pytest test_v1_twin_track_map.py -k border -v` | 4 failed（`compute_border_coverage_metrics` ImportError） | 1 |
| 边界检测 GREEN | 同上（实现后） | 4 passed | 0 |
| 轨道单元模块 | `pytest test_v1_twin_track_map.py -q` | 41 passed | 0 |
| 真实验收模块 | `pytest test_v1_twin_track_map_acceptance.py -v` | **5 passed + 1 failed**（裁切门禁 FAIL，真实地图阻塞） | 1 |
| 轨道全套 | `pytest test_v1_twin_track_map.py test_v1_twin_track_map_acceptance.py -q` → `pytest_track_rework.log` | **46 passed + 1 failed** | 1 |
| 四模块核心回归 | `pytest test_v1_twin_camera.py test_v1_twin_calibration.py test_v1_twin_track_map.py test_v1_twin_pose_tracker.py -q` → `pytest_core_rework.log` | **82 passed** | 0 |

- 核心回归 82 = 前基线 75 + 3 waypoint 单元测试 + 4 新增边界单元测试；75 项原测试
  全部保持通过，无回归，已有门槛未降低。
- 真实验收模块的 1 个 FAIL 是输入证据门禁（`test_real_artifact_input_not_cropped`），
  为预期/真实阻塞，非算法失败；5 个路线算法门禁全绿说明路线提取算法本身正确。

## 最终收尾重跑（2026-08-02，极小范围：两处遗漏）

本轮只做两处收尾，未重构路线算法、未扩展任务：

| 修复 | 内容 |
|------|------|
| 1. 计划文档断言同步 | `docs/superpowers/plans/2026-08-02-task4b2-c1-open-route.md` Task 3 断言代码块约第 199 行：`(929, 700)` → `(928, 599)`；全文件确认 `(929,700)` 仅出现在"像素纠错"历史说明（88–90 行），不再作为有效断言/契约值 |
| 2. `extract_selected_route.py` 退出码契约 | 证据文件（4 个）总先完整写出；`gates_pass==true`→退出码 0；`status==BLOCKED_INPUT_CROPPED`→退出码 **2**；`BLOCKED_ROUTE_METRICS`→退出码 **3**。非零退出码=门禁阻塞，**不是脚本崩溃**（脚本正常跑完并打印 `exit_code`） |

重跑命令 / 数量 / 退出码：

| 步骤 | 命令 | 结果 | 退出码 |
|------|------|------|--------|
| 边界单元测试 | `pytest test_v1_twin_track_map.py -k border -v` | **4 passed** | 0 |
| 四模块核心回归 | `pytest test_v1_twin_camera.py test_v1_twin_calibration.py test_v1_twin_track_map.py test_v1_twin_pose_tracker.py -q` | **82 passed** | 0 |
| 真实 acceptance | `pytest test_v1_twin_track_map_acceptance.py -v` | **5 passed + 1 failed**（裁切门禁 FAIL，`input_cropped=True`，真实地图仍阻塞） | 1 |
| 证据脚本 | `python extract_selected_route.py` | 4 个证据文件全部写出；`status=BLOCKED_INPUT_CROPPED`、`gates_pass=false`、`snapped_start=[928,599]` | **2** |

证据脚本可重复验证（`VERIFY_OK`）：重跑后 `selected_route.json` / `metrics.json` /
`selected_route_centerline.npy`(2859,2) / `selected_route_overlay.png`(87118B) 均存在，
JSON 中 `status==BLOCKED_INPUT_CROPPED`、`gates_pass==false`、`start_px==[928,599]`，
进程退出码 **2**（非零 = 输入被裁切阻塞，非脚本故障）。

---

## 路线指标（`metrics.json` / `selected_route.json`，本次重新生成）

```json
{
  "point_count": 2859,
  "route_length_px": 3125.58,
  "max_consecutive_jump_px": 1.414,
  "blank_space_point_count": 0,
  "repeated_edge_count": 0,
  "waypoint_count": 12,
  "waypoints_visited_in_order": true,
  "start_to_finish_distance_px": 168.29,
  "mask_border_touch_count": 167,
  "route_border_point_count": 131,
  "route_points_within_2px_of_border": 135,
  "min_route_border_clearance_px": 0.0,
  "input_cropped": true,
  "gates_pass": false,
  "status": "BLOCKED_INPUT_CROPPED"
}
```

- 起点（吸附后）：`(928,599)` — C1 发车支线物理端点（发字锚点像素纠错值）
- 终点（吸附后）：`(809,480)` — 全黑终点标记中心附近（距锚点 `(810,480)` 1.4px）
- 锚点 9 吸附到 `(390,719)` — 左侧下弯被画面底边裁切的直接证据
- 进入主赛道后首个方向为右：锚点 2→3 方向 `dx=+198, dy=-3`
- overlay 程序化验证：`(720,1280,3)` 可解码；底部裁切红带约 4198px；BLOCKED 文案
  红色文本带约 2670px；C1 绿、C2—C7 灰、路线红、起点蓝、终点黄均正常渲染。

---

## 证据路径

```
.embeddedskills/build/v1_task4b2_c1_open_route/
├── route_selection.json              路线契约（唯一事实来源，waypoints 含 (928,599)）
├── extract_selected_route.py         证据生成脚本（离线可重跑，含裁切门禁）
├── selected_route.json               路线元数据 + 吸附锚点 + 指标 + status
├── selected_route_centerline.npy     (2859, 2) float64 有序中心线
├── selected_route_overlay.png        1280×720 可视化（含底部裁切红带 + BLOCKED: TRACK CROPPED）
├── metrics.json                      机器可读验收指标（gates_pass=false, status=BLOCKED_INPUT_CROPPED）
├── border_gate_red_output.txt        边界检测 RED 日志（4 failed, ImportError）
├── border_gate_green_output.txt      边界检测 GREEN 日志（4 passed）
├── pytest_track_rework.log           轨道全套 46 passed + 1 failed
├── pytest_core_rework.log            四模块 82 passed
├── pytest_acceptance_rework.log      验收模块 5 passed + 1 failed
├── red_green_evidence.md             TDD RED→GREEN 记录（含本次返工追加节）
├── _verify_border_facts.py           真实图片边界指标实测脚本
├── _scratch_cropped_mask.py          合成掩码提取行为验证脚本
├── handoff_pre_rework_2026-08-02.md  返工前 handoff（READY_FOR_CODEX，gates_pass=true）
├── metrics_pre_rework_2026-08-02.json  返工前 metrics（gates_pass=true）
├── selected_route_centerline_pre_rework.npy  旧中心线副本（路线未改，与新版一致）
└── handoff.md                        本文件（BLOCKED_INPUT_CROPPED）
```

---

## 计划与真实代码不一致处（沿用 + 本次新增）

1. **锚点 1 修正 `(929,700) → (928,599)`**（沿用，本次同步文档）：`(929,700)` 落在
   印刷“发”字上（纸面墨迹，非 C1 掩码），距最近 C1 骨架点 101px，违反 60px 吸附
   硬性要求；移到发车支线物理端点 `(928,599)`（吸附 0px）。“发”字位于支线末端
   正下方，进入语义保留。
2. **骨架不用 `_thin_skeleton_to_1px`**（沿用）：该步在真实 C1 上把骨架打散成 188
   个碎片；`extract_waypoint_constrained_centerline` 直接使用原始 Zhang–Suen 骨架。
3. **新增裁切门禁（本次）**：旧 `gates_pass` 无画面边界/裁切门禁，对裁切输入仍为
   true；本次 `gates_pass` 必须同时要求 `input_cropped == false`，并暴露
   `status=BLOCKED_INPUT_CROPPED`。

未降低任何门槛、未伪造 PASS、未删除历史 RED/GREEN 证据。

---

## 下一步需要的新摄像头输入条件（解锁 BLOCKED_INPUT_CROPPED 的前提）

重新采集完整赛道俯视图，需同时满足：

1. **四周留白**：C1 掩码不得接触图像任一边界（`mask_border_touch_count == 0`）；
   赛道四周至少留出 >20px 白边，避免裁切与吸附歧义。
2. **包含完整赛道**：左侧下弯（原锚点 9 附近）、右侧、上侧、全黑终点标记、全白区域
   必须完整入画；底部不得切断任何轨道线段。
3. **清晰成像**：保持当前 Otsu+开闭二值化可正确分离 C1 与背景；避免强反光、阴影把
   轨道与纸边合并。
4. **同样的俯视几何**：相机高度/角度尽量接近现标定设置，使 homography 与锚点
   `(928,599)`、`(390,690)`、`(810,480)` 等仍可在 60px 内吸附。
5. 新图就绪后：替换/补充 `track_bare.png` → 重跑 `extract_selected_route.py` →
   确认 `metrics.json` 中 `input_cropped=false` 且 `status=PASS` →
   重跑验收模块确认 `test_real_artifact_input_not_cropped` 通过，方可继续下游任务。

---

## 仍未验证项（如实列出）

- **真车实跑未验证**：4B-2 为纯离线软件阶段；不证明真车已跑完全程。
- **终点行为参数未定**：全黑标记去抖时间、穿越速度、安全超时属后续控制任务，需真车
  实验确定，本阶段仅在元数据中记录 `cross_marker_then_stop_on_white`，不臆造数值。
- **“发”字物理位置**：基于 track_bare.png 图像推断（位于支线末端下方），未做现场复核。
- **骨架连通性对阈值敏感**：验证基于当前 Otsu+开闭运算管线；其他二值化参数下未测。
- **C2—C7 排除**：掩码层面验证（路线像素全在 C1 内）；组件编号与历史
  `route_choices.json` 一致。
- **真实地图验收被裁切阻塞**：需按上节条件重新采集完整赛道俯视图。
- 未执行任何 MCU/ST-Link/ESP/串口/TCP/摄像头/电机/烧录/复位操作；未运行 Git 命令。

---

## 状态

**`BLOCKED_INPUT_CROPPED`** — 路线算法与检测测试通过，但真实 `track_bare.png` 输入
被画面底边裁切，真实轨道地图不可验收。本会话未获取新图，不自行宣布 Task 4B-2
complete；需按“下一步需要的新摄像头输入条件”重新采集完整赛道俯视图后重跑验收。
