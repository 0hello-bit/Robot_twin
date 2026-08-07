# Robot Twin AI - 数字孪生工作区

这是 Robot Twin AI 的唯一正式工作区。外层目录
stm32小车 只保留原始资料、旧代码和历史环境，不是后续 agent 的工作目录。

## 入口

- 当前状态：docs/agent-context/CURRENT_STATUS.md
- 项目记忆与复用规则：docs/agent-context/PROJECT_MEMORY.md
- 当前总计划：docs/Robot_Twin_AI_完整计划说明书_v2.7.md
- V1-B 详细计划：docs/superpowers/plans/2026-08-05-v1-b-real-calibration-holdout.md
- 当前唯一可发送的 B2 agent 提示词：docs/superpowers/prompts/2026-08-05-v1-b2-active-agent-prompt.md
- V1-A handoff：docs/evidence/v1_offline_foundation_20260805_r1/handoff.md
- 独立验收：docs/evidence/v1_offline_foundation_20260805_r1/codex_acceptance.md

## 目录

- simulation/digital_twin/：数字孪生、预测器和仿真测试
- firmware/stm32_line_follower/：当前 STM32 固件源工程的精选副本
- hardware/：硬件参考资料和 PCB 证据
- docs/：计划、状态、handoff 和证据索引
- archive/：不属于当前执行路径的历史范围说明

## 当前状态

V1-A 离线基础和 V1-B B1 离线 preflight 已通过独立复验，但这不等于真实数字孪生 READY。B2 已完成一次经授权的硬件 Smoke，但当前证据状态仍为 `INSUFFICIENT_EVIDENCE`；正在补齐固件身份、连接生命周期和相机实际模式的证据契约。离线修复经 Codex 独立验收后，下一步仍需用户对一次新的 B2 复跑明确授权，不能自动进入 B3 或硬件优化。
