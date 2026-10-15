# AgentTinker · 产品研究与设计

2026-10-08 · 第一轮研究 · 产品名称：AgentTinker

**建议以“可交互的 Agent 实验室”为主线：让用户观察一次执行、定位失败、修改一个因素，再用新的运行验证自己的判断。** 学习和开发共享同一个实验及其运行记录。

这份方案延续原对话中兼顾 Learn、Playground、Builder、Debugger、Evaluation、Explore 的愿景。仓库已完成第一轮调研与设计，以及 M0 的 Python 工程、模拟和首次真实 DeepSeek 分支验证；实验工作台尚未实现，M0 的实际费用验收仍未完成。

**接续开发入口：**新对话或新环境先阅读 [开发断点与交接](HANDOFF.md)，其中保存已核对的实现、验证结果、当前边界、阻塞及下一步。

| 文档 | 内容 |
| --- | --- |
| [竞品调研](docs/01-landscape.md) | 11 个相关产品/项目、官方证据、竞争重叠、仍需验证的机会 |
| [产品设计](docs/02-product-design.md) | 产品定位、六模块关系、首个实验、界面草图、首版验收 |
| [架构与开发路线](docs/03-architecture-roadmap.md) | 回放与重新执行的边界、运行记录、适配器、开发任务和退出条件 |
| [开发约定](CONTRIBUTING.md) | 工作节点、验证、Git 提交与推送、文档同步和日志要求 |
| [开发日志](docs/development-log.md) | 已完成工作、验证结果、限制和下一步 |
| [M0 验证说明](docs/m0-validation.md) | 本地环境、检查点分支验证和真实调用验收进度 |
| [云端环境配置](docs/cloud-environment.md) | 设置页填写内容、固定安装入口及配置生效检查 |
| [新环境接续审视](docs/resumption-audit.md) | 2026-10-15 全仓核对、环境实测、真实 M0 证据及待修问题 |

当前最重要的三个判断：

- 可视化、时间旅行、评测本身都有成熟先例。优先验证“更容易理解并修复一次失败”的完整体验。
- 用一个带故障注入和前后对比的真实实验打通核心，再按证据扩展六个模块。
- 统一实验与记录协议，先接一个执行框架；外部 trace 的可观察性不代表有能力恢复执行。

**命名约定：**产品、文档和界面统一使用 **AgentTinker**。当前仓库为 [AgentTinker-preview](https://github.com/Babapei/AgentTinker-preview)，`-preview` 标记开发预览阶段；完成后仓库更名为 `AgentTinker`。

当前正在执行 **M0：验证检查点分支与记录协议**，模拟与真实 DeepSeek 分支的 7 项检查均通过；异常响应用量保留问题已修复，63 项测试通过，实际费用仍待核对。详见 [M0 验证说明](docs/m0-validation.md)和[接续审视](docs/resumption-audit.md)。M0 完成后再实现第一个端到端实验工作台。
