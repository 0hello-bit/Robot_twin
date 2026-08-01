# Robot Twin AI V1.5 轮式机器人可迁移架构设计

## 1. 背景与定位

Robot Twin AI 的当前 V1 以“大圣小车”巡线 PID 自动优化闭环为首个验证场景。V1 的目的，是证明“数字模型预筛选、受限参数部署、真车测试、指标评价、接受或回滚、结果记录”能够形成安全且可复现的闭环。

V1.5 的目标不是扩大本轮小车功能，而是把已经验证的闭环能力整理成可迁移平台，使下一台轮式机器人只需实现机器人专用适配层，而不需要复制或重写活动管理、评价、优化、回滚和报告系统。

直接目标是兼容不同控制器、通信方式、传感器和运动形式的轮式机器人。机械臂、无人机、四足机器人和自主 PCB 设计属于更长期扩展，本设计只为其保留接口，不承诺在 V1.5 中直接兼容。

## 2. 设计原则

1. **实时控制留在机器人端。** 毫秒级 PID、电机输出、急停、看门狗和硬件保护必须由 MCU、实时控制器或本地安全进程执行，不能依赖 MCP、AI 或网络往返。
2. **AI 只通过受限能力操作机器人。** AI 不得生成裸电机命令，也不得绕过参数范围、版本校验、安全策略和人工审批。
3. **通用核心不依赖具体硬件。** 活动、运行、指标、优化、回滚和报告模块不得直接导入 ESP、STM32、CAN、ROS 或某一传感器的实现。
4. **机器人差异通过适配器和声明文件表达。** 新机器人必须显式声明能力，不允许核心或 AI 根据文件名、外观或历史项目猜测硬件。
5. **MCP 是控制面，不是实时数据面。** MCP 负责向 AI 暴露稳定、可审计的工具；高频遥测由本地服务采集和保存，MCP 返回摘要、状态或数据引用。
6. **Skill 规定流程，代码保证约束。** Skill 可以指导 AI 按正确顺序调用工具，但安全边界必须由固件、适配器和核心代码强制执行。
7. **所有接口必须版本化并可验证。** Manifest、参数、遥测、MCP 工具和适配器契约均包含版本，并提供自动兼容性测试。

## 3. 总体架构

```text
AI Agent
   |
   +-- Robot Twin Skill
   |      规定能力发现、模拟、部署、测试、评价和回滚流程
   |
   +-- Robot Twin MCP Server
          提供稳定、受审计的工具接口
                    |
                    v
          Robot Twin Core
          活动 / 存储 / 指标 / 优化 / 编排 / 报告
                    |
                    v
          Robot Adapter Contract
          能力 / 参数 / 遥测 / 安全 / 数字孪生 / 传输
                    |
          +---------+-------------------+
          |                             |
   Dasheng STM32 Adapter         Future Wheeled Adapter
   ESP + P/R/A/S + AA55          CAN / ROS / Serial / Other
          |                             |
          v                             v
   MCU 实时控制与保护             机器人实时控制与保护
```

架构分成三个运行平面：

- **实时平面：** MCU 或机器人控制器运行闭环控制、执行器保护和本地急停。
- **执行与数据平面：** Robot Adapter、本地通信服务、数字孪生、数据存储和测试执行器。
- **AI 控制平面：** MCP Server 与 Skill，用于能力发现、任务编排、解释和决策。

## 4. Robot Twin Core

Robot Twin Core 是平台中最需要保持稳定和可迁移的部分，包括：

- `CampaignManager`：创建和维护一次优化活动；
- `RunManager`：管理基线运行和候选运行；
- `CampaignStore`：保存原始数据、参数版本、状态和报告；
- `MetricEvaluator`：计算误差、完成率、安全停止、耗时等指标；
- `CandidateOptimizer`：在参数 Schema 允许的范围内生成候选；
- `CampaignOrchestrator`：执行模拟、部署、运行、评价、接受或回滚；
- `ReportBuilder`：生成可追溯的活动报告。

Core 只能依赖抽象接口和规范化数据结构。任何机器人专用字节帧、AT 命令、引脚、电机编号和网络地址都不得进入 Core。

## 5. Robot Manifest

每种机器人必须提供一个版本化的 `robot_manifest.yaml`。首版至少包含：

