# Legacy Scope

本目录记录正式工作区没有主动复制的内容。父目录原文件暂时保留，
不在没有明确授权的情况下删除。

## Excluded From Active Workspace

- 父目录 .embeddedskills 的构建缓存和大部分运行产物；只复制了本次
  V1 handoff。
- _unrelated、测试以及根目录的旧 .obj、.exe、临时脚本。
- simulation/digital_twin/web_showcase 及其 node_modules、dist 和
  截图缓存；当前 V1 不依赖 UI。
- STM32 工程的 Objects、Listings、构建产物和个人 IDE 状态文件。
- .claude、.codex_work、.easyeda 的工具状态；只保留 PCB 快照证据。

## Policy

后续 agent 只在 数字孪生 中工作。若某个历史文件被证明是当前任务的
必要输入，应先复制到正式目录、修正引用并重新验证，再考虑处理父目录
中的原始副本。
