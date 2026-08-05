# MPU6050 Observability Audit

日期：2026-08-05  
范围：对当前工作区的固件、遥测协议、Python parser、数字孪生和计划文档做静态只读审计。本文不是 MPU6050 真机验收，也不授权其参与电机控制。

## 已核实事实

- 当前 Keil `Target 1` 编译清单包含 `Hardware/mpu6050.c`：[project.uvprojx](../../../程序/3.%20麦轮巡线小车/project.uvprojx#L708)。主程序包含头文件并执行 `MPU6050_Init()`：[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L8)、[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L673)。
- 驱动实现的是软件 I2C，使用 `PB10=SCL`、`PB11=SDA`，地址固定为 `0x68`：[mpu6050.c](../../../程序/3.%20麦轮巡线小车/Hardware/mpu6050.c#L4)、[mpu6050.h](../../../程序/3.%20麦轮巡线小车/Hardware/mpu6050.h#L7)。这不是 STM32 的 I2C 外设驱动。
- 初始化依次复位、唤醒、设置 `SMPLRT_DIV=4`（代码注释为 200 Hz）、`CONFIG=3`（注释约 44 Hz DLPF）、陀螺 +/-500 deg/s、加速度 +/-4 g，并读取 `WHO_AM_I` 要求为 `0x68`：[mpu6050.c](../../../程序/3.%20麦轮巡线小车/Hardware/mpu6050.c#L191)。
- 初始化会做 100 次 Z 轴陀螺原始值采样、每次 `Delay_ms(2)`，计算 `gz_bias`；不校准 X/Y 轴陀螺或加速度计：[mpu6050.c](../../../程序/3.%20麦轮巡线小车/Hardware/mpu6050.c#L216)。
- `MPU6050_ReadAll()` 读取 14 字节并保存原始 `ax/ay/az/gx/gy/gz`；温度字节跳过：[mpu6050.c](../../../程序/3.%20麦轮巡线小车/Hardware/mpu6050.c#L235)。
- 只有 Z 轴陀螺参与姿态计算：用 `65.5 LSB/(deg/s)` 换算为 `gz_dps`，用一阶滤波 `0.85 * old + 0.15 * new`，再积分为 `yaw`（度）：[mpu6050.c](../../../程序/3.%20麦轮巡线小车/Hardware/mpu6050.c#L254)。没有 pitch/roll、加速度融合、磁力计或绝对航向参考。
- 主循环仅在运动未被抑制时轮询 IMU；`dt` 来自 TIM3 的单调毫秒计数器并钳在 1--100 ms：[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L787)、[mono_time.c](../../../程序/3.%20麦轮巡线小车/System/mono_time.c#L4)。
- 二进制遥测 `0x01` 为 24-byte payload；最后四字节是 little-endian signed `yaw * 100`，前面的四字节 `tick_ms` 是 MCU 单调毫秒：[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L235)。发送的名义阈值为 20 ms：[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L450)。
- Python parser 对 payload 末尾四字节除以 100 得出 `yaw`，即实际单位是 degree：[frame_parser.py](../../../simulation/digital_twin/real_world/frame_parser.py#L218)。两个 WiFi bridge 都将该值转发给上层：[wifi_bridge.py](../../../simulation/digital_twin/real_world/wifi_bridge.py#L294)、[live_wifi_bridge.py](../../../simulation/digital_twin/web_showcase/live_wifi_bridge.py#L1904)。
- 控制回路未读取 IMU 值。线传感器误差构成 PID，随后以 `speed +/- turn` 驱动电机：[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L908)。`mpu_data.yaw` 的主目标消费仅为遥测编码：[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L849)、[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L877)、[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L1009)。
- 目前主工程的 PB10/PB11 不与电机 PWM 的 PB6--PB9 或巡线传感器的 PB0/PB1/PB4/PB5 冲突：[Motor.c](../../../程序/3.%20麦轮巡线小车/Hardware/Motor.c#L81)、[Sensor.c](../../../程序/3.%20麦轮巡线小车/Hardware/Sensor.c#L23)。
- 当前文档将 MPU6050 问题归入未来地面试跑要发现的事项，而非已验收能力：[2026-08-04-ground-shakedown-recorder-design.md](../../superpowers/specs/2026-08-04-ground-shakedown-recorder-design.md#L8)。历史 `yaw_rad` 字段已被文档明确标为实际 degree：[2026-08-04-ground-shakedown-recorder.md](../../superpowers/plans/2026-08-04-ground-shakedown-recorder.md#L22)。

## 合理推断

- MPU6050 不是遗留死代码：它已进入当前固件的初始化、轮询和遥测路径。但它只是未验收的观测量，不是控制量。
- 驱动中配置的 200 Hz 是器件寄存器目标速率，不等价于已证实的 MCU 实际采样率、网络发送率或数字孪生接收率。读取由主循环轮询，并在 motion-inhibited 状态停止；实际频率会受主循环和传输负载影响。
- 当前 yaw 是无绝对参考的 Z 轴相对积分角，静态零偏只能减缓而不能消除漂移；它不应被表述为车体绝对航向，也不能直接与相机 yaw 比较。

## 证据不足

- 没有本次或可追溯的真机证据证明 MPU 模块存在、PB10/PB11 实际连通、外部上拉和 3.3 V 电平正确、AD0 地址为 `0x68`，或 `WHO_AM_I`/读数确实成功。
- 没有试验数据证明 100 样本零偏收敛、噪声水平、yaw 符号、比例、漂移或动态角速度有效。
- 没有车体坐标系、IMU 安装方向、右手系、车头零向、正 yaw 方向、yaw 包络和 MCU yaw 至相机/数字孪生坐标变换的定义。相机 yaw 也尚未完成与车头的绝对方向对齐：[Robot_Twin_AI_完整计划说明书_v2.0.md](../../Robot_Twin_AI_完整计划说明书_v2.0.md#L191)。
- 遥测不含原始/校正 `ax..gz`、温度、IMU 样本时间戳、样本序号、数据有效位或失败原因；因此上位机无法区分静止、陈旧值、总线失败和未初始化。
- 没有覆盖 MPU 寄存器写入、读失败、校准、单位/符号、积分、时间戳回绕或 parser 协议互操作的离线测试。已有构建、模拟或非 IMU 硬件证据不能替代这些证据。

## 已发现缺陷

1. **初始化失败没有锁存。** `MPU6050_Init()` 在 I2C 写失败、WHO_AM_I 不匹配或校准读取失败时直接 `return`，仅保留先前写入的 `ready=0`：[mpu6050.c](../../../程序/3.%20麦轮巡线小车/Hardware/mpu6050.c#L179)。但主循环无条件在解除运动抑制后继续调用 `MPU6050_ReadAll()`：[main.c](../../../程序/3.%20麦轮巡线小车/User/main.c#L787)。只要之后一次 14-byte 读取成功，`MPU6050_ReadAll()` 就会直接写入 `ready=1`：[mpu6050.c](../../../程序/3.%20麦轮巡线小车/Hardware/mpu6050.c#L238)。因此 `ready` 不能证明初始化配置、ID 校验和零偏校准均已成功。
2. **状态不可观测。** 即使读取失败时 `ready` 被清零，当前遥测不发送 `ready` 或任何 IMU health 字段；上位机仍只会收到 yaw 数值，无法安全解释其质量。
3. **标称采样率与实际时间基未绑定。** `SMPLRT_DIV` 的配置、主循环 `dt` 和遥测 `tick_ms` 是不同层的时间概念，没有样本 tick 或数据就绪中断来证明具体积分对应哪一个传感器样本。
4. **坐标与单位的兼容风险。** 固件/parse 实际用 degree，而历史字段曾称 `yaw_rad`；同时没有定义正方向和安装矩阵。任何跨相机、孪生和固件的 yaw 比较均可能出现符号、零点或单位错误。

## 建议的最小遥测 Schema

在保留现有控制字段的前提下，新增独立、版本化的 IMU 区块；未完成离线测试和真机 gate 前，不改变控制逻辑。

| 字段 | 类型和单位 | 语义 |
| --- | --- | --- |
| `imu_ready` | `bool` | 仅当配置写入、WHO_AM_I、静止校准和当前总线健康都满足定义时为真；初始化失败必须锁存为假，除非显式、可记录地重新初始化成功。 |
| `sample_tick_ms` | `uint32`, MCU 单调 ms | 完成该 IMU 样本读取的本地采样时刻；不能借用遥测排队或 PC 接收时刻。 |
| `gz_dps` | `float32`, deg/s | 已减零偏、滤波策略版本明确后的车体 Z 轴角速度；应保留或版本化原始值以便追溯。 |
| `yaw_deg` | `float32`, degree | 从定义的 yaw 零点起的相对积分航向，明确不是绝对航向；应规定是否 wrap 到 [-180, 180) 或连续累积。 |
| `validity` | 位图/枚举 | 至少区分 `BUS_OK`、`CONFIG_OK`、`WHOAMI_OK`、`BIAS_OK`、`SAMPLE_FRESH`、`DT_CLAMPED`、`STALE`、`READ_ERROR`。 |

坐标和单位约定必须随 schema 一并写死：车体系采用的轴向、Z 轴正向、绕 Z 正方向（右手定则）、模块到车体系的安装矩阵、`gz_dps` 的正号和 `yaw_deg` 零点/包络。没有该约定，字段虽能传输却不可可靠融合。

## 后续真机 Gate

以下操作须在后续取得用户明确硬件授权后进行；本审计没有执行它们。

1. 电机断电或轮子悬空，确认 PB10/PB11、GND、供电、上拉、电平和 AD0；先只读 WHO_AM_I，记录时间、固件版本和结果。
2. 静止采样足够长的原始 `gz`，量化零偏、标准差和 `imu_ready` 状态转换；验证校准失败后不会自行恢复为 ready。
3. 在受控手动正/反向转动中，验证 `gz_dps` 和 `yaw_deg` 的符号、比例、dt、漂移以及 `sample_tick_ms` 单调性。
4. 仅在坐标系已定义后，做低风险的相对转角相机对比；不将相机结果或单次成功读数误报为 IMU 控制有效性。
5. 通过上述 gate、离线测试和安全评审后，才可单独评估“IMU 是否适合作为控制观测量”的新需求。

## 控制边界

**在初始化锁存、数据有效性、单位/坐标约定、离线测试和上述真机 gate 均未验收前，禁止将 MPU6050 的 yaw、角速度、加速度或任何派生姿态量接入电机输出、PID、速度规划、转向、停止判据或自动安全结论。** 当前允许范围仅为带明确有效性标记的观测和数据采集。