```yaml
schema_version: 1
robot_type: dasheng_stm32_line_car
display_name: 大圣 STM32 巡线车

controller:
  family: STM32F103C8
  realtime_loop_ms: 5

capabilities:
  runtime_parameter_update: true
  start_stop: true
  rollback: true
  digital_twin: true
  firmware_flash: false

parameters:
  schema: schemas/line_pid_parameters.json

telemetry:
  schema: schemas/line_following_telemetry.json

transport:
  adapter: dasheng_esp_tcp

safety:
  policy: policies/dasheng_line_car.yaml

twin:
  adapter: dasheng_line_twin
```

Manifest 表示“机器人声明支持什么”，不是“平台假设机器人具有什么”。能力为 `false` 或缺失时，MCP 不得暴露对应的可执行操作。

## 6. Robot Adapter Contract

轮式机器人适配器必须实现以下逻辑接口：

```python
class RobotAdapter:
    async def health(self) -> RobotHealth: ...
    async def capabilities(self) -> RobotCapabilities: ...
    async def deploy_parameters(self, packet: ParameterPacket) -> DeploymentAck: ...
    async def start_run(self, run: RunRequest) -> RunStatus: ...
    async def stop_run(self, reason: str) -> RunStatus: ...
    async def rollback(self, target_version: str) -> DeploymentAck: ...
    async def telemetry_stream(self, run_id: str): ...
    async def run_status(self, run_id: str) -> RunStatus: ...
```

接口表达的是语义，不规定底层通信方式。ESP TCP、UART、CAN、ROS 2、蓝牙或其他传输均在适配器内部处理。

每个适配器还必须提供：

- `ParameterSchema`：参数类型、单位、范围、单步限制和版本规则；
- `TelemetrySchema`：规范化的时间、状态、误差、执行器输出和机器人专用扩展字段；
- `SafetyPolicy`：部署前置条件、急停、超时、失联和回滚策略；
- `TwinAdapter`：将规范化参数和场景输入映射到该机器人的数字模型；
- `TransportAdapter`：底层连接、分帧、重连和可靠传输。

## 7. 规范化数据封装

所有遥测和状态都使用统一信封，机器人专用字段放入扩展区：

```json
{
  "schema_version": 1,
  "robot_id": "dasheng-001",
  "campaign_id": "campaign-001",
  "run_id": "run-003",
  "parameter_version": 4,
  "timestamp_ms": 1200,
  "state": "running",
  "safety": {
    "stopped": false,
    "reason": ""
  },
  "metrics_source": {
    "tracking_error": 0.18,
    "actuator_outputs": [420, 385, 385, 420]
  },
  "extensions": {
    "line_sensors": [1, 1, 0, 0],
    "yaw_deg": 3.25
  }
}
```

Core 只读取标准字段和该活动声明使用的指标源。机器人专用扩展不得成为 Core 的隐式依赖。

## 8. MCP Server

MCP Server 是 Robot Twin Core 面向 AI Agent 的标准控制接口。首版建议暴露：

- `robot_list`
- `robot_get_manifest`
- `robot_health`
- `campaign_create`
- `campaign_status`
- `campaign_generate_candidates`
- `campaign_simulate_candidate`
- `campaign_deploy_candidate`
- `campaign_start_run`
- `campaign_stop`
- `campaign_evaluate`
- `campaign_rollback`
- `campaign_get_report`

所有会改变机器人状态的工具必须：

1. 校验机器人能力；
2. 校验活动和参数版本；
3. 校验安全策略；
4. 生成审计记录；
5. 返回明确 ACK 或失败原因；
6. 在超时、断线和状态不确定时进入安全停止，不得假定操作成功。

MCP 不直接持续传输高频原始遥测。原始数据由本地采集器写入活动存储，MCP 返回运行状态、指标摘要或数据文件引用。

## 9. Robot Twin Skill

Skill 是 AI 使用 MCP 的标准操作规程，应规定：

1. 先调用 `robot_get_manifest` 和 `robot_health`；
2. 不支持的能力不得尝试；
3. 建立基线并检查有效运行次数；
4. 候选先通过数字模型筛选；
5. 参数部署必须获得匹配活动和版本的 ACK；
6. ACK 后才能启动真实运行；
7. 出线、急停、断线、超时或数据无效时先停止再回滚；
8. 不得伪造遥测、补全缺失测试或把模拟结果当真车证据；
9. 最终报告必须区分软件、模拟和真实硬件证据。

