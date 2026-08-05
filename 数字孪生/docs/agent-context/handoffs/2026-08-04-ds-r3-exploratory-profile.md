# Claude Code / DS 执行 Handoff：R3 Raw-Pixel Exploratory Profile

**日期**：2026-08-04
**工作区根**：`C:\Users\24668\Desktop\stm32小车`
**执行者**：Claude Code 中配置的 DS 模型
**协调与最终验收**：Codex
**本轮唯一任务**：生成并验证正确的 raw-pixel exploratory calibration profile；完成后立即停止

## 1. 启动顺序

只读取以下文件，然后执行 implementation plan，不要全仓扫描：

1. `CLAUDE.md`
2. 本 handoff
3. `docs/superpowers/specs/2026-08-04-a4-global-charuco-2mm-calibration-design.md`
4. `docs/superpowers/plans/2026-08-04-r3-exploratory-calibration-profile.md`
5. `simulation/digital_twin/v1_twin/v1_twin_calibration.py`
6. `simulation/digital_twin/tests/test_v1_twin_calibration.py`
7. `.embeddedskills/build/codex_r3_acceptance_20260804/joint_fit_v1/verification_corrected/joint_raw_linear.json`

使用 `superpowers:executing-plans`，逐项勾选 plan。不要再派生实现代理。

## 2. 已核实前提

- corrected raw-pixel ground mapping：9/7 holdout p95=`10.62712398475308 mm`，LOO p95=`11.01137209510592 mm`。
- source SHA-256：`D02DBB33D9258F63575A67036228C52E27AD589D1BA60070B7C9167E9938037D`。
- 当前旧内参去畸变路径同类 holdout 约 `19.386 mm`，所以当前运行链不能自动称为“10 mm 版”。
- 10-11 mm 只验证地面控制点；车顶 AprilTag 高度视差未解决，车体绝对位置没有相同精度证据。
- 2 mm gate 仍 `BLOCKED`。本任务的成功标准是“探索 profile 正确生成且正式 gate 明确拒绝”，不是 2 mm PASS。
- 基线：`test_v1_twin_calibration.py` 为 12 passed；`test_v1_twin_pose_tracker.py` 为 8 passed。

## 3. 允许修改范围

严格按 plan，仅允许：

- 新增 `simulation/digital_twin/v1_twin/v1_twin_calibration_profile.py`
- 新增 `simulation/digital_twin/tests/test_v1_twin_calibration_profile.py`
- 新增 `.embeddedskills/tools/camera_toolchain/export_exploratory_profile.py`
- 新增 `simulation/digital_twin/tests/test_export_exploratory_profile.py`
- 追加更正 `docs/agent-context/CURRENT_STATUS.md`
- 在新的 `.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/` 写生成物与 `ds_execution_report.md`

发现这些目标文件在启动后被其他进程修改，或输出目录已经存在时，停止并报告 `BLOCKED_WORKTREE_CONFLICT` / `BLOCKED_EVIDENCE_DIR_EXISTS`，不得覆盖。

## 4. 明确禁止

- 不改 `PoseTracker`、`TrackMap`、4B-4 capture、固件、依赖、PDF/ChArUco 工具或总计划书。
- 不打开摄像头，不连接网络/ESP/MCU，不烧录、不复位、不发命令、不运行电机。
- 不覆盖或编辑任何旧 `.embeddedskills/build/**` 证据。
- 不执行任何 Git 写操作：无 add/commit/push/reset/checkout/stash/clean/branch。
- 不把 `EXPLORATORY_RELATIVE_ONLY` 写成 2 mm、4B-2/3/4 COMPLETE、READY、G1-G8 或正式 PID 证据。
- 不在完成本 plan 后自行开始下一任务。

## 5. 必须实现的防错契约

1. profile 显式记录 `input_domain=RAW_PIXEL`，不能暗含或重复去畸变。
2. profile 显式记录 `quality=EXPLORATORY_RELATIVE_ONLY`。
3. `require_ground_holdout_verified_2mm()` 必须拒绝该 profile。
4. exporter 必须验证 source SHA、corrected `anchor_correction`、矩阵和四个独立误差指标。
5. exporter 对已有非空输出目录必须失败，不能删除、覆盖或补写。
6. 生成 JSON 必须确定性、UTF-8、LF、排序键、无时间戳漂移。
7. 新状态文档保留旧历史，但明确旧“板附近 0.3 mm / 全图约 5%”不是全赛道绝对精度证据。

## 6. DS 回传

完成后在
`.embeddedskills/build/v1_task4b2_r3_exploratory_profile_20260804_r1/ds_execution_report.md`
逐项给出：

1. `READY_FOR_CODEX_REVIEW / BLOCKED`
2. 实际新增/修改文件
3. RED 与 GREEN 命令、完整计数、退出码
4. source/profile/report SHA-256
5. 导出的 3x3 matrix、holdout p95/max、LOO p95/max
6. formal 2 mm gate 为何必须 REJECT
7. 未验证项
8. 未使用硬件/网络且未做 Git 写操作的声明
9. 下一接口：`CalibrationProfile` 和生成的 `calibration_profile.json`

报告完成后停止。Codex 会独立查看 diff、重算哈希、复跑测试和恶意输入，再给 `PASS / REJECT / INSUFFICIENT_EVIDENCE`。

## 7. 后续编排（本轮不得执行）

只有 Codex 验收本轮 PASS 后才依次发新 handoff：

1. A4 全局 ChArUco 20 页 PDF/manifest 软件包。
2. profile 接入 C960 采集、保留原始 AprilTag 像素与时间戳。
3. 4B-4 遥测批量离线 TDD/Keil；真机另行授权。
4. 4B-5 固件等价控制器和 world-to-mask 契约。
5. 4B-6/4B-7 仅骨架与离线隔离；停在 4B-8 前。
