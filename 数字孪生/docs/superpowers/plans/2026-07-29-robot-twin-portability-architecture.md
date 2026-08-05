# Robot Twin AI V1.5 Portability Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将大圣小车已验收的 PID 优化闭环提取为面向轮式机器人的通用 Core、Robot Adapter、MCP Server 和 Robot Twin Skill，并用多个适配器契约测试证明 Core 不依赖具体硬件。

**Architecture:** 保留 MCU/控制器的实时控制与安全保护，以 `RobotAdapter` 隔离通信、参数、遥测、安全策略和数字孪生差异；Robot Twin Core 只处理活动、评价、优化、部署编排和报告。官方 MCP Python SDK v2 仅暴露 AI 控制面工具，高频遥测留在本地数据平面；Skill 规定 AI 的安全调用流程。

**Tech Stack:** Python 3.10+、dataclasses、ABC、PyYAML 6.x、pytest、官方 MCP Python SDK v2、现有 STM32 `P/R/A/S` 与 `AA 55` 协议、现有 V1 campaign/optimizer/orchestrator 模块。

## Global Constraints

- 本计划只能在当前 V1 六个任务和真车验收完成后正式执行；不得为了 V1.5 重构阻塞当前 V1。
- 当前工作区没有 Git 仓库；不得运行 `git init`，每个任务以文件清单、测试命令、测试结果和未验证项作为交接证据。
- Python 必须使用 `C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe`；不得使用缺少当前测试依赖的系统 Python 3.7。
- Python 支持范围保持 `>=3.10`。
- MCP SDK 使用当前稳定 v2 线：`mcp>=2,<3`。官方 SDK v2 使用 `from mcp.server import MCPServer`，并支持内存客户端测试。
- `PyYAML>=6,<7` 只用于机器人 Manifest 和安全策略；参数与遥测 Schema 使用标准 JSON。
- MCP、AI 和网络不得承担毫秒级 PID、急停、看门狗或电机保护。
- Core 不得直接导入或引用 ESP、STM32、CAN、ROS、UART、引脚、电机编号、`+IPD` 或 `AA 55` 字段偏移。
- AI 不得通过平台发送裸电机命令、自动烧录固件、擦除 Flash 或绕过安全策略。
- 状态不确定、ACK 超时或传输断线一律按失败处理；不得推定命令已经执行。
- 每次只允许一个候选参数版本处于 deployed/running 状态。
- 真实硬件证据必须在独立硬件 Work 中取得；Mock、单元测试和编译结果不得描述成第二台真实机器人迁移成功。
- 每个 Task 由独立代理完成并验收，后一个 Task 只能使用前一个 Task 报告中明确列出的接口。

---

## Planned File Structure

```text
simulation/digital_twin/
├─ robot_twin/
│  ├─ __init__.py
│  ├─ errors.py
│  ├─ models.py
│  ├─ adapter.py
│  ├─ manifest.py
│  ├─ registry.py
│  ├─ core.py
│  ├─ mcp_server.py
│  ├─ adapters/
│  │  ├─ __init__.py
│  │  ├─ dasheng.py
│  │  ├─ mock_line_car.py
│  │  └─ mock_encoder_car.py
│  ├─ manifests/
│  │  ├─ dasheng_stm32_line_car.yaml
│  │  ├─ mock_line_car.yaml
│  │  └─ mock_encoder_car.yaml
│  ├─ schemas/
│  │  ├─ line_pid_parameters.json
│  │  ├─ line_following_telemetry.json
│  │  ├─ encoder_pid_parameters.json
│  │  └─ encoder_telemetry.json
│  └─ policies/
│     ├─ dasheng_line_car.yaml
│     ├─ mock_line_car.yaml
│     └─ mock_encoder_car.yaml
├─ tests/
│  ├─ test_robot_contracts.py
│  ├─ test_robot_manifest.py
│  ├─ test_robot_twin_core.py
│  ├─ test_dasheng_adapter.py
│  ├─ test_adapter_portability.py
│  ├─ test_robot_twin_mcp.py
│  └─ test_robot_twin_integration.py
├─ skills/
│  └─ robot-twin-ai/
│     └─ SKILL.md
└─ docs/
   └─ porting-a-wheeled-robot.md
```

Existing V1 files expected to be consumed, not duplicated:

```text
analysis/campaign_metrics.py
analysis/campaign_optimizer.py
analysis/sim_candidate_filter.py
analysis/campaign_orchestrator.py
real_world/campaign_store.py
real_world/runtime_protocol.py
real_world/telemetry_protocol.py
web_showcase/live_wifi_bridge.py
```

## Specification Coverage Map

