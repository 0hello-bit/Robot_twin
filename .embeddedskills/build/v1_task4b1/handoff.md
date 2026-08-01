## Handoff — Task 4B-1

### Task ID / Status
- **Task:** 4B-1 — 摄像头实时输入 Gate 0
- **Status:** COMPLETE ✅（自动验收 gate PASS）
- **上下文:** 4B-0 人工验收通过；用户授权进入 4B-1 并开启 DroidCam 实时流。

### Changed files

| 操作 | 路径 | 说明 |
|------|------|------|
| NEW | `simulation/digital_twin/v1_twin/v1_twin_camera.py` (约 320 行) | CameraSource 抽象 + OpenCVCameraSource 实现 + CameraStats/compute_camera_stats + verify_gate0 + CLI |
| NEW | `simulation/digital_twin/tests/test_v1_twin_camera.py` (165 行) | 抽象契约 / 统计纯函数 / verify_gate0 注入 Fake 端到端测试 |
| — | 既有生产源码、测试、固件、Keil、配置、模型 JSON、数据文件 | **未修改** |

新建文件 sha256（供 §21 回滚审计）：
- `v1_twin_camera.py`: `1b921a09…`
- `test_v1_twin_camera.py`: `37c107e3…`

### Gate 0 自动验收结果（§6b / G1）

**最终结论: PASS ✅**

| 指标 | 要求 | 实测 | 结果 |
|------|------|------|------|
| 录制时长 | 连续 10 分钟 | 600.301 s | ✅ |
| 有效帧率 | ≥ 20 fps | 30.0 fps | ✅ |
| 丢帧率 | ≤ 5% | **4.845%** | ✅（边界）|
| 时间戳 | 严格单调 | True | ✅ |

报告：`.embeddedskills/build/v1_task4b1/gate0_report.json`（source=0，frame_count=17991，nominal_period_ms=33.331，dropped=916，expected=18907，drop_detection=`gap>1.5x mean-interval`）。

### Commands

```bash
# 单元测试 (RED→GREEN)
python -m pytest simulation/digital_twin/tests/test_v1_twin_camera.py -v        # 10 passed

# Gate 0 真机验证（源 index0，连续 600s，后台运行）
python -m v1_twin.v1_twin_camera --gate0 --source 0 --duration 600 \
  --outdir "c:/Users/24668/Desktop/stm32小车/.embeddedskills/build/v1_task4b1"

# 全部 4B-0 + 4B-1 回归
python -m pytest simulation/digital_twin/tests/test_v1_twin_schema.py \
  simulation/digital_twin/tests/test_v1_twin_isolation.py \
  simulation/digital_twin/tests/test_v1_twin_camera.py                          # 44 passed
```

### Exact results and exit codes

```
TDD RED→GREEN:
  测试实现前:  ModuleNotFoundError: No module named 'v1_twin.v1_twin_camera'   (RED)
  实现后:      10 passed                                                       (GREEN)

Gate 0 两次真机运行:
  第 1 次 (中位数标称):  fps=30.00 drop_rate=6.730% monotonic=True -> FAIL (exit=1)
  第 2 次 (均值标称):    fps=30.00 drop_rate=4.845% monotonic=True -> PASS (exit=0)

诊断 (60s, 源 index0):  effective_fps=29.87; 间隔 ms mean=33.30 median=32.20
  p90=45.99 p99=64.31 max=80.89; 均值标称丢帧 4.88% / 中位数 6.96% / 30fps 目标 4.83%
  gaps>2x mean 仅 7 个 (0.39%) —— 无明显"硬掉帧"，主要是 WiFi MJPEG 抖动
```

### Artifact/log/report paths
- `.embeddedskills/build/v1_task4b1/gate0_report.json` — Gate 0 统计报告（PASS）
- `.embeddedskills/build/v1_task4b1/frames/frame_{start,mid,end}.png` — 样例帧（640×480，供人工验收确认画面覆盖赛道）
- `.embeddedskills/build/v1_task4b1/handoff.md` — 本文件

