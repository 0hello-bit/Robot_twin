# R3 毫米级映射 — 物理控制点测量协议

Codex 要求：控制点必须覆盖完整赛道、具有**统一物理坐标**、包含**独立 holdout**，
不得只用拟合残差。以下是获取物理控制点的操作步骤。

## 需要的材料
- 9×6 棋盘格（纸，15mm/格，120×75mm）
- 一把卷尺/直尺（mm 精度）
- 赛道（摄像头保持垂直固定）

## 步骤（约 10-15 分钟）

1. **选固定原点**：在赛道上定一个固定参考点（如"发"字发车支线某个角），
   作为全局 mm 坐标原点 (0,0)。以后所有测量都相对它。

2. **放棋盘格 + 测量**：把棋盘格平放在赛道 8-10 个位置（覆盖**四角 + 四边 + 中央**），
   每个位置：
   - 用尺子量**棋盘格左上内角**相对原点的 **x_mm、y_mm**（沿赛道横/纵两个方向）。
   - 尽量让棋盘格与赛道轴对齐（angle≈0）；若明显旋转，量出角度。
   - 拍一张图保存（用 `guided_capture.py` 或直接拍）。

3. **记录到 controls.json**：
   ```json
   [
     {"image": "pos_00.png", "x_mm": 0, "y_mm": 0, "angle_deg": 0},
     {"image": "pos_01.png", "x_mm": 250, "y_mm": 0, "angle_deg": 0},
     ...
   ]
   ```

4. **运行评估**：
   ```
    py tools/camera_toolchain/homography_holdout_eval.py \
     controls.json r3_report.json --mm-gate 2.0
   ```
   工具自动分层划分 calibration/holdout，分中心/边缘/四角报告绝对误差，
   应用 mm 门限（默认 p95 ≤ 2mm）。

## 判读
- `gate_ok=true` 且 holdout p95 ≤ 门限 → mm 级映射达成，可解 4B-3/4B-4 映射前置。
- 若 holdout 四角误差仍大 → 需要更小心测量 / 换大平板 / 更多 holdout 点。
- 报告必须同时给：控制点坐标表、原始图像、拟合/holdout 划分、分区域误差分布。

## 工具链相关
- `guided_capture.py`：实时引导采集（覆盖地图 + 平贴度反馈），用于拍控制点图。
- `homography_holdout_eval.py`：拟合 + holdout 评估。
- 摄像头索引自动检测见 `camera_common.py`；Codex 在用摄像头时不要启动采集。
