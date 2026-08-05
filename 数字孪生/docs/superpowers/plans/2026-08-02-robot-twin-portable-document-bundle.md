# Robot Twin AI 可移植资料包（Portable Document Bundle）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans。本计划由执行代理逐 Task 执行（checkbox 跟踪）；本项目执行模型为 **DeepSeek 逐任务执行、Codex 最终独立验收**。任何 Task 的产物都不是验收结论，Codex 以 gate 结果与 manifest 为准独立复核。
>
> 设计源（唯一依据，执行前必须只读通读）：`docs/superpowers/specs/2026-08-02-robot-twin-portable-document-bundle-design.md`。
>
> 本计划是**文档产物**，本身不授权复制/改写/验收。实际执行（复制 PDF/证据、生成 `.portable` 副本、改写总说明书、跑 gates）需要用户另行批准一次独立执行任务；执行时遵循本计划全部步骤、停机条件与回滚边界。

**Goal:** 把主说明书实际引用的证据、3 份 PDF 与 22 个可移植证据副本复制进 `docs/sources/` + `docs/evidence/`，生成 `docs/evidence/manifest.json`，并把主说明书全部 Markdown 链接/§6 证据列改写为从 `docs/` 可解析的仓库内相对路径，用 10 项只读 gate 证明可移植性、哈希/脱敏一致、敏感信息 0 命中、无 Git 写操作、无产品代码变化，输出最小可回滚足迹。

**Architecture:** 一个五阶段流水线——阶段 0 预检/分类（只读快照 + 全量扫描 → 三种 `content_mode` 决策树）；阶段 1 复制（PDF 先、证据后、`.portable` 脱敏副本生成并复扫）；阶段 2 生成 `docs/evidence/manifest.json`；阶段 3 主说明书链接/§6 证据列/§14.1 易变计数纯目标改写；阶段 4 跑 §9 全部 10 项只读 gate；阶段 5 写执行 handoff。全程原件只读、Git 只读、无硬件、无产品代码改动。

**Tech Stack:** Python 3.11（`<PROJECT_PYTHON>`，见 Global Constraints）、pypdf（PDF 页数/元数据/文本提取，需 preflight 安装）、PowerShell 5.1（只读文件/哈希/git 操作）、JSON/Markdown、`git status/check-ignore/rev-parse` 只读核对。

## Global Constraints

1. 先只读通读设计文档（见上）。任何与设计不一致的执行决定必须写入 classification report / handoff 并交 Codex 复核，不得静默偏离。
2. **无 Git 写操作**：全程只允许 `git status` / `git check-ignore` / `git rev-parse` / `git log` 等只读命令；禁止 `git add/commit/push/reset/checkout/init/branch/tag/remote`。若某步骤出现任何 Git 写命令、硬件命令、或对 `.embeddedskills/**`/外部 PDF 原件的写/删/移，立即停机（设计 §11.7 停机条件 8）。
3. **无硬件动作**：不连接 MCU/ESP/串口/TCP/烧录/电机/摄像头；不执行构建或网络扫描。
4. **无产品代码改动**：`simulation/digital_twin/`、固件、Keil 工程、Host C、测试一律不动（含当前已修改的 `test_v1_twin_track_map.py`、`v1_twin_track_map.py`，保持现状）。任何执行动作只落在：`docs/sources/**`、`docs/evidence/**`、主说明书允许行、以及 git 忽略的本地工作目录。
5. **原件只读**：`.embeddedskills/**` 与外部 PDF 原件永不改写、永不删除、永不移动；脱敏只发生在 `docs/evidence/` 下本任务新增的 `.portable` 副本上。
6. **本地工作目录** `LOCAL_DIR = _unrelated/portable_bundle_preflight/`（已实测 `git check-ignore _unrelated` exit=0，git 忽略、不入库）。所有 preflight/classification/redactions/scan/gate 中间产物、总说明书字节备份、命令日志都写在这里；任何外部 PDF 源绝对路径只出现在本目录文件与执行提示上下文，**永不进入仓库或 manifest**。
7. **隐私边界**：仓库内任何产物（`docs/sources/**`、`docs/evidence/**`、manifest、改写后总说明书、本计划、handoff）不得含个人绝对路径、账号标识、密码/密钥/token 实际值、wxid 实际值、私网 IP 实际值。redaction 记录只含 `{category, location, placeholder}`，绝不含原敏感值。
8. **本轮只允许创建/修改** `docs/superpowers/plans/2026-08-02-robot-twin-portable-document-bundle.md`（本文件）。执行阶段（另一次用户批准）才允许创建/修改本计划列出的交付物路径。
9. **停机条件**（设计 §11.7，任一命中立即停止并写失败说明，不进入下一阶段）：
   | # | 条件 |
   |---|---|
   | 1 | 任一候选源或 PDF 源缺失/不可读 |
   | 2 | 目标已存在且哈希与预期不符（写 `conflict_report.json` 后停机） |
   | 3 | PDF pypdf 打不开或页数 0 |
   | 4 | 敏感扫描（§9 gate 5 全量范围）有**实际敏感值**命中 |
   | 5 | 主说明书改写 diff 超出 §6/§14/§17 允许行集 |
   | 6 | 预检发现 `docs/sources/` 或 `docs/evidence/` 非空且含未预期文件 |
   | 7 | 任一验收 gate FAIL |
   | 8 | 出现任何 Git 写 / 硬件 / 原件写删移 |
   | 9 | 某候选是必要证据但无法安全脱敏 → 停机交用户裁决 |
   | 10 | 用户随时中止 |
10. **执行上下文参数解析规则**（占位符 → 运行值；非占位性任务，均有明确解析规则，不得留空）：
    - `<PROJECT_PYTHON>` = Python 3.11 解释器绝对路径，由执行提示上下文提供（用户 Python 安装目录下的解释器；本机对应路径**不写入本计划**）。校验：`<PROJECT_PYTHON> -c "import sys; assert sys.version_info[:2] == (3, 11)"`。失败 → 停机条件 1。
    - `<WORKSPACE_ROOT>` = 本任务执行会话的工作目录（= 仓库根，本计划全部命令在仓库根运行，不书写其绝对路径）。sanitize 时按该实际值构建替换模式。
    - `<PDF_SOURCE_1|2|3>` = 三份 PDF 的外部源绝对路径，解析顺序：执行提示上下文提供 → 或 `LOCAL_DIR/pdf_local_sources.json`（Task 1 建立）读取。绝对源路径只存在于该 git 忽略清单，永不进入仓库/manifest/本计划。
    - 全部命令在仓库根执行；所有仓库内路径以 `/` 分隔的相对路径书写。

---

### Task 1: 执行前只读快照与 Preflight

**Files:**
- 创建（git 忽略）：`_unrelated/portable_bundle_preflight/`（含 `baseline_git_status.txt`、`preflight_manifest.json`、`master_spec_backup.md`、`command_log.md`、`pdf_local_sources.json`）
- 只读：`docs/Robot_Twin_AI_完整计划说明书_v2.0.md`、`.embeddedskills/build/**`、`.gitignore`、git 状态
- 本 Task 不创建任何 `docs/` 下交付物，不改动任何产品文件。

**Interfaces:**
- 产出 `preflight_manifest.json`：`{baseline:{head,branch,recorded_at}, created:[目标路径], modified:[主说明书], source_hashes:{候选:sha256}, rollback_boundary:"..."}`。
- 产出 `master_spec_backup.md`：总说明书的字节备份（回滚恢复依据）。

**本 Task 独立验收点：** preflight_manifest.json 覆盖全部 23 候选 + 3 PDF 源 + 目标路径清单 + 总说明书 backup；`docs/sources/`、`docs/evidence/` 确认不存在（或为空）；3 个 PDF 源已解析；pypdf 可用；scan_tool selftest PASS；git 只读基线记录完毕。

- [ ] **Step 1: 建立本地工作目录并记录命令日志**
  ```powershell
  New-Item -ItemType Directory -Force _unrelated/portable_bundle_preflight | Out-Null
  "T1: 创建 LOCAL_DIR；时间戳见 preflight_manifest.recorded_at" | Add-Content _unrelated/portable_bundle_preflight/command_log.md
  ```
  失败判定：目录创建失败（权限/路径）→ 停机。成功：`Test-Path _unrelated/portable_bundle_preflight` 为 True。

- [ ] **Step 2: 记录只读 git 基线**
  ```powershell
  git rev-parse --short HEAD | Out-File -Encoding utf8 _unrelated/portable_bundle_preflight/head.txt
  git status --porcelain -uall | Out-File -Encoding utf8 _unrelated/portable_bundle_preflight/baseline_git_status.txt
  git rev-parse --abbrev-ref HEAD | Out-File -Encoding utf8 _unrelated/portable_bundle_preflight/branch.txt
  ```
  判定：`head.txt` 非空且等于 `git rev-parse --short HEAD` 重跑值（应为 `a9ea390`，无 Git 写则不变）。`baseline_git_status.txt` 非空。记录 `(git ls-files | Measure-Object -Line).Lines`、`(git status --porcelain -uall | Select-String -Pattern '^\?\?').Count`、`(git status --porcelain | Select-String -Pattern '^ M').Count` 到 preflight_manifest.json（Task 6 需刷新值）。

