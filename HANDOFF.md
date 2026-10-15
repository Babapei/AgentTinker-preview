# AgentTinker 开发断点与交接

更新时间：2026-10-15（Asia/Shanghai）。面向新对话、新环境及中断后的接续开发。

**当前停在 M0：最小检查点验证已实现，47 项测试通过；真实 DeepSeek 调用与费用验收未完成，M1 尚未开始。** 本文件由实际代码、Git、测试与环境状态核对生成，不依赖读取旧聊天。

## 1. 接手先确认这几件事

1. 阅读本文件、[工作规则](AGENTS.md)、[开发约定](CONTRIBUTING.md)和 [README](README.md)。
2. 阅读 [产品设计](docs/02-product-design.md)、[架构路线](docs/03-architecture-roadmap.md)和 [开发日志](docs/development-log.md)；需要理解复用选择时查看 [竞品调研](docs/01-landscape.md)。
3. 执行 git status、git log、git remote，核对实际 checkout 和远程；保留已有改动。若后续代码与本快照不同，以实际提交和更新后的日志核对进度。
4. 检查当前环境的配置与真实可访问性。不要沿用旧环境“已发布”“已就绪”或“已失败”的推断。
5. 从第 7 节继续；先完成 M0 的真实验收，再按既定阶段进入 M1。

本文件是当前状态索引；详细设计以对应文档为准。每个完成的工作节点继续更新开发日志；阶段、阻塞、入口或下一步变化时，同步维护本文件。

## 2. 已确定的用户意图和开发约定

- 正式产品名 **AgentTinker**；仓库 **AgentTinker-preview**，完成后由用户移除仓库名的 -preview。本机旧目录名不决定产品或仓库名称。
- 愿景是 Learn、Playground、Builder、Debugger、Evaluation、Explore 六模块共享实验与运行记录。首版按文档先打通有证据的故障诊断、分支和对比闭环。
- 复用成熟执行引擎、模型 SDK、图形组件和可用能力，围绕既定产品做适配；“复用”不等于只拼接外部产品页面，也不意味着擅自删改原架构任务。
- 用户已授权按当前文档持续推进日常实现。产品定位、范围、关键架构或验收条件若需变更，先说明依据、影响并与用户确定；不要只因用户提出一个想法就直接改写方案。
- **做一点、验证一点、记录一点、提交并推送一点**：按独立目的完成工作节点，不积压到项目结束；默认使用 work 分支，不强制每次建立 PR。
- 沿用仓库已有 Git 身份，不自行换署名、重写历史或强制推送。用户曾确认旧署名属于本人；新环境若身份缺失，先核对，不能编造。
- 日志和回复区分设计、实现、模拟验证、真实调用、费用估算与实际账单。已提交和已推送也要分别确认。
- 用户此前只能通过聊天操作，后来找到了环境设置页，但保存/发布遇到报错。不要预设用户拥有终端或管理员入口；密钥通过平台秘密输入，不让用户贴入聊天。
- 本次交接只核对并保存进度，没有删除、重建环境，也没有迁移对话。尚未确认当前聊天是否支持直接更换环境。

## 3. 仓库和可恢复基线

| 项目 | 本次核对结果 |
| --- | --- |
| 远程 | https://github.com/Babapei/AgentTinker-preview.git |
| 开发分支 | work |
| 交接文档修改前的代码基线 | 9ef7fe0f59878a11b52c63872451cb8d6085a9ce，本地与远程一致 |
| 原工作目录 | /workspace/AgentLab-preview；新环境应自行定位 checkout，不硬编码此路径 |
| 开始核对时的工作区 | 无已跟踪修改或未跟踪的非忽略文件 |
| 当前包 | agenttinker 0.0.1；尚未发布包或网站 |

本交接文件及入口变更在上述代码基线之后提交；其提交号以 git log 为准，不将前一代码基线误当作永远最新的 HEAD。新环境务必取得 work 分支，不能假定默认分支已含这些改动。

主要已推送节点：

| 提交 | 目的 |
| --- | --- |
| 35c1745 | 初始研究和统一平台设计，使用当时的 AgentLab 工作名 |
| 536212b / 4057f49 | 确定名称、建立开发规范和日志 |
| 72e16ad / 0d8de02 | Python 工程与模拟模型下的真实 LangGraph 分支验证 |
| ef3a214 / 581d174 | 官方 SDK 的 live 入口及 DeepSeek 请求配置 |
| debcc72 / dcd84eb | 新增用量与价格估算、失败诊断 |
| 9ef7fe0 | 固定云端安装入口与配置说明 |

Git 保存了源码、锁文件、设计、日志和 examples 中的示例。artifacts/、.venv/、缓存及 .env 文件不入库，不能将它们视为已备份。当前本地 artifacts 中的记录为 synthetic；新环境可重新生成。当前 checkpoint 只在单个进程内存中，JSON 报告不能恢复已退出进程的 checkpoint。