- Design Sections 1–3 (scope, principles, three operating planes): Global Constraints and Tasks 1–3.
- Design Section 4 (Robot Twin Core): Task 3.
- Design Sections 5–7 (Manifest, Adapter contract, normalized data): Tasks 1–2.
- Design Section 8 (MCP Server): Task 6.
- Design Section 9 (Robot Twin Skill): Task 7.
- Design Section 10 (Dasheng mapping): Task 4.
- Design Section 11 (typed errors and safety model): Tasks 1, 3, 4 and 6.
- Design Section 12 (portability acceptance): Tasks 5 and 8.
- Design Section 13 (test strategy): every Task's test gate plus Task 8 full integration.
- Design Section 14 (non-goals): Global Constraints and the Final Acceptance Gate.
- Design Section 15 (implementation timing): the V1 prerequisite in Global Constraints.

---

### Task 1: Define Versioned Domain Models and Robot Adapter Contract

**Files:**
- Create: `simulation/digital_twin/robot_twin/__init__.py`
- Create: `simulation/digital_twin/robot_twin/errors.py`
- Create: `simulation/digital_twin/robot_twin/models.py`
- Create: `simulation/digital_twin/robot_twin/adapter.py`
- Test: `simulation/digital_twin/tests/test_robot_contracts.py`

**Interfaces:**
- Consumes: no V1 implementation modules; Python standard library only.
- Produces: `RobotAdapter`, `RobotHealth`, `RobotCapabilities`, `ParameterPacket`, `DeploymentAck`, `RunRequest`, `RunStatus`, `TelemetryEnvelope`, `RobotTwinError`.

- [ ] **Step 1: Write failing immutable-model tests**

```python
from dataclasses import FrozenInstanceError

import pytest

from robot_twin.models import ParameterPacket, TelemetryEnvelope


def test_parameter_packet_is_immutable_and_versioned():
    packet = ParameterPacket(
        schema_version=1,
        robot_id="dasheng-001",
        campaign_id="campaign-001",
        parameter_version=2,
        values={"kp": 35.0, "ki": 0.0, "kd": 10.0, "speed_max": 680},
    )
    assert packet.parameter_version == 2
    with pytest.raises(FrozenInstanceError):
        packet.parameter_version = 3


def test_telemetry_envelope_separates_standard_and_extension_fields():
    packet = TelemetryEnvelope(
        schema_version=1,
        robot_id="dasheng-001",
        campaign_id="campaign-001",
        run_id="run-001",
        parameter_version=2,
        timestamp_ms=20,
        state="running",
        tracking_error=0.25,
        actuator_outputs=(400.0, 380.0, 380.0, 400.0),
        safety_stopped=False,
        safety_reason="",
        extensions={"line_sensors": [1, 1, 0, 0]},
    )
    assert packet.tracking_error == 0.25
    assert packet.extensions["line_sensors"] == [1, 1, 0, 0]
```

- [ ] **Step 2: Run tests and confirm missing-module failure**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_robot_contracts.py -v
```

Expected: collection fails because `robot_twin.models` does not exist.

- [ ] **Step 3: Implement typed error categories**

```python
class RobotTwinError(RuntimeError):
    code = "robot_twin_error"


class CapabilityNotSupported(RobotTwinError):
    code = "capability_not_supported"


class HealthCheckFailed(RobotTwinError):
    code = "health_check_failed"


class ParameterInvalid(RobotTwinError):
    code = "parameter_invalid"


class VersionMismatch(RobotTwinError):
    code = "version_mismatch"


class DeploymentRejected(RobotTwinError):
    code = "deployment_rejected"


class AckTimeout(RobotTwinError):
    code = "ack_timeout"


class TransportDisconnected(RobotTwinError):
    code = "transport_disconnected"


class TelemetryInvalid(RobotTwinError):
    code = "telemetry_invalid"


class SafetyStop(RobotTwinError):
    code = "safety_stop"


class RollbackFailed(RobotTwinError):
    code = "rollback_failed"


class StateConflict(RobotTwinError):
    code = "state_conflict"
```

- [ ] **Step 4: Implement immutable domain dataclasses**

Use `@dataclass(frozen=True)` for every cross-layer value. Define:

```python
@dataclass(frozen=True)
class RobotHealth:
    connected: bool
    ready: bool
    safe: bool
    reason: str


@dataclass(frozen=True)
class RobotCapabilities:
    runtime_parameter_update: bool
    start_stop: bool
    rollback: bool
    digital_twin: bool
    firmware_flash: bool = False


@dataclass(frozen=True)
class ParameterPacket:
    schema_version: int
    robot_id: str
    campaign_id: str
    parameter_version: int
    values: Mapping[str, float | int]


@dataclass(frozen=True)
class DeploymentAck:
    robot_id: str
    campaign_id: str
    parameter_version: int
    applied: bool
    reason: str