- [ ] **Step 3: 确认 23 个候选源存在（只读）**
  对以下相对 `.embeddedskills/build/` 的 23 个路径逐一 `Test-Path`（相对仓库根为 `.embeddedskills/build/<路径>`）：
  `task2b-motor-register-diag/report.md`、`task3-campaign-storage-metrics/report.md`、`task4a-digital-twin-audit/report.md`、`v1_task4b0/handoff.md`、`v1_task4b1/handoff.md`、`v1_task4b1/gate0_report.json`、`v1_task4b2/handoff.md`、`v1_task4b2_c1_open_route/handoff.md`、`v1_task4b2_c1_open_route/metrics.json`、`v1_task4b2_c1_open_route/selected_route.json`、`v1_task4b2_c1_open_route/route_selection.json`、`v1_task4b3/handoff.md`、`v1_task4b3/static_pose_report.json`、`v1_task4b4_fix/handoff.md`、`v1_task4b4_fix/BLOCKED_duplicate_execution.md`、`v1_task4b4_fix/task4b4_final_offline_acceptance.md`、`v1_task4b4_fix/task4b4_hardware_gate_runbook.md`、`v1_task4b_offline_rework/final_report.md`、`v1_task4b_reacceptance/4b1/gate0_report.json`、`v1_task4b_reacceptance/4b2/handoff.md`、`v1_task4b_reacceptance/4bd/gate_report.json`、`v1_task4bd/handoff.md`、`project_plan_v2/deepseek_project_plan_v2_prompt.md`。
  ```powershell
  $candidates = @(...上面 23 个，相对路径...)
  $missing = $candidates | Where-Object { -not (Test-Path (".embeddedskills/build/" + $_)) }
  if ($missing) { Write-Output "MISSING: $missing"; throw "停机条件 1" }
  ```
  任一缺失 → 停机条件 1。

- [ ] **Step 4: 解析并确认 3 份 PDF 源（不写入仓库）**
  按 Global Constraints 的解析顺序取得 `<PDF_SOURCE_1|2|3>`；若本地清单不存在则创建：
  ```powershell
  if (-not (Test-Path _unrelated/portable_bundle_preflight/pdf_local_sources.json)) {
    @{
      pdf_1 = "<PDF_SOURCE_1>"; pdf_2 = "<PDF_SOURCE_2>"; pdf_3 = "<PDF_SOURCE_3>";
    } | ConvertTo-Json | Set-Content -Encoding utf8 _unrelated/portable_bundle_preflight/pdf_local_sources.json
  }
  ```
  对每个源 `Test-Path -LiteralPath` 且 `Get-Item` 可读、`Get-Item.Length -gt 0`。任一源缺失/不可读 → 停机条件 1。**该清单 git 忽略，永不入库；manifest 不含源绝对路径。**

- [ ] **Step 5: docs/sources 与 docs/evidence 冲突检查**
  ```powershell
  if (Test-Path docs/sources) { $c = Get-ChildItem docs/sources -Recurse -File; if ($c) { throw "停机条件 6" } }
  if (Test-Path docs/evidence) { $c = Get-ChildItem docs/evidence -Recurse -File; if ($c) { throw "停机条件 6" } }
  git check-ignore docs/sources; if ($LASTEXITCODE -eq 0) { throw "docs/sources 被 git 忽略，无法入库" }
  git check-ignore docs/evidence; if ($LASTEXITCODE -eq 0) { throw "docs/evidence 被 git 忽略，无法入库" }
  ```
  判定：两目录不存在或为空；`git check-ignore` 对两者 exit=1（未忽略）。任一违反 → 停机条件 6。

- [ ] **Step 6: pypdf 前置依赖**
  ```powershell
  <PROJECT_PYTHON> -c "import pypdf; print(pypdf.__version__)"
  ```
  失败（ModuleNotFoundError）时安装：
  ```powershell
  <PROJECT_PYTHON> -m pip install pypdf
  ```
  再校验 import 成功。重装仍失败 → 停机条件 1（缺依赖）。该安装只改 Python 环境，不改仓库。

