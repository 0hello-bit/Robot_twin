# Robot Twin AI A4 全局 ChArUco 2 mm 标定设计

> 日期：2026-08-04
> 状态：方案选型已获用户批准；书面设计待用户复核
> 范围：固定 EMEET C960、固定 1280x720 画面、固定共面赛道
> 目标：新的、未参与模型选择的独立 holdout 绝对位置误差 `p95 <= 2.0 mm`

## 1. 背景与当前基线

当前 R3 不是 2 mm 映射。修正棋盘外角坐标后，两种独立计算相互印证：

- 原始像素 + 全局 homography + 每视图角度：9/7 holdout 外角 `p95=10.63 mm`，LOO `p95=11.01 mm`。
- 完整棋盘 PnP-IPPE 交叉检查：9/7 holdout `p95=11.18 mm`，LOO `p95=10.89 mm`。
- 当前内参去畸变会把同类 holdout 恶化到 `19.39 mm`，因此不得把现有内参直接当作全局精度依据。

结论：R3 保持 `BLOCKED`。当前约 10-11 mm 映射只能标记为
`EXPLORATORY_RELATIVE_ONLY`，不能覆盖 2 mm 硬门。

这里的 10-11 mm 是经修正的 raw-pixel 联合拟合证据，不是当前运行链自动具备的精度。现有 `PoseTracker` 会先使用旧内参去畸变，再调用 homography；而该去畸变路径的同类 holdout 为 `19.39 mm`。因此今晚不得仅给旧配置改名，必须先冻结并接通一个输入域、矩阵和消费者一致的 raw-pixel exploratory profile。

## 2. 设计原则

1. 内参与地面映射分开。内参使用倾斜、多姿态的小 A4 ChArUco；地面映射使用铺满赛道的全局板。
2. 固定相机、固定赛道优先使用全局密集控制点直接建立地面映射，不强迫单一 homography 解释镜头全场畸变。
3. 标定、模型选择、最终 holdout 三者隔离。最终 holdout ID 在采集前冻结，最终门只打开一次。
4. 路线位于地面，车顶 AprilTag 位于另一高度。两者不得继续共用“把标签中心直接投到地面”的近似。
5. 新证据写入新目录，不覆盖 R3、旧内参或旧 homography。
6. 2 mm 是验收目标，不是打印前的承诺。任何自动门不满足时状态保持 `BLOCKED`。

## 3. 物理标定板

### 3.1 全局板规格

| 项目 | 规格 |
|---|---|
| 纸张 | 20 张 A4，横向，打印比例 100%，禁止“适合页面” |
| 排列 | 5 列 x 4 行 |
| 每页有效图案 | 270 x 180 mm |
| 完整图案 | 1350 x 720 mm |
| ChArUco 方格 | 30 mm |
| ArUco 黑标 | 22 mm |
| 全局方格数 | 45 x 24 |
| 字典 | `DICT_4X4_1000` |
| ID | 全板唯一，按同一全局 board 生成后分页，不能逐页重新编号 |

分页边界落在方格边界上，因此标记不会被分页切断。每页页边空白区打印：页号、行列号、全局毫米范围、100 mm 校验尺、裁切线和配准十字；这些文字不得进入 ChArUco 有效区。

软件可行性预检已确认：该规格产生 540 个唯一 marker；将整板按相机覆盖比例渲染为 1280 x 683 时，OpenCV 5.0 能恢复全部 1012 个 ChArUco 角点。这只证明数字版图可检测，不替代打印和实拍验收。

### 3.2 世界坐标

全局板左上角为 board `(0,0)`，board y 向下。发车原点位于 board
`(690,480) mm`：

```text
world_x_mm    = board_x_mm - 690
world_y_up_mm = 480 - board_y_mm
```

覆盖范围：`x=-690..+660 mm`，`y=-240..+480 mm`。新世界坐标轴由打印板定义；不再用目测赛道边缘重新旋转坐标。

发车原点印十字和 1 mm 定位孔。铺板时定位孔对准赛道发车原点，板的 x 轴作为世界 x 轴。相机、支架和赛道从铺板开始到裸赛道采集结束均不得移动。

### 3.3 打印与拼接质量门