@dataclass(frozen=True)
class RunRequest:
    robot_id: str
    campaign_id: str
    run_id: str
    parameter_version: int


@dataclass(frozen=True)
class RunStatus:
    robot_id: str
    campaign_id: str
    run_id: str
    state: str
    reason: str
    tick_ms: int


@dataclass(frozen=True)
class TelemetryEnvelope:
    schema_version: int
    robot_id: str
    campaign_id: str
    run_id: str
    parameter_version: int
    timestamp_ms: int
    state: str
    tracking_error: float
    actuator_outputs: tuple[float, ...]
    safety_stopped: bool
    safety_reason: str
    extensions: Mapping[str, object]
```

Reject empty IDs, non-positive versions and negative timestamps in `__post_init__`.

- [ ] **Step 5: Add adapter-contract behavior tests**

```python
import inspect

from robot_twin.adapter import RobotAdapter


def test_robot_adapter_has_only_semantic_operations():
    methods = {
        name
        for name, value in inspect.getmembers(RobotAdapter, inspect.isfunction)
        if not name.startswith("_")
    }
    assert methods == {
        "health",
        "capabilities",
        "deploy_parameters",
        "start_run",
        "stop_run",
        "rollback",
        "telemetry_stream",
        "run_status",
    }
```

- [ ] **Step 6: Implement `RobotAdapter` as an async ABC**

Every method must be abstract and use the exact domain types listed under **Interfaces**. Do not include `send_motor`, `write_uart`, `flash`, `erase`, `send_can_frame` or another transport-specific method.

- [ ] **Step 7: Run Task 1 tests**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_robot_contracts.py -v
```

Expected: PASS.

- [ ] **Step 8: Produce Task 1 handoff**

List the four created modules, exact method signatures, test output and the explicit statement that no robot, transport or hardware implementation was added.

---

### Task 2: Implement Robot Manifest, Schemas, Safety Policies, and Registry

**Files:**
- Modify: `simulation/digital_twin/pyproject.toml`
- Create: `simulation/digital_twin/robot_twin/manifest.py`
- Create: `simulation/digital_twin/robot_twin/registry.py`
- Create: `simulation/digital_twin/robot_twin/manifests/dasheng_stm32_line_car.yaml`
- Create: `simulation/digital_twin/robot_twin/schemas/line_pid_parameters.json`
- Create: `simulation/digital_twin/robot_twin/schemas/line_following_telemetry.json`
- Create: `simulation/digital_twin/robot_twin/policies/dasheng_line_car.yaml`
- Test: `simulation/digital_twin/tests/test_robot_manifest.py`

**Interfaces:**
- Consumes: `RobotCapabilities`, `RobotAdapter`.
- Produces: `RobotManifest`, `load_manifest(path)`, `AdapterRegistry.register(name, factory)`, `AdapterRegistry.create(manifest)`.

- [ ] **Step 1: Add manifest validation tests**

```python
from pathlib import Path

import pytest

from robot_twin.manifest import ManifestError, load_manifest


def test_dasheng_manifest_declares_no_firmware_flash():
    root = Path("robot_twin")
    manifest = load_manifest(root / "manifests" / "dasheng_stm32_line_car.yaml")
    assert manifest.robot_type == "dasheng_stm32_line_car"
    assert manifest.capabilities.runtime_parameter_update
    assert not manifest.capabilities.firmware_flash


def test_manifest_rejects_unknown_schema_version(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("schema_version: 99\nrobot_type: bad\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="schema_version"):
        load_manifest(path)
```

- [ ] **Step 2: Run tests and confirm failure**

Expected: missing `robot_twin.manifest`.

- [ ] **Step 3: Add the only new manifest dependency**

Add to `pyproject.toml` dependencies:

```toml
"PyYAML>=6,<7",
```

Do not add a second YAML library or JSON Schema framework.

- [ ] **Step 4: Implement `RobotManifest` and strict loader**

`RobotManifest` must contain:

```python
schema_version: int
robot_type: str
display_name: str
controller_family: str
realtime_loop_ms: int
capabilities: RobotCapabilities
parameter_schema_path: Path
telemetry_schema_path: Path
transport_adapter: str
safety_policy_path: Path
twin_adapter: str
```

The loader must:

- accept only `schema_version == 1`;
- require every listed field;
- resolve referenced files relative to the manifest directory;
- reject referenced paths that escape `robot_twin/`;
- reject non-positive `realtime_loop_ms`;
- default no capability to `true`;
- reject `firmware_flash: true` in V1.5 manifests.

- [ ] **Step 5: Create exact Dasheng parameter Schema**

`line_pid_parameters.json`:

