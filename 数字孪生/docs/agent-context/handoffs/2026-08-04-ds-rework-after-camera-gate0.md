# DS 返工 Handoff - C960 Gate 0 通过后的剩余阻断项

**日期**：2026-08-04  
**工作区根目录**：`C:\Users\24668\Desktop\stm32小车`  
**交接来源**：Codex 独立复核与本机命令复跑  
**接收者**：Claude Code 中的 DS 执行/复核代理

## 1. 当前结论

- **4B-1 USB 摄像头 Gate 0：PASS。**
- EMEET SmartCam C960 当前为 DirectShow 索引 `1`。
- 捕获模式已固定为 `DSHOW + MJPG + 1280x720 + 30 FPS`，并校验驱动实际返回值。
- 新鲜 600 秒重验：`effective_fps=29.50`、`drop_rate=0.629%`、`duplicate=0%`、时间戳单调、无效帧 `0`、分辨率匹配。
- Codex 已视觉检查首/中/尾画面：均为正确 C960 俯拍画面，完整赛道持续可见，无黑屏、花屏或切换到笔记本摄像头。
- **整个 Task 4B 尚不可宣布完成。** 下面 R1-R3 仍为返工阻断，R4 为未完成真机 Gate。

此前 `22.63 FPS` 不是摄像头持续能力上限。在隔离负载并固定模式后，60 秒实测 `29.481 FPS`，600 秒实测 `29.50 FPS`。只能判断先前结果更像并行负载或驱动瞬态，不能反推唯一根因。

## 2. 本次已经修改

### 摄像头配置与正式入口

- `.embeddedskills/tools/camera_toolchain/camera_config.json`
  - 当前保存索引改为 `1`。
- `.embeddedskills/tools/camera_toolchain/camera_common.py`
  - 公共打开模式默认改为 DirectShow、MJPEG、30 FPS。
  - 请求后校验实际 FPS 和 FourCC；不匹配时释放设备并失败。
- `.embeddedskills/tools/camera_toolchain/run_gate0_usb.py`
  - Gate 0 显式使用 `DSHOW/MJPG/1280x720/30 FPS`。
  - 报告新增 `capture_mode`，记录后端、FourCC、请求 FPS 和驱动 FPS。
  - 修复无需外部 `PYTHONPATH` 时 `ModuleNotFoundError: v1_twin`。
  - 摄像头索引解析移入 `main()`，导入脚本不再立即占用摄像头。
- `simulation/digital_twin/v1_twin/v1_twin_camera.py`
  - `OpenCVCameraSource` 新增可选 `backend/fps/fourcc`。
  - 驱动拒绝请求或实际模式不匹配时抛出 `CameraError`。

### 新增/更新测试

- `simulation/digital_twin/tests/test_v1_twin_camera.py`
  - 验证 DirectShow/MJPEG/720p30 设置传给驱动。
  - 验证驱动实际返回 `22.63 FPS` 时必须失败并释放设备。
- `simulation/digital_twin/tests/test_camera_toolchain_common.py`
  - 验证持久索引为 `1`。
  - 验证公共工具请求 C960 720p30 MJPEG 模式。
  - 验证 Gate 0 runner 在隔离 Python 环境中可独立导入。

## 3. 新鲜验证证据

### 3.1 离线回归

```powershell
py -3.11 -m pytest -q simulation/digital_twin/tests/test_v1_twin_camera.py simulation/digital_twin/tests/test_camera_toolchain_common.py
```

结果：`26 passed in 2.18s`，退出码 `0`。

```powershell
py -3.11 -m compileall -q .embeddedskills/tools/camera_toolchain
```

结果：退出码 `0`。

### 3.2 C960 600 秒 Gate 0

证据目录：

`.embeddedskills/build/codex_camera_config_600s_20260804/`

关键文件：

- `gate0_report.json`
- `gate0_log.txt`
- `frame_start.png`
- `frame_mid.png`
- `frame_end.png`
- `montage.png`

