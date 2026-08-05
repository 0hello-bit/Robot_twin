# Robot Twin AI 当前状态

**技术状态快照更新时间：2026-08-03（深夜，C960 重采 + 4B-2 解锁 + 仲裁修复真机验证）**

## 项目定位（2026-08-05 更新，优先于单个任务的局部描述）

本项目要做的是一个以数字孪生为基础的 AI 机器人研发闭环，不是一个单独的 PID 自动调参器。最终要验证的链路是：

`真实机器人表现 → AI 发现问题/提出假设 → 算法、固件或硬件/PCB 候选 → 数字孪生虚拟测试 → 候选落到真实机器人 → 真机验证 → 真实反馈修正数字孪生和下一轮方案`

- **最终研究命题**：在明确约束下，AI 能否完成连续的机器人研发迭代，并让后一轮真实表现优于前一轮。
- **V1 的角色**：数字孪生基础和第一种最小候选载荷。运行时 PID 参数验证用于打通“虚拟测试 → 真实验证 → 反馈”链路，不是项目最终目标，也不能证明 AI 已能自主修改核心算法或硬件。
- **当前切入场景**：高速运行，尤其是高速急弯时的丢线和抖动。场景已被确定为后续研发问题，但根因尚未被证据确认，不能预先归因于传感器、PID 或某个硬件。
- **真实成功判据**：在相同、可重复的测试条件下，第二轮 AI 输出实际落地后的真机表现稳定优于第一轮；仿真变好不能代替真机改进证据。
- **人工边界**：长期目标允许人工打板、焊接、装配和做安全监管，但不应替 AI 手工修改候选或指定胜者；当前 V1 仍需人工授权和在场执行真机操作，不能描述为已经无人参与。
- **当前工作状态**：离线 V1 正由另一 agent 推进。在离线实现明确需要现实权限之前，不连接、控制或测试真实硬件。

## 2026-08-04 R3 独立复核更正（覆盖旧精度解读）

> 依据 Codex R3 独立复核（修正后的 raw-pixel 联合拟合报告
> `joint_raw_linear.json`，SHA-256 `d02dbb33...`），本节**取代**下面的旧全局精度解读；
> 旧内容保留为历史/局部证据。当前修正包证据目录：
> `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r2/`
> （r1 包保留于 `..._r1/`，字节未变：profile `5c131d03...`、report `7f96ea9a...`）。

- 旧“板附近 0.3 mm / 全图约 5%”**不证明**全赛道绝对毫米精度。
- 修正后的 raw-pixel ground holdout p95=10.627 mm（max 10.759 mm），
  LOO p95=11.011 mm（max 11.577 mm）。
- **模型类 vs 直接矩阵**：上述 10.627 / 11.011 mm 是该模型类
  （joint pixel-to-mm homography + 每训练视图一个 in-plane 角）的**交叉验证估计**，
  用于**选择**全 16 视图拟合矩阵；**不是**对导出的 exact full-16-view 矩阵的
  直接留出（direct holdout）评估。导出矩阵本身是 `full_16_view_fit_in_sample`（in-sample）。
- 当前去畸变路径的同类 holdout=19.386 mm；**运行链不能自动称为 10 mm**。
- 新 profile（`calibration_profile.json`）只是 `EXPLORATORY_RELATIVE_ONLY`，
  **尚未接入** PoseTracker / route 转换 / 4B-4 capture。
- AprilTag 高度视差未修正，车体绝对 x/y 精度未验证
  （`pose_absolute_accuracy=UNVERIFIED_TAG_HEIGHT_PARALLAX`）。
- R3 / 2 mm gate 仍 `BLOCKED`；下一步必须由独立 package 接线和复验。

## 已验证事实

### 4B-1 Gate 0 — USB 摄像头重验收 PASS（解除旧 BLOCKED）

- 设备：EMEET SmartCam C960，USB 直连。OpenCV DirectShow 索引 **1**（**热插拔后索引会漂移**：曾为 2，重插后为 1；0/1/3 可开）。
- **600s Gate 0 重验 PASS**：effective_fps=30.0、drop_rate=4.671%（≤5%）、时间戳单调、1280×720 匹配、无效帧 0、重复率 5.106%。
  对比旧 DroidCam 无线流 FAIL：drop 12.2%、duplicate 29.7%。
- 视觉复核通过（montage 首/中/尾帧无黑屏/花屏）。报告：
  `.embeddedskills/build/v1_task4b_reacceptance/4b1_usb_gate0/gate0_report.json`。
- 按计划 §6.2 权威规则，新 USB 验收 PASS 覆盖旧 BLOCKED（**4B-1 当前状态 = 解锁**）。

### 摄像头构图 / 标定（C960）

- 垂直度已调正：棋盘格纵横比 1.60、px/mm 各向异性 1.00（镜头平行地面）。
- **相机内参（畸变）标定完成（全覆盖视频法）**：`record_chessboard_video.py` +
  `extract_calibration_frames.py`（4×4 空间覆盖 16/16 + 清晰度过滤，18 视图），
  `reprojection_error_p95=2.54px`；主点 cy=316.7 落画面中心（旧 11 视图中右覆盖的
  cy=13.5 是病态解）。文件 `track_rework/intrinsics_c960.json`（旧版备份为
  `intrinsics_c960_pre_fullcov.json`）。