```json
{
  "schema_version": 1,
  "name": "line_pid_parameters",
  "fields": {
    "kp": {"type": "number", "minimum": 20.0, "maximum": 50.0, "max_step": 5.0},
    "ki": {"type": "number", "minimum": 0.0, "maximum": 5.0, "max_step": 1.0},
    "kd": {"type": "number", "minimum": 5.0, "maximum": 20.0, "max_step": 3.0},
    "speed_max": {"type": "integer", "minimum": 260, "maximum": 680, "max_step": 100}
  }
}
```

- [ ] **Step 6: Create telemetry Schema and safety policy**

The telemetry Schema must require standard fields from `TelemetryEnvelope` and allow robot-specific `extensions`. The Dasheng policy must state:

```yaml
policy_version: 1
require_health_ready: true
require_health_safe: true
ack_timeout_s: 2.0
disconnect_action: rollback
telemetry_timeout_s: 1.0
line_lost_action: stop_then_rollback
allow_firmware_flash: false
allow_raw_motor_command: false
```

- [ ] **Step 7: Implement adapter registry and tests**

```python
def test_registry_constructs_only_named_adapter(dasheng_manifest):
    registry = AdapterRegistry()
    registry.register("dasheng_esp_tcp", lambda manifest: object())
    assert registry.create(dasheng_manifest) is not None


def test_registry_rejects_unregistered_adapter(dasheng_manifest):
    with pytest.raises(ManifestError, match="dasheng_esp_tcp"):
        AdapterRegistry().create(dasheng_manifest)
```

Registry lookup must be explicit; do not use `eval`, arbitrary imports from Manifest text or filesystem code execution.

- [ ] **Step 8: Run Task 2 tests**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_robot_contracts.py tests/test_robot_manifest.py -v
```

Expected: PASS.

- [ ] **Step 9: Produce Task 2 handoff**

Include the resolved Dasheng manifest, parameter limits, default-false capability behavior and proof that unsafe manifest paths and firmware-flash capability are rejected.

---

### Task 3: Extract a Hardware-Neutral Robot Twin Core Facade

**Files:**
- Create: `simulation/digital_twin/robot_twin/core.py`
- Modify: `simulation/digital_twin/analysis/campaign_orchestrator.py`
- Modify: `simulation/digital_twin/analysis/campaign_optimizer.py`
- Modify: `simulation/digital_twin/real_world/campaign_store.py`
- Test: `simulation/digital_twin/tests/test_robot_twin_core.py`

**Interfaces:**
- Consumes: `RobotAdapter`, Task 1 domain models, existing V1 metrics/store/optimizer/orchestrator.
- Produces: `RobotTwinCore.register_robot()`, `robot_list()`, `robot_manifest()`, `create_campaign()`, `status()`, `generate_candidates()`, `simulate_candidate()`, `deploy_candidate()`, `start_run()`, `stop()`, `evaluate()`, `rollback()`, `report()`.

- [ ] **Step 1: Write a fake adapter inside the test file**

The fake must implement all `RobotAdapter` methods, record semantic calls and never expose transport details.

```python
class FakeRobotAdapter(RobotAdapter):
    def __init__(self):
        self.calls = []
        self.current_version = 1

    async def health(self):
        self.calls.append(("health",))
        return RobotHealth(True, True, True, "ok")

    async def capabilities(self):
        return RobotCapabilities(True, True, True, True, False)

    async def deploy_parameters(self, packet):
        self.calls.append(("deploy", packet.parameter_version))
        self.current_version = packet.parameter_version
        return DeploymentAck(
            packet.robot_id, packet.campaign_id,
            packet.parameter_version, True, "APPLIED",
        )
```

Implement the remaining abstract methods with deterministic states and an async telemetry iterator.

- [ ] **Step 2: Write failing Core behavior tests**

```python
def test_core_requires_health_before_deployment(tmp_path):
    adapter = FakeRobotAdapter()
    core = build_test_core(tmp_path, adapter)
    result = asyncio.run(core.deploy_candidate("campaign-001", 2))
    assert result.applied
    assert adapter.calls[0][0] == "health"
    assert adapter.calls[1] == ("deploy", 2)


def test_core_rolls_back_when_ack_times_out(tmp_path):
    adapter = TimeoutAdapter()
    core = build_test_core(tmp_path, adapter)
    with pytest.raises(AckTimeout):
        asyncio.run(core.deploy_candidate("campaign-001", 2))
    assert adapter.calls[-1][0] == "rollback"
