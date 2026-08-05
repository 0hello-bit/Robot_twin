# Robot Twin AI 可移植资料包设计（Portable Document Bundle Design）

- **任务性质**：纯设计。本文件只规定“把项目必要文件复制进工作区，形成可移植 Git 仓库的资料层”的方案；本轮**不执行**任何文件复制、链接改写、Git 写操作或硬件动作。
- **日期**：2026-08-02
- **修订记录**：v2.0 返工（同日）。依据独立 Codex 审核结论，废除“证据必须字节一致且证据不参与敏感扫描”的旧规则；引入三种证据内容模式（byte_identical / sanitized_copy / excluded_hash_only），并把敏感扫描扩展到全部入包内容与 PDF。已批准决策（state.json/config.json 排除、三份 PDF 复制进 docs/sources、链接一律改向 docs/evidence 可移植证据、外部 PDF 路径仅限执行提示上下文）保持不变。
- **安全语义（已批准）**：复制必要资料、保留原件；绝不删除微信目录或任何历史证据原件；任何“移动”语义在本任务中一律按“复制 + 保留原件”执行。脱敏只发生在 `docs/evidence/` 下本任务**新增的可移植副本**上，源证据原件只读、永不改写。
- **授权边界**：本设计仅允许执行阶段做三件事——文件复制（含脱敏副本生成）、主说明书 Markdown 链接与 §6 证据列更新、验收。禁止修改产品代码、固件、测试、Keil 工程、数字孪生实现、旧历史证据原件；禁止任何 Git 写操作；禁止连接/控制硬件。
- **隐私边界**：本设计文件本身不写入任何个人绝对路径、账号标识、密码/密钥值、私网 IP 实际值、wxid 实际值。敏感内容只用“模式类别名”与泛化示例（如 `C:\Users\<用户名>\...`、`192.168.x.x`）描述。

---

## 1. 目标与非目标

### 1.1 目标

1. 在仓库内建立 `docs/sources/`（3 份原始 Robot Twin AI PDF 的副本）与 `docs/evidence/`（总说明书实际引用的权威 handoff/报告/JSON 的**可移植副本** + manifest）。证据副本按 §5 分类为两种形态之一：`byte_identical`（与原件字节一致）或 `sanitized_copy`（脱敏可移植副本，原件只读保留）。
2. 让主说明书 `docs/Robot_Twin_AI_完整计划说明书_v2.0.md` 内全部 Markdown 链接在本机 `docs/` 目录与未来任何 clone 出的仓库中**都能真实解析**；所有指向证据的链接一律指向 `docs/evidence/` 下的可移植副本（含 `.portable` 脱敏副本），不指向任何被排除条目。
3. 提供 `docs/evidence/manifest.json`：记录每个条目的相对路径、用途、大小、内容模式、源哈希、可移植副本哈希、脱敏记录；**不记录个人绝对路径、账号标识、密码/密钥值、原始敏感值**。未复制但可再生成或仅本地历史的条目记入 `excluded_hash_only[]` 或 `external_or_regenerable[]`。
4. 用只读验收 gate 证明：链接全解析、目标存在且不被 git ignore、哈希一致（含脱敏副本与其 redaction 记录）、**全部入包内容（含 3 份 PDF）敏感扫描 0 命中**、无产品代码变化、Git 只读、PDF 可打开。
5. 提供可回滚的最小足迹：回滚仅删除本任务新增副本（含脱敏副本）、恢复本任务改写的文档，依赖执行前 manifest，禁止广泛删除。

### 1.2 非目标

1. **不执行 Git 写操作**（无 add/commit/push/reset/checkout/init/branch/tag/remote）。
2. **不执行文件复制/移动/删除/链接改写**——本设计仅描述，执行需另一次独立、经用户确认的执行任务。
3. **不修改产品代码**：`simulation/digital_twin/` 下的 `.py`/测试/配置、固件源码、Keil 工程、Host C 一律不动（含 `test_v1_twin_track_map.py`、`v1_twin_track_map.py` 两处已修改文件，保持现状）。
4. **不复制**缓存、二进制构建产物、重复日志、临时文件、原始海量数据、大体积图片/npy/遥测流（细则见 §3）。
5. **不修改任何源证据原件**：`.embeddedskills/` 与外部 PDF 一律只读；脱敏只发生在 `docs/evidence/` 下本任务新增的副本上。任何“净化/改写”都不落到原件，原件字节永不改变、永不删除。
6. **不宣布项目完成**：本任务不修改任何 Task 状态，不认定任何验收结果有效；§6 权威规则（最新、更严格、新鲜 Gate）不变。
7. **不做去重/合并/归档**：`.embeddedskills/` 目录保留原样，不搬入仓库；原 `docs/sources`/`docs/evidence` 之外的任何目录不被触碰。
8. **不连接硬件、不执行构建/烧录/网络扫描**：执行阶段所有命令只读（`git status`/`git check-ignore`/`git log` 属只读核对）。

---

## 2. 目录结构

目标布局（`工作区根` 以下；只展示本任务新增部分，其余目录不动）：