先打印单页测试件，实测 240 x 150 mm 校验框：

- x、y 任一方向误差 `>0.5 mm`：停止，不拼板，修正打印缩放后重印。
- 单页对角线差 `>0.7 mm`：停止，检查非等比缩放或纸张变形。

拼板使用全局尺标定位，不允许只按相邻页逐页累积：

- 每条接缝错位 `<=0.5 mm`。
- 0、270、540、810、1080、1350 mm 全局 x 标线相对统一直尺误差 `<=0.5 mm`。
- 0、180、360、540、720 mm 全局 y 标线相对统一直尺误差 `<=0.5 mm`。
- 完整宽、高实测分别为 `1350+/-1.0 mm`、`720+/-1.0 mm`；两条对角线差 `<=2.0 mm`。
- 板面翘起、折痕或接缝台阶 `>1.0 mm`：停止并重新压平。

标定算法排除距接缝或裁切边 `<=5 mm` 的角点，以及发车原点定位孔破坏或遮挡的角点。打印实测值、照片和 PDF SHA-256 写入 print manifest。

## 4. 采集与计算

### 4.1 独立内参

另生成一张单 A4 ChArUco 内参板。手持该板完成至少 48 张有效视图：覆盖画面 4 x 4 区域、四边四角、远近距离以及正负倾角。按视图冻结 calibration/validation 划分。

本机 OpenCV 5.0 没有 `calibrateCameraCharucoExtended` / `calibrateCameraCharuco` 旧入口。实现必须使用兼容链：

```text
CharucoDetector.detectBoard
  -> CharucoBoard.matchImagePoints
  -> cv2.calibrateCameraExtended
```

manifest 固定并记录 OpenCV 精确版本、dictionary、marker IDs、`legacyPattern` 显式值、board 参数和输入哈希；测试同时覆盖 OpenCV 返回 IDs 为 `(N,1)` 与 `(N,)` 的差异。

内参门：

- validation 重投影误差整体及 center/edge/corner 分区 `p95 <= 1.0 px`。
- 留一视图结果不得出现单独边缘区域明显发散。
- 相机矩阵、畸变参数、图像尺寸和输入图像哈希全部落盘。

现有 `intrinsics_c960.json` 只作历史对照；只有新内参通过以上门后，才可用于 AprilTag PnP。

### 4.2 全局地面映射

全局板铺平并固定后，锁定 1280x720、30 fps、焦点、曝光和白平衡，分三批采集，每批至少 30 个清晰帧。检测器按全局唯一 ID 恢复每个 ChArUco 角点的理想 board/world 坐标。

在读取任何实拍结果前，按全局 ChArUco corner ID 生成并冻结 `split_manifest.json`。同一 ID 在三批约 90 帧中必须始终属于同一集合，不允许按帧拆到 fit/holdout：

- fit：约 70%，覆盖每一页、中心、边缘和四角。
- validation：约 10%，用于在预声明模型中选型和调参。
- final holdout：至少 10%，每页均有点，且不参与拟合、模型选择或阈值调整。
- reserve holdout：至少 10%，首次验收全过程完全不可见；仅在首次 final 失败、模型被修改后，冻结为下一轮新的 final。
- seam-excluded 点不属于上述任何集合。

每个 ID 先对同一批内的检测坐标取稳健中位数，再用于拟合或绝对误差统计。p95 的独立样本单位是唯一物理 corner ID，不是重复帧；三批重复帧只用于检测漂移和稳定性指标。

预声明两个映射，不在看到 final holdout 后新增模型：

1. `undistort + homography`：可解释基线。
2. `global piecewise-affine mesh`：固定平面生产候选，直接用密集全局点吸收单 homography 无法描述的平滑全场残差；同时提供 `pixel_to_mm` 与 `mm_to_pixel`。

mesh 必须验证每个三角形为正 Jacobian、无翻转/折叠、相邻三角形局部尺度无异常跳变，并通过 mm->pixel->mm 往返门。模型选择只看 validation。选定后冻结网格拓扑、正则参数、模型文件和哈希，再对 final holdout 运行一次正式验收。