```

- [ ] **Step 3: Run tests and confirm missing-Core failure**

Run the single test file and expect import failure.

- [ ] **Step 4: Refactor the existing orchestrator dependency**

Replace transport-specific methods such as `send_runtime_command()` and `wait_for_ack()` inside campaign orchestration with the semantic `RobotAdapter` methods. Preserve V1 state sequence and acceptance gates.

Do not change:

- five valid runs per baseline/candidate group;
- maximum 12 candidates;
- completion rate cannot regress;
- RMS/mean error improvement requirement;
- maximum error and line-loss non-regression;
- speed improvement evaluated only after quality gates;
- stop-then-rollback ordering.

- [ ] **Step 5: Implement `RobotTwinCore` as a facade**

The facade owns a registry of robot IDs to `(manifest, adapter)` and delegates deterministic work to existing V1 modules. Every mutating method must:

1. resolve a registered robot;
2. check capability;
3. call `health()`;
4. validate campaign state and version;
5. append an audit event;
6. call the semantic Adapter operation;
7. persist the result before returning.

- [ ] **Step 6: Add a forbidden-import regression test**

```python
def test_core_has_no_hardware_specific_imports():
    source = Path("robot_twin/core.py").read_text(encoding="utf-8")
    forbidden = ("ESP", "+IPD", "AA 55", "USART", "STM32", "CAN", "Motor")
    assert not any(token in source for token in forbidden)
```

- [ ] **Step 7: Run Core and existing V1 suites**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_robot_twin_core.py tests/test_campaign_metrics.py tests/test_campaign_optimizer.py tests/test_campaign_orchestrator.py -v
```

Expected: PASS. If the V1 test filenames differ after completion, use the filenames recorded in the V1 Task 3–5 handoff; do not silently skip those suites.

If any of the four named V1 modules or their recorded replacement paths are absent, stop Task 3 and report `v1_prerequisite_missing`; do not create substitute campaign logic inside `robot_twin/core.py`.

- [ ] **Step 8: Produce Task 3 handoff**

Report the exact V1 modules reused, removed hardware dependencies, facade signatures and all regression results.

---

### Task 4: Wrap the 大圣 STM32 Car as the First Robot Adapter

**Files:**
- Create: `simulation/digital_twin/robot_twin/adapters/__init__.py`
- Create: `simulation/digital_twin/robot_twin/adapters/dasheng.py`
- Read only: `simulation/digital_twin/web_showcase/live_wifi_bridge.py`
- Test: `simulation/digital_twin/tests/test_dasheng_adapter.py`

**Interfaces:**
- Consumes: `RobotAdapter`; `P/R/A/S` from `real_world/runtime_protocol.py`; final V1 Task 2 bridge API; existing `AA 55` telemetry parser.
- Produces: `DashengStm32Adapter`, `map_dasheng_telemetry(frame, run_context) -> TelemetryEnvelope`.

- [ ] **Step 1: Write bridge fakes and failing adapter tests**

```python
def test_dasheng_deploy_maps_generic_packet_to_runtime_protocol():
    bridge = FakeLiveWifiBridge()
    adapter = DashengStm32Adapter(manifest, bridge)
    ack = asyncio.run(adapter.deploy_parameters(PARAMETER_PACKET))
    assert bridge.sent == ["P,campaign-001,2,35,0,10,680,69\n"]
    assert ack.applied


def test_dasheng_disconnect_is_not_reported_as_success():
    bridge = DisconnectedBridge()
    adapter = DashengStm32Adapter(manifest, bridge)
    with pytest.raises(TransportDisconnected):
        asyncio.run(adapter.deploy_parameters(PARAMETER_PACKET))
```

- [ ] **Step 2: Run tests and confirm missing-adapter failure**

- [ ] **Step 3: Implement parameter mapping**

The adapter must:

- require exactly `kp`, `ki`, `kd`, `speed_max`;
- validate against the JSON parameter Schema before encoding;
- use existing `ParameterCommand` instead of reimplementing checksum logic;
- wait for an ACK matching both campaign and parameter version;
- convert timeout and disconnect exceptions into typed Robot Twin errors;
- never return `applied=True` without the matching ACK.

- [ ] **Step 4: Implement run-control mapping**

Map:

```text
start_run  -> R,<campaign_id>,<run_id>,START
stop_run   -> R,<campaign_id>,<run_id>,STOP
rollback   -> R,<campaign_id>,<run_id>,RESTORE_BASELINE
```

Use the final Task 2 `S` status evidence to build `RunStatus`. Do not infer status from successful socket writes.

- [ ] **Step 5: Implement telemetry normalization**

Map four line sensors, four motor outputs, error, PID output, tick and yaw into `TelemetryEnvelope`. Preserve the raw parser result in `extensions["dasheng_raw"]` only when it is JSON-serializable.

- [ ] **Step 6: Add safety regression tests**

Cover:

- wrong campaign/version ACK;
- duplicate ACK;
- disconnected bridge;
- telemetry timeout;
- status `line_lost`;
- status `safety_stop`;
- failed rollback;
- unavailable runtime-parameter capability;
- unknown parameter field;
- parameter outside firmware bounds.

