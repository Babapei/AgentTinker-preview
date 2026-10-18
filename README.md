# AgentTinker · 产品研究与设计

2026-10-08 · 第一轮研究 · 产品名称：AgentTinker

**建议以“可交互的 Agent 实验室”为主线：让用户观察一次执行、定位失败、修改一个因素，再用新的运行验证自己的判断。** 学习和开发共享同一个实验及其运行记录。

这份方案延续原对话中兼顾 Learn、Playground、Builder、Debugger、Evaluation、Explore 的愿景。仓库已完成第一轮调研与设计，以及 M0 的模拟和真实 DeepSeek 分支技术验收，M1 运行记录服务已完成，M2 检查/回放、M3 超时闭环和 M4 内置实验可用首版已完成；M5 已有内置首版完整助手演练、Phoenix 历史观察/实验比较，以及[Studio 开发 API 检查点分支](docs/m5-studio.md)；Studio 页面完整操作、执行控制差异核对、真实用户试用与反馈待完成。实际扣费仍未知，按用户确认独立保留待办。

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
| [M3 验收证据](docs/m3-acceptance.md) | 首个超时实验闭环、原生真实参考和费用边界 |
| [M4 验收证据](docs/m4-acceptance.md) | 两类实验、独立评价、文件与无密钥阅读；真实引用失败保留 |
| [M5 使用验证](docs/m5-validation.md) | 内置首版完整助手演练、同案例材料；其余工具对照/真人试用待完成 |
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

**M0–M4 已完成，M5 进行中。** 超时实验已贯通任务/模式/策略、实际运行与取消、持久化检查点的单变量分支、A/B 配置/过程/输出/新增量对比与讲解。当前 308 项后端全量通过；81 项前端单元和 43 项 Chromium 沿用此前通过的应用基线（模型为模拟/离线 SDK），M5 工具操作另记证据。

[当前协议的真实参考](examples/m3/deepseek-timeout-live.json)通过 12 项检查：A/B 各一次真实 DeepSeek 模型请求，374/250 Token，共 624；B 引用前缀，A 不变。另有真实参考浏览器只读核对。未选价格表，费用与实际扣费未知，见 [M3 验收](docs/m3-acceptance.md)。M4 已建立[文档实验](docs/document-experiment.md)的版本化定义、本地工具、独立 ReAct 运行/分支与场景 HTTP 接口、纯规则评价；评价/人工复核已接不可变存储、HTTP 和场景/评价界面；[实验包 v1](docs/experiment-packages.md)已有契约、原生导出、事务导入/来源接口与强制只读能力。新建使用支持多意图逐项执行的文档 v2，旧 v1 失败保留；新版真实 A/B 均完成执行，B 读取必需正文后生成 hrelease-v2 错误引用，规则判 fail，18/19 采集检查满足，real_reference_verified=false。[三份参考包](examples/m4/README.md)覆盖两类实验；生产页面无密钥导入六条记录、回放与再导出通过。M4 按原 P06–P10 完成功能验收，答案引用预期仍失败，见[验收与限制](docs/m4-acceptance.md)。按用户最新确认，先完成当前内置首版的 M5 实操对照、真实用户试用与反馈修正，再将现成 Agent 做成可选接入；当前不开始外部 Agent 适配。记录/检查/回放/文件基础保留复用边界，执行控制与评价以后按对象验证。

本机完整页面与 API（启动不调用模型）：

```bash
bash scripts/setup.sh
npm --prefix web run build
uv run agenttinker-server --database artifacts/runs.sqlite --web-dist web/dist
```

打开 `http://127.0.0.1:8000` 使用页面，同一地址下 `/api` 与 `/docs` 可用；省略 --web-dist 仍仅提供原 API。创建 Run 时必须显式选择 live/synthetic，详见 [HTTP 与 SSE](docs/runtime-api.md)。开发时也可另启 npm --prefix web run dev（5173），见[前端说明](docs/web-inspector.md)。这是本机单用户入口，完整实验工作台与公开部署尚未完成。