## 4. 已实现的代码及边界

| 文件/目录 | 已实现内容 |
| --- | --- |
| [pyproject.toml](pyproject.toml)、uv.lock | Python >=3.12、uv、LangGraph、Pydantic、OpenAI SDK、pytest、ruff |
| [scripts/setup.sh](scripts/setup.sh) | 固定安装入口：定位仓库并执行 uv sync --locked；不调用模型 |
| [probe.py](src/agenttinker/m0/probe.py) | StateGraph、InMemorySaver、工具前 checkpoint、允许字段分支、A 历史不变性检查 |
| [fixtures.py](src/agenttinker/m0/fixtures.py) | 带版本与哈希的虚构发布说明、本地只读检索 |
| [models.py](src/agenttinker/m0/models.py)、[synthetic.py](src/agenttinker/m0/synthetic.py) | M0 模型/策略/span 类型与明确标注的模拟模型 |
| [openai_model.py](src/agenttinker/m0/openai_model.py) | 官方 SDK 薄适配、原始响应和请求/用量保留、独立配置校验 |
| [deepseek_model.py](src/agenttinker/m0/deepseek_model.py) | DeepSeek 非思考模式请求，保留工具调用与缓存用量 |
| [accounting.py](src/agenttinker/m0/accounting.py) | 每个 Run 新增 Token 覆盖率、缓存字段核对、版本化价格与 Decimal 估算 |
| [cli.py](src/agenttinker/m0/cli.py) | 显式 live/synthetic 模式、价格输入、原子写报告和单独失败诊断 |
| [tests](tests) | 47 项测试：分支、策略校验、SDK 模拟 HTTP、用量费用及失败诊断 |

本次实际安装版本：LangGraph 1.2.14、langgraph-checkpoint 4.2.0、OpenAI SDK 2.54.0、Pydantic 2.13.5。依赖安装以仓库锁文件为准。

M0 实验语义：

- 首次模型请求选择 search_documents；工具执行前保存 checkpoint。每个 Run 使用独立 run_id，A/B 共用 LangGraph 线程中的不同 checkpoint。
- A 的 tool_retry_limit=0，首次工具尝试注入超时后失败。
- B 从 A 的工具前 checkpoint 派生，只改 tool_retry_limit=1；B 首次尝试仍超时，第二次成功，然后新增一次模型请求生成答案。
- A/B 各新增一次模型调用、一次逻辑工具调用；工具尝试分别为 1 和 2。B 引用 A 的模型前缀，不将它重复计入新增调用或费用。
- 旧 Run 使用显式 checkpoint 配置定位；检查历史时沿 parent_config 遍历祖先。不能用线程最新 head 代表 A，也不能只检查一个终点就声称全部历史不变。
- 允许的策略补丁只有 tool_retry_limit 和 top_k；保留原查询和模型 tool call ID。top_k 分支已有针对性测试，完整第二个产品实验尚未实现。
- 当前是一次串行工具调用的验证图，不是完整 ReAct 产品。CLI 强制首次调用指定工具，不证明模型自主选工具能力。

模型、用量与失败处理：

- SDK 自动重试关闭，单次超时 30 秒、输出上限 1024。DeepSeek 使用 max_tokens、显式禁用 thinking；标准端点不发送 Beta strict 或 OpenAI 专属的 parallel_tool_calls。
- 无配置时 CLI 退出码为 2，不回退为模拟模式。执行或协议失败退出码为 1，将诊断写入同名 .failed.json，保留先前成功报告和已发生调用。
- 模型返回成功与协议被接受分别处理；截断、过滤或无效工具参数会停止工具执行并保留返回记录。失败节点未生成新 checkpoint 时，快照可能仍为 running，诊断用 observed_status 标识失败，不改写旧历史。
- 未知用量/费用为 null，报告覆盖率。费用仅对新增调用计算；缺少匹配价格或缓存分解时不冒充完整总额。价格估算不代表真实扣费。
- examples/m0/ 中有历史 synthetic 记录及 DeepSeek 高峰/低峰价格快照。价格和模型资料采集于 2026-10-08；真实验收前重新核对适用模型、官方协议、价格和调用时段，不自动按峰谷或节假日套价。

## 5. 尚未实现的阶段

| 阶段 | 当前状态 / 下一阶段目标 |
| --- | --- |
| M0 | 进行中；缺真实模型分支记录、新增真实用量与费用核对 |
| M1 | 未开始：正式对象/事件 schema、Run 状态机、SQLite、持久化、SSE 及续传去重 |
| M2 | 未开始：步骤列表/图、详情、时间线、历史记录播放 |
| M3 | 未开始：完整超时实验、单变量 fork、A/B 对比和内嵌讲解 |
| M4 | 未开始：第二个实验、评价、实验包导入导出、真实参考记录无密钥回看 |
| M5 | 未开始：实际工具对照与用户使用验证 |