```text
工作区根/
├── docs/
│   ├── Robot_Twin_AI_完整计划说明书_v2.0.md   # 主说明书（链接改写，见 §8；其余内容不动）
│   ├── superpowers/                            # 既有，仅链接被引用，不新增文件
│   ├── sources/                                # 本任务新建：3 份原始 PDF 副本（byte_identical）
│   │   ├── Robot_Twin_AI_具身智能机器人自主优化平台规划文档.pdf
│   │   ├── Robot_Twin_AI_V1.0_软件架构设计文档.pdf
│   │   └── Robot_Twin_AI_V1.0_开发任务拆解与里程碑文档.pdf
│   └── evidence/                               # 本任务新建：权威证据可移植副本
│       ├── manifest.json                       # 清单（schema 见 §6）
│       ├── conflict_report.json                # 仅当发生哈希冲突时生成（见 §7）
│       ├── task2b-motor-register-diag/report.md              # byte_identical
│       ├── task3-campaign-storage-metrics/report.md          # byte_identical
│       ├── task4a-digital-twin-audit/report.md                # byte_identical
│       ├── v1_task4b0/handoff.portable.md       # sanitized_copy（Python 解释器绝对路径→占位符）
│       ├── v1_task4b1/handoff.portable.md       # sanitized_copy（outdir 绝对路径→占位符）
│       ├── v1_task4b1/gate0_report.json                        # byte_identical
│       ├── v1_task4b2/handoff.md                                # byte_identical
│       ├── v1_task4b2_c1_open_route/handoff.md                  # byte_identical
│       ├── v1_task4b2_c1_open_route/metrics.json                # byte_identical
│       ├── v1_task4b2_c1_open_route/selected_route.portable.json # sanitized_copy（source→相对逻辑标识）
│       ├── v1_task4b2_c1_open_route/route_selection.json        # byte_identical
│       ├── v1_task4b3/handoff.md                                # byte_identical
│       ├── v1_task4b3/static_pose_report.json                   # byte_identical
│       ├── v1_task4b4_fix/handoff.portable.md    # sanitized_copy（F:/keil→占位符）
│       ├── v1_task4b4_fix/BLOCKED_duplicate_execution.md        # byte_identical
│       ├── v1_task4b4_fix/task4b4_final_offline_acceptance.md   # byte_identical
│       ├── v1_task4b4_fix/task4b4_hardware_gate_runbook.portable.md # sanitized_copy（192.168.x.x→<ESP_HOST>）
│       ├── v1_task4b_offline_rework/final_report.md             # byte_identical
│       ├── v1_task4b_reacceptance/4b1/gate0_report.json         # byte_identical
│       ├── v1_task4b_reacceptance/4b2/handoff.md                # byte_identical
│       ├── v1_task4b_reacceptance/4bd/gate_report.json          # byte_identical
│       └── v1_task4bd/handoff.portable.md       # sanitized_copy（用户目录/本地记忆路径→占位符）
└── .embeddedskills/        # 既有，原样保留（原件只读，永不删除）
```

要点：

- `docs/evidence/` 采用**源相对镜像**布局：`docs/evidence/<子路径>` 一一对应 `.embeddedskills/build/<子路径>`（去掉 `.embeddedskills/build/` 前缀）。
- **脱敏副本命名**：`sanitized_copy` 条目统一用 `.portable.` 文件名中缀（如 `selected_route.portable.json`、`handoff.portable.md`），与源文件名区分；`byte_identical` 条目保留原名。该命名是**刻意**的：使“非字节一致”形态自解释、可被 §9 gate 4 机器校验，防止脱敏副本冒充字节一致。主说明书链接、§6 证据列、manifest 的 `rel_path` 一律指向 `.portable` 名。
- **排除项不入目录**：`project_plan_v2/deepseek_project_plan_v2_prompt.md`（执行提示词，含工作区/微信路径与 wxid）不在 `docs/evidence/` 中出现——按 §5 归 `excluded_hash_only`，仅记入 manifest，不复制、不链接。
- `state.json`、`config.json` **不复制**（含局域网 IP 与机器相关状态，属可再生产物，见 §5.5、§6.4）。
- 目录名用 ASCII 小写；文件名保留原件中文名（PDF 与部分证据），不改名。

---

## 3. “必要文件”判定规则与明确排除规则

### 3.1 判定规则（必要条件，缺一不可）

某文件 `F` 进入**候选集**，必须同时满足：

1. **被引用**：`F` 是主说明书 §17.1 的 Markdown 链接目标，**或**出现在 §6 状态表“证据路径”列，**或**在 §6.2/§17.3 中被明确点名引用（如 `route_selection.json`、`v1_task4b1/gate0_report.json`）。
2. **是权威/历史证据**：handoff、gate/验收报告、关键标定或契约 JSON、审计/诊断报告。按 §6.2 权威规则，同一 Task 的“当前权威”与“被点名保留的历史记录”**都**纳入候选（历史记录在 manifest 的 `purpose` 中标注）。
3. **体积/类型允许**：文本类（`.md`/`.json`/`.txt`）或用户批准纳入的原始 PDF。小体积（本设计预计单个 < 1 MiB）。
4. **在磁盘上存在**：执行阶段预检确认源文件存在且可读；缺失即停机（§11）。

**候选集不等于复制集**。进入候选集后，每个候选还须经 §5.3 的 content_mode 分类：只有 `byte_identical` 或 `sanitized_copy` 才进入复制集；`excluded_hash_only` 不复制。

### 3.2 明确排除规则（不复制）

以下类别一律不复制，即使被提及：

- **二进制构建产物**：`*.exe`、`*.obj`、`*.pdb`、`*.axf`、`*.hex`、`*.lnp`、`*.crf`、`*.d`、`*.sct`、`.rsp`。
- **缓存/临时**：`__pycache__/`、`.pytest_cache/`、`*.tmp`、`*.bak`、`nul`。
- **重复日志**：`*.log`（含 keil/host-c/pytest 日志）、`*.txt` 运行脚本输出、`.jsonl` 遥测流（无论体积）。
- **大体积媒体/数据**：`*.png`、`*.jpg`、`*.npy`、`*.jsonl`、`frames/`、raw 遥测、`sync_report.json` 关联的原始 pose/telemetry JSON（`raw_poses.json`、`raw_telemetry.json`）。
- **运行脚本/驱动**：`*.bat`、`*.ps1`、`*.sh`、`*.py`（证据目录内的采集/分析脚本；这些是工具不是证据）。例外：被 §17.1 或 §6 明确点名的 `.py` 才纳入——当前链接与 §6 证据列均无 `.py`，故实际全排除。
- **执行提示词/过程性产物**：纯执行提示（如 `project_plan_v2/deepseek_project_plan_v2_prompt.md`）不是验收证据，默认 `excluded_hash_only`；若被主说明书链接，改写为内联代码（§8.1）。判定为“过程性产物”的标准：内容仅是给代理的指令/上下文，不含可独立验收的事实结论；若某提示词内含唯一不可再生的验收结论，则按 §5.3 改判。
- **可再生状态**：`state.json`、`config.json`（含机器/网络地址，见 §5.5）。
- **目录引用**：`.../build/`、`.../rollback/` 这类纯目录路径不复制，只由 manifest 说明。
- **无关资料**：`安装说明书/`、`_unrelated/`、`.vscode/`、`.claude/` 等非权威证据；`LZ5X-3.pdf` 等非本任务 PDF。