仅使用内部 ChArUco 角点时，有效凸包比 1350 x 720 mm 图案四周各缩进约 30 mm。实现可将检测可靠的外圈 ArUco marker corners 作为预声明边界控制点；无论是否采用，生产 ROI 必须取最终接受控制点的凸包与赛道 ROI 的交集，任何路线或小车点落在凸包外都返回无效，禁止外推。

### 4.3 2 mm 正式门

正式报告同时给出 overall、center、edge、corner、每页和三批重复采集结果：

- final holdout overall `p95 <= 2.0 mm`。
- center、edge、corner 各自 `p95 <= 2.0 mm`。
- final holdout `max <= 5.0 mm`，无无效映射点。
- 同一静止角点跨批次位置漂移 `p95 <= 0.5 mm`。
- 重新装载冻结模型复算，结果与首次逐字节一致。

final holdout 验证的是“图像 -> 打印板理想坐标”，它与打印制造误差并非完全独立。因此只有 §3.3 的物理尺度/接缝门和本节 final holdout 同时通过，才允许声称绝对毫米映射通过；任一部分缺失只能标记为 `INSUFFICIENT_EVIDENCE`。报告必须把打印尺具精度列入不确定度，不得把同一 PDF 的理想尺寸当成物理实测。

任一项失败即 `BLOCKED`。失败后的 final 点自动降为诊断数据，不得在调参后再次充当 final；下一轮必须使用预留 reserve，若 reserve 已使用或物理板/相机发生变化，则重新冻结新的独立证据。不得只报告训练残差、棋盘附近残差或视觉 overlay。

## 5. AprilTag 高度视差

当前 `PoseTracker` 已明确承认：车顶标签高于地面，却被地面 homography 直接投影，x/y 存在视差。这个近似不能进入 2 mm 版本。

新位姿链路使用：

```text
AprilTag 四角 + 标签真实边长
  -> 新内参下 solvePnP
  -> 全局板求得的 camera-to-world 外参
  -> 标签坐标系到小车参考点的实测 x/y/z/yaw 刚体偏置
  -> 地面上的小车参考点 x/y/yaw
```

必须实测并记录标签边长、标签平面离地高度、标签中心到小车控制参考点的 x/y 偏移和标签朝向偏差。4B-3 在新链路上重新做静态重复性和已知全局点绝对位置验收；地面映射通过但标签高度未修正时，4B-3 仍不得标记为 2 mm 可信。

## 6. 今晚 10 mm 临时推进边界

先建立独立 calibration ID（建议 `c960_r3_raw_global_exploratory_v1`），质量等级固定为 `EXPLORATORY_RELATIVE_ONLY`：

- matrix 必须来自修正后的 raw-pixel 全量联合拟合，并记录源报告哈希。
- profile 明确声明 `input_domain=RAW_PIXEL`，消费者不得再次 undistort 后再套该 matrix。
- 旧的 `undistorted pixel + homography_c960` 保留为历史配置，不得冒充 10 mm profile。
- 10-11 mm 只描述地面控制点。AprilTag 高度视差尚未修正，因此小车绝对 x/y 不得标成“11 mm 已验证”。
- calibration ID、input domain、映射哈希必须进入数据集和以后模型的身份；更换 2 mm profile 后，基于旧 profile 冻结的模型自动失效。

所有数据集同时保存原始帧、AprilTag 原始像素角点、路线像素点、遥测和 calibration ID，保证以后可用 2 mm 映射重投影而无需重采原始数据。

允许推进：

- 4B-4 时间同步、遥测批量、解析器、数据集与回放等不依赖绝对空间精度的离线工作。
- UI/overlay、粗略轨迹和同一相机/同一赛道的探索性 A/B 比较。
- 4B-5 控制器与虚拟传感器的软件接口、单元测试和 exploratory 输出。
- 为 4B-6/4B-7 准备数据结构、覆盖矩阵与模型骨架，但不冻结参数。

禁止：

- 宣称 4B-2 的 `p95 <= 2 mm` 前置已通过。
- 用该映射冻结 4B-7 行为模型或通过 4B-8 READY/G1-G8。
- 用其进行最终 PID 排名、danger recall、安全间隙、碰撞或出线保证。
- 没有用户当次明确授权时烧录、启动电机或运行真车。