- [ ] **Step 7: 写入扫描/脱敏/验收工具并跑 selftest**
  将本计划「附录 A：scan_tool.py」「附录 B：sanitize_tool.py」「附录 C：verify_tool.py」原样写入 `_unrelated/portable_bundle_preflight/` 三个文件（UTF-8，无 BOM）。
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/scan_tool.py --selftest
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py selftest
  ```
  判定：两条都输出 `ok` 且 exit=0。任一 FAIL → 停机（工具不自洽，不得继续）。
  **工具必须用 `python <脚本>` 方式运行（不 import），配合脚本内 `sys.dont_write_bytecode=True`，保证不产生 `__pycache__`。**

- [ ] **Step 8: 生成 preflight_manifest.json 与主说明书字节备份**
  ```powershell
  Copy-Item -LiteralPath "docs/Robot_Twin_AI_完整计划说明书_v2.0.md" -Destination "_unrelated/portable_bundle_preflight/master_spec_backup.md"
  ```
  计算 23 候选源 `Get-FileHash -Algorithm SHA256 -LiteralPath <源>` 并写入 preflight_manifest.json 的 `source_hashes`。`created` 列表 = 本计划「附录 D」全部目标路径（3 PDF + 22 evidence + manifest）。`modified` = `["docs/Robot_Twin_AI_完整计划说明书_v2.0.md"]`。`rollback_boundary` = "回滚仅删除 created 列表内文件、恢复 master_spec_backup.md；禁止广泛删除；禁止 git 写"。
  判定：preflight_manifest.json 可被 `<PROJECT_PYTHON> -c "import json,sys; json.load(open(sys.argv[1],encoding='utf-8'))" _unrelated/portable_bundle_preflight/preflight_manifest.json` 解析。

- [ ] **Step 9: 只读核对 `docs/superpowers/**` 其余文档无跨目录链接**
  ```powershell
  Select-String -Path docs/superpowers/*.md,docs/superpowers/specs/*.md,docs/superpowers/plans/*.md -Pattern '\]\((?!(#|http|https|mailto))' | Where-Object { $_.Line -match '(docs/|\.embeddedskills)' }
  ```
  判定：无命中（设计已实测仅锚点链接）。若有命中 → 停机并交设计层复核（超出本计划允许行集），不停留在本 Task。

---

### Task 2: 全量扫描与 content_mode 分类

**Files:**
- 创建（git 忽略）：`_unrelated/portable_bundle_preflight/classification_report.json`、`_unrelated/portable_bundle_preflight/scan_hits_<name>.json`
- 只读：23 候选源 + 3 PDF 源

**Interfaces:**
- 输入：候选源、PDF 源、`scan_tool.py`。
- 产出：逐候选 `content_mode ∈ {byte_identical, sanitized_copy, excluded_hash_only}`、`source_sha256`、`size_bytes`、`purpose`、`section_ref`、`redactions_plan`、`is_authoritative`、`narrative_reviewed[]`。

**本 Task 独立验收点：** 23 候选全部被扫描、全部有明确 content_mode、无候选被跳过；预期分布（16 byte_identical / 6 sanitized_copy / 1 excluded_hash_only）以现场扫描为准并记录偏差；必要证据无法安全脱敏时停机（条件 9）。

- [ ] **Step 1: 对 23 候选运行全量扫描**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/scan_tool.py --scan `
    .embeddedskills/build/task2b-motor-register-diag/report.md `
    .embeddedskills/build/task3-campaign-storage-metrics/report.md `
    .embeddedskills/build/task4a-digital-twin-audit/report.md `
    .embeddedskills/build/v1_task4b0/handoff.md `
    .embeddedskills/build/v1_task4b1/handoff.md `
    .embeddedskills/build/v1_task4b1/gate0_report.json `
    .embeddedskills/build/v1_task4b2/handoff.md `
    .embeddedskills/build/v1_task4b2_c1_open_route/handoff.md `
    .embeddedskills/build/v1_task4b2_c1_open_route/metrics.json `
    .embeddedskills/build/v1_task4b2_c1_open_route/selected_route.json `
    .embeddedskills/build/v1_task4b2_c1_open_route/route_selection.json `
    .embeddedskills/build/v1_task4b3/handoff.md `
    .embeddedskills/build/v1_task4b3/static_pose_report.json `
    .embeddedskills/build/v1_task4b4_fix/handoff.md `
    .embeddedskills/build/v1_task4b4_fix/BLOCKED_duplicate_execution.md `
    .embeddedskills/build/v1_task4b4_fix/task4b4_final_offline_acceptance.md `
    .embeddedskills/build/v1_task4b4_fix/task4b4_hardware_gate_runbook.md `
    .embeddedskills/build/v1_task4b_offline_rework/final_report.md `
    .embeddedskills/build/v1_task4b_reacceptance/4b1/gate0_report.json `
    .embeddedskills/build/v1_task4b_reacceptance/4b2/handoff.md `
    .embeddedskills/build/v1_task4b_reacceptance/4bd/gate_report.json `
    .embeddedskills/build/v1_task4bd/handoff.md `
    .embeddedskills/build/project_plan_v2/deepseek_project_plan_v2_prompt.md `
    --output _unrelated/portable_bundle_preflight/scan_hits_candidates.json
  ```
  判定：输出文件可解析；每个输入文件在 `files[]` 中都有条目（无漏扫）；若某文件条目含 `error` → 停机条件 1。扫描覆盖**文件名 + 全部字节**（scan_tool 内 `scan_name` + `scan_bytes`）。

- [ ] **Step 2: 对 3 份 PDF 源试提取文本并扫描（只读）**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/scan_tool.py --pdf <PDF_SOURCE_1> --output _unrelated/portable_bundle_preflight/pdf_src_1.json
  ```
  对 2、3 同理。判定：每份输出含 `pages>0`、`extraction_status`（`ok`/`degraded_binary_scan`/`failed_binary_scan_human_review`）、`hits[]`。PDF 无 `pages` 或页数 0 → 停机条件 3。PDF 的 `hits[]`（元数据 + 可提取文本 + 内容流 + 文件名）有实际敏感值 → 停机条件 4（PDF 无法脱敏）。

- [ ] **Step 3: 逐候选分类（决策树 = 设计 §5.3）**
  对每个候选，按扫描命中执行：
  - 无敏感命中 → `byte_identical`。
  - 有敏感命中且是必要验收证据 → `sanitized_copy`，按附录 D 的脱敏表生成 `redactions_plan`。
  - 有敏感命中且非必要证据（执行提示/过程性产物/可再生摘要）→ `excluded_hash_only`。
  - 有敏感命中、是必要证据、且**无法安全脱敏**（敏感值内嵌无中立替换语义）→ 停机条件 9，写清命中类别/脱敏可行性/排除后果交用户裁决。
  - 命中类别词但复核无实际值（如安全自审叙述）→ 人工复核后记入 `narrative_reviewed[]`，`note` 填「已复核：叙述性、无值」，分类可判 `byte_identical`。**任何实际敏感值命中不得借此类复核跳过脱敏。**

- [ ] **Step 4: 对照预期分布并记录偏差**
  预期：16 `byte_identical` + 6 `sanitized_copy` + 1 `excluded_hash_only`（设计 §5.4，预扫描）。现场分类与之不符时，在 classification_report.json 记录每条偏差的理由（新命中/复核改判）。预期不强制：**以现场扫描为准**，但必须逐条可解释。

- [ ] **Step 5: 计算源哈希并落盘 classification_report.json**
  对每个候选计算 `Get-FileHash -Algorithm SHA256`（与 Task 1 Step 8 的 source_hashes 一致）；组装：
  ```json
  {
    "candidates": [
      {
        "origin_repo_path": ".embeddedskills/build/<子路径>",
        "target_repo_path": "docs/evidence/<镜像>/<原名[.portable].ext>",
        "content_mode": "byte_identical|sanitized_copy|excluded_hash_only",
        "source_sha256": "<hex>",
        "size_bytes": 0,
        "purpose": "§17.1 链接 / §6 <Task> / 历史记录说明",
        "section_ref": ["§17.1"],
        "is_authoritative": true,
        "redactions_plan": [{"category": "...", "location": "字段/行", "placeholder": "<...>"}]
      }
    ],
    "narrative_reviewed": [{"file": "...", "category": "...", "line": 0, "note": "已复核：叙述性、无值"}],
    "scanned_all_candidates": true,
    "expectation": {"byte_identical": 16, "sanitized_copy": 6, "excluded_hash_only": 1}
  }
  ```
  `redactions_plan` 只含类别/位置/占位符，**不含原敏感值**。文件经 JSON 解析校验。判定：每个候选 `content_mode` 三选一；`scanned_all_candidates=true`；排除项仅在 `project_plan_v2/deepseek_project_plan_v2_prompt.md` 上（若现场扫描改判则记录理由）。

- [ ] **Step 6: 脱敏表核对（附录 D）**
  逐个 `sanitized_copy` 候选核对 redactions_plan 与附录 D 一致（类别 + 目标 `.portable` 名 + 占位符）。不一致时按现场扫描修正并记录。判定：6 个 sanitized 候选均有非空 `redactions_plan`；16 个 byte_identical 候选 `redactions_plan=[]`。

---

### Task 3: 复制 3 份 PDF 并验证

**Files:**
- 创建（入库）：`docs/sources/Robot_Twin_AI_具身智能机器人自主优化平台规划文档.pdf`、`docs/sources/Robot_Twin_AI_V1.0_软件架构设计文档.pdf`、`docs/sources/Robot_Twin_AI_V1.0_开发任务拆解与里程碑文档.pdf`
- 创建（git 忽略）：`_unrelated/portable_bundle_preflight/pdf_copy_<n>.json`

**Interfaces:**
- 输入：3 份 PDF 源（仅本地清单/提示上下文）。
- 产出：3 份字节一致副本 + 每份 {pages, source_sha256, portable_sha256, extraction_status, hits}。

**本 Task 独立验收点：** 3 份 PDF 均可被 pypdf 打开、页数>0、副本哈希=源哈希、元数据/文件名/可提取文本（或内容流降级扫描）敏感 0 命中、不被 git ignore。

- [ ] **Step 1: 逐份复制**
  从 `pdf_local_sources.json` 读取源，复制到目标（保留原文件名）：
  ```powershell
  Copy-Item -LiteralPath <PDF_SOURCE_n> -Destination "docs/sources/<PDF文件名>"
  ```
  判定：`Test-Path docs/sources/<PDF文件名>` 为 True；`(Get-Item).Length` 与源一致。

- [ ] **Step 2: 每份验证可打开、页数、哈希、提取状态**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/scan_tool.py --pdf "docs/sources/<PDF文件名>" --output _unrelated/portable_bundle_preflight/pdf_copy_<n>.json
  Get-FileHash -Algorithm SHA256 -LiteralPath <PDF_SOURCE_n>  # 源哈希
  Get-FileHash -Algorithm SHA256 -LiteralPath "docs/sources/<PDF文件名>"  # 副本哈希
  ```
  判定：
  - `pages > 0`，否则停机条件 3。
  - 副本哈希 == 源哈希（byte_identical），否则停机条件 2。
  - `hits[]` 无**实际敏感值**命中，否则停机条件 4。
  - `extraction_status`：`ok` → 常规文本提取成功；`degraded_binary_scan` → 常规提取为空但内容流/降级扫描有文本 → 对该 PDF 执行人工边界复核清单（查看页眉页脚/注释/嵌入对象）后记录；`failed_binary_scan_human_review` → 常规与内容流提取均失败 → 执行同一人工复核清单，并把状态如实写入 manifest `pdf_text_extraction`。

- [ ] **Step 3: 体积与 ignore 检查**
  - 任一份 > 10 MiB：写入 manifest 与报告提示 LFS/外置选项（仍按批准复制）。
  - ```powershell
    git check-ignore "docs/sources/<PDF文件名>"
    ```
    判定：exit=1（未忽略），否则停机（无法入库）。
  - 结果写入 `_unrelated/portable_bundle_preflight/pdf_copy_<n>.json`（含 pages、两哈希、extraction_status、hits、size_bytes），供 Task 5 组 manifest。

---

### Task 4: 生成 22 个可移植证据副本

**Files:**
- 创建（入库）：`docs/evidence/<镜像路径>/` 下 22 个目标（16 个原名 byte_identical + 6 个 `.portable.` 脱敏副本；完整清单见附录 D）
- 创建（git 忽略）：`_unrelated/portable_bundle_preflight/redactions/<slug>.json`、`_unrelated/portable_bundle_preflight/copy_record.json`、`docs/evidence/conflict_report.json`（仅冲突时）
- 只读：`.embeddedskills/build/**` 源文件（原件永不写/删/移）

**Interfaces:**
- 输入：classification_report.json、附录 D 脱敏表、sanitize_tool.py。
- 产出：22 个目标副本 + 每副本 {source_sha256, portable_sha256, content_mode}，并保证**源哈希在执行前后不变**。

**本 Task 独立验收点：** 22 个目标齐全且非空；byte_identical 副本哈希=源哈希；sanitized 副本哈希≠源哈希且其脱敏类别复扫 0 命中；无任何源文件被改动；无静默覆盖（冲突先写 conflict_report 并停机）。

- [ ] **Step 1: 处理 byte_identical 条目（预期 16 个）**
  对每个：先算源 `source_sha256`；若目标已存在 → 算目标哈希：等于源哈希 → 幂等跳过（`status=copied`）；不等于 → 写 `docs/evidence/conflict_report.json`（rel_path、两个哈希、双方修改时间）并**停机条件 2**。目标不存在 → 复制：
  ```powershell
  New-Item -ItemType Directory -Force docs/evidence/<镜像父目录> | Out-Null
  Copy-Item -LiteralPath ".embeddedskills/build/<源>" -Destination "docs/evidence/<镜像>"
  ```
  复制后再算目标哈希并断言 == `source_sha256`（二次校验，写入 copy_record.json 的 `portable_sha256`）。
  判定：任一不满足 → 停机条件 2。

- [ ] **Step 2: 生成 sanitized_copy 条目（预期 6 个）**
  对每个：按附录 D + 扫描命中，在 `_unrelated/portable_bundle_preflight/redactions/<slug>.json` 写 `[{category, pattern, replacement, kind}]`（`kind` 可为 `regex`/`literal`/`json_field`；实际值只出现在该 git 忽略文件）。随后：
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/sanitize_tool.py ".embeddedskills/build/<源>" "docs/evidence/<镜像>/<原名>.portable.<ext>" _unrelated/portable_bundle_preflight/redactions/<slug>.json
  ```
  复扫副本被脱敏类别（`scan_tool.py --scan <副本>`），必须 0 命中，否则停机条件 4。计算副本哈希，必须 `!= source_sha256`（不得冒充 byte_identical），否则停机。若 `.portable` 目标已存在且哈希等于本次生成值 → 幂等跳过；不等 → 写 conflict_report 并停机条件 2。
  判定：6 个副本均生成、复扫 0 命中、哈希≠源哈希。

- [ ] **Step 3: 源文件只读校验**
  对全部 22 源（与 16 byte + 6 sanitized 对应）重算哈希，与 preflight_manifest.json `source_hashes` 一致。任一变化 → 停机（有原件被改，条件 8）。判定：全部一致。

- [ ] **Step 4: 结构与数量核验**
  - 递归列出 `docs/evidence/` 全部文件：恰为附录 D 的 22 个目标 + `manifest.json`（Task 5 生成），无多余文件（额外文件 → 停机条件 6）。
  - 每个文件非空（`size_bytes > 0`）。
  - 镜像目录名与文件名与设计 §2 布局一致（ASCII 小写目录；`.portable.` 中缀只出现在 6 个 sanitized 目标）。

---

### Task 5: 生成 `docs/evidence/manifest.json`

**Files:**
- 创建（入库）：`docs/evidence/manifest.json`
- 只读：copy_record.json、classification_report.json、pdf_copy_*.json

**Interfaces:**
- 输入：Task 2/3/4 的实测数据。
- 产出：符合设计 §6 schema 的 manifest，含 entries（25 条：3 PDF + 22 evidence）、excluded_hash_only（1）、external_or_regenerable（§6.5 必现 + 扩充）、sensitive_scan、validation（动态值）。

**本 Task 独立验收点：** manifest 可被 JSON 解析；全部 rel_path 是仓库相对路径、无绝对路径/账号/私网 IP/wxid/原敏感值；redactions 记录只含 `{category, location, placeholder}`；entries 覆盖全部 22 evidence + 3 PDF；excluded/external 条目如实。

- [ ] **Step 1: 组装 `entries[]`（25 条）**
  按分类报告，每条：
  - 3 份 PDF：`category=source_pdf`、`content_mode=byte_identical`、`rel_path=docs/sources/<PDF名>`、`origin_repo_path=""`、`source_category=pdf_original`、`portable_sha256=source_sha256`、`pdf_pages=<实测>`、`purpose="§17.1 原始 PDF；PDF 原始愿景，非当前验证事实"`。
  - 22 evidence：`category=evidence`、`origin_repo_path=.embeddedskills/build/<源>`、`source_category=embeddedskills_evidence`、`content_mode`、`rel_path`、`portable_sha256`、`redactions`（byte 恒 `[]`；sanitized 为 `[{category,location,placeholder}]`）。
  - `is_authoritative` 按设计 §6.2：`v1_task4b1/handoff.portable.md`、`v1_task4b1/gate0_report.json`、`v1_task4b2/handoff.md`、`v1_task4bd/handoff.portable.md` 记 `false`（历史记录），其当前权威对应（`v1_task4b_reacceptance/4b1/gate0_report.json`、`v1_task4b2_c1_open_route/*`、`v1_task4b_reacceptance/4bd/gate_report.json`）记 `true`；其余 `true`。`purpose` 注明当前权威/历史记录。
  判定：entries 长度=25；每个 rel_path 对应磁盘存在的文件；`content_mode` 与分类一致。

- [ ] **Step 2: 组装 `excluded_hash_only[]` 与 `external_or_regenerable[]`**
  - `excluded_hash_only`：`project_plan_v2/deepseek_project_plan_v2_prompt.md`（logical_name、origin_repo_path 相对、source_sha256、reason、regeneration_or_local_history_note）。
  - `external_or_regenerable`（设计 §6.5 必现 + 扩充）：`state.json`、`config.json`（含机器/局域网地址，可再生）；`v1_task4b2/intrinsics_final.json`、`homography.json`、`track_map.json`、`sync_report.json`、`baseline_hashes.json`、`closed_path_scope_review.json`（叙事提及/可再生或已按 `.gitignore` 白名单入库）；大体积/数据：`selected_route_centerline.npy`、`selected_route_overlay.png`、`route_choices.json`、各 `.jsonl` 遥测、`frames/`、`raw_poses.json`、`raw_telemetry.json`（重跑采集/脚本再生成）；`v1_task4b1_recheck/gate0_report.json`（未被主说明书引用，不入可移植包，原件保留仓库已跟踪状态）。
  每条含 `name`、`rel_path`、`reason`、`regeneration_note`。判定：`excluded_hash_only` 恰 1 条；`external_or_regenerable` ≥ 设计必现 6.5 所列；全字段非空。

- [ ] **Step 3: 组装顶层 `sensitive_scan` 与 `validation`（动态值）**
  - `sensitive_scan.patterns` = `["drive_abs_path","user_home_abs_path","wechat_download_path","wxid","private_ip","device_serial","ssid","credential_value","password_value"]`；`scope` 按设计 §6.1 原文；`pdf_text_extraction` 取各 PDF 实测状态（`ok`/`degraded_binary_scan`/`failed_binary_scan_human_review`）；`hits` 本轮填 0（Task 7 gate 5 复核后固化）。
  - `validation`：`candidates_scanned=23`、`byte_identical_copied`/`sanitized_copied`/`excluded_hash_only`/`pdfs_copied`/`pdf_pages_ok` 从实测填；`links_checked`/`links_ok`/`hashes_match`/`redactions_complete` 由 Task 7 在 gates 通过后固化（本轮暂以现场值填，Task 7 覆盖）。
  - `git_snapshot` = `{commit: git rev-parse --short HEAD 只读值, branch: master, note: "只读快照，非 Git 写操作"}`。
  判定：字段类型与设计 §6.1 一致；无任何绝对路径。

- [ ] **Step 4: 校验 JSON 与自我敏感扫描**
  ```powershell
  <PROJECT_PYTHON> -c "import json; json.load(open('docs/evidence/manifest.json',encoding='utf-8')); print('manifest json ok')"
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/scan_tool.py --scan docs/evidence/manifest.json --output _unrelated/portable_bundle_preflight/manifest_scan.json
  ```
  判定：JSON 可解析；manifest_scan.json 的 `hits[]` 为空（manifest 自身不触发类别命中，含 pattern 列表中的类别名——如 `password_value` 不含 `=value`、`wxid` 不带下划线值，scan_tool 已保证不误报）。有命中 → 检查是否为误报（工具 selftest 已覆盖通用形态），仍报 → 修正 manifest 后重扫。

---

### Task 6: 改写主说明书链接、§6 证据列与 Git 易变计数

**Files:**
- 修改（唯一允许）：`docs/Robot_Twin_AI_完整计划说明书_v2.0.md`
- 创建（git 忽略）：`_unrelated/portable_bundle_preflight/modify_record.json`（每条 {old_string, new_string, section, line_in_backup}）

**Interfaces:**
- 输入：master_spec_backup.md、附录 E 映射表。
- 产出：改写后主说明书 + modify_record.json（回滚依据）。**除附录 E 列出的行外，其余行字节不变；行数不变。**

**本 Task 独立验收点：** 全部改写在附录 E 允许行集内；diff 校验通过（行数不变、变更行集 == modify_record 行集）；未改任何事实/数字/状态/章节号（除 §14.1/§17.3 的易变计数按当次新鲜值更新）。

- [ ] **Step 1: 更新 §14.1 与 §17.3#1 的 Git 易变计数（当次新鲜值）**
  重新测量并替换两个位置的计数：
  ```powershell
  (git ls-files | Measure-Object -Line).Lines                                   # 已跟踪文件数
  (git status --porcelain -uall | Select-String -Pattern '^\?\?').Count         # 未跟踪条目数
  (git status --porcelain | Select-String -Pattern '^ M').Count                 # 已修改文件数
  ```
  把 `docs/Robot_Twin_AI_完整计划说明书_v2.0.md` 中 §14.1「104 个已跟踪文件、89 个未跟踪条目、2 处已修改源码」与 §17.3 第 1 行「104 跟踪/89 未跟踪/2 修改」内的计数替换为上述实测值（104 与 2 应保持不变；未跟踪数按实测更新，并可在句末追加「（含本可移植资料包 docs/sources、docs/evidence，未入库）」）。判定：数字为当次实测；其余句子不动。

- [ ] **Step 2: 改写 §17.1 链接（附录 E 第 1 组：docs/superpowers → superpowers；第 2 组：simulation → ../simulation；第 3 组：.embeddedskills/build → evidence/，含 5 个 `.portable` 改名）**
  用 Edit 逐条按附录 E 的 old→new 精确替换链接目标字符串（Markdown 链接 `[text](target)` 的 `target`）。文件名含中文/空格/括号时按原样书写，不插入 URL 编码。判定：替换后链接目标与附录 E 完全一致；相邻文本不变。

- [ ] **Step 3: 三个被排除条目转内联代码（附录 E 第 4 组）**
  `.embeddedskills/state.json`、`.embeddedskills/config.json`、`.embeddedskills/build/project_plan_v2/deepseek_project_plan_v2_prompt.md` 三处由 Markdown 链接改为内联代码（去掉 `[`/`](...)`，保留文件名，包在反引号内），不再构成链接。判定：`](.embeddedskills/...` 不再出现在主说明书链接中；gate 1 不计这三条。

- [ ] **Step 4: 为 3 份 PDF 增加 `sources/` 链接（附录 E 第 5 组）**
  §17.1 三行 PDF 条目由 `` `文件名.pdf` `` 改为 `` [`文件名.pdf`](sources/文件名.pdf) ``，其余句子不变。判定：新增链接解析到 `docs/sources/文件名.pdf`（Task 3 已存在）。

- [ ] **Step 5: 改写 §6 状态表证据列（附录 E 第 6 组）**
  逐单元格把 `.embeddedskills/build/...`、裸文件名（`metrics.json`、`selected_route.json`、`static_pose_report.json`、`task4b4_final_offline_acceptance.md`、`task4b4_hardware_gate_runbook.md` 等）、目录引用（`.embeddedskills/build/task3-campaign-storage-metrics/` → 指向文件 `evidence/task3-campaign-storage-metrics/report.md`）改写为 `evidence/<镜像>`（含 `.portable`）。同时改 §6.2 的 `BLOCKED_duplicate_execution.md` 引用为 `evidence/...`。判定：每个单元格与附录 E 一致；`—` 单元格与其余列不动。

- [ ] **Step 6: 记录 modify_record.json**
  对每一步 Edit 记录 `{old_string, new_string, section, line_in_backup}`。判定：modify_record.json 覆盖全部改动，且 `old_string` 可在 `master_spec_backup.md` 中唯一找到。

- [ ] **Step 7: diff 校验（只允许附录 E 允许行变化）**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py diff `
    _unrelated/portable_bundle_preflight/master_spec_backup.md `
    docs/Robot_Twin_AI_完整计划说明书_v2.0.md `
    _unrelated/portable_bundle_preflight/modify_record.json `
    _unrelated/portable_bundle_preflight/diff_result.json
  ```
  判定：`diff_result.json.status == "PASS"` 且行数不变；`not_allowed` 为空。行数变化或变更行不在 modify_record 行集 → 停机条件 5，恢复 backup 后重来。

---

### Task 7: 全量验收（§9 全部 10 项 gate）

**Files:**
- 创建（git 忽略）：`_unrelated/portable_bundle_preflight/gates/*.json`、`_unrelated/portable_bundle_preflight/final_git_status.txt`
- 只读：全部交付物、主说明书、manifest

**Interfaces:**
- 输入：Task 1-6 产物。
- 产出：gate 结果（PASS/FAIL），manifest `validation` 固化，最终 manifest 哈希。

**本 Task 独立验收点：** 10 项 gate 全部 PASS；manifest 最终版 self-scan 0 命中、哈希一致；任一 FAIL 停机（条件 7）。

- [ ] **Step 1: Gate 1 — 链接全解析 + §6 证据列一致**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py links `
    _unrelated/portable_bundle_preflight/gates/gate1_links.json docs/Robot_Twin_AI_完整计划说明书_v2.0.md
  ```
  判定：`links_broken` 与 `evidence_tokens_missing` 为空（本计划加入 3 个 `sources/` 链接后 links_checked 应为 33，动态以实测为准）。`#/http/https/mailto` 不计入。

- [ ] **Step 2: Gate 2 — 目标存在且非空**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py targets _unrelated/portable_bundle_preflight/gates/gate2_targets.json
  ```
  判定：`missing` 为空。

- [ ] **Step 3: Gate 3 — 目标不被 git ignore**
  ```powershell
  $fail = 0
  Get-ChildItem -Path docs/sources,docs/evidence -Recurse -File | ForEach-Object {
    git check-ignore $_.FullName
    if ($LASTEXITCODE -eq 0) { Write-Output "IGNORED: $($_.FullName)"; $fail = 1 }
  }
  if ($fail -eq 1) { throw "GATE3 FAIL" }
  ```
  判定：无任何文件被 ignore（git check-ignore 全 exit=1）。

- [ ] **Step 4: Gate 4 — 哈希 + 脱敏一致**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py hash _unrelated/portable_bundle_preflight/gates/gate4_hash.json
  ```
  判定：`failures` 为空（source_sha256 与原件一致、portable_sha256 与磁盘一致、byte_identical 副本两哈希相等、sanitized 副本两哈希不等且 redactions 非空）。

- [ ] **Step 5: Gate 5 — 敏感信息 0 命中（全量）**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py scan `
    _unrelated/portable_bundle_preflight/gates/gate5_scan.json _unrelated/portable_bundle_preflight/classification_report.json
  ```
  范围 = `docs/sources/**` + `docs/evidence/**`（字节 + 文件名）+ `manifest.json` + 主说明书（含改写链接）+ 本计划 + 3 份 PDF（PDF 另由 Task 3 `--pdf` 探针覆盖元数据/可提取文本/内容流）。判定：`real_hits` 为空（命中若在 `classification_report.json.narrative_reviewed` 中且已复核「叙述性、无值」则不计）。任何实际敏感值命中 → 停机条件 4。

- [ ] **Step 6: Gate 6 — 无产品代码/意外文件变化**
  ```powershell
  git status --porcelain -uall | Out-File -Encoding utf8 _unrelated/portable_bundle_preflight/final_git_status.txt
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py status `
    _unrelated/portable_bundle_preflight/gates/gate6_status.json _unrelated/portable_bundle_preflight
  ```
  判定：相对 baseline 新增的 porcelain 行全部是 `?? docs/sources/...` 或 `?? docs/evidence/...`；`unexpected_added` 为空；baseline 既有条目（含 2 处已修改源码、本计划、总说明书等）全部保留；无 `docs/superpowers/plans` 下新计划以外的意外改动。

- [ ] **Step 7: Gate 7 — Git 只读**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py readonly `
    _unrelated/portable_bundle_preflight/gates/gate7_readonly.json _unrelated/portable_bundle_preflight
  ```
  判定：`head_before == head_after`（无 HEAD 变化）且 `forbidden_git_verbs` 为空（command_log.md 中无 `git add/commit/push/reset/checkout/init/branch/tag/remote`）。

- [ ] **Step 8: Gate 8 — PDF 可打开**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py pdfs _unrelated/portable_bundle_preflight/gates/gate8_pdf.json
  ```
  判定：`pdf_failures` 为空（3 份均可 pypdf 打开、页数>0）。

- [ ] **Step 9: Gate 9 — 无意外产物**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py artifacts `
    _unrelated/portable_bundle_preflight/gates/gate9_artifacts.json _unrelated/portable_bundle_preflight
  ```
  判定：`artifacts` 为空（docs/sources、docs/evidence、LOCAL_DIR 下无 `nul`/`*.tmp`/`*.log`/`__pycache__`）。

- [ ] **Step 10: Gate 10 — 分类完整性**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/verify_tool.py class `
    _unrelated/portable_bundle_preflight/gates/gate10_class.json _unrelated/portable_bundle_preflight/classification_report.json
  ```
  判定：`excluded_leaked` 为空且所有候选有明确 content_mode；`excluded_hash_only` 条目未出现在 docs/evidence 与任何链接中。

- [ ] **Step 11: 固化 manifest `validation` 并最终复核**
  把 gate 1 的 links_checked/links_ok、gate 5 的 hits=0、gate 4 的 hashes_match=true、redactions_complete=true 与 pdf_text_extraction 写入 `docs/evidence/manifest.json` 对应字段；重新校验 JSON、重扫 manifest（0 命中），并记录最终 manifest SHA-256 到 `_unrelated/portable_bundle_preflight/manifest_final_sha256.txt`。判定：10 项 gate 全 PASS 且 manifest 最终版 self-scan 0 命中。

---

### Task 8: 写执行 handoff

**Files:**
- 创建（git 忽略）：`.embeddedskills/build/v2_portable_document_bundle/handoff.md`

**Interfaces:**
- 输入：Task 1-7 的命令日志、gate 结果、manifest 摘要。
- 产出：一份如实记录执行过程与结果的 handoff。**该目录实测被 `.gitignore` 覆盖（`git check-ignore` exit=0）**，故 handoff 不可入库、不属于可移植包——必须在 handoff 中如实说明这一点，并指出可移植交付物在 `docs/sources/**`、`docs/evidence/**`（当前均未入库，等待治理 Task 的受控快照）。

**本 Task 独立验收点：** handoff 存在、内容含命令/结果/产物/未验证项、不宣布项目或 4B-4 完成、自身 self-scan 0 命中。

- [ ] **Step 1: 撰写 handoff**
  内容至少含：
  - 执行日期、<PROJECT_PYTHON> 解析结果（用占位符书写）、Git HEAD（只读）。
  - 每个 Task 实际运行的命令与 exit code（从 command_log.md 摘录）。
  - 产物清单：3 PDF（含 pages/哈希/extraction_status）、22 个证据副本（16 byte + 6 sanitized）、manifest（25 entries + excluded 1 + external N）、改写后主说明书（变更行集摘要）、gate 结果摘要（10/10 PASS）。
  - 仍未验证项：PDF 文本提取状态（若 degraded/failed）、克隆仓库后的外部解析验证（本机未做 clone 测试）、任何人工复核边界结论。
  - 明确声明：`.embeddedskills/build/v2_portable_document_bundle/` 被 git 忽略，本 handoff 不入库；`docs/sources/**`、`docs/evidence/**`、总说明书改写、本计划均未入库；**不宣布项目完成，不改变 §6 任何 Task 状态，4B-1/4B-2/4B-4 现状不变**。
  判定：写入成功；不含个人绝对路径/私网 IP/wxid/凭据（用占位符或仓库相对路径书写）。

- [ ] **Step 2: handoff 自扫**
  ```powershell
  <PROJECT_PYTHON> _unrelated/portable_bundle_preflight/scan_tool.py --scan .embeddedskills/build/v2_portable_document_bundle/handoff.md --output _unrelated/portable_bundle_preflight/handoff_scan.json
  ```
  判定：`hits[]` 为空。有实际命中 → 修正 handoff 后重扫。

---

### Task 9: 失败与回滚（精确步骤）

**触发条件：** 任一停机条件命中、任一 gate FAIL、或用户要求中止/回滚。**只允许以下精确操作；禁止广泛删除。**

**Files（回滚时）：**
- 删除：`docs/sources/**`、`docs/evidence/**` 中**仅 preflight_manifest.json `created` 列表所列**文件与随附空目录
- 恢复：`docs/Robot_Twin_AI_完整计划说明书_v2.0.md` ← `master_spec_backup.md`
- 保留：`.embeddedskills/**`、外部 PDF 原件、产品代码、本计划、`_unrelated/portable_bundle_preflight/**`（供复盘）

**本 Task 独立验收点：** 回滚后 `git status --porcelain -uall` 与 baseline 一致（除既有脏状态外无新增差异）；无任何源文件/原件被删；未执行任何 git 写命令。

- [ ] **Step 1: 停机并记录失败说明**
  在 command_log.md 追加停机原因（停机条件编号、gate 名、现场现象）。判定：记录完成。

- [ ] **Step 2: 只删除 created 列表内副本**
  ```powershell
  $created = (Get-Content _unrelated/portable_bundle_preflight/preflight_manifest.json | ConvertFrom-Json).created
  foreach ($p in $created) {
    if (Test-Path $p) {
      # 先确认该路径确实由本任务创建（preflight 记录 + 修改时间晚于执行开始）
      Remove-Item -LiteralPath $p -Force -Confirm:$false
    }
  }
  ```
  删除后清理仅剩本任务空目录的 `docs/sources/`、`docs/evidence/` 空目录（`Remove-Item` 空目录需先确认无残留）。**绝不删除** `preflight_manifest.json created` 列表之外的任何文件；**绝不**用 `Remove-Item -Recurse` 对整个 `docs/evidence` 做泛化删除。判定：删除集合 == created 列表；非本任务文件保留。

- [ ] **Step 3: 恢复总说明书**
  ```powershell
  Copy-Item -LiteralPath _unrelated/portable_bundle_preflight/master_spec_backup.md -Destination "docs/Robot_Twin_AI_完整计划说明书_v2.0.md"
  ```
  判定：恢复后文件与 backup 字节一致（`Get-FileHash` 相等）。

- [ ] **Step 4: 回滚后复核**
  ```powershell
  git status --porcelain -uall | Out-File -Encoding utf8 _unrelated/portable_bundle_preflight/post_rollback_status.txt
  ```
  判定：post_rollback_status.txt 与 baseline_git_status.txt 一致（除本计划、总说明书、`docs/superpowers/specs/` 等既有无入库文档外无新增差异；docs/sources、docs/evidence 不再出现）。若仍不一致 → 停机并交人工处置，不继续删除。

---

## 附录 A：scan_tool.py（写入 `_unrelated/portable_bundle_preflight/scan_tool.py`）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portable Document Bundle — sensitive-content scanner.
Usage:
  scan_tool.py --selftest
  scan_tool.py --scan <path>... --output <out.json>
  scan_tool.py --pdf <path> --output <out.json>
Hits are reported as {category,line,column} only; matched values are never emitted.
Run as a script (python scan_tool.py), never imported, so no __pycache__ is created.
"""
import base64, json, os, re, sys, zlib
sys.dont_write_bytecode = True

CATEGORIES = [
    ("user_home_abs_path", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]Users[\\/](?!<)[^\s\"'<>|?*]{0,}")),
    ("drive_abs_path", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?!<)[^\s\"'<>|?*]{0,}")),
    ("wechat_download_path", re.compile(r"(?i)wechat[\\/ _-]?files")),
    ("wxid", re.compile(r"wxid_[A-Za-z0-9_]+")),
    ("private_ip", re.compile(r"\b(?:192\.168\.|10\.|172\.(?:1[6-9]|2[0-9]|3[01])\.)\d{1,3}\.\d{1,3}\b")),
    ("device_serial", re.compile(r"(?i)(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b|serial\s*[:=]\s*\S+|ST[0-9A-F]{8,}")),
    ("ssid", re.compile(r"(?i)(?:ssid|wifi_ssid|wlan_ssid)\s*[:=]\s*\S+")),
    ("credential_value", re.compile(r"(?i)(?:api[_-]?key|token|secret|access[_-]?key|authorization|bearer)\s*[:=]\s*(?:\S+|\"[^\"]*\")")),
    ("password_value", re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*(?:\S+|\"[^\"]*\")")),
]

SAFE_EXAMPLES = [
    "192.168.x.x", "10.x.x.x", "wxid 标识", "password 无实际值", "token 未落盘",
    "<WORKSPACE_ROOT>", "<ESP_HOST>", "<USER_PROFILE>", "<KEIL_ROOT>", "盘符:/keil 形态",
]

def scan_text(text):
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for cat, rx in CATEGORIES:
            for m in rx.finditer(line):
                hits.append({"category": cat, "line": lineno, "column": m.start() + 1})
    return hits

def scan_bytes(data):
    hits = scan_text(data.decode("utf-8", errors="replace"))
    raw = data.decode("latin-1", errors="replace")
    for cat, rx in CATEGORIES:
        for m in rx.finditer(raw):
            hits.append({"category": cat, "line": 0, "column": m.start() + 1})
    seen, out = set(), []
    for h in hits:
        k = (h["category"], h["line"], h["column"])
        if k not in seen:
            seen.add(k); out.append(h)
    return out

def scan_name(name):
    hits = []
    for cat, rx in CATEGORIES:
        for m in rx.finditer(name):
            hits.append({"category": cat, "line": -1, "column": m.start() + 1})
    return hits

def _decode_streams(path):
    raw = open(path, "rb").read()
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        data = m.group(1)
        try:
            data = zlib.decompress(data)
        except Exception:
            pass
        for enc in ("utf-16-be", "utf-8"):
            try:
                out.append(data.decode(enc, errors="replace")); break
            except Exception:
                continue
    try:
        a85 = base64.a85decode(raw, adobe=True)
        out.append(a85.decode("utf-16-be", errors="replace"))
    except Exception:
        pass
    return "\n".join(out)

def pdf_probe(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = len(reader.pages)
    meta = {str(k): str(v) for k, v in (reader.metadata.items() if reader.metadata else {})}
    text = ""
    for p in reader.pages:
        try:
            text += (p.extract_text() or "") + "\n"
        except Exception:
            pass
    stream_text = _decode_streams(path)
    if len(text.strip()) >= 100:
        status = "ok"
    elif len(stream_text.strip()) > 0:
        status = "degraded_binary_scan"
    else:
        status = "failed_binary_scan_human_review"
    return {"pages": pages, "metadata": meta, "extraction_status": status,
            "text": text, "stream_text": stream_text}

def selftest():
    fails = []
    fixtures = {
        "user_home_abs_path": "C" + ":" + "/Users/zhang/.codex/x",
        "drive_abs_path": "G" + ":" + "/data/out/x",
        "wechat_download_path": "WeChat " + "Files/x.pdf",
        "wxid": "wxid_" + "abc123",
        "private_ip": "192.168" + ".1.5",
        "device_serial": "ST" + "123456789012345",
        "ssid": "ssid" + "=MyWiFi",
        "credential_value": "api" + "_key=" + "abc123",
        "password_value": "pass" + "word=" + "hunter2",
    }
    for cat, rx in CATEGORIES:
        if not rx.search(fixtures[cat]):
            fails.append("no-fire:" + cat)
    for s in SAFE_EXAMPLES:
        for cat, rx in CATEGORIES:
            if rx.search(s):
                fails.append("false-fire:%s@%s" % (cat, s))
    print(json.dumps({"selftest": "ok" if not fails else "fail", "fails": fails}, ensure_ascii=False))
    return 0 if not fails else 1

def main(argv):
    if "--selftest" in argv:
        return selftest()
    if "--pdf" in argv:
        path = argv[argv.index("--pdf") + 1]
        info = pdf_probe(path)
        hits = scan_bytes(open(path, "rb").read()) + scan_name(os.path.basename(path))
        hits += scan_text(json.dumps(info["metadata"], ensure_ascii=False))
        out = {"path": path, "pages": info["pages"], "extraction_status": info["extraction_status"],
               "metadata": info["metadata"], "hits": hits, "text_len": len(info["text"]),
               "stream_text_len": len(info["stream_text"])}
    elif "--scan" in argv:
        i = argv.index("--scan")
        paths = argv[i + 1:]
        if "--output" in paths:
            paths = paths[:paths.index("--output")]
        files = []
        for p in paths:
            if os.path.isdir(p):
                for root, _dirs, names in os.walk(p):
                    for n in names:
                        files.append(os.path.join(root, n))
            else:
                files.append(p)
        out = {"files": []}
        for f in files:
            try:
                data = open(f, "rb").read()
            except OSError as e:
                out["files"].append({"path": f, "error": str(e), "hits": []}); continue
            hits = scan_name(os.path.basename(f)) + scan_bytes(data)
            out["files"].append({"path": f, "size": len(data), "hits": hits})
    else:
        print("usage: scan_tool.py --selftest | --scan <paths> --output out.json | --pdf <pdf> --output out.json", file=sys.stderr)
        return 2
    if "--output" in argv:
        op = argv[argv.index("--output") + 1]
        os.makedirs(os.path.dirname(op) or ".", exist_ok=True)
        with open(op, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(out, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

## 附录 B：sanitize_tool.py（写入 `_unrelated/portable_bundle_preflight/sanitize_tool.py`）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portable Document Bundle — sanitized-copy generator.
Usage:
  sanitize_tool.py <src> <dst> <redactions.json>
redactions.json = [{ "kind": "regex|literal|json_field", "pattern": <regex|literal|field>,
                     "replacement": <str>, "flags": "i", "field": "source", "value": <str> }]
Applied in order; dst is written UTF-8 (no BOM) with \n newlines. Only new copies in
docs/evidence are ever touched; src is opened read-only.
"""
import json, os, re, sys
sys.dont_write_bytecode = True

def main(argv):
    if len(argv) < 3:
        print("usage: sanitize_tool.py <src> <dst> <redactions.json>", file=sys.stderr)
        return 2
    src, dst, redfile = argv[0], argv[1], argv[2]
    redactions = json.load(open(redfile, encoding="utf-8"))
    with open(src, "rb") as fh:
        text = fh.read().decode("utf-8", errors="surrogateescape")
    for r in redactions:
        kind = r.get("kind", "regex")
        if kind == "json_field":
            obj = json.loads(text)
            obj[r["field"]] = r["value"]
            text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        elif kind == "literal":
            text = text.replace(r["pattern"], r["replacement"])
        else:
            flags = re.IGNORECASE if "i" in r.get("flags", "") else 0
            text = re.sub(r["pattern"], r["replacement"], text, flags=flags)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(json.dumps({"src": src, "dst": dst, "applied": len(redactions)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

## 附录 C：verify_tool.py（写入 `_unrelated/portable_bundle_preflight/verify_tool.py`）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portable Document Bundle — deterministic read-only acceptance checks.
Usage (from repository root):
  verify_tool.py selftest
  verify_tool.py links <out.json> <spec_rel>
  verify_tool.py hash <out.json>
  verify_tool.py targets <out.json>
  verify_tool.py pdfs <out.json>
  verify_tool.py class <out.json> <classification_rel>
  verify_tool.py scan <out.json> <classification_rel>
  verify_tool.py status <out.json> <preflight_dir>
  verify_tool.py readonly <out.json> <preflight_dir>
  verify_tool.py artifacts <out.json> <preflight_dir>
  verify_tool.py diff <backup.md> <current.md> <modify_record.json> <out.json>
Exit 0 iff the check PASSes. Read-only only.
"""
import hashlib, json, os, re, subprocess, sys
sys.dont_write_bytecode = True

def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def _resolve(root, rel):
    return os.path.normpath(os.path.join(root, rel))

def _dump(out, obj):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump(obj, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def _links(out, spec):
    text = open(spec, encoding="utf-8").read()
    links = [m.group(1) for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", text)
             if not m.group(1).startswith(("#", "http:", "https:", "mailto:"))]
    base = os.path.dirname(spec)
    broken = [l for l in links if not os.path.exists(_resolve(base, l))]
    ev_broken = []
    for tok in re.findall(r"evidence/[^)\s，、；（）()]+", text):
        tok = tok.rstrip("，、；。).")
        if not os.path.exists(_resolve(base, tok)):
            ev_broken.append(tok)
    ok = not broken and not ev_broken
    _dump(out, {"status": "PASS" if ok else "FAIL", "links_checked": len(links),
                "links_broken": broken, "evidence_tokens_missing": ev_broken})
    return 0 if ok else 1

def _hash(out):
    manifest = json.load(open("docs/evidence/manifest.json", encoding="utf-8"))
    fails = []
    for e in manifest["entries"]:
        p = e["rel_path"]
        if not os.path.exists(p):
            fails.append(e["id"] + ":missing"); continue
        if _sha(p) != e["portable_sha256"]:
            fails.append(e["id"] + ":portable_disk_mismatch")
        if e.get("origin_repo_path") and os.path.exists(e["origin_repo_path"]):
            if _sha(e["origin_repo_path"]) != e["source_sha256"]:
                fails.append(e["id"] + ":source_changed")
        if e["content_mode"] == "byte_identical" and e["portable_sha256"] != e["source_sha256"]:
            fails.append(e["id"] + ":byte_not_identical")
        if e["content_mode"] == "sanitized_copy":
            if e["portable_sha256"] == e["source_sha256"]:
                fails.append(e["id"] + ":sanitized_impersonates_byte_identical")
            if not e.get("redactions"):
                fails.append(e["id"] + ":no_redactions")
    ok = not fails
    _dump(out, {"status": "PASS" if ok else "FAIL", "failures": fails})
    return 0 if ok else 1

def _targets(out):
    manifest = json.load(open("docs/evidence/manifest.json", encoding="utf-8"))
    missing = [e["rel_path"] for e in manifest["entries"]
               if not os.path.exists(e["rel_path"]) or os.path.getsize(e["rel_path"]) <= 0]
    ok = not missing
    _dump(out, {"status": "PASS" if ok else "FAIL", "missing": missing})
    return 0 if ok else 1

def _pdfs(out):
    from pypdf import PdfReader
    fails = []
    if os.path.isdir("docs/sources"):
        for n in os.listdir("docs/sources"):
            if not n.lower().endswith(".pdf"):
                continue
            p = os.path.join("docs/sources", n)
            try:
                if len(PdfReader(p).pages) <= 0:
                    fails.append(n + ":zero_pages")
            except Exception as exc:
                fails.append(n + ":" + str(exc))
    ok = not fails
    _dump(out, {"status": "PASS" if ok else "FAIL", "pdf_failures": fails})
    return 0 if ok else 1

def _class(out, classification):
    cls = json.load(open(classification, encoding="utf-8"))
    ok = all(c.get("content_mode") in ("byte_identical", "sanitized_copy", "excluded_hash_only")
             for c in cls["candidates"])
    leaked = []
    for c in cls["candidates"]:
        if c.get("content_mode") == "excluded_hash_only":
            base = c.get("logical_name") or os.path.basename(c.get("origin_repo_path", ""))
            if base and os.path.exists(os.path.join("docs/evidence", base)):
                leaked.append(base)
    ok = ok and not leaked
    _dump(out, {"status": "PASS" if ok else "FAIL", "excluded_leaked": leaked})
    return 0 if ok else 1

def _scan(out, classification):
    scan_tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan_tool.py")
    raw = out.replace(".json", "_raw.json")
    targets = ["docs/sources", "docs/evidence", "docs/evidence/manifest.json",
               "docs/Robot_Twin_AI_完整计划说明书_v2.0.md",
               "docs/superpowers/plans/2026-08-02-robot-twin-portable-document-bundle.md"]
    subprocess.run([sys.executable, scan_tool, "--scan"] + targets + ["--output", raw],
                   check=True)
    scan = json.load(open(raw, encoding="utf-8"))
    cls = json.load(open(classification, encoding="utf-8"))
    reviewed = {(h["file"].replace("\\", "/"), h["category"], h["line"])
                for h in cls.get("narrative_reviewed", [])}
    real = []
    total = 0
    for f in scan["files"]:
        total += len(f["hits"])
        for h in f["hits"]:
            key = (f["path"].replace("\\", "/"), h["category"], h["line"])
            if key not in reviewed:
                real.append({"path": f["path"], "category": h["category"], "line": h["line"]})
    ok = not real
    _dump(out, {"status": "PASS" if ok else "FAIL", "real_hits": real[:50], "total_raw_hits": total})
    return 0 if ok else 1

def _status(out, pre):
    base = set(open(os.path.join(pre, "baseline_git_status.txt"), encoding="utf-8").read().splitlines())
    r = subprocess.run(["git", "status", "--porcelain", "-uall"], capture_output=True, text=True)
    final = set(r.stdout.splitlines())
    added = sorted(final - base)
    bad = [ln for ln in added if not (ln.startswith("?? docs/sources/") or ln.startswith("?? docs/evidence/"))]
    ok = not bad
    _dump(out, {"status": "PASS" if ok else "FAIL", "unexpected_added": bad, "added_count": len(added)})
    return 0 if ok else 1

def _readonly(out, pre):
    pre_manifest = json.load(open(os.path.join(pre, "preflight_manifest.json"), encoding="utf-8"))
    hb = pre_manifest["baseline"]["head"]
    ha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    log = open(os.path.join(pre, "command_log.md"), encoding="utf-8").read()
    forbidden = re.findall(r"git\s+(add|commit|push|reset|checkout|init|branch|tag|remote)\b", log)
    ok = (hb == ha) and not forbidden
    _dump(out, {"status": "PASS" if ok else "FAIL", "head_before": hb, "head_after": ha,
                "forbidden_git_verbs": forbidden})
    return 0 if ok else 1

def _artifacts(out, pre):
    bad = []
    for d in ("docs/sources", "docs/evidence", pre):
        if not os.path.isdir(d):
            continue
        for dirpath, dirnames, filenames in os.walk(d):
            for dn in dirnames:
                if dn == "__pycache__":
                    bad.append(os.path.join(dirpath, dn))
            for fn in filenames:
                if fn == "nul" or fn.endswith((".tmp", ".log")):
                    bad.append(os.path.join(dirpath, fn))
    ok = not bad
    _dump(out, {"status": "PASS" if ok else "FAIL", "artifacts": bad})
    return 0 if ok else 1

def _diff(out, backup, current, record):
    bk = open(backup, encoding="utf-8").read().splitlines()
    cur = open(current, encoding="utf-8").read().splitlines()
    rec = json.load(open(record, encoding="utf-8"))
    allowed = {r["line_in_backup"] for r in rec}
    if len(bk) != len(cur):
        _dump(out, {"status": "FAIL", "reason": "line_count_changed",
                    "backup_lines": len(bk), "current_lines": len(cur)})
        return 1
    changed = [i for i, (a, b) in enumerate(zip(bk, cur), 1) if a != b]
    bad = [ln for ln in changed if ln not in allowed]
    ok = not bad
    _dump(out, {"status": "PASS" if ok else "FAIL", "changed_lines": changed, "not_allowed": bad})
    return 0 if ok else 1

def selftest():
    import tempfile
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "docs/superpowers"), exist_ok=True)
    open(os.path.join(d, "docs/superpowers/t1.md"), "w").write("x")
    open(os.path.join(d, "docs/spec.md"), "w", encoding="utf-8").write(
        "[ok](superpowers/t1.md)\n[bad](nope.md)\n")
    out = os.path.join(d, "out.json")
    rc = _links(out, os.path.join(d, "docs/spec.md"))
    res = json.load(open(out, encoding="utf-8"))
    assert res["links_checked"] == 2, res
    assert res["status"] == "FAIL" and res["links_broken"] == ["nope.md"], res
    print("verify_tool selftest ok")
    return 0

def main(argv):
    if not argv:
        print("usage: verify_tool.py <subcommand> ...", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "selftest":
        return selftest()
    if cmd == "links":
        return _links(rest[0], rest[1])
    if cmd == "hash":
        return _hash(rest[0])
    if cmd == "targets":
        return _targets(rest[0])
    if cmd == "pdfs":
        return _pdfs(rest[0])
    if cmd == "class":
        return _class(rest[0], rest[1])
    if cmd == "scan":
        return _scan(rest[0], rest[1])
    if cmd == "status":
        return _status(rest[0], rest[1])
    if cmd == "readonly":
        return _readonly(rest[0], rest[1])
    if cmd == "artifacts":
        return _artifacts(rest[0], rest[1])
    if cmd == "diff":
        return _diff(rest[0], rest[1], rest[2], rest[3])
    print("unknown subcommand: " + cmd, file=sys.stderr)
    return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

## 附录 D：证据目标清单与脱敏表

**byte_identical（16，复制到 `docs/evidence/<镜像>` 保留原名）**：`task2b-motor-register-diag/report.md`、`task3-campaign-storage-metrics/report.md`、`task4a-digital-twin-audit/report.md`、`v1_task4b1/gate0_report.json`、`v1_task4b2/handoff.md`、`v1_task4b2_c1_open_route/handoff.md`、`v1_task4b2_c1_open_route/metrics.json`、`v1_task4b2_c1_open_route/route_selection.json`、`v1_task4b3/handoff.md`、`v1_task4b3/static_pose_report.json`、`v1_task4b4_fix/BLOCKED_duplicate_execution.md`、`v1_task4b4_fix/task4b4_final_offline_acceptance.md`、`v1_task4b_offline_rework/final_report.md`、`v1_task4b_reacceptance/4b1/gate0_report.json`、`v1_task4b_reacceptance/4b2/handoff.md`、`v1_task4b_reacceptance/4bd/gate_report.json`。

**sanitized_copy（6，`.portable.` 中缀；副本名与占位符见下表）**：

| 源（相对 `.embeddedskills/build/`） | 目标（`docs/evidence/` 下） | 命中类别（扫描确认） | 替换占位符 / 规则 |
|---|---|---|---|
| `v1_task4b0/handoff.md` | `v1_task4b0/handoff.portable.md` | Python 解释器绝对路径（盘符开头的 `python.exe` 路径） | → `<PYTHON_INTERPRETER>` |
| `v1_task4b1/handoff.md` | `v1_task4b1/handoff.portable.md` | 工作区根绝对前缀（命令 outdir 参数） | 工作区根前缀 → `<WORKSPACE_ROOT>`，保留仓库相对剩余 |
| `v1_task4b2_c1_open_route/selected_route.json` | `v1_task4b2_c1_open_route/selected_route.portable.json` | `source` 字段为本机绝对路径 | → 相对逻辑标识 `v1_task4b2/track_bare.png`（kind=json_field） |
| `v1_task4b4_fix/handoff.md` | `v1_task4b4_fix/handoff.portable.md` | Keil 工具链根绝对路径（盘符开头的 keil 目录） | → `<KEIL_ROOT>` |
| `v1_task4b4_fix/task4b4_hardware_gate_runbook.md` | `v1_task4b4_fix/task4b4_hardware_gate_runbook.portable.md` | 私网 IP（`192.168.*` / `10.*` / `172.16-31.*`）；Keil 工具链根绝对路径 | IP → `<ESP_HOST>`；keil → `<KEIL_ROOT>` |
| `v1_task4bd/handoff.md` | `v1_task4bd/handoff.portable.md` | 用户主目录绝对路径；本地代理记忆路径（`.codex` / `.claude` 形态） | 主目录前缀 → `<USER_PROFILE>`；记忆路径 → `<LOCAL_AGENT_MEMORY>` |

**excluded_hash_only（1，不复制、不链接）**：`project_plan_v2/deepseek_project_plan_v2_prompt.md`。

实际替换值由现场扫描命中确定；`redactions/<slug>.json`（git 忽略）可含运行时值，manifest/报告仅记 `{category, location, placeholder}`。

## 附录 E：主说明书允许变更行映射表

改写仅限以下行集；其余行字节不变、行数不变。`old → new` 中 `.embeddedskills/build/<子路径>` 简写为 `E/<子路径>`。

1. **§17.1 权威 Markdown 链接（11 条）**：`docs/superpowers/<p>` → `superpowers/<p>`（plans 2026-07-30 charter、specs 2026-07-28、specs 2026-07-29、plans 2026-07-29、specs 2026-08-02 C1、plans 2026-08-02 C1、specs 2026-08-01 reacceptance、plans 2026-08-01 reacceptance、AGENTS.md、task1-final-acceptance.md、task2a-final-acceptance.md）。
2. **§17.1 simulation 链接（2 条）**：`simulation/digital_twin/<p>` → `../simulation/digital_twin/<p>`（OPEN_SOURCE_REFACTOR_REPORT.md、README.md）。
3. **§17.1 证据链接（17 条，相对 `.embeddedskills/build/`）**：byte_identical 12 条 → `evidence/<镜像>`（task2b report、task3 report、task4a report、v1_task4b2 handoff、v1_task4b2_c1_open_route handoff/metrics、v1_task4b3 handoff、v1_task4b4_fix BLOCKED、v1_task4b_offline_rework final_report、v1_task4b_reacceptance 4b1/4b2/4bd）；sanitized 5 条 → `evidence/<原名>.portable.<ext>`（v1_task4bd handoff、v1_task4b4_fix handoff、v1_task4b2_c1_open_route selected_route、v1_task4b1 handoff、v1_task4b0 handoff）。
4. **§17.1 内联转换（3 条）**：`[`.embeddedskills/state.json`](...)` → `` `.embeddedskills/state.json` ``；同 `config.json`；`[本任务提示词副本](.embeddedskills/build/project_plan_v2/deepseek_project_plan_v2_prompt.md)` → 内联代码。
5. **§17.1 PDF 链接（3 条，新增）**：`` `文件名.pdf` `` → `` [`文件名.pdf`](sources/文件名.pdf) ``（3 份 PDF 行）。
6. **§6 状态表证据列（11 行）**：Task 1/2A 单元格 `docs/superpowers/...` → `superpowers/...`；Task 2B/3/4A/4B-D/4B-0/4B-1/4B-2/4B-3/4B-4 单元格 `.embeddedskills/build/...` 与裸文件名（含 Task 3 目录引用改指 `evidence/task3-campaign-storage-metrics/report.md`）→ `evidence/<镜像>`（含 `.portable`）。**§6.2** 的 `BLOCKED_duplicate_execution.md` 引用 → `evidence/v1_task4b4_fix/BLOCKED_duplicate_execution.md`。
7. **Git 易变计数（2 处）**：§14.1「104 个已跟踪文件、89 个未跟踪条目、2 处已修改源码」与 §17.3 第 1 行「104 跟踪/89 未跟踪/2 修改」→ 按 Task 6 Step 1 实测值替换（104 与 2 应不变；未跟踪数按实测）。

**明确不改**：§17.3 表内 code-span 引用（历史叙述，非链接）、版本号与 §17.5 变更记录（超出本任务允许行集，由后续治理 Task 处理）、§1.1/§14.3 等 prose 路径提及、任何事实/数字（除上述易变计数）/状态/章节号。

## Self-review checklist

- 设计全覆盖：Goal/Architecture/Stack/Constraints；§2 目录树、§3 排除、§4 PDF、§5 分类、§6 manifest schema、§7 复制语义、§8 链接、§9 十 gate、§10 回滚、§11 阶段与停机条件均已落为可执行步骤。
- 无占位性任务：每个 Step 有精确路径、命令、成功/失败判定、停机条件；参数占位符（`<PROJECT_PYTHON>`/`<PDF_SOURCE_n>`）有明确解析规则；无 TODO/TBD/「自行处理」。
- 无敏感值：本计划不含个人绝对路径、私网 IP 实际值、wxid 实际值、密码/密钥/token 值；占位符一律尖括号；redaction 记录只记类别/位置/占位符。
- 类型/manifest 字段一致：manifest `entries`/`excluded_hash_only`/`external_or_regenerable`/`validation`/`sensitive_scan` 字段名与设计 §6 一致；`content_mode` 三值贯穿 §2/§5/§6/§7/§9。
- 无 Git 写命令：本计划命令仅 `git status/check-ignore/rev-parse/branch` 只读核对；gate 7 显式审计。
- 只允许创建/修改本计划文件；执行所需中间产物全部落在 git 忽略的 `_unrelated/portable_bundle_preflight/`。