- [ ] **Step 7: Run adapter and V1 transport suites**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_dasheng_adapter.py tests/test_runtime_protocol.py web_showcase/test_live_wifi_bridge.py -v
```

Also run the Keil Target 1 Rebuild All command recorded by V1 Task 1 if this Task changes any firmware file. Expected: 0 errors and 0 warnings. Normally this Adapter task must not modify firmware.

- [ ] **Step 8: Produce Task 4 handoff**

State explicitly that the Adapter is software-tested and whether any real ESP, UART, TCP, PWM, motor or track validation occurred.

---

### Task 5: Prove Software Portability with Two Independent Mock Adapters

**Files:**
- Create: `simulation/digital_twin/robot_twin/adapters/mock_line_car.py`
- Create: `simulation/digital_twin/robot_twin/adapters/mock_encoder_car.py`
- Create: `simulation/digital_twin/robot_twin/manifests/mock_line_car.yaml`
- Create: `simulation/digital_twin/robot_twin/manifests/mock_encoder_car.yaml`
- Create: `simulation/digital_twin/robot_twin/schemas/encoder_pid_parameters.json`
- Create: `simulation/digital_twin/robot_twin/schemas/encoder_telemetry.json`
- Create: `simulation/digital_twin/robot_twin/policies/mock_line_car.yaml`
- Create: `simulation/digital_twin/robot_twin/policies/mock_encoder_car.yaml`
- Test: `simulation/digital_twin/tests/test_adapter_portability.py`

**Interfaces:**
- Consumes: the unchanged `RobotAdapter` contract and `RobotTwinCore`.
- Produces: `MockLineCarAdapter`, `MockEncoderCarAdapter`, reusable `adapter_contract_cases(adapter_factory)`.

- [ ] **Step 1: Write one contract suite used by every adapter**

The suite must verify:

```python
def adapter_contract_cases(factory):
    adapter = factory()
    health = asyncio.run(adapter.health())
    assert health.ready and health.safe

    ack = asyncio.run(adapter.deploy_parameters(factory.valid_packet()))
    assert ack.applied

    status = asyncio.run(adapter.start_run(factory.valid_run()))
    assert status.state == "running"

    stopped = asyncio.run(adapter.stop_run("contract_test"))
    assert stopped.state == "stopped"

    rolled_back = asyncio.run(adapter.rollback("baseline"))
    assert rolled_back.applied
```

Run the same contract against Dasheng-with-fake-bridge, MockLine and MockEncoder.

- [ ] **Step 2: Implement `MockLineCarAdapter`**

Use line sensors and `kp/ki/kd/speed_max`, but use an in-memory transport unrelated to ESP framing. Generate deterministic tracking-error telemetry.

- [ ] **Step 3: Implement `MockEncoderCarAdapter`**

Use a different parameter set:

```json
{
  "left_speed_kp": {"minimum": 0.0, "maximum": 10.0, "max_step": 1.0},
  "right_speed_kp": {"minimum": 0.0, "maximum": 10.0, "max_step": 1.0},
  "target_speed_mps": {"minimum": 0.1, "maximum": 2.0, "max_step": 0.2}
}
```

Its telemetry extensions must contain encoder ticks and wheel speed, not line sensors. The Core must run without changes.

- [ ] **Step 4: Add a Core-source immutability check**

Record the SHA-256 of `robot_twin/core.py` before adding the two adapters. The test report must show the same hash after both adapters and manifests are added.

- [ ] **Step 5: Run portability tests**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_adapter_portability.py tests/test_robot_twin_core.py -v
```

Expected: all three adapters pass the same contract and both mock robots complete one deterministic campaign without modifying Core.

- [ ] **Step 6: Label the evidence honestly**

The handoff must say “software adapter portability demonstrated.” It must not say a second physical robot was migrated or validated.

---

### Task 6: Expose the Core through an Official MCP Python SDK v2 Server

**Files:**
- Modify: `simulation/digital_twin/pyproject.toml`
- Create: `simulation/digital_twin/robot_twin/mcp_server.py`
- Test: `simulation/digital_twin/tests/test_robot_twin_mcp.py`

**Interfaces:**
- Consumes: `RobotTwinCore`, Manifest registry and typed errors.
- Produces: `build_mcp_server(core) -> MCPServer` and the tools defined in the approved design.

- [ ] **Step 1: Pin the official MCP v2 line**

Add:

```toml
"mcp>=2,<3",
```

Do not install or import the unrelated standalone `fastmcp` package.

- [ ] **Step 2: Write an in-memory MCP client test**

Use the official SDK v2 pattern:

```python
import asyncio

from mcp import Client

from robot_twin.mcp_server import build_mcp_server


def test_mcp_lists_robot_and_returns_structured_manifest(test_core):
    async def scenario():
        server = build_mcp_server(test_core)
        async with Client(server) as client:
            result = await client.call_tool("robot_list", {})
            return result.structured_content

    content = asyncio.run(scenario())
    assert content["robots"][0]["robot_id"] == "mock-line-001"
```

