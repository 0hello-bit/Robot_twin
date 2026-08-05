## Handoff — Task 4B-D (Phase A: 计划同步) — 返工 v2

### Task ID / Status
- **Task:** 4B-D — 计划同步与旧 Task 4 文档更新（返工）
- **Status:** COMPLETE（返工修订完成）
- **背景:** 上一轮独立验收结论为 **FAIL**；本文件为 FAIL 后的返工输出
- **4B-D 人工验收 gate:** ⬜ **尚未满足** — 等待用户/独立验证者重新验收

---

### Changed files（本次返工）

| 操作 | 路径 | 说明 |
|------|------|------|
| MODIFIED | `docs/superpowers/plans/2026-07-28-line-following-pid-closed-loop.md` | ① 补入 Task 5B 章节（P1）；② 删除文件结构表中两行幽灵条目（P2） |
| MODIFIED | `docs/superpowers/specs/2026-07-28-line-following-pid-closed-loop-design.md` | 本次返工未修改（哈希未变） |
| MODIFIED | `.embeddedskills/build/v1_task4bd/handoff.md` | 本文件 — 覆盖更新，修正 P3/P4 表述并记录 P6 |
| NEW | `.embeddedskills/rollback/v1_task4bd/` | 修改前快照 2 份 + manifest（P6，依据 §21 回滚规程） |
| — | 生产代码、测试、固件、Keil 工程、配置、模型 JSON、数据文件 | **未触碰** |

