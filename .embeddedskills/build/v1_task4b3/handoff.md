# Task 4B-3 车顶标记二维位姿跟踪 — Handoff

**日期**: 2026-08-01
**状态**: ✅ **完成**（自动 gate PASS + 人工 gate PASS）
**前置条件**: ✅ 4B-2（标定完成，已知像素↔mm 映射）

---

## 一、验收 gate 状态

### 自动验收 gate: ✅ PASS（静态测试，100 帧，index1 DroidCam）
| 指标 | 结果 | 阈值 | 状态 |
|---|---|---|---|
| 有效检测率 | **99.0%**（99/100） | ≥95% | ✅ |
| x p95 抖动 | **0.387mm** | ≤5% 线宽 = 1.025mm | ✅ |
| y p95 抖动 | **0.114mm** | ≤1.025mm | ✅ |
| yaw p95 抖动 | **1.248°** | ≤2° | ✅ |

报告: `.embeddedskills/build/v1_task4b3/static_pose_report.json`

### 人工验收 gate: ✅ PASS
用户确认 **AprilTag 固定在小车车顶且无遮挡**（2026-08-01）。

---

## 二、实现（Produces）

**`v1_twin_pose_tracker.py`** — `PoseTracker.track(frame) → V1Pose(x_mm, y_mm, yaw_rad, confidence, t_pc_ns)`

- 检测: OpenCV ArUco `DICT_APRILTAG_36h11` ID=0（**锁定 OpenCV aruco**；pupil_apriltags 已安装作为备选但当前帧解码不如 aruco，未采用）
- **多尺度检测** `detect_scales=(1.0, 2.0, 3.0)`: 逐个放大尝试直到解码成功（关键！见 R1）
- 投影: 标签中心 → `cv2.undistortPoints` 去畸变 → 地面单应 → (x_mm, y_mm)
- yaw: 标签"印刷正上"方向（TL−BL = corner0−corner3）投影到 mm 帧 → atan2，加 `car_forward_offset_rad` 偏移
- confidence: 基于标签像素边长（≥30px→1.0，线性衰减到 0.2）
- 约定: 检测角点序 `[TL,TR,BR,BL]`（OpenCV 实测）；标签印刷正上默认=车头（偏移可调）

**测试**: `test_v1_twin_pose_tracker.py` 8/8 GREEN（合成标签检测/中心/homography 投影/旋转 yaw/confidence/t_pc_ns）；全套 **81/81 GREEN**

---

## 三、真机执行过程与关键发现

1. **标签解码失败诊断**（曾持续失败）:
   - 标签在 4B-2 帧（track_live.png）可解码，但当前实时流全部失败（OpenCV + pupil_apriltags 均失败，各种预处理/参数均无效）
   - 根因一: **DroidCam 流质量下降**（全帧 Laplacian var ~705→95，白地板区 407→99），用户调整 DroidCam 质量设置后恢复（sharpness 838）
   - 根因二: **标签偏小（~49px）+ 原始尺度 1× 解码率仅 5.4%** → 多尺度检测（1/2/3×）将检测率提升到 **99.1%**
2. **帧率正常**: DroidCam 30fps（属性 30.0，实测 28.87）
3. **解码器对比**: OpenCV aruco 能解码当前帧；pupil_apriltags（quad_decimate=1.0）不能 → 锁定 OpenCV aruco
4. **车顶深色 vs 白色边距**: 标签区域 56% 暗（深色车顶），曾怀疑白边问题；实测加白边不影响解码，最终由流质量 + 多尺度解决

---

## 四、产物清单（`.embeddedskills/build/v1_task4b3/`）

| 文件 | 说明 |
|---|---|
| `v1_twin_pose_tracker.py`（在 `simulation/digital_twin/v1_twin/`） | PoseTracker 实现 |
| `test_v1_twin_pose_tracker.py`（在 `tests/`） | 单元测试 8/8 |
| `static_pose_validation.py` | 真机静态验证脚本 |
| `static_pose_report.json` | 静态 gate 报告（PASS） |
| `handoff.md` | 本文件 |

---

## 五、风险与待办

### R1 [已缓解] 流质量不稳定
DroidCam H.264 流质量会**间歇性下降**（根因未查明，全帧 Laplacian var 可从 ~840 降到 ~100），导致小标签无法解码。**重连 DroidCam 即可恢复**（用户实测 2026-08-01）。缓解: 多尺度检测容忍大部分波动；质量再降时优先**重连 DroidCam**。⚠️ **验收 agent 建议**：4B-8 重检 G1 时换更稳的源（USB 摄像头）或采集前先确认流质量正常。

### R2 [待处理，4B-6 前必做] yaw 绝对方向约定
当前 `car_forward_offset_rad=0`（假设标签印刷正上=车头）。静态抖动验收只验证了稳定性（1.248°），**未验证绝对方向**。4B-6 拟合车速方向前需一次**真车实测**：车头朝已知方向放好，对比 yaw，把偏移写入配置。

### R3 [已知限制] 标签尺寸与视差
- 标签 ~49px，已靠多尺度检测兜底；大场地若标签更小（<30px），检测可能失败 → 建议大场地换更大标签或调摄像头
- 标签在车顶高于地面，单应按地面投影有视差偏移（对 yaw 无影响，x/y 有小量偏移）——V1 接受

### R4 [已装依赖] pupil_apriltags
已 pip 安装 pupil_apriltags（备选解码器），当前锁定 OpenCV aruco，未实际使用。如需锁版本留档，可写入 requirements。

---

## 六、下一 Task 进入条件（4B-4）

⬜ 4B-4（相机与遥测时间同步）尚未开始；前置: 4B-3 静态位姿验收通过 ✅ + 4B-1 摄像头 ✅

**结论**: 4B-3 交付完成，自动 + 人工 gate 均 **PASS**。PoseTracker 可输出每帧 V1Pose（x/y/yaw/confidence），供 4B-4 同步与后续模型拟合使用。