- **homography**：棋盘格平放单位置 + 全覆盖畸变矫正，板附近 `p95=0.321mm`。
  **映射精度验证（旋转无关局部尺度比）**：中心 1.006、四角 1.039~1.052（理想 1.0）
  → 摄像头一直垂直 + 全图映射基本均匀（~5% 内）。文件 `track_rework/homography_c960.json`。
- ⚠️ 教训：勿用"图像四角 mm 跨度比"判断垂直度（对旋转敏感，误报 0.31）；
  必须用 homography 局部 Jacobian 奇异值比（旋转无关）。多点位合并 homography 不可行
  （局部 mm 坐标矛盾），单位置+正确 undistort 才是正解。

### 4B-2 — C1 路线解锁（从 BLOCKED_INPUT_CROPPED → input_cropped=false）

- 新 `track_bare.png`（C960 垂直俯拍，1280×720）：四周留白 71px，不再裁切。
- **12 锚点在新图上重选**（`v1_task4b2_c1_c960_reacceptance/route_selection_c960.json`）。
- **检测修复**：`extract_selected_route.py` 的 `largest_component` → `component_containing_waypoints`
  （选"含锚点最多的连通分量"= 实际赛道；新图桌面/阴影暗区比赛道大，最大分量非赛道）。
  向后兼容：旧图锚点在最大分量内时结果不变。
- **C1 路线提取 PASS**：`input_cropped=false`、`gates_pass=true`、`status=PASS`、
  `mask_border_touch_count=0`、`min_route_border_clearance_px=71.0`、point_count=2354、
  12 锚点按序、无空白跳变、无重复边。overlay 用户视觉确认正确。
- **验收测试全绿**：`test_v1_twin_track_map.py` + `test_v1_twin_track_map_acceptance.py`
  = **47 passed**（含此前 RED 阻塞的 `test_real_artifact_input_not_cropped`）。
- 新证据目录：`.embeddedskills/build/v1_task4b2_c1_c960_reacceptance/`（handoff.md 已写）。
  旧 BLOCKED 状态保留在 `v1_task4b2_c1_open_route/handoff.md` 与总计划 §6.1。

### 固件发送仲裁修复（B1/B2）— 真机验证成功

- **根因**：`health_emit()` 在 `cipsend_tx_busy || txfq_has_retry` 时直接 drop；遥测 ~10Hz×~100ms
  让 TX 几乎 100% 忙，1Hz 健康帧 97% 被饿死（此前实测 generated=521 / dropped=507 / started=14）。
- **修复**（`health_stats.h/.c` + `main.c` 5 处）：忙时**延迟不丢**（`health_due` 标志）+ 主循环 flush 补发
  + 遥测让行 + 断连/代次变化清待发帧。ACK/STATUS 仍最高优先级。
- **离线验证**：Host C `test_health_stats`（新增仲裁测试）GREEN、`test_coordinator_boundary` PASS、
  `test_twin_control_protocol` PASS、Keil 0 Error/0 Warning、Python 健康回归 53 passed。
- **真机验证**（架空轮 30s，经用户当次授权）：
  - 运行中健康帧 **+30 generated / +30 started / +30 ok / 0 dropped / 0 failed**（修复前 97% 饿死）。
  - 心跳链：soak 发 148 条 H，MCU 计数 148，`lease_active=1` 全程维持，无超时。
  - 遥测 289 帧 ~10.4Hz、288 ok、0 failed（仲裁未饿死遥测）。
  - 计数恒等式 `generated==dropped+started`（diff=0）成立。
- 烧录：Keil UV4 `Erase Done / Programming Done / Verify OK`，新 AXF SHA256 `17b7e022...`。
  烧录前 AXF 已备份（`v1_task4b4_arbitration_fix/rollback_artifacts/preflash/`）。

## 未验证项

- 4B-2 完整验收的**正式 handoff / Codex 独立复核**未做（本状态为执行代理自报 + 用户视觉确认）。
- 4B-3 AprilTag 静态位姿在新源（C960）上重验、4B-4 真机同步 Gate 均未跑。
- homography 外推精度对 4B-3 是否足够未评估。
- 新固件的长时运行（健康帧持续送达 + ESP 断连/重连）未做。
- 本状态不代表 Task 4B 或整个项目完成。

## 工具链（统一位置，Codex/Claude 必读）

摄像头采集/标定/选点工具统一在 `.embeddedskills/tools/camera_toolchain/`（README.md）。
关键：DirectShow 索引热插拔漂移，用 `camera_common.get_camera_index()` 自动检测；
内参标定必须用 `capture_intrinsics_coverage.py`（3×3 全覆盖，否则边缘畸变未约束）。

## 当前下一步

1. 4B-2 正式 handoff 整理 + 计划文档 §6 快照更新（本会话已做证据目录，等待独立复核）。
2. **mm 级映射（4B-3 硬前置，未解决）**：单位置 homography 只在棋盘格附近准（2%），
   远离处实测失真最高 44%。**必须全图控制点**：方案 A=打印大棋盘格/网格纸铺满赛道
   区域一帧采集（推荐）；方案 B=棋盘格多点位 + 尺子量各位置 mm 偏移统一坐标。
   当前映射精度：板附近 ~0.3mm，边缘远未达 mm 级。
3. 4B-3 静态位姿重验（新源稳定性；车顶 AprilTag，需用户在场）。
4. 4B-4 真机同步 Gate：已知风险（遥测实际 10Hz vs Gate 假设 33.3ms）；建议固件遥测
   批量（打包 2-3 帧/ CIPSEND → ~30Hz）作为独立固件任务。
