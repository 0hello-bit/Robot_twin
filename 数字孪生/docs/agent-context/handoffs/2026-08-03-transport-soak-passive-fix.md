# Handoff：修复 transport_soak 假被动模式

## 启动要求

先读取仓库根 `CLAUDE.md` 和 `docs/agent-context/CURRENT_STATUS.md`。不要扫描全仓库，只读取下列允许文件及其直接 import 的必要接口。

## 问题与真实证据

在 2026-08-03 真机验证中，命令未传 `--run`，报告却显示并实际发送：

- `R,...,STOP`
- `R,...,START`
- 周期 `H,...`
- final `R,...,STOP`

代码根因已经定位：CLI 分支把 `"passive(no commands)"` 传入 `capture_session()`，而函数只检查 `run_mode == "passive"`；不相等时进入运行分支。最终 STOP 已确认，车辆随后又经独立 STOP 确认处于运动禁止状态。

## 允许范围

- 修改：`.embeddedskills/build/v1_task4b4/transport_soak.py`
- 修改：`.embeddedskills/build/v1_task4b4/test_transport_soak_rework.py`
- 只读必要接口：`simulation/digital_twin/real_world/` 中被上述两文件直接 import 的模块。

禁止修改产品固件、Keil 工程、其他计划或历史证据。

## 强制实现要求

1. 先添加 RED 回归测试，证明当前未传 `--run` 的完整控制路径发生非零 TX。
2. 修复后，被动模式必须满足：
   - 不发送 STOP。
   - 不发送 START。
   - 不发送 H。
   - 不发送任何其他 TCP 字节。
   - `raw_io.n_send == 0`。
3. 不得再用面向显示的字符串作为内部控制分支值；使用单一规范模式值、枚举或布尔值，并仅在生成报告时转换显示文本。
4. 显式 `--run` 必须继续执行 pre-STOP → START/RUNNING → H → final STOP/STOPPED 安全链路。
5. 不连接硬件、不打开真实 TCP、不烧录、不复位、不操作电机、不执行 Git 写操作。

## 验收

- 运行新增的定向 RED→GREEN 测试并保存关键输出。
- 运行 `.embeddedskills/build/v1_task4b4/test_transport_soak_rework.py` 全套测试。
- 运行与 health 0x02 混合流解析直接相关的现有测试。
- 所有真实网络均须使用 scripted/fake transport；报告证明本轮没有硬件或网络操作。

## 最终报告格式

- 根因。
- 实际修改文件。
- RED 证据与 GREEN 证据。
- 完整测试数、退出码和失败数。
- 被动模式零 TX 的可执行证据。
- 仍未验证项。
- 明确声明未连接或控制硬件、未执行 Git 写操作。