排除项分两类记入 manifest：候选但被分类排除的 → `excluded_hash_only[]`（§6.3）；非候选的可再生/已知不复制项 → `external_or_regenerable[]`（§6.4）。

---

## 4. 三份 PDF 的目标文件名

目标文件名（进入 `docs/sources/`）严格采用主说明书 §17.1 所列原件文件名，不改名：

| # | 目标文件名（`docs/sources/` 下） | 来源类别 | 内容模式 |
|---|---|---|---|
| 1 | `Robot_Twin_AI_具身智能机器人自主优化平台规划文档.pdf` | `pdf_original`（外部本地来源） | `byte_identical` |
| 2 | `Robot_Twin_AI_V1.0_软件架构设计文档.pdf` | `pdf_original`（外部本地来源） | `byte_identical` |
| 3 | `Robot_Twin_AI_V1.0_开发任务拆解与里程碑文档.pdf` | `pdf_original`（外部本地来源） | `byte_identical` |

- **源定位**：三份 PDF 位于工作区之外（微信文件下载目录等外部本地位置）。执行阶段须先有 §14.3 提案的“本地来源清单”（`_unrelated/` 或 `docs/.local/`，git 忽略、不入库），或用户当次提供源路径；源绝对路径**只出现在清单中，永不进入仓库或 manifest**。
- **原件只读**：PDF 原件只读引用；`docs/sources/` 下为字节一致副本。
- **PDF 敏感扫描**：三份副本进入仓库前必须通过元数据 + 可提取文本扫描（§9 gate 5）。若某份 PDF 文本提取失败，按 §9 的二进制/内容流扫描与人工边界复核处理，并把提取状态写入 manifest `pdf_text_extraction`。
- **校验**：复制后用 pypdf 打开确认页数 > 0 且能读，并记录 SHA-256 到 manifest；两者任一失败即停机（§11）。
- **体积注记**：§14.4 对大二进制默认外置；PDF 因用户已批准纳入 `docs/sources/` 而例外。若执行时发现单份 PDF 体积异常（> 10 MiB），写入 manifest 并在报告中提示 LFS/外置选项，但复制仍按批准范围执行。

---

## 5. 权威证据选择算法与 content_mode 分类（反向 allowlist）

### 5.1 输入

只读解析主说明书 `docs/Robot_Twin_AI_完整计划说明书_v2.0.md` 的四处引用来源：

1. **§17.1 Markdown 链接目标**（实测 33 个，全部存在，从仓库根可解析；其中 20 个位于 `.embeddedskills/`）。
2. **§6 状态表“证据路径”列**的每个单元格（含无前缀书写的文件名）。
3. **§6.2**（权威规则说明中显式点名的文件，如 `v1_task4b4_fix/BLOCKED_duplicate_execution.md`）。
4. **§17.3 过期陈述表**（“处理”列显式点名当前依据，如 `route_selection.json`（C1 契约））。

### 5.2 提取与过滤步骤（执行阶段只读执行）

1. 用正则提取所有 `.embeddedskills/...` 与 §6 证据列中的文件路径（含内联代码形式），同时保留 §17.1 链接目标。
2. 过滤：丢弃纯目录引用（如 `.../build/`、`.../rollback/`）；丢弃“叙事提及”而非“证据引用”的路径（判定见第 3 步）。
3. 分类（两级）：
   - **候选集（candidate set）**：作为 §17.1 链接目标出现，或出现在 §6 证据列 / §6.2 / §17.3 显式引用中。实测为 23 个文件（§2 布局列出）。
   - **非候选（不复制，记 `external_or_regenerable[]`）**：仅出现在叙事说明中的条目（如 §14.6 列举 .gitignore 白名单内容时提到的 `intrinsics_final.json`、`homography.json`、`track_map.json`、`sync_report.json` 等），以及所有被 §3.2 排除的条目。
4. **同名/冲突处理**：`docs/evidence/` 按“源相对镜像”布局映射；`byte_identical` 条目源文件唯一映射到同名目标。`sanitized_copy` 条目目标文件名带 `.portable.` 中缀，与任何源文件名都不会碰撞。若执行中发现两个源映射到同一目标（理论上不可能），视为设计违反，停机并写 conflict_report（§7）。
5. **历史记录处理**：§6.2 要求“初版 PASS 仅作为历史记录、当前以新鲜 Gate 为准”。算法保留**两者**：`v1_task4b1/handoff.md`（初版）与 `v1_task4b_reacceptance/4b1/gate0_report.json`（2026-08-02 新鲜 FAIL）都复制；`v1_task4b1/gate0_report.json`（初版 Gate 0）因 §6.2 权威讨论与 `.gitignore` 白名单点名，归入候选集。manifest 的 `purpose` 明确标注哪个是当前权威、哪个是历史记录。
6. **冲突文档处理**：同一目录下 `handoff.md`（终稿）与 `handoff_pre_rework_*.md`（返工前）若被点名都保留原名复制；未被点名的不复制。

### 5.3 content_mode 分类（核心规则）

候选集中的每个文件，在复制前必须对源文件运行敏感模式扫描（模式类别见 §9 gate 5，全部类别见 §9），并按以下决策树分类：

| 扫描结果 | 该文件是否必要验收证据 | 分类 | 处置 |
|---|---|---|---|
| 无敏感命中 | — | `byte_identical` | 原字节复制到 `docs/evidence/<镜像路径>`，保留原名 |
| 有敏感命中 | 是 | `sanitized_copy` | 原件只读；在 `docs/evidence/` 生成脱敏可移植副本（`.portable.` 名），敏感值替换为占位符；manifest 记 redactions |
| 有敏感命中 | 否（执行提示/过程性产物/可再生摘要） | `excluded_hash_only` | 不复制；manifest 记逻辑名、原始 SHA、排除原因、可再生成/本地历史说明；主说明书不链接 |
| 有敏感命中 | 是，但**无法安全脱敏**（敏感值内嵌且无中立替换语义） | — | **停机，让用户裁决**（§11 停机条件 9） |

**占位符集（替换敏感值用，统一大写尖括号）**：