- [ ] **Step 3: Implement the server factory**

```python
from mcp.server import MCPServer


def build_mcp_server(core: RobotTwinCore) -> MCPServer:
    server = MCPServer("Robot Twin AI")

    @server.tool()
    async def robot_list() -> dict:
        return {"robots": core.robot_list()}

    @server.tool()
    async def robot_get_manifest(robot_id: str) -> dict:
        return core.robot_manifest(robot_id)

    return server
```

Add the remaining tools:

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

- [ ] **Step 4: Convert errors into stable structured results**

Every tool failure must return:

```json
{
  "ok": false,
  "error": {
    "code": "ack_timeout",
    "message": "parameter acknowledgement timed out"
  }
}
```

Do not return Python tracebacks, socket exceptions or raw firmware buffers to the AI client.

- [ ] **Step 5: Add MCP safety tests**

Verify through the in-memory MCP client:

- unknown robot;
- unsupported capability;
- unhealthy robot;
- invalid parameter;
- wrong version;
- ACK timeout;
- safety stop;
- rollback failure;
- state conflict;
- `campaign_deploy_candidate` cannot accept raw `kp/ki/kd` values and only accepts a stored candidate version.

- [ ] **Step 6: Verify no raw real-time MCP tools exist**

```python
def test_mcp_has_no_raw_actuator_or_flash_tool(server_tool_names):
    forbidden = {"motor_write", "send_pwm", "flash", "erase_flash", "uart_write"}
    assert forbidden.isdisjoint(server_tool_names)
```

- [ ] **Step 7: Run MCP tests**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_robot_twin_mcp.py tests/test_robot_twin_core.py -v
```

Expected: PASS.

- [ ] **Step 8: Smoke-test with MCP Inspector**

Run from `simulation/digital_twin`:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m mcp dev robot_twin/mcp_server.py
```

Use only Mock adapters for this smoke test. Record the Inspector-visible tool names and one read-only `robot_list` result. Do not connect a real robot.

- [ ] **Step 9: Produce Task 6 handoff**

Include SDK version, MCP transport used, exact tools, structured error examples and proof that no flash/raw motor tool exists.

---

### Task 7: Package the Robot Twin AI Skill

**Files:**
- Create: `simulation/digital_twin/skills/robot-twin-ai/SKILL.md`
- Test: `simulation/digital_twin/tests/test_robot_twin_skill.py`

**Interfaces:**
- Consumes: MCP tool names and error codes from Task 6.
- Produces: a project-local Skill that teaches an AI agent the required safe workflow without duplicating executable safety logic.

- [ ] **Step 1: Write Skill-content contract tests**

```python
def test_skill_requires_capability_and_health_checks():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "robot_get_manifest" in text
    assert "robot_health" in text
    assert text.index("robot_get_manifest") < text.index("campaign_deploy_candidate")
    assert text.index("robot_health") < text.index("campaign_deploy_candidate")


def test_skill_requires_stop_then_rollback():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "campaign_stop" in text
    assert "campaign_rollback" in text
    assert "不得伪造遥测" in text
```

- [ ] **Step 2: Create complete Skill front matter**

```yaml
---
name: robot-twin-ai
description: Use for safe Robot Twin AI campaign operations across supported wheeled robots through the Robot Twin MCP server.
---
```

- [ ] **Step 3: Define the exact workflow**

The Skill must require this order:

```text
robot_list
-> robot_get_manifest
-> robot_health
-> campaign_create
-> baseline evidence
-> campaign_generate_candidates
-> campaign_simulate_candidate
-> campaign_deploy_candidate
-> matching ACK
-> campaign_start_run
-> campaign_evaluate
-> accept or campaign_stop + campaign_rollback
-> campaign_get_report
```

It must also state:

- unsupported capability means stop;
- missing real telemetry means no acceptance;
- simulation is not physical evidence;
- timeout or disconnect means stop and rollback;
- never pass natural-language values as raw actuator commands;
- never call unlisted external flash/debug tools as part of an automatic campaign.