今晚的离线顺序固定为：

1. 新增更正 handoff，冻结 raw-pixel exploratory profile，并让旧的 28-70 mm 报告和“板附近 0.380 mm”陈述明确降为历史局部结果。
2. 先修 4B-4 采集入口：现脚本仍硬加载旧 DroidCam 标定、绕过 C960 DirectShow/MJPG/30fps 公共工具，且只保存派生位姿。新入口必须显式选择 calibration profile，记录相机设置/哈希，并保存原始帧或视频、AprilTag 原始像素角点和逐帧单调时间戳；旧脚本不得生成新的 C960 验收证据。
3. 按现有遥测批量设计完成 4B-4 的离线 TDD、Host C、Python 和 Keil 复核；保持 `p95<=33.3 ms` 原门，不因当前约 10 Hz 到达率而降低门槛。
4. 4B-5 先逐行核对真实固件控制公式并完成控制器。不得依赖计划中提到、但当前固件并不存在的 `SENSOR_THRESHOLD` 宏；真实语义是四路数字 GPIO 的黑线电平取反/稳定，再进入离散误差、滤波、D/积分限幅和 `turn_gain`。虚拟传感器只作 exploratory 实现，并须先补 world-to-mask/metric raster 契约，因为当前 mask 是像素域而 centerline/width 是毫米域。
5. 4B-6/4B-7 只做数据结构、合成恢复、覆盖矩阵、隔离和冻结机制测试，停在正式拟合和 4B-8 之前。

正式 gate 消费者必须拒绝 `EXPLORATORY_RELATIVE_ONLY`；只能接受
`HOLDOUT_VERIFIED_2MM`。这条防线防止今晚的临时结果以后被误当正式证据。

## 7. 预计产物

实现计划应覆盖以下新增产物，具体文件拆分由实施计划确定：

- 全局 ChArUco A4 分页 PDF、单页内参板 PDF、拼接地图和 print manifest。
- 全局板检测/采集、split manifest、地面映射拟合和独立验收工具。
- 支持 homography 与 mesh 的统一 ground transform 接口，并保留旧格式兼容读取。
- AprilTag PnP + tag-to-car 刚体偏置的新位姿路径。
- calibration ID、质量等级和正式 gate 拒绝规则。
- 单元测试、合成畸变测试、PDF 渲染检测测试和新证据目录：
  `.embeddedskills/build/v1_task4b2_r4_global_charuco/`。

PDF 生成不能依赖位图 DPI 元数据。实施环境应锁定 `reportlab` 与 PDF 解析依赖的精确版本，按 A4 物理 point 尺寸绘制；使用现有 Poppler `pdfinfo`/`pdftoppm` 在 300/600 dpi 渲染复核页面尺寸、裁切和检测结果。

## 8. 验证与交接

软件阶段必须完成：

1. PDF 每页物理尺寸、有效区尺寸、ID 唯一性、分页连续性和原点坐标自动检查。
2. 渲染 20 页并重组虚拟整板，OpenCV 能恢复全局 ID/坐标。
3. 合成透视、径向畸变和噪声下，fit/validation/final holdout 无泄漏。
4. transform 往返、边界、序列化和旧 homography 兼容测试。
5. exploratory 质量等级能继续非正式流水线，但被 4B-7/4B-8 正式门拒绝。

物理阶段由用户打印、测量、拼接和放置；代理只能复核记录与采集结果。最终 handoff 必须明确区分：软件生成已验证、打印装配实测、相机采集实测、独立 holdout 结果和仍未验证项。

## 9. 预期精度与失败处理

在单页缩放和接缝均控制到 0.5 mm、板面平整、相机不动且检测覆盖充分时，预计 final holdout p95 约为 1.2-2.0 mm；这是工程估计，不是已验证事实。普通手工拼接更可能为 2-4 mm。

若未达到 2 mm，按以下顺序诊断，不降低门槛：打印尺度/接缝/平整度 -> 图像清晰度与曝光 -> ID/坐标错误 -> 内参稳定性 -> homography 与 mesh 的 validation 差异 -> 标签高度链路。失败报告保留全部原始数据，下一轮写入新的证据目录。