| 占位符 | 语义 | 典型用途 |
|---|---|---|
| `<WORKSPACE_ROOT>` | 工作区/仓库根 | 替换“盘符+工作区目录”形态绝对路径 |
| `<USER_PROFILE>` | 操作系统用户主目录 | 替换 `C:\Users\<用户名>\...` |
| `<LOCAL_AGENT_MEMORY>` | 本地代理记忆目录 | 替换 `.codex/`、`.claude/projects/.../memory/` 形态路径 |
| `<ESP_HOST>` | ESP 的 WiFi/IP 目标地址 | 替换私网 IP（如 `192.168.x.x`） |
| `<KEIL_ROOT>` | Keil 安装根目录 | 替换 `F:/keil` 形态工具链路径 |
| `<PYTHON_INTERPRETER>` | Python 解释器绝对路径 | 替换 `C:/Users/.../Python311/python.exe` 形态路径 |
| 相对逻辑标识 | 指向仓库内文件的中立相对路径 | `selected_route.json` 的 `source` 字段 → `v1_task4b2/track_bare.png`（相对 `.embeddedskills/build/`） |

**redaction 记录格式**：每条 `{category, location, placeholder}`——只记类别、位置（行/字段/近似偏移）、占位符；**绝不记录原敏感值**（§6.2、§9 gate 4/5 强制）。

**分类复核**：对命中的“类别词但无实际值”情况（如安全自审叙述中出现 `password`/`token`/`secret` 字样而无值），执行阶段须人工/上下文复核，确认无实际敏感值后记 `byte_identical`，并在 classification report 与 manifest 中记录“已复核：叙述性、无值”。**任何实际敏感值命中都不得借此类复核跳过脱敏。**

### 5.4 已知文件的预期分类（设计阶段只读预扫描结论）

以下为设计阶段对 23 个候选源逐文件预扫描（只读）得到的预期值；正式分类以执行前生成的 classification report 为准（§11.1 阶段 0）。路径均为仓库相对路径（相对 `.embeddedskills/build/`）。

| 候选源（相对 `.embeddedskills/build/`） | 预扫描命中类别 | 预期 content_mode | 处置说明 |
|---|---|---|---|
| `project_plan_v2/deepseek_project_plan_v2_prompt.md` | 工作区绝对路径、微信 PDF 路径、wxid | `excluded_hash_only` | 执行提示词，非关键验收证据；主说明书 §17.1 该链接改内联代码；manifest 记逻辑名 + 原始 SHA + 排除原因 + 本地历史说明 |
| `v1_task4b2_c1_open_route/selected_route.json` | `source` 字段含本机绝对路径 | `sanitized_copy` | 必要 C1 契约证据；`source` 改写为相对逻辑标识 `v1_task4b2/track_bare.png`；副本名 `selected_route.portable.json` |
| `v1_task4b4_fix/task4b4_hardware_gate_runbook.md` | 私网 IP（`192.168.x.x`）、`F:/keil` 路径 | `sanitized_copy` | 必要 runbook；IP→`<ESP_HOST>`、keil→`<KEIL_ROOT>`；副本名 `*.portable.md` |
| `v1_task4bd/handoff.md` | 用户目录、`.codex`/`.claude` 本地记忆绝对路径 | `sanitized_copy` | 必要历史证据（§17.3 点名）；→`<USER_PROFILE>`/`<WORKSPACE_ROOT>`/`<LOCAL_AGENT_MEMORY>`；副本名 `handoff.portable.md` |
| `v1_task4b0/handoff.md` | Python 解释器绝对路径 | `sanitized_copy` | 必要历史证据；→`<PYTHON_INTERPRETER>`；副本名 `handoff.portable.md` |
| `v1_task4b1/handoff.md` | 命令 outdir 参数绝对路径 | `sanitized_copy` | 必要历史证据；→`<WORKSPACE_ROOT>` 相对形式；副本名 `handoff.portable.md` |
| `v1_task4b4_fix/handoff.md` | `F:/keil` 工具链绝对路径 | `sanitized_copy` | 必要历史证据；→`<KEIL_ROOT>`；副本名 `handoff.portable.md` |
| `task2b-motor-register-diag/report.md` | 关键词 `password/secret/token` 仅现于安全自审叙述，无实际值 | `byte_identical` | 分类报告记录“已复核：叙述性、无值”；若执行扫描器误报，按 §9 gate 5 复核规则处置 |
| 其余 15 个候选 | 无命中 | `byte_identical` | 全量扫描通过后原字节复制 |

**预期复制数**：22（16 个 `byte_identical` + 6 个 `sanitized_copy`）+ 1 个 `excluded_hash_only`。该数字由分类规则可推导，非固定承诺；任何执行期新命中都可能改变，一律以 classification report 为准。

### 5.5 特殊条目：state.json / config.json

- 实测 `state.json`、`config.json` 含局域网 IP（如 `192.168.x.x`）与机器相关 Keil 路径。
- 决策：**不复制**，归 `external_or_regenerable[]`；生成方式 =“运行相关工具链后由工具重写（含当前扫描目标地址）”。§17.1 指向它们的两个链接改写为内联代码（§8.1），保证“全部链接可解析”gate 不被这两个可再生条目卡住。
- 该决策列为用户确认项（§12.2）。

### 5.6 算法产出

- **`classification_report.json`**（执行前 preflight 产物，置于 git 忽略目录 `docs/.local/` 或 `_unrelated/`，不入库）：逐候选一行，含 `origin_repo_path`（相对仓库）、`target_repo_path`（含 `.portable` 命名）、`content_mode`、`source_sha256`、`size_bytes`、`purpose`、`section_ref`、`redactions` 计划（类别/位置/占位符）。
- 复制集（allowlist）= classification 中 `content_mode ∈ {byte_identical, sanitized_copy}` 的子集。`excluded_hash_only` 不进复制集，进入 manifest 的 `excluded_hash_only[]`。
- 任何候选源磁盘缺失 → 停机（§11 停机条件 1）；任何候选无法安全脱敏且又是必要证据 → 停机让用户裁决（§11 停机条件 9）。
- 允许最终复制数少于候选数；选择规则即 §5.3 决策树，全程可推导。

---

## 6. manifest schema（`docs/evidence/manifest.json`）

**硬性约束**：全文件不得含个人绝对路径（以盘符 + 操作系统用户目录形态开头的路径、微信下载目录的完整路径）、账号标识、密码/密钥值、私网 IP 实际值、wxid 实际值、任何机器绝对路径或等价形式；redaction 记录不得含原始敏感值。源定位一律用“仓库相对路径”或“来源类别 + 用途说明”。

