# AgentTinker · 产品研究与设计

2026-10-08 · 第一轮研究 · 产品名称：AgentTinker

**建议以“可交互的 Agent 实验室”为主线：让用户观察一次执行、定位失败、修改一个因素，再用新的运行验证自己的判断。** 学习和开发共享同一个实验及其运行记录。

这份方案延续原对话中兼顾 Learn、Playground、Builder、Debugger、Evaluation、Explore 的愿景。仓库已完成第一轮调研与设计，以及 M0 的模拟和真实 DeepSeek 分支技术验收，M1 运行记录服务已完成，M2 的事件订阅、实际执行图、时间线和只读历史播放已实现；完整实验工作台尚未实现。实际扣费仍未知，按用户确认独立保留待办。

**接续开发入口：**新对话或新环境先阅读 [开发断点与交接](HANDOFF.md)，其中保存已核对的实现、验证结果、当前边界、阻塞及下一步。

| 文档 | 内容 |
| --- | --- |
| [竞品调研](docs/01-landscape.md) | 11 个相关产品/项目、官方证据、竞争重叠、仍需验证的机会 |
| [产品设计](docs/02-product-design.md) | 产品定位、六模块关系、首个实验、界面草图、首版验收 |
| [架构与开发路线](docs/03-architecture-roadmap.md) | 回放与重新执行的边界、运行记录、适配器、开发任务和退出条件 |
| [开发约定](CONTRIBUTING.md) | 工作节点、验证、Git 提交与推送、文档同步和日志要求 |
| [开发日志](docs/development-log.md) | 已完成工作、验证结果、限制和下一步 |
| [M0 验证说明](docs/m0-validation.md) | 本地环境、检查点分支验证和真实调用验收进度 |
| [M0 验收证据](docs/m0-acceptance.md) | 技术验收表、费用明细与用户已确认的阶段结论 |
| [M2 验收证据](docs/m2-acceptance.md) | 事件驱动检查与历史播放的验证及边界 |
| [前端开发](docs/web-inspector.md) | M2 开发入口、共享协议生成与验证 |
| [HTTP 与 SSE](docs/runtime-api.md) | 本地服务启动、控制接口和断线续传协议 |
| [M1 验收证据](docs/m1-acceptance.md) | 运行记录阶段的集成验证及实现边界 |
| [运行服务](docs/runtime-service.md) | M1 串行执行、持久化生命周期、取消与重启边界 |
| [运行记录协议](docs/runtime-records.md) | M1 对象、事件、状态转换与重建规则 |
| [云端环境配置](docs/cloud-environment.md) | 设置页填写内容、固定安装入口及配置生效检查 |
| [新环境接续审视](docs/resumption-audit.md) | 2026-10-15 全仓核对、环境实测、真实 M0 证据及待修问题 |

当前最重要的三个判断：

- 可视化、时间旅行、评测本身都有成熟先例。优先验证“更容易理解并修复一次失败”的完整体验。
- 用一个带故障注入和前后对比的真实实验打通核心，再按证据扩展六个模块。
- 统一实验与记录协议，先接一个执行框架；外部 trace 的可观察性不代表有能力恢复执行。

**命名约定：**产品、文档和界面统一使用 **AgentTinker**。当前仓库为 [AgentTinker-preview](https://github.com/Babapei/AgentTinker-preview)，`-preview` 标记开发预览阶段；完成后仓库更名为 `AgentTinker`。

**M0–M2 已完成，下一步 M3 首个实验闭环。** 已贯通核心协议、SQLite、运行服务、HTTP/SSE 和浏览器事件校验，支持列表/实际执行图、节点详情、时间线与只读历史播放。后端 136 项、前端 40 项单元及 15 项浏览器集成通过；本轮模型侧为模拟，没有新付费调用。证据见 [M2 验收](docs/m2-acceptance.md)，实际账单独立待办。

本地后端入口（启动不调用模型）：

```bash
bash scripts/setup.sh
uv run agenttinker-server --database artifacts/runs.sqlite
```

默认监听 `127.0.0.1:8000`，API 文档 `/docs`。创建 Run 时必须显式选择 live/synthetic，详见 [HTTP 与 SSE](docs/runtime-api.md)。只读检查界面通过 npm --prefix web run dev 启动，默认本机 5173；详见 [前端说明](docs/web-inspector.md)。完整实验工作台和公开部署尚未完成。