Skill 不能成为唯一的安全实现。即使 AI 不遵守 Skill，MCP、Core、Adapter 和固件仍必须拒绝危险操作。

## 10. 大圣小车映射

当前大圣小车将作为首个 Adapter：

- `P/R/A/S` 行协议映射到参数部署和运行控制；
- ESP `+IPD` 解析属于 `TransportAdapter`；
- `AA 55` 24 字节遥测映射到规范化 `TelemetryEnvelope`；
- STM32 参数范围、单步限制、STOP、TIMEOUT 和基线恢复属于固件与 `SafetyPolicy`；
- 当前巡线数字模型由 `TwinAdapter` 包装；
- Core 不得直接引用 `main.c`、ESP 客户端 ID或 `AA 55` 字段偏移。

V1 当前实现可以继续按既定六个任务完成。V1.5 在 V1 验收后进行提取，不在 Task 1 或 Task 2 中提前大规模重构。

## 11. 错误与安全模型

平台统一使用可机器判断的错误类别：

- `capability_not_supported`
- `health_check_failed`
- `parameter_invalid`
- `version_mismatch`
- `deployment_rejected`
- `ack_timeout`
- `transport_disconnected`
- `telemetry_invalid`
- `safety_stop`
- `rollback_failed`
- `state_conflict`

状态不确定时必须按失败处理。任何部署或运行命令超时后，Core 不能自行推定机器人已经执行，也不能继续部署下一候选。

固件烧录、Flash 擦除、PCB修改、真实电机动作和高风险测试不作为普通 MCP 自动工具开放；未来需要独立审批能力和更严格的安全执行器。

## 12. 可迁移性验收

V1.5 只有同时满足以下条件才算具备实际可迁移性：

1. 大圣小车通过 Robot Adapter 运行完整闭环；
2. 新增一个 Mock 轮式机器人 Adapter，不修改 Core 即可完成同一闭环；
3. 再新增一个传输或传感器结构不同的轮式机器人 Adapter，Core 仍无需修改；
4. 所有 Adapter 通过同一套契约测试；
5. MCP 工具 Schema 不因机器人型号变化；
6. 更换机器人后仅替换 Manifest、Schema、Adapter、SafetyPolicy 和 TwinAdapter；
7. 缺失能力、错误版本、断线和回滚失败均有一致且可审计的结果。

可迁移性的证据不是目录结构或接口声明，而是“第二种机器人在不修改 Core 的前提下通过相同契约和闭环测试”。

## 13. 测试策略

- **Core 单元测试：** 活动、指标、优化、状态机、回滚和持久化；
- **Adapter 契约测试：** 使用统一测试套件验证每个机器人适配器；
- **协议一致性测试：** 固件端、PC 端和 Adapter 对相同向量产生相同结果；
- **MCP Schema 测试：** 工具参数、返回值和错误类型保持兼容；
- **安全故障测试：** ACK 超时、断线、状态冲突、无效遥测和回滚失败；
- **迁移演示测试：** 大圣小车 Adapter 与 Mock 第二机器人运行同一闭环；
- **真实硬件测试：** 只在独立硬件 Work 中执行，并与软件和模拟证据分开记录。

## 14. 非目标

V1.5 不包含：

- 通过 MCP 执行毫秒级实时控制；
- 任意自然语言直接生成电机命令；
- AI 自动修改和烧录固件；
- 自动修改原理图或 PCB 并直接制造；
- 不经校准就复用其他机器人的数字孪生模型；
- 宣称一个适配器即可覆盖所有机器人类型。

这些能力只能在轮式机器人闭环和安全执行边界得到充分验证后分阶段引入。

## 15. 实施时机

1. 当前继续完成既定 V1 六个任务，避免为抽象而阻塞首个闭环。
2. Task 2 至 Task 5 实现时保持传输、遥测、优化和编排边界，避免新增硬件专用依赖。
3. V1 真车验收后启动 V1.5 提取工作。
4. 先将大圣小车包装为首个 Adapter，再以 Mock 第二机器人验证 Core 未被硬编码。
5. 完成 MCP Server 和配套 Skill，最后用另一类轮式机器人验证实际迁移。

