# Codex 独立验收请求 — 2026-08-03/04 会话工作

请作为独立验收者，对以下五项工作做**只读复核 + 命令复跑**，逐项给出
`PASS / REJECT / INSUFFICIENT_EVIDENCE` 裁决与证据。所有路径相对工作区根。

> 纪律：请用 `git status`/`git log` 只读核对；不要做任何 Git 写操作。
> 复跑命令均在对应证据目录。真机证据（soak/烧录）为代理自报 + 用户在场授权，
> 你只能复核报告与脚本逻辑，无法重跑真机。

---

## 1. 4B-1 Gate 0 — USB 摄像头稳定性重验收

**声明状态**：`VERIFIED_COMPLETE`（新 USB 600s，视觉复核通过）

**证据**：`.embeddedskills/build/v1_task4b_reacceptance/4b1_usb_gate0/gate0_report.json`

**应复跑**：`py -3.11 .embeddedskills/tools/camera_toolchain/run_gate0_usb.py 1`
（600s，注意 DirectShow 索引会漂移，先用 `probe_camera.py` 确认 C960 索引）

**验收判据**：fps≥20、drop≤5%、时间戳单调、1280×720 匹配、无效帧=0。
报告实测：fps=30.0、drop=4.671%、duplicate=5.106%、单调、无效帧 0。

**注意**：计划 §6.2 权威规则——新 USB 验收 PASS 覆盖旧 DroidCam FAIL，无需用户逐次裁定。

---

## 2. 4B-2 C1 路线 — 从 BLOCKED_INPUT_CROPPED 解锁

**声明状态**：`SOFTWARE_ONLY`（C960 新图 + 标定 + 路线 PASS；正式 handoff 待独立复核）

**证据**：`.embeddedskills/build/v1_task4b2_c1_c960_reacceptance/`
（`metrics.json`、`selected_route.json`、`selected_route_centerline.npy`、
`selected_route_overlay.png`、`route_selection_c960.json`、`handoff.md`）

**应复跑**：
- `py -3.11 .embeddedskills/build/v1_task4b2_c1_open_route/extract_selected_route.py route_selection_c960.json`
  → 期望 `input_cropped=false`、`gates_pass=true`、`status=PASS`、退出码 0。
- `py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_track_map.py simulation/digital_twin/tests/test_v1_twin_track_map_acceptance.py`
  → 期望 47 passed。

**关键代码变更（请审查）**：
- `extract_selected_route.py`：`largest_component` → `component_containing_waypoints`
  （新图桌面/阴影暗区比赛道大，选"含锚点最多的连通分量"；向后兼容）。
- `test_v1_twin_track_map_acceptance.py`：契约路径指向 `route_selection_c960.json`、
  C1 选择改为按锚点、锚点断言更新为新坐标。

**历史**：旧 `v1_task4b2_c1_open_route/` 为 BLOCKED 记录（handoff.md 保留旧指标）。

---

## 3. B1/B2 — 固件发送仲裁修复（健康帧不被遥测饿死）

**声明状态**：离线全绿 + 真机验证（运行中健康帧 0 dropped）

**证据**：
- 代码：`程序/3. 麦轮巡线小车/User/health_stats.h/.c`、`main.c`（仲裁改动）
- 离线：`.embeddedskills/build/firmware_health_baseline_design/test_health_stats.exe`
- 真机：`.embeddedskills/build/v1_task4b4_arbitration_fix/verification_active/`
  （`raw_health.json`、`transport_report.json`）、`verification_passive/`

**应复跑（离线）**：
- Host C：`bash .embeddedskills/build/v1_task4b4_fix/build_host_c_tests.sh \
  .embeddedskills/build/firmware_health_baseline_design/test_health_stats.exe \
  simulation/digital_twin/tests/test_health_stats.c \
  .embeddedskills/build/v1_task4b4_fix/hostc/User/health_stats.c \
  .embeddedskills/build/v1_task4b4_fix/hostc/System/mono_time_core.c` 然后运行 exe。
- Keil：`"F:/keil/UV4/UV4.exe" -r "C:\Users\24668\Desktop\stm32小车\程序\3. 麦轮巡线小车\project.uvprojx" -j0`
  → 0 Error / 0 Warning。
- Python：`py -3.11 -m pytest -q simulation/digital_twin/tests/test_frame_parser_health.py .embeddedskills/build/v1_task4b4/test_transport_soak_rework.py`

**真机证据（代理自报，你只能审报告与逻辑）**：
- 架空轮 30s 主动：health +30 gen/+30 start/+30 ok/**0 dropped**/0 failed（修复前 507/521 dropped）。
- 心跳 148/148，`lease_active=1` 全程，遥测 289 帧 288 ok。
- 计数恒等式 `generated==dropped+started`（diff=0）。

**审查要点**：仲裁逻辑是否满足"ACK/STATUS 最高优先级 + 健康帧延迟不丢 + 遥测让行 +
代次变化清待发"；恒等式在 pending 帧下是否仍成立。

---

## 4. C1 — 相机工具链整合

**证据**：`.embeddedskills/tools/camera_toolchain/`（`README.md`、`camera_common.py`、10+ 工具）

**应复跑**：`py -3.11 -m py_compile .embeddedskills/tools/camera_toolchain/*.py` → 全过。
`py -3.11 .embeddedskills/tools/camera_toolchain/probe_camera.py` → 能自动检测索引。

**审查要点**：索引自动检测逻辑（热插拔漂移）、unicode 图像 IO、覆盖采集工具合理性。

---

## 5. C2 — 标定与映射（含未解决项）

**证据**：`.embeddedskills/build/v1_task4b_reacceptance/4b1_usb_gate0/track_rework/`
（`intrinsics_c960.json`（全覆盖，p95=2.54px）、`homography_c960.json`、
`intrinsics_c960_fullcov.json`、`homography_mosaic.json`）

**已解决**：
- 全覆盖畸变标定（视频法 16/16 网格）——主点 cy=316.7 落画面中心（旧中右覆盖的
  cy=13.5 是病态解）。
- 垂直度判据修正：**勿用图像四角 mm 跨度比**（对旋转敏感误报 0.31），须用
  homography 局部 Jacobian 奇异值比（实测中心 1.006、四角 1.04-1.05，摄像头一直垂直）。

**未解决（重要，请确认我如实标注）**：
- **单位置 homography 只在棋盘格附近准（~2%），远离处实测失真最高 44%**。
- **mm 级映射未达成**：需要全图控制点。方案 A=大棋盘格/网格纸铺满赛道；方案 B=多点位
  +尺子量偏移；方案 C=视频拼接 bundle adjustment（`mosaic_homography.py`，当前
  误差 ~6.9% 未收敛，**待优化**）。
- 4B-3/4B-4 硬前置 = mm 级映射，当前未满足。

---

## 全局注意

1. 摄像头 DirectShow 索引热插拔漂移（C960 曾 2 现 1）——复跑前先 `probe_camera.py`。
2. `scipy` 本次会话新安装（mosaic 优化用）。
3. 证据不可变铁律：重跑任何写证据的脚本前先复制证据目录到新目录。
4. 未验证项：4B-3 位姿、4B-4 同步 Gate（遥测实际 10Hz vs Gate 假设 33.3ms，需固件遥测
   批量作为独立任务）、mm 级映射。

## 请求的输出

逐项给 `PASS / REJECT / INSUFFICIENT_EVIDENCE` + 复跑命令/输出/退出码 + 裁决理由；
对第 5 项明确是否同意"mm 级映射未达成"的判断。
