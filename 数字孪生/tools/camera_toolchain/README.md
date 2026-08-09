# 相机工具链（Camera Toolchain）

**位置**：`tools/camera_toolchain/`

摄像头采集/标定/选点的**统一可复用工具**。所有工具自动检测摄像头索引、
unicode 安全读写图像。任何新会话（Claude/Codex）涉及摄像头操作**先读本文件**。

---

## 当前 1080p 地面标定契约（2026-08-09）

- 活动相机工具统一请求 `1920x1080`、`MJPG`、`30 FPS`，同步录制器和地面
  shakedown 会拒绝实际帧尺寸不一致的输入。
- 当前地面标定使用已有的实体棋盘格，单格实际尺寸是 `15 mm`，9x6 内角点
  对应的棋盘范围是 `120x75 mm`；活动地面几何工具默认使用这一物理尺度。
- 手持棋盘格在不同角度移动，只适用于相机内参覆盖。地面单应性必须使用刚性
  背板上的棋盘格，平放且与赛道平面共面；这一步是相机-only采集，小车不需要
  上电或运动。
- 仓库中的 `a4_checkerboard_9x6_25mm.*` 是独立的打印目标候选，保留但不能把
  25 mm 坐标与当前 15 mm 地面标定混用。

## 摄像头索引自动检测（重要）

DirectShow 索引**热插拔会漂移**（2026-08-03 实测：EMEET C960 曾为 2，重插后为 1；
0/1/3 可开，2 关闭）。**不要硬编码索引**。

- `camera_common.get_camera_index(preferred=None)`：
  优先级 = 显式 `--index` > `camera_config.json` 保存值 > 扫描首个可开索引。
  扫描结果自动写入 `camera_config.json`。
- 工具均支持 `python tool.py [index]` 显式指定。

**识别 C960 的启发式**：当前无法从 OpenCV 直接读设备名；先跑 `probe_camera.py`
看哪路画面是 C960（对赛道/工作台），把正确索引存进 `camera_config.json`。

---

## 工具清单

| 工具 | 用途 | 用法 |
|---|---|---|
| `probe_camera.py` | 探测索引/分辨率/帧率/单调/内容 | `py probe_camera.py [index]` |
| `live_preview.py` | 实时预览窗口（调构图/角度用） | `py live_preview.py [index]`，ESC 关 |
| `preview_ascii.py` | 无图像渲染时把画面转 ASCII 亮度图 | `py preview_ascii.py [index]` |
| `frame_border_analysis.py` | 暗区贴边/裁切分析（4B-2 input_cropped 检查） | `py frame_border_analysis.py [index]` |
| `perpendicularity_preview.py` | 实时垂直度检查（棋盘格纵横比/各向异性） | `py perpendicularity_preview.py [index]` |
| `capture_intrinsics_views.py` | 多角度采集（内参标定，15 张） | `py capture_intrinsics_views.py [index] [outdir]` |
| `capture_intrinsics_coverage.py` | **带目标格引导的多角度全覆盖采集**（4×4 网格；黄色=下一格，绿色=已完成；畸变标定必须用这个） | `py capture_intrinsics_coverage.py [index] [outdir]` |
| `record_chessboard_video.py` | **录棋盘格视频**（1920×1080@30，检测到棋盘格后自动开录；内参标定用） | `py record_chessboard_video.py [index] [out.mp4] [sec]` |
| `extract_calibration_frames.py` | **从视频解析标定视图**（逐帧检测 + 清晰度过滤 + 4×4 空间覆盖 + 角度去重） | `py extract_calibration_frames.py video.mp4 outdir [--grid 4] [--min-sharpness 100]` |
| `guided_capture.py` | **实时引导采集**：4×4 覆盖地图 + 清晰度/平贴度实时反馈 + 下一步提示，质量达标自动存（免返工） | `py guided_capture.py [index] [outdir]` |
| `mosaic_homography.py` | **视频拼接 homography**（平面镶嵌 bundle adjustment，需共面滑动数据） | `py mosaic_homography.py video.mp4 out.json` |
| `homography_holdout_eval.py` | **R3 mm 级评估**：物理控制点 + 分层 calibration/holdout + 分区域绝对误差 + mm 门限 | `py homography_holdout_eval.py controls.json out.json --mm-gate 2.0` |
| `R3_measurement_protocol.md` | R3 物理控制点测量协议（放棋盘格 + 尺测 mm 偏移） | 文档 |
| `capture_homography_positions.py` | 棋盘格平放多点位采集（空格保存） | `py capture_homography_positions.py [index] [outdir]` |
| `select_waypoints.py` | 在赛道图上点选 12 个路线锚点 | `py select_waypoints.py [image] [out.json]` |
| `run_gate0_usb.py` | 4B-1 Gate 0（600s 稳定性验收） | `py run_gate0_usb.py [index]` |