仓库没有 FastAPI 服务、React/Vite 工程、网页预览、持久化 checkpoint、取消能力或公开部署。M0 的内存状态/span 和 JSON 输出不能当作 M1 已完成；synthetic 成功不能当作真实验收。

首版技术路线仍为 React/TypeScript/Vite + React Flow、Python/FastAPI/Pydantic、LangGraph、SQLite + 文件存储、HTTP + SSE。公开托管、域名、额外模型和外部工具服务尚未确定；当前不需要额外托管数据库或搜索服务账号。

## 6. 2026-10-15 重新执行的验证与环境快照

| 操作 | 实际结果 |
| --- | --- |
| bash scripts/setup.sh | 成功，锁定依赖同步通过 |
| uv run pytest -q | 47 passed |
| uv run ruff check . | 通过 |
| uv run ruff format --check . | 通过 |
| uv run agenttinker-m0 --mode synthetic --output artifacts/m0-handoff-synthetic.json | 7 项 checks 全部 true，m0_real_call_verified=false |
| git ls-remote origin refs/heads/work | 与上述代码基线一致 |
| curl HEAD https://api.deepseek.com（无密钥） | 代理 CONNECT 返回 403；请求尚未到达 DeepSeek |

当前执行命令的能力已恢复。环境状态接口 observations_current=true，报告 running；网络策略 restricted/enforced，仅允许依赖下载等域名，未允许 api.deepseek.com；secrets 和 runtime_variables 为空。进程中也没有 DEEPSEEK_API_KEY、DEEPSEEK_MODEL。

用户先前提供的设置页截图显示“全部互联网访问”、DeepSeek 密钥及模型条目，并报告保存/发布报错；当前实例与页面显示存在差异。尚未取得明确的页面报错原文，无法确认草稿、发布目标、绑定、权限或平台故障中的具体原因。曾出现执行环境配置能力查询失败，而状态接口仍显示 running；不能据此断定旧环境已损坏或新环境一定能修复。

历史环境状态、配置版本与本节结果都不是新环境的前置事实。进入新环境后重新检查；不要反复让用户确认“已发布”而不读取实际错误或就绪证据。本次没有真实 DeepSeek 请求、有效凭据验证或账单核对。

## 7. 下一步：完成真实 M0 验收

1. **先确认环境可运行。** 核对 checkout、work 分支、工作区及远程，执行固定安装入口。若新环境安装失败，先查看实际错误。
2. **确认配置已作用于当前实例。** 需要可访问 api.deepseek.com、秘密绑定 DEEPSEEK_API_KEY、模型变量 DEEPSEEK_MODEL。此前配置值为 deepseek-flash，默认地址为 https://api.deepseek.com；模型可通过 --model 明确指定。CLI 不自动加载 .env。
3. **区分平台配置和代码。** 查看当前配置状态与 SDK 实际错误；仅检查密钥存在/就绪，不打印密钥。云端网络凭据可能通过占位变量和代理注入，按平台支持方式使用；不能仅因值看起来不像真实密钥就替换它。不得把重写本地策略文件、绕开代理当作放行方式。
4. **重新核对模型协议与价格后执行：**

```bash
uv run agenttinker-m0 --mode live --provider deepseek \
  --output artifacts/m0-deepseek-live.json
```

需要费用估算时，先核对价格适用性，再通过 --pricing 显式选择版本化价格文件；可参考 [M0 验证说明](docs/m0-validation.md)，不能在未核对时默认采用高峰快照。

5. **核对证据。** 七项分支检查均通过，保留真实请求/响应、模型 ID、A/B 谱系、原历史不变证据、工具 attempts 和 B 的新增调用/Token。核对价格估算与可获取的账户扣费证据；缺失费用信息明确保留未知及未完成验收项。
6. **形成可审阅结果。** 更新 M0 验证说明、日志和本文件；确有可分发的真实参考记录时检查凭据与数据范围后保存。m0_real_call_verified=true 只表示真实调用/分支检查通过，不能替代完整费用验收。
7. **满足架构退出条件后进入 M1。** 按 CORE-01、STORE-01 等既定任务实现事件、状态、SQLite 和 SSE；每块工作验证、记录、提交、推送并核对远程。

如环境仍受阻，准确记录错误及缺失配置，继续既定范围内不依赖真实调用的独立工作；不将 M0 标为完成，也不擅自跳过阶段依赖或改写产品范围。

## 8. 给新对话的最短接续提示

> 请在 Babapei/AgentTinker-preview 的 work 分支接续开发。先完整阅读仓库根目录 HANDOFF.md 和 AGENTS.md，再核对源码、日志及当前环境。沿用现有产品设计与 M0–M5 路线、每块工作验证后提交推送并写日志的约定。从 M0 真实 DeepSeek 分支验收继续；先重查凭据和网络，区分 synthetic/mock 与 live。不要重做已完成工程，不把历史环境状态当作当前状态，关键范围变更先与我确定。