### 6.1 顶层字段

```json
{
  "schema_version": "1.1",
  "bundle": "robot-twin-ai-portable-document-bundle",
  "generated_at": "2026-08-02T00:00:00+08:00",
  "git_snapshot": {
    "commit": "<HEAD 短哈希，只读读取>",
    "branch": "master",
    "note": "只读快照，非 Git 写操作"
  },
  "sensitive_scan": {
    "patterns": ["drive_abs_path", "user_home_abs_path", "wechat_download_path", "wxid", "private_ip", "device_serial", "ssid", "credential_value", "password_value"],
    "scope": "docs/sources/** + docs/evidence/** 全部字节与文件名 + manifest.json + 主说明书（含改写链接）+ 本任务新增 Markdown + 3 份 PDF（元数据 + 可提取文本）",
    "pdf_text_extraction": "ok",
    "hits": 0,
    "pattern_note": "drive_abs_path = 形如 <盘符>:\\ 的绝对路径；user_home_abs_path = 形如 C:\\Users\\<用户名>\\ 的路径；均以类别名与泛化示例描述，具体正则由执行工具实现，不在此处展开"
  },
  "entries": [],
  "excluded_hash_only": [],
  "external_or_regenerable": [],
  "validation": {
    "links_checked": 30,
    "links_ok": 30,
    "candidates_scanned": 23,
    "byte_identical_copied": 16,
    "sanitized_copied": 6,
    "excluded_hash_only": 1,
    "pdfs_copied": 3,
    "pdf_pages_ok": 3,
    "hashes_match": true,
    "redactions_complete": true
  }
}
```

- `git_snapshot.commit` 取 `git rev-parse --short HEAD`（只读），仅为时间点对齐，不构成写操作。
- `sensitive_scan.hits` 在 §9 gate 5 通过后写 0；`pdf_text_extraction` 取值 `ok` / `degraded_binary_scan` / `failed_binary_scan_human_review`，对应 §9 gate 5 的 PDF 处理路径。
- `validation` 各计数为**动态值**（执行时按 classification report 与 gate 结果如实填）；上面是 §5.4 预扫描预期下的示例，`links_checked` 30 = 33 − state.json − config.json − deepseek 提示词链接（3 个转内联代码，§8.1）。

### 6.2 `entries[]`（每个复制条目）

| 字段 | 类型 | 语义 |
|---|---|---|
| `id` | string | 稳定短 slug，如 `v1_task4b1_handoff` |
| `category` | enum | `source_pdf` / `evidence` |
| `content_mode` | enum | `byte_identical` / `sanitized_copy` |
| `rel_path` | string | 仓库相对目标路径，如 `docs/evidence/v1_task4b1/handoff.portable.md`（**相对路径，无绝对路径**） |
| `origin_repo_path` | string | 仓库相对源路径，如 `.embeddedskills/build/v1_task4b1/handoff.md`（对 PDF 为 `source_category=external_local` 时可为空） |
| `purpose` | string | 引用位置 + 用途，如“§17.1 链接 / §6 4B-1 初版 handoff（历史记录，当前权威见 v1_task4b_reacceptance/4b1/gate0_report.json）” |
| `section_ref` | string[] | 引用章节，如 `["§17.1", "§6 4B-1"]` |
| `size_bytes` | int | 字节数（执行时实测） |
| `source_sha256` | string | 原件 SHA-256（执行时对原件复算） |
| `portable_sha256` | string | 可移植副本 SHA-256（`byte_identical` 时等于 `source_sha256`；`sanitized_copy` 时必须不等） |
| `redactions` | array | `byte_identical` 恒为 `[]`；`sanitized_copy` 为 `{category, location, placeholder}` 数组，**不含原敏感值** |
| `source_category` | enum | `pdf_original`（外部本地）/ `embeddedskills_evidence`（工作区 .embeddedskills）/ 其他 |
| `status` | string | `copied` |
| `is_authoritative` | bool | 按 §6.2 规则标注：当前权威 true；历史记录 false（如初版 handoff / 初版 gate0_report） |
| `pdf_pages` | int? | 仅 PDF 条目；pypdf 页数 |

### 6.3 `excluded_hash_only[]`（候选但分类为不复制）

| 字段 | 类型 | 语义 |
|---|---|---|
| `logical_name` | string | 逻辑名，如 `project_plan_v2/deepseek_project_plan_v2_prompt.md` |
| `origin_repo_path` | string? | 仓库相对原位置（相对，非绝对；供本地追溯） |
| `source_sha256` | string | 原件 SHA-256 |
| `reason` | string | 排除原因（如“执行提示词，非关键验收证据”“无法安全脱敏且非必要”） |
| `regeneration_or_local_history_note` | string | 可再生成方式或本地历史保留说明 |

**硬性约束**：不得含绝对源路径；不得出现 `rel_path`（无可移植入口）；主说明书不得链接此类条目（§8.1）。

示例条目（写入 manifest）：

```json
{
  "logical_name": "project_plan_v2/deepseek_project_plan_v2_prompt.md",
  "origin_repo_path": ".embeddedskills/build/project_plan_v2/deepseek_project_plan_v2_prompt.md",
  "source_sha256": "<原件 SHA-256>",
  "reason": "执行提示词，含工作区/微信路径与 wxid；非关键验收证据",
  "regeneration_or_local_history_note": "原件仅存于本地 .embeddedskills/（git 忽略）；交付物为该提示词产出的计划说明书，不复制提示词本身"
}
```

### 6.4 `external_or_regenerable[]`（非候选但记录生成方式）

| 字段 | 类型 | 语义 |
|---|---|---|
| `name` | string | 文件名 |
| `rel_path` | string | 原仓库相对位置（如 `.embeddedskills/state.json`） |
| `reason` | string | 排除原因（含敏感地址 / 可再生 / 大体积 / 构建产物 / 缓存） |
| `regeneration_note` | string | 生成方式或再取得方式，如“运行工具链后由工具重写”“重跑 `extract_selected_route.py` 再生成 `selected_route_centerline.npy`”“原始采集数据重跑采集脚本” |

示例条目（写入 manifest）：

```json
{
  "name": "state.json",
  "rel_path": ".embeddedskills/state.json",
  "reason": "可再生运行状态，含机器/局域网地址，不入可移植包",
  "regeneration_note": "工具链执行后由工具重写；网络目标地址为当时扫描目标，非任务权威证据"
}
```