公共模块 `camera_common.py`：`get_camera_index / detect_camera_indices /
imread_unicode / imwrite_unicode / open_camera`。

---

## 标准 A4 棋盘格目标（当前标定基准）

生成器：`generate_a4_checkerboard.py`

```powershell
py generate_a4_checkerboard.py
```

默认输出到 `calibration_targets/`：

- `a4_checkerboard_9x6_25mm.pdf`：打印用 PDF；
- `a4_checkerboard_9x6_25mm.png`：300 DPI 预览图；
- `a4_checkerboard_9x6_25mm.json`：几何尺寸和打印比例元数据。

这是独立的 A4 打印目标候选：A4 横向、9×6 个内角点、10×7 个方格、每格
25 mm，连续棋盘区域为 250×175 mm，四周白边 10 mm。PDF 和 PNG 必须按
`100% / 实际大小` 打印，禁止“适应页面”“缩放到可打印区域”或拼接多张纸。

当前 B3 地面标定不使用这个 25 mm 候选，而使用已有的 15 mm 实体棋盘格；
地面工具默认使用 `--square-size-mm 15` 对应的物理尺度。两种目标必须保持
独立，不能把 25 mm 与 15 mm 坐标混写进同一个标定数据集。

---

## 标定工作流（4B-2/4B-3 顺序）

1. **架好摄像头**：垂直正俯拍赛道（`perpendicularity_preview.py` 调至
   纵横比≈1.60、各向异性≈1.00）。注意：均值法会漏掉轻微梯形倾角，
   最终以 homography 局部 Jacobian ratio≈1.0 为准。
2. **多角度全覆盖内参采集**：**推荐录视频法**——`record_chessboard_video.py` 以 1920×1080@30 录 60-90s
   （手持棋盘格慢速扫过 4×4 目标格、变换角度）→ `extract_calibration_frames.py`
   解析出 ~20-30 张覆盖全画面的视图。备选：`capture_intrinsics_coverage.py` 实时 3×3 覆盖。
   然后标定畸变（p95 ≤ 2px；覆盖不足时边缘畸变未约束 → homography 全局失真）。
   视频法覆盖更密更平滑，优于离散采帧。
3. **homography**：棋盘格平放赛道中央一帧 → undistort 角点 → 拟合。
   垂直+正确 undistort 后应全局均匀（全局 mm/px ratio≈1.0）。
4. **裸赛道图 + 选锚点**：拿开棋盘格抓 `track_bare.png` → `select_waypoints.py`
   点 12 锚点 → `extract_selected_route.py`（v1_task4b2_c1_c960_reacceptance 的
   改进版：`component_containing_waypoints` 选含锚点最多的分量）。
5. **Gate 0**（可选）：`run_gate0_usb.py` 600s 稳定性（fps≥20、drop≤5%）。

---

## 已知限制 / 教训（2026-08-03）

1. **DirectShow 索引漂移**：用 `camera_common`，勿硬编码。
2. **畸变标定空间覆盖不足** → undistort 边缘错误 → homography 全局失真
   （实测 ratio 0.337）。**必须用 coverage 版采集**。
3. **perpendicularity 均值法局限**：均值纵横比会掩盖梯形畸变；严格用 homography
   Jacobian ratio（局部各向异性）。
4. **多点位 homography 不能直接合并**：各位置棋盘格是局部 mm 坐标，合并需实测
   物理偏移；单位置 + 正确 undistort 才是正解。
5. **证据不可变**：重跑任何写证据的脚本前，先把目标证据目录复制到新目录。

---

## 相关产物（C960，2026-08-03）

- 内参：`simulation/digital_twin/data/calibration/` 下的相机标定输出
- homography：同一 calibration 目录下的平面映射输出
- 4B-2 证据：`docs/evidence/v1_task4b2_c1_open_route/`