- [ ] **Step 4: Run Skill tests**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_robot_twin_skill.py -v
```

Expected: PASS.

- [ ] **Step 5: Perform a Mock Skill walkthrough**

Follow the Skill manually against the Task 6 Mock MCP server. Record every tool call and confirm the sequence contains health before deployment and stop before rollback.

- [ ] **Step 6: Produce Task 7 handoff**

List the Skill path, trigger description, MCP dependencies, safety ordering and walkthrough log. Do not claim it is installed globally unless installation is separately performed and verified.

---

### Task 8: Full Integration, Packaging, Porting Guide, and Release Gate

**Files:**
- Modify: `simulation/digital_twin/pyproject.toml`
- Create: `simulation/digital_twin/tests/test_robot_twin_integration.py`
- Create: `simulation/digital_twin/docs/porting-a-wheeled-robot.md`
- Modify: `simulation/digital_twin/README.md`

**Interfaces:**
- Consumes: all Tasks 1–7.
- Produces: reproducible package/test commands, full Mock campaign demonstration, Adapter porting guide and a release report that separates software from hardware evidence.

- [ ] **Step 1: Add package discovery and build dependency**

Ensure setuptools includes `robot_twin*`. Extend the existing dev dependencies to include:

```toml
dev = ["pytest>=7.0", "build>=1,<2"]
```

The packaged MCP server is launched with the official SDK command:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\Scripts\mcp.exe run robot_twin/mcp_server.py
```

Importing or launching the server module must not auto-connect to a robot or start a campaign.

- [ ] **Step 2: Write the full Mock integration test**

The test must:

1. load the MockLine Manifest;
2. register the MockLine Adapter;
3. build Core;
4. build MCP Server;
5. call tools through an in-memory MCP client;
6. create a campaign;
7. supply five deterministic baseline runs;
8. generate and simulate a candidate;
9. deploy the stored candidate;
10. receive matching ACK;
11. run five candidate trials;
12. evaluate;
13. produce a report;
14. separately inject a timeout campaign and prove stop-then-rollback.

- [ ] **Step 3: Add cross-adapter integration**

Run the same Core and MCP flow with `MockEncoderCarAdapter`. Assert:

```python
assert line_report["robot_type"] == "mock_line_car"
assert encoder_report["robot_type"] == "mock_encoder_car"
assert line_report["core_schema_version"] == encoder_report["core_schema_version"]
```

- [ ] **Step 4: Write the porting guide**

`porting-a-wheeled-robot.md` must give exact steps:

1. copy neither Core nor another Adapter;
2. create one Manifest;
3. create parameter and telemetry Schemas;
4. create one SafetyPolicy;
5. implement all `RobotAdapter` methods;
6. map robot telemetry to `TelemetryEnvelope`;
7. run the shared Adapter contract;
8. run a Mock campaign;
9. perform an independent hardware Work;
10. record unsupported capabilities and remaining physical uncertainties.

Include a checklist showing which files a new adapter may modify. `robot_twin/core.py` and `robot_twin/mcp_server.py` must be marked “must not change for normal migration.”

- [ ] **Step 5: Run the full portability suite**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_robot_contracts.py tests/test_robot_manifest.py tests/test_robot_twin_core.py tests/test_dasheng_adapter.py tests/test_adapter_portability.py tests/test_robot_twin_mcp.py tests/test_robot_twin_skill.py tests/test_robot_twin_integration.py -v
```

Then run the V1 regression suites listed in the V1 final handoff.

Expected: zero failed tests.

- [ ] **Step 6: Build and inspect the Python package**

Run:

```powershell
C:\Users\24668\AppData\Local\Programs\Python\Python311\python.exe -m build
```

Inspect the wheel and confirm it contains:

- `robot_twin` Core and Adapter contracts;
- all three bundled Manifests and Schemas;
- no firmware object files, `.axf`, Wi-Fi credentials, logs or captured real telemetry.

- [ ] **Step 7: Run a local MCP read-only smoke test**

Start the packaged MCP server with Mock adapters and call:

- `robot_list`;
- `robot_get_manifest`;
- `robot_health`;
- `campaign_status`.

Do not register the Dasheng real transport during this release smoke test.

- [ ] **Step 8: Produce the V1.5 release report**

The report must contain:

- architecture version;
- Python and MCP SDK versions;
- package artifact path and hash;
- exact tests and results;
- Adapter contract results for Dasheng-fake, MockLine and MockEncoder;
- MCP tool list;
- Skill walkthrough;
- Core file hash before and after new adapters;
- explicit statement that software portability is demonstrated;
- explicit statement that real portability to a second physical robot remains unverified until such hardware is selected and tested.

---

## Final Acceptance Gate

V1.5 is accepted as a **software-portable wheel-robot framework** only when:

- Core tests and all V1 regression tests pass;
- Dasheng Adapter passes against a fake Task 2 bridge;
- two structurally different Mock adapters pass the same contract;
- the Core hash does not change while adding those adapters;
- the official MCP v2 server exposes only semantic, audited tools;
- the Skill enforces capability discovery, health checking and stop-then-rollback ordering;
- package inspection contains no credentials, build artifacts or real telemetry;
- no hardware, flash or motor action is falsely reported as performed.

V1.5 must not be described as physically portable to arbitrary robots until a second real wheeled robot completes its own Adapter implementation, independent hardware validation and full closed-loop campaign.