> **⚠️ Changed files 更正（针对上一轮 FAIL 的 P3 / P4 项）**
>
> 上一轮 handoff 的 Changed files 存在两处错误，现更正如下：
>
> 1. **`NEW: docs/superpowers/AGENTS.md`（P3）** — 纲领 §5 卡片"允许修改的文件"仅列两份设计文档，**未授权创建该文件**；本会话亦无上一轮用户对该文件的明确授权记录（无法回溯确认，等级 ⚪ INSUFFICIENT EVIDENCE）。经核查：该文件磁盘存在（mtime 2026-07-30 23:37:28，早于上一轮 handoff 的 00:22），内容为从主目录 `<USER_PROFILE>\.codex\AGENTS.md`（存在，mtime 2026-07-23）复制的 8 条通用批判性思维原则。**更正为:** 不将 AGENTS.md 计为 4B-D 交付物；保留/删除交由用户决定。本返工按约束不修改、不删除该文件。
>
> 2. **`NEW: docs/superpowers/... memory entries`（P4）** — 路径错误。三条 memory 条目（摄像头方案、标记尺寸、AGENTS 来源记录）真实存放于 **`<LOCAL_AGENT_MEMORY>\`**：`camera-droidcam.md`、`markers-chessboard-sizes.md`、`agents-md-copied.md`（由 `MEMORY.md` 索引；创建于 2026-07-31 00:16，originSessionId `657d7c50`，即上一轮 4B-D 会话）。`docs/superpowers/` 下不存在任何 memory 条目。**更正为:** 真实路径如上，不在 `docs/superpowers/`。

---

### 修复前后对照（验收 FAIL 项 → 本轮修复）

| # | FAIL 项 | 修复前 | 修复后 | 验证方式 |
|---|---------|--------|--------|---------|
| P1 | plan 缺失 Task 5B 章节 | Task 5A 之后直接进入 Task 6，无 5B | 补入 **"Task 5B: 固定赛道真机闭环活动"**（plan L434-481），含：前置条件（🔴4B-8 READY + ✅4C PASS + ✅5A PASS + 🔴用户本次明确硬件授权，旧授权不可沿用、当次确认赛道净空/急停可用/供电正常）；硬件需求（🔴用户必须在场、赛道净空、急停可用、一次一个动作、每次部署逐次授权，安全规则引 §13 Track Run）；Task 完成 gate（真机 campaign 按 exact-5 完整结束、回滚闭环完成、不能宣称 V1 已找到更优 PID）；V1 成功 gate（无候选满足时 V1 不得标记完成，应回 4C 生成下一批候选且不得降低门槛）；步骤 1-6 | `grep -n "Task 5B"` 命中 L434；Read 核对 L434-481 |
| P2 | plan 残留幽灵条目 | 文件结构表含 `simulation/digital_twin/analysis/campaign_orchestrator.py`、`simulation/digital_twin/tests/test_campaign_orchestrator.py` 两行 | 两行已删除；编排器唯一指向 `v1_twin/v1_twin_orchestrator.py`（表中已存在 L60 行） | Glob 确认两文件磁盘不存在；`grep "analysis/campaign_orchestrator|test_campaign_orchestrator"` 无匹配 |
| P3 | AGENTS.md 授权来源未说明 | Changed files 将 AGENTS.md 列为 NEW 交付物 | 已更正（见上节）：不在 §5 允许清单、无授权记录、不计为交付物；源为 `<USER_PROFILE>\.codex\AGENTS.md`；保留/删除交用户决定 | 文件系统核查 mtime、内容、源文件 |
| P4 | "memory entries" 路径声明错误 | `docs/superpowers/...` | 更正为真实路径 `<LOCAL_AGENT_MEMORY>/` | 目录列举 + 读取 3 个 memory 文件 |
| P6 | 无回滚快照 | 无 | `.embeddedskills/rollback/v1_task4bd/` 含修改前快照 2 份 + manifest；前后哈希已记录 | sha256sum 前后对照 |

---

### Commands

```bash
# 纯文档修改，无代码变更，未运行测试。
# 已执行的核查命令（exit=0）:
grep -n "Task 5B" docs/superpowers/plans/2026-07-28-line-following-pid-closed-loop.md
grep -n "analysis/campaign_orchestrator|test_campaign_orchestrator" docs/superpowers/plans/2026-07-28-line-following-pid-closed-loop.md
sha256sum docs/superpowers/plans/2026-07-28-line-following-pid-closed-loop.md docs/superpowers/specs/2026-07-28-line-following-pid-closed-loop-design.md
```

### Exact results and exit codes
```
grep "Task 5B"                                   -> L434, L457 命中
grep "analysis/campaign_orchestrator|..."        -> No matches found
sha256sum (修改后) plan=23ee72d7…, spec=d7ff44e4…
exit=0
```

### Artifact/log/report paths
- `.embeddedskills/build/v1_task4bd/handoff.md` — 本文件（覆盖更新）
- `.embeddedskills/rollback/v1_task4bd/manifest.md` — 回滚清单（前后哈希对照）
- `.embeddedskills/rollback/v1_task4bd/2026-07-28-line-following-pid-closed-loop.plan.before-rework.md` — plan 修改前快照
- `.embeddedskills/rollback/v1_task4bd/2026-07-28-line-following-pid-closed-loop-design.spec.before-rework.md` — spec 修改前快照

---

### Verified facts

- ✅ **[VERIFIED SOFTWARE]** — plan 已含 Task 5B 章节（L434-481），内容与纲领 §8b 卡片一致（grep + Read 核对）
- ✅ **[VERIFIED SOFTWARE]** — plan 幽灵条目已清除（grep 无匹配）
- ✅ **[VERIFIED SOFTWARE]** — 前后哈希已记录（sha256sum）：plan `6afa38f8…` → `23ee72d7…`；spec 未变 `d7ff44e4…`
- ✅ **[VERIFIED SOFTWARE]** — 两份幽灵文件 `simulation/digital_twin/analysis/campaign_orchestrator.py`、`simulation/digital_twin/tests/test_campaign_orchestrator.py` 磁盘不存在（Glob）
- ✅ **[VERIFIED SOFTWARE]** — `docs/superpowers/AGENTS.md` 磁盘存在（mtime 2026-07-30 23:37:28），源文件 `<USER_PROFILE>\.codex\AGENTS.md` 存在（mtime 2026-07-23）
- ✅ **[VERIFIED SOFTWARE]** — 三条 memory 条目真实路径在 `<LOCAL_AGENT_MEMORY>/`（3 文件已读取）

### Inferences

- 🔶 AGENTS.md 由上一轮 4B-D 会话新建（磁盘 mtime 早于上一轮 handoff，且记忆文件 `agents-md-copied.md` 的 originSessionId=`657d7c50` 与该会话一致）——即"该文件非本次新建"的辩护不成立，故按"更正 Changed files 表述"处理。

### Unverified items

- ⚪ 上一轮创建 AGENTS.md 时是否取得用户明确授权 — 无法回溯确认（INSUFFICIENT EVIDENCE）
- ⚪ 4B-D 人工验收 gate（用户确认 spec/plan 的 Task 4 章节已正确反映新设计）— 尚未满足，等待重新验收
- ⚪ 摄像头实时能力、标定板、车顶标记等硬件事实 — 仍为待实测状态（未连接硬件）

### Scope review

- 未修改生产源代码、测试、配置、固件、Keil 工程、模型 JSON 或真实数据 ✓
- 未连接摄像头、小车、串口或网络设备 ✓
- 未烧录、未复位、未发送电机命令 ✓
- 未安装软件或修改系统环境 ✓
- 未降低任何验收阈值或硬件安全要求 ✓
- 未 git init ✓
- 本次返工仅修改 plan（P1/P2）与 handoff（P3/P4/P6 记录）；spec 未修改 ✓
- AGENTS.md 未修改、未删除（是否保留交由用户决定）✓

### Hardware actions performed
- ❌ 无

### Safety/rollback state
- 无硬件安全隐患
- 回滚快照已留存于 `.embeddedskills/rollback/v1_task4bd/`（§21 规程：覆盖/删除前须核对哈希并经用户确认）

---

### 4B-D 人工验收 gate 自评

| 检查项 | 状态 |
|--------|------|
| 旧 Task 4 方案已废弃；两份文档不再把旧数字孪生当作可信 PID 预筛选依据 | ✅ 满足 |
| 4B-0→4B-8、4C 顺序与依赖一致；4B-8 未 READY 时 4C 不得开始 | ✅ 满足 |
| **Task 5B 章节存在**，依赖 4B-8 READY + 4C PASS + 5A PASS + 用户当次授权（P1） | ✅ 满足 |
| calibration 与 holdout 按 run_id 硬隔离，程序硬检查交集为空 | ✅ 满足 |
| 全部候选被拒绝只能证明编排/回滚闭环完成，不能宣称 V1 已找到更优 PID；V1 不得标记完成、回 4C 且不得降低门槛 | ✅ 满足 |
| plan 文件结构无幽灵条目，编排器指向 `v1_twin/v1_twin_orchestrator.py`（P2） | ✅ 满足 |
| Changed files 表述如实、无越权/错误路径声明（AGENTS.md、memory entries，P3/P4） | ✅ 满足 |
| 回滚快照与前后哈希已留存（P6） | ✅ 满足 |
| 摄像头实时能力仍为待实测事实，未写成已验证 | ✅ 满足 |

**4B-D 人工验收 gate（纲领 §5）结论:** ⬜ **NOT MET — 等待重新验收。** 上述 9 项为修复后的事实自评，需用户或独立验证者对返工输出执行独立验收并给出 PASS/FAIL 后方可判定 gate 满足。

### 下一 Task 进入条件

| 条件 | 状态 |
|------|------|
| 用户确认 plan 章节更新完成（4B-D 人工验收 PASS） | ⬜ **待重新验收** |
| 进入 Task 4B-0 | ⬜ **禁止** — 须待 4B-D 重新验收 PASS 后由用户/独立验证者指示 |

**是否具备进入 Task 4B-0 的条件？** ❌ 否。本返工完成后立即停止，**不进入 Task 4B-0**，等待用户或独立验证者重新验收。

---

*Task 4B-D 返工 v2 完成。等待重新验收。*