`gate0_report.json` SHA-256：

`F7C5A402FD06FFC09720FF10CB2E479B5DC915005BE330B69B83963B4AB7E70A`

关键结果：

```text
source=EMEET SmartCam C960 (USB DirectShow index-1)
backend=DSHOW
fourcc=MJPG
driver_fps=30.0
duration_s=600.361
frame_count=17699
effective_fps=29.5
nominal_period_ms=33.898
drop_rate_pct=0.629
duplicate_rate_pct=0.0
timestamps_monotonic=true
invalid_content_frames=0
resolution=1280x720, match=true
verdict=PASS
```

证据目录不可覆盖。再次复跑必须创建新目录。

## 4. DS 必须返工

### R1 - P0：ACK/STATUS 严格优先级仍存在同轮竞争漏洞

**已核实代码事实**：

`程序/3. 麦轮巡线小车/User/main.c` 的主循环当前顺序为：

1. `health_emit()`
2. `ESP_ServiceRX()` / `ESP_ServiceTX()`
3. `esp_transport_apply_and_ack()`
4. `ESP_SendQueuedFrames()`
5. `health_flush_pending()`
6. 消费并排队新的 STATUS

`health_emit()` 只检查当前 `cipsend_tx_busy` 和已保留的 `txfq_has_retry`。新 ACK/STATUS 尚未从 RX/transport 进入发送队列时，健康帧可能先启动，因此当前实现不能证明“ACK/STATUS 永远高于健康帧”。

**要求**：

- 重新设计同一轮的发送仲裁顺序或统一仲裁器。
- 在任何可丢/健康帧启动前，必须先物化并检查 transport 中的新 ACK/STATUS。
- 保留：健康帧延迟不丢、遥测让行、连接代次变化清待发。
- 不得把 `generated==dropped+started` 用于 `due=1` 的中间态；正确扩展恒等式是 `generated==dropped+started+due`。

**最低验收测试**：

- 同一轮同时出现 1 Hz 健康帧和新 ACK：首个启动 tag 必须是 ACK，健康帧保持 due。
- 同一轮同时出现健康帧和新 STATUS：首个启动 tag 必须是 STATUS。
- ACK 与 STATUS 同时存在：顺序仍为 ACK -> STATUS -> health -> telemetry。
- 连接代次变化：旧 health due 和旧 A/S 均不得泄漏到新客户端。
- Host C、Keil `0 Error/0 Warning`、Python 回归全部通过。

### R2 - P1：摄像头自动检测与工具链尚未真正统一

**已核实代码事实**：

- `camera_common.detect_camera_indices()` 仅使用 `cap.isOpened()`，不验证能否读取有效帧。
- 保存索引失效后仍选择第一个可打开索引，可能重新选到笔记本摄像头。
- `probe_camera.py` 绕过 `cc.open_camera()`，仍使用通用 `cv2.VideoCapture(SOURCE)`。
- `probe_camera.py` 即使 `0/30` 帧成功，也会在末尾返回退出码 `0`。
- 多个实时采集脚本仍直接调用 `cv2.VideoCapture`，没有统一应用 DSHOW/MJPG/30 FPS 和实际模式校验。

**要求**：

- 所有实时 USB 摄像头工具统一通过一个公共打开入口。
- 探测索引必须读取多帧并验证分辨率、有效内容和成功帧数；仅 `isOpened()` 不算检测成功。
- `0` 帧或成功帧不足时返回非零退出码。
- 多个设备都有效但无法确认 C960 身份时，明确报告歧义，不得静默选择第一个。
- 保留显式索引参数作为最高优先级；当前本机 C960 为索引 `1`，但不得假设热插拔后永远不变。

**最低验收测试**：

- 可打开但连续读帧失败的索引不得进入候选列表。
- 保存索引仍可打开但内容无效，必须重新探测或失败。
- 多摄像头歧义时不得自动选笔记本摄像头并宣称 C960。
- `probe_camera.py` 的全失败路径退出码非零。
- 全部实时采集脚本使用统一模式并记录实际 backend/FourCC/FPS。

