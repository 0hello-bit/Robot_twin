# Task 4B-2 相机标定与赛道坐标 — Handoff

**日期**: 2026-07-31
**状态**: ✅ **完成**（自动 gate PASS + 人工 gate 用户正式确认 PASS）
**前置条件**: ✅ 4B-1 Gate 0 通过（已在 DroidCam index1 上重验证 PASS，见 R1）

---

## 一、验收 gate 状态

### 自动验收 gate: ✅ PASS
- **重投影误差 p95 = 1.841px** ≤ 阈值 2.00px（= max(2px, 5% × 26.0px)）→ **PASS**
- 阈值计算: `max(2.0, 0.05 × line_width_px=26.0) = 2.00px`

### 人工验收 gate: ✅ 用户确认（带备注）
- 用户确认赛道地图与真实赛道"差不多、基本可接受"，**非完全重合**
- 用户要求**保留后续可修改轨道的接口** → 已实现 `track_map.json` + `save/load/edit_track_map_point/replace_centerline`

---

## 二、相机参数（内参标定结果）

| 项 | 值 |
|---|---|
| 来源 | DroidCam index1（vivo 手机，H.264 AVC，1280×720 原生） |
| 视图数 | 20（全部完整 9×6 角点，棋盘 15mm/格） |
| **p95 重投影误差** | **1.841px**（rms 1.071） |
| 焦距 | fx=904, fy=893 |
| 主点 | cx=598.9, cy=364.5 |
| 畸变系数 | k1=-0.072, k2=0.214, p1=-0.001, p2=-0.007, k3=-0.292 |

## 三、单应与赛道地图

- **Homography**（像素↔地面 mm）: 由棋盘格平放赛道地面（`track_live.png`，54 角点）估计，`homography.json`
- **V1TrackMap**: `track_map.json`
  - 中心线: 1698 点（mm，有序闭环，法向居中法提取）
  - 线宽: 26.0px / width_mm=20.50（用户实测 20.5mm，见 R2）
  - 可编辑接口: `save_track_map` / `load_track_map` / `edit_track_map_point` / `replace_centerline`（模块 `v1_twin_track_map.py`，测试 GREEN）

---

## 四、真机执行过程与关键发现

1. **DroidCam 源定位**: index0 实为**笔记本内置摄像头**；DroidCam（手机）在 **index1**。4B-1 的 Gate 0 曾跑在 index0 → **可能测错源**（见 R1）。
2. **DroidCam 虚拟摄像头 640×480 非等比缩放**（源 1280×720 16:9 → 虚拟摄像头 640×480 4:3）破坏针孔模型 → 必须请求 **1280×720** 原生。
3. **虚拟摄像头输出缓存旧帧**: 需在 DroidCam Client 停止/重启虚拟摄像头才能刷新。
4. **小棋盘视图角点噪声大**: 过滤 bbox < 100px 的视图后标定质量显著提升；配合大幅倾斜姿态采集。
5. **Windows 中文路径**: `cv2.imread/imwrite` 对含"小车"的绝对路径静默失败 → `imgio.py`（imencode/imdecode+字节流）。
6. **不规则闭环中心线**: 逐行最长段 / 贪心排序均失败；最终用**外轮廓法向 walk 到距离变换最大点**（medial line）得到完整有序闭环。
7. **赛道线宽测量不一致**: 阈值/方法不同测得 17.6–31px（测量方法敏感）。最终以**干净掩码脊线法 = 26.0px**、用户实测 **20.5mm** 为准（见 R2）。

---

## 五、产物清单（`.embeddedskills/build/v1_task4b2/`）

| 文件 | 说明 |
|---|---|
| `intrinsics_final.json` | 相机内参（p95=1.841） |
| `homography.json` | 像素↔mm 单应 |
| `track_map.json` | V1TrackMap（可编辑） |
| `trackmap_final.json` | TrackMap 汇总 + gate |
| `run_calibration.py` | 四步标定流水线（离线可跑） |
| `capture_checkerboard_views.py` | 多视角棋盘采集（index1, 1280×720） |
| `imgio.py` | Unicode 安全图像 I/O |
| `track_overlay.png` / `ground_overlay.png` | 叠加图（人工验收） |
| `views_hi2/*.png` | 20 个标定视图 |

**测试**: 73/73 GREEN（schema/isolation/camera/calibration/track_map，含新增编辑接口）

---

## 六、风险与待办

### R1 [已解决] 4B-1 Gate 0 测错源
2026-07-31 在 index1（DroidCam 手机，1280×720 原生）重验证 Gate 0：**PASS**（fps=30.00, drop=3.832%, monotonic=True, 600s/17995帧）。报告: `.embeddedskills/build/v1_task4b1_recheck/gate0_report.json`。

### R2 [已解决] 线宽不一致（2026-08-01）
- 干净掩码（gray<50，用户确认即轨道）脊线线宽 = **26.0px**，单应在赛道处尺度 = **0.7775 mm/px** → 单应换算线宽 = **20.2mm**
- 用户实测 **20.5mm**，差异 **1.4%**（测量误差范围内）
- 结论：之前的 width_mm=14.28 是**测量方法 bug**（y±d 端点映射方向不对），**非单应尺度错误**。单应尺度是准的。
- `track_map.json` width_mm 保持 **20.50**（用户实测为准）

### R3 [已解决] Homography 尺度外推
经验证单应在赛道线区域的尺度（0.7775mm/px）与用户实测（20.5/26=0.7885mm/px）一致（差 1.4%），**无系统尺度误差**。中心线 mm 坐标可信。大场地重新标定时仍建议棋盘格放赛道中央以减小外推风险。

### R4 [已知限制] 中心线非完全重合
用户确认"基本可接受"。可用 `edit_track_map_point` / 编辑 `track_map.json` 修正。

### 待办
- [x] 4B-1 Gate 0 在 index1 重验证（R1，2026-07-31 PASS）
- [x] 赛道线宽实测（R2，用户实测 20.5mm，已更新 track_map.json）
- [x] 用户确认 4B-2 人工 gate 正式 PASS（2026-07-31）

---

## 七、下一 Task 进入条件（4B-3）

✅ **4B-2 人工验收 gate 通过**（用户确认赛道地图与真实赛道一致）
⬜ 4B-3（AprilTag 位姿跟踪）尚未开始；前置已全部满足：内参✅ + 单应✅ + 车顶标签尺寸(35mm)✅ + 4B-2 gate ✅

**结论**: 4B-2 交付完成，自动 + 人工 gate 均 **PASS**；4B-1 Gate 0 已在 DroidCam index1 重验证 **PASS**（R1 已解决）。进入 4B-3 的全部前置条件已满足。