### 6.5 必现条目（初始默认集，执行时按实际扩充）

- `excluded_hash_only[]`：`project_plan_v2/deepseek_project_plan_v2_prompt.md`（§5.4）。
- `external_or_regenerable[]`：`state.json`、`config.json`（§5.5）。
- `external_or_regenerable[]`：§14.6 叙事提及的 `intrinsics_final.json`、`homography.json`、`track_map.json`、`sync_report.json`、`baseline_hashes.json`、`closed_path_scope_review.json`。
- `external_or_regenerable[]`：大体积媒体/数据：`selected_route_centerline.npy`（重跑 `extract_selected_route.py` 再生成）、`selected_route_overlay.png`、`route_choices.json`（历史阻塞证据，原件保留于 `.embeddedskills/`，不在可移植包内）、各 `.jsonl` 遥测流、`frames/`、`raw_poses.json`、`raw_telemetry.json`。

---

## 7. 复制语义与冲突处理

### 7.1 复制流程（每个源 → 目标）

**`byte_identical` 条目**：

1. 计算源文件 `source_sha256`（读 `.embeddedskills/` 或外部 PDF 原件）。
2. 源文件先通过 §9 gate 5 全量扫描（0 命中）——该条目才允许复制。
3. 若目标不存在 → 复制（字节复制，不改内容、不改编码、不追加 BOM）。
4. 若目标已存在：
   - 复算目标 `target_sha256`：
     - `target_sha256 == source_sha256` → **幂等**，跳过复制，`status=copied`（视为已就绪，不算错误）。
     - `target_sha256 != source_sha256` → **不得覆盖**：将冲突写入 `docs/evidence/conflict_report.json`（记录 rel_path、两个哈希、双方修改时间），并**立即停机**（停机条件 2）。人工裁决后才能继续；裁决选项仅“保留现有并跳过”或“在用户确认下以副本替换”，绝不静默覆盖。
5. 复制完成后再复算一次目标哈希写入 manifest（二次校验；`portable_sha256 == source_sha256`）。

**`sanitized_copy` 条目**：

1. 计算源文件 `source_sha256`（原件只读复算）。
2. 按 classification_report 的 redactions 计划读取原件、生成脱敏副本 → 写入 `docs/evidence/<镜像路径>/<原名>.portable.<ext>`。
3. 对脱敏副本重扫其被脱敏类别：0 命中才算生成成功（§9 gate 4）；复算 `portable_sha256`（必须 ≠ `source_sha256`）。
4. 若 `.portable` 目标已存在：复算目标哈希，等于本次生成的 `portable_sha256` → 幂等跳过；不等 → 写 conflict_report 并**立即停机**（停机条件 2），绝不静默覆盖。
5. 原件永不写、永不改、永不删。

### 7.2 全局约束

- **原件永不删除/移动/改写**：`.embeddedskills/` 与外部 PDF 源只读；脱敏只发生在新增副本上。
- 目标目录 `docs/sources/`、`docs/evidence/` 若执行时已存在且含未记录文件，先核对 manifest 与 classification report；出现未预期文件即停机（停机条件 6 前置检查）。
- 复制顺序：先 PDF（页数校验 + 扫描）→ 再 evidence（byte_identical 与 sanitized_copy 并行或顺序皆可，但 sanitized 副本必须先过 §9 gate 4 复扫）→ 最后生成 manifest；manifest 生成前任何冲突都停机，不产出“半成品 manifest”。

---

## 8. Markdown 链接解析规则及可移植性要求

### 8.1 规则（针对主说明书；其余 `docs/superpowers/` 下文档实测无 Markdown 链接）

主说明书位于 `docs/`，改写后的链接一律以 `docs/` 为基准的**仓库内相对路径**：

| 原目标（按仓库根书写） | 改写后（从 `docs/` 解析） | 依据 |
|---|---|---|
| `docs/superpowers/<path>` | `superpowers/<path>` | 同目录内 |
| `.embeddedskills/build/<path>`（该条目为 `byte_identical`） | `evidence/<path>` | 副本已复制到 `docs/evidence/` |
| `.embeddedskills/build/<path>`（该条目为 `sanitized_copy`） | `evidence/<原名>.portable.<ext>` | 脱敏副本已复制到 `docs/evidence/` |
| `.embeddedskills/build/project_plan_v2/deepseek_project_plan_v2_prompt.md` | 内联代码 `` `.embeddedskills/build/project_plan_v2/deepseek_project_plan_v2_prompt.md` ``（非链接） | `excluded_hash_only`；不复制、不链接（§5.4） |
| `.embeddedskills/state.json`、`.embeddedskills/config.json` | 内联代码 `` `.embeddedskills/state.json` `` / `` `.embeddedskills/config.json` ``（非链接） | 未复制；可再生成（§5.5） |
| `simulation/digital_twin/<path>` | `../simulation/digital_twin/<path>` | 上溯到仓库根再下行 |
| `docs/sources/<pdf名>`（新增，如 §17.1 如需为 PDF 加链接） | `sources/<pdf名>` | 同目录内 |

**§6 状态表证据列**：凡单元格命中的证据路径，同步改写为指向 `docs/evidence/` 对应可移植副本（含 `.portable` 名）；被排除条目（state.json/config.json/deepseek 提示词）在 §6 单元格中以内联代码形态保留原名，不构成链接。