### R3 - P0：毫米级全赛道映射仍未达成或未被独立证据证明

**已核实证据**：

- `intrinsics_c960.json`：`reprojection_error_p95_px=2.5435137629508824`，高于现有 `2 px` 门限。
- `homography_mosaic.json`：板尺寸误差平均 `6.8855%`、最大 `16.5630%`。
- `homography_flat_robust.json`：最大 `1.5896 mm` 仅是优化内部 detection residual；没有全赛道独立物理控制点，不能证明绝对 mm 映射精度。
- 旧多位置实测显示单位置 homography 远离棋盘格时失真可达约 `44%`。

**要求**：

- 使用覆盖完整赛道区域、具有统一物理坐标的控制点。
- 控制点必须包含独立 holdout，不得只报告参与拟合的数据残差。
- 分别报告中心、边缘、四角的绝对位置误差和尺度误差。
- 明确 mm 级门限及通过规则；未满足时保持 `BLOCKED/INSUFFICIENT_EVIDENCE`。
- 不得用局部 Jacobian 接近 1 推导全局绝对 mm 精度；它只能说明局部各向异性较小。

**最低验收证据**：

- 控制点物理测量方法、坐标表、原始图像和拟合/holdout 划分。
- 全画面 holdout 绝对误差分布：mean、p95、max。
- 可复跑脚本和退出码。
- 只有达到事先定义的 mm 门限，才允许解除 4B-3/4B-4 的映射前置阻断。

### R4 - 未完成真机 Gate：4B-4 相机与遥测同步

这不是已经证明的代码错误，而是 **INSUFFICIENT_EVIDENCE**：

- 真机遥测稳态约 `10 Hz`，而当前同步 Gate 目标包含 `p95 <= 33.3 ms`。
- 10 Hz 遥测很可能使最近邻匹配 coverage 或 p95 不达标，但尚未用本次 C960 真机同步数据验证。

**要求**：

- 作为独立硬件任务处理固件遥测批量发送或同步策略。
- 真机运行、烧录、车轮运动必须重新取得用户当次授权；不得沿用旧授权。
- 完成真实 C960 + MCU 遥测联合采集后，再给 `PASS/REJECT`；当前不得宣称 4B-4 完成。

## 5. 本轮不要求重复返工

- 不需要再处理 DroidCam；用户已确认不再使用虚拟/手机摄像头。
- 不需要因旧 DroidCam FAIL 降级新的 C960 Gate 0 PASS。
- 不需要再次修改 C960 索引为 `0`；当前正确设备是索引 `1`。
- 不要覆盖 `.embeddedskills/build/codex_camera_config_600s_20260804/`。
- 4B-2 C1 路线的软件验收此前已通过；除非 R3 的新映射改变其坐标契约，否则不要无关重写路线算法。

## 6. 纪律与边界

- 先用 `git status` 和 `git diff` 只读确认工作区；存在大量用户未提交改动，不得回滚或覆盖。
- 未经明确授权，不执行 `git add/commit/push/reset/checkout`。
- 未经用户当次授权，不烧录、不启动车轮、不发运动命令。
- 证据不可变：任何会写输出的复跑使用新目录。
- 明确区分：已核实事实、合理推测、证据不足、真实错误。
- 不得用离线测试代替真机证据，也不得用优化内部残差代替物理 holdout。

## 7. DS 返工回传格式

逐项回传 R1-R4：

1. `PASS / REJECT / INSUFFICIENT_EVIDENCE`
2. 实际修改文件
3. 精确复跑命令、关键输出、退出码
4. 新证据目录及哈希
5. 未验证事项
6. 是否建议整个 Task 4B 完工

只有 DS 完成返工并给出可复跑证据，且 Codex 再次独立复核同意后，相关项目才可关闭。当前允许关闭的仅是本次 C960 4B-1 Gate 0。