---

### Verified facts

- ✅ **[VERIFIED HARDWARE]** — DroidCam 实时流（源 `cv2.VideoCapture(0)`，640×480）连续 10 分钟: fps=30.0 ≥20、drop_rate=4.845% ≤5%、时间戳严格单调。实测于 2026-07-31 11:25–11:35。
- ✅ **[VERIFIED SOFTWARE]** — camera 单元测试 10/10 PASS；4B-0 + 4B-1 共 44 项回归全过。
- ✅ **[VERIFIED HARDWARE]** — 样例帧 3 张已保存，像素统计: 平均亮度 ~116、stddev ~57、暗像素 ~17%（有效场景内容，非黑屏）。
- ✅ **[VERIFIED SOFTWARE]** — 时序诊断证实 DroidCam 流以 ~30fps 平均节奏稳定交付（17991 帧 / 600.3s）。

### Inferences

- 🔶 **丢帧检测偏差已修正（中位数→均值标称）**：首次运行中位数标称给出 6.73% 被判 FAIL。60s 诊断揭示间隔右偏（median 32.2ms < mean 33.3ms），中位数假设 32fps 节奏、把正常抖动误计为丢帧。改用**均值**（真实平均交付节奏）后 10 分钟实测 4.845%。此修正为测量方法校正，非降低门槛；报告已记录所用 `nominal_period_ms` 与检测方法。
- 🔶 **帧时间戳时钟**：本平台 `time.monotonic_ns()` 量化 ~15.6ms（相邻调用返回相同值），不满足帧时间戳严格单调；改用 `time.perf_counter_ns()`（QPC，~100ns）。此差异记录于此，供用户决定是否同步修订 4B-0 schema 的时钟约定文档（schema 本身仅存 int ns，实现时钟可替换）。
- 🔶 **样例帧保存**：`cv2.imwrite` 在 Windows 上无法处理含非 ASCII（`小车`）路径，静默失败；改用 `imencode` + Python 写入后正常。

### Unverified items

- ⚪ **4B-1 人工验收 gate 未满足** — 需用户打开 `frames/frame_{start,mid,end}.png` 确认摄像头画面正确覆盖赛道区域（纲领 §6b）。
- ⚪ 丢帧率 4.845% 距 5% 门槛仅 ~0.16 个百分点，**边界余量极小**。若后续 4B-2~4B-4 发现抖动影响标定/位姿跟踪，可考虑更换串流方式（USB 直连 / MJPEG URL）再复测。

### Scope review

- 未修改任何既有生产源代码、测试、配置、固件、Keil 工程、模型 JSON 或真实数据 ✓
- 仅新建 §6b 允许清单内的 2 个文件 ✓
- 未触碰小车、电机、串口、烧录 ✓
- 未安装软件或修改系统环境 ✓
- 未 git init ✓

### Hardware actions performed
- 🔴 连接了摄像头（DroidCam 虚拟摄像头 index 0），连续 10 分钟录制（Camera-only 模式，§13 矩阵）
- ❌ 小车断电未连接，电机未运行，无烧录/复位/命令

### Safety/rollback state
- 无硬件安全隐患（Camera-only，用户在场）
- 回滚 = 删除 Changed files 所列 2 个新建文件（§21 规程：操作前核对哈希）

### Next prerequisites
- **下一 Task: 4B-2（相机标定与赛道坐标）** — 🔴 需要硬件：摄像头 + 标定板（棋盘格 15mm/格，已在 `~/Desktop/calibration_apriltag_chessboard.pdf` 生成）
- ⬜ 4B-1 自动验收 gate PASS；**人工验收 gate（用户确认画面覆盖赛道）待用户执行**
- ⬜ 4B-2 进入条件：4B-1 人工验收通过 + 用户明确指示

---

*Task 4B-1 COMPLETE. 等待用户确认人工验收 gate（画面覆盖赛道区域）后由用户指示进入 4B-2。*