- 统一使用 `/` 分隔符（Markdown 标准），不使用 `\`。
- 文件名含空格/中文/括号时按 Markdown 原样书写（执行阶段验证解析），不插入 URL 编码。
- 改写是**纯目标替换**：只动链接目标字符串、§6 证据列单元格、以及 §8.1 明确的内联代码转换（state.json/config.json/deepseek 提示词），不改任何事实、数字、状态、章节号。改写后 diff 允许的变化**仅限于上述行**；出现其他行变化即停机（停机条件 5）。

### 8.2 本机可移植性

- 链接在本机 `docs/` 下从编辑器/仓库根打开都能解析（相对路径不依赖机器路径）。
- `git status`/`git check-ignore` 只读核对：`docs/sources/`、`docs/evidence/` 不被任何 ignore 规则覆盖（执行阶段预检已实测 exit=1，即未被忽略）。

### 8.3 仓库可移植性（clone 后）

- 唯一依赖的“非仓库内容”是三份 PDF 的外部源与 `.embeddedskills/` 原件；clone 出的仓库不含二者，但 `docs/sources/`、`docs/evidence/` 与改写后链接自洽，所有链接仍解析。
- 证据内部对 `.embeddedskills/` 的引用（如 handoff 内提到别的证据路径）是历史指针，**不要求解析**；验收只核对主说明书中的 Markdown 链接与 §6 证据列改写（§9 gate 1 明确限定范围）。

---

## 9. 验收 gates（全部通过才算本任务完成）

执行阶段按以下顺序逐项核对，任一 FAIL 即停机（停机条件 7）；gates 全部 PASS 才写 `validation` 并进入报告。

| # | Gate | 判定方法（只读） |
|---|---|---|
| 1 | **链接全解析 + 证据引用改写一致** | Python 脚本从 `docs/` 解析主说明书全部 Markdown 链接（改写后，预计 30 个），逐一对 `os.path.exists` 验证；URL 型（http/https/#锚点）不计入。同时核对 §6 证据路径列每个单元格指向 `docs/evidence/...` 实际存在的可移植副本（含 `.portable`），且无指向 `excluded_hash_only`/`external_or_regenerable` 的链接。结果写入 `validation.links_ok`。 |
| 2 | **目标存在** | classification report 中每个复制目标（`byte_identical` 与 `sanitized_copy`）`os.path.exists` 且非空（`size_bytes>0`）。 |
| 3 | **目标不被 git ignore** | 对 `docs/sources/**`、`docs/evidence/**` 全部新增文件跑 `git check-ignore`，返回码必须全为“未忽略”。 |
| 4 | **哈希 + 脱敏一致** | 每条 entry：`source_sha256` 与原件一致（原件未变）；`portable_sha256` 与磁盘副本一致；`content_mode=byte_identical` 时 `portable_sha256 == source_sha256`；`content_mode=sanitized_copy` 时 `portable_sha256 != source_sha256`（**不得冒充字节一致**）且 `redactions[]` 非空且每条记录类别/位置/占位符；对每个 `sanitized_copy` 副本重扫其被脱敏类别，0 命中。manifest 自身哈希记录于报告。 |
| 5 | **敏感信息 0 命中（全量）** | 扫描范围 = `docs/sources/**` + `docs/evidence/**`（全部字节 + 文件名）+ `manifest.json` + 主说明书（含改写链接）+ 本任务新增 Markdown + 3 份 PDF。模式类别：盘符绝对路径、用户主目录、微信下载目录路径、wxid、私网 IP（`192.168.*`/`10.*`/`172.16-31.*`）、设备序列号、SSID、密码/API key/token/secret 值形态等。**任何实际敏感值命中即 FAIL，不存在“原件属性例外”**；类别词但经复核无实际值的情况须在 classification report 中记录“已复核：叙述性、无值”后方可不计。PDF：先扫元数据（pypdf 元数据 + 文件名）与可提取文本；若文本提取失败，降级为二进制/内容流扫描，并对该 PDF 执行人工边界复核清单（查看页眉页脚/注释/嵌入对象），把提取状态写入 manifest `pdf_text_extraction`。 |
| 6 | **无产品代码变化** | 执行前 `git status --porcelain` 快照对比执行后：允许变化仅限 `docs/sources/**`、`docs/evidence/**`、主说明书链接行与 §6 证据列单元格；出现其他路径变化即 FAIL。 |
| 7 | **Git 只读** | 复核本任务运行记录中无任何 `git add/commit/push/reset/checkout/init/branch/tag/remote`；只使用 `status/check-ignore/rev-parse/log` 等只读命令。 |
| 8 | **PDF 可打开** | pypdf 打开 3 份 PDF，页数 > 0；页数与哈希写入 manifest；任一失败即 FAIL。 |
| 9 | **无意外产物** | 扫描确认未生成 `nul`、`*.tmp`、`*.log` 等临时物（本任务自身不应写这些）；`__pycache__/` 不新增。 |
| 10 | **分类完整性（无遗漏扫描面）** | classification report 中每个候选都有明确 content_mode；无候选被跳过敏感扫描；`excluded_hash_only` 条目均未出现在 `docs/evidence/` 与任何链接中。 |

gates 全部 PASS 后，输出执行报告（§12.1）并列出待用户确认事项（§12.2）；**不**执行 `git add/commit/push`，不宣布任何 Task 完成。

---

## 10. 回滚策略

回滚只撤销“本任务造成的文件系统与文档变化”，且**必须依赖执行前 manifest**：

1. **执行前基线**：进入执行阶段第 0 步先写 `执行前 manifest`（`_local/portable_bundle_preflight.json`，置于 git 忽略目录，如 `docs/.local/` 或 `_unrelated/`，不在仓库内发布）：记录本次将新建的每个目标路径（含 `.portable` 脱敏副本）、将改写的文档路径、改写的唯一链接行与 §6 单元格、源哈希与预期 `portable_sha256`。
2. **回滚操作集**（按需）：
   - 删除“执行前 manifest 中 `created` 列表”所列文件与空目录（仅这些路径；`docs/sources/`、`docs/evidence/` 只删本任务生成物，若全空则连目录一并删除）。`byte_identical` 与 `sanitized_copy` 副本都在删除范围，但**原件永不删除**。
   - 将主说明书从执行前备份（字节副本，置于 git 忽略目录）恢复；或反向替换“链接行/§6 单元格”回到改写前字符串。
3. **禁止**：通配符广泛删除（如 `rm -rf docs/evidence` 之外的任何泛化删除）、删除任何 `.embeddedskills/` 或外部原件、删除任何未记录在本任务 created 列表中的文件、执行任何 `git` 写命令回滚。
4. **冲突兼容**：回滚与 §7 冲突策略一致——执行中若发现目标被非本任务内容占用，写入 conflict_report 交用户裁决，绝不静默覆盖或删除；回滚不触碰非本任务创建的文件。
5. 回滚后复核 `git status --porcelain` 与执行前快照一致（除既有脏状态外无新增差异）。

---

## 11. 分阶段执行步骤与停机条件

> 执行需用户批准另一次任务；本节供执行代理遵守。

### 11.1 阶段 0 — 预检（全只读）

1. 记录 `git status --porcelain`、`git rev-parse --short HEAD`、`git check-ignore` 关键目标。
2. 运行 §5 算法生成候选集；确认 23 个候选源存在、3 份 PDF 源可由本地来源清单/用户提供定位。
3. **生成逐文件 classification report**（preflight 产物，§5.6）：对每个候选运行 §9 gate 5 全量模式扫描 → 定 content_mode、redactions 计划、源哈希；对 PDF 试提取文本确认提取可行性。扫描工具先在待扫描目录试运行，确认无漏扫（无候选被跳过）。
4. 确认 `docs/sources/`、`docs/evidence/` 不存在或为空（非空则停机）。
5. 写执行前 manifest 与主说明书备份。
6. 对分类为 `excluded_hash_only` 的条目，核对主说明书是否仍链接——若链接未在 §8.1 映射中覆盖，停机交用户确认。

### 11.2 阶段 1 — 复制与脱敏副本生成

按 §7 执行：3 份 PDF（页数校验 + 扫描）+ 全部 `byte_identical` 证据（原字节复制）+ 全部 `sanitized_copy` 证据（生成 `.portable` 脱敏副本并复扫）。

### 11.3 阶段 2 — 生成 `docs/evidence/manifest.json`

按 §6 生成；`validation` 中已跑项如实填。

### 11.4 阶段 3 — 主说明书链接与 §6 证据列改写

按 §8.1 映射改写链接（预计 30 个保留 + 3 个转内联代码）与 §6 证据列单元格；diff 校验仅允许 §8.1 列出的行变化。

### 11.5 阶段 4 — 验收 gates

跑 §9 全部 10 项。

### 11.6 阶段 5 — 报告

输出：新增文件清单（按 content_mode 分组）、manifest 摘要（含 redactions 摘要、`excluded_hash_only` 条目）、gate 结果、遗留/待确认事项（§12.2）。不执行 Git 写操作。

### 11.7 停机条件（任一命中立即停止，不进入下一阶段）

1. 任一候选源文件或 PDF 源在磁盘上缺失/不可读。
2. 目标已存在且与预期哈希不同（冲突，§7.1）；写 conflict_report。
3. PDF pypdf 打不开或页数 0。
4. 敏感扫描（§9 gate 5 全量范围）有实际敏感值命中。
5. 主说明书链接/§6 单元格改写 diff 超出 §8.1 允许行集。
6. 预检发现 `docs/sources/` 或 `docs/evidence/` 非空且含未预期文件。
7. 任一验收 gate FAIL。
8. 需要或出现任何 Git 写命令、硬件命令、或对 `.embeddedskills/`/外部原件的写/删/移操作。
9. **某候选无法安全脱敏且又是必要证据 → 停机，让用户裁决**（裁决输入：该候选的命中类别、脱敏可行性分析、排除后果；裁决选项：改判 excluded_hash_only、改判 external_or_regenerable、生成人工指定副本、或终止任务）。
10. 用户在任何阶段提出中止。

---

## 12. 本设计不授权 Git 写操作、不宣布项目完成

1. **Git 只读**：本设计及未来执行阶段仅允许 `git status`、`git check-ignore`、`git rev-parse`、`git log` 等只读核对；**不授权** `git add/commit/push/reset/checkout/init/branch/tag/remote` 或任何改写仓库元数据/历史的操作。首个受控快照属 §14.7 独立 Task，须用户另行授权。
2. **不宣布项目完成**：本设计只产出“可移植资料层”方案；不改变 §6 任何 Task 状态、不认定 4B 系列验收结果、不改变“4B-1 BLOCKED / 4B-2 BLOCKED_INPUT_CROPPED / 4B-4 SOFTWARE_ONLY(NEEDS_REVALIDATION)”等现状；主说明书状态、路线图、里程碑判定权不变。
3. 本设计文件本身是文档产物；任何对本设计的分歧（如 §5.3 分类、§5.5 决策）按 §17.3 登记，不自行改写总说明书。
4. **待用户确认项（执行前须确认）**：① 三份 PDF 的外部源由用户当次提供或经本地来源清单确认；② §5.3 对“类别词叙述性误报”的处理口径（按 gate 5 复核规则不计为命中）；③ 若预检出现任何无法安全脱敏的必要证据，用户按停机条件 9 裁决。

---

## 13. 自审

- **无未决标记**：全部决策已定值——复制集不再固定为“23 个字节一致证据”，而是由 §5.3 决策树动态确定（§5.4 预扫描预期：22 复制 + 1 excluded；正式以 preflight classification report 为准）。三 content_mode、10 项 gate、10 条停机条件、1 条回滚策略、7 个占位符均为定值。
- **无个人绝对路径**：本文件未出现任何机器绝对路径、用户主目录、微信目录路径、wxid 实际值、私网 IP 实际值；只使用“工作区根”“仓库相对路径”表述与泛化示例（`C:\Users\<用户名>\...`、`192.168.x.x`）；manifest 与 redaction 已硬性禁止。
- **无敏感值**：未记录任何密码/密钥/token/wxid 实际值；redaction 记录只含类别/位置/占位符。
- **无“证据不扫描”例外**：旧 §1.2-5 与旧 gate 5 的“字节一致原件属性例外”已废除；§9 gate 5 覆盖全部入包内容与 PDF，任何实际敏感值命中都 FAIL。
- **与现场一致**（只读核实）：33 个链接全部存在（3 个将转内联代码 → 预计保留 30）；23 个候选源全部存在；4 个已知敏感文件内容核实；预扫描另发现 3 个候选含绝对路径（v1_task4b0 / v1_task4b1 / v1_task4b4_fix 的 handoff）与 1 个叙述性误报（task2b）；`docs/sources`/`docs/evidence` 不存在且不被忽略；3 份 PDF 在工作区外；`state.json`/`config.json` 含局域网 IP 已核实并据实写入本设计。
- **内部规则一致**：三 content_mode 贯穿 §2/§5/§6/§7/§9/§11；`excluded_hash_only` 在 §5.4/§6.3/§8.1/gate 1/停机条件 9 中行为一致；`sanitized_copy` 在 §2 命名/§6.2 schema/§7.1 流程/§9 gate 4/§10 回滚中行为一致；§6.1 示例数字与 §5.4 预期一致。
