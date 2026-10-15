# AgentTinker 开发断点与交接

更新时间：2026-10-15（Asia/Shanghai）。面向新对话、新环境及中断后的接续开发。

**当前停在 M0：47 项测试通过，模拟与首次真实 DeepSeek 分支的 7 项检查均通过；实际费用验收未完成，另有异常响应用量保留问题待修复，M1 尚未开始。** 本文件由实际代码、Git、测试与环境状态核对生成，不依赖读取旧聊天。最新完整审视见 [新环境接续审视](docs/resumption-audit.md)。

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
- 用户已在新环境开启接续对话；本次完成全仓审视和首次真实 M0 验证，没有删除旧环境或迁移聊天。旧环境未提交文件和内存 checkpoint 不视为已恢复。

## 3. 仓库和可恢复基线

| 项目 | 本次核对结果 |
| --- | --- |
| 远程 | https://github.com/Babapei/AgentTinker-preview.git |
| 开发分支 | work |
| 新环境本次核对起点 | 17c19c21dc49ceb17e3e960e3d632490627c5f26，本地与远程一致 |
| 当前工作目录 | /workspace/AgentTinker-preview；旧环境为 /workspace/AgentLab-preview，后续仍应自行定位 checkout |
| 开始核对时的工作区 | 无已跟踪修改或未跟踪的非忽略文件 |
| 当前包 | agenttinker 0.0.1；尚未发布包或网站 |

本次审视记录及真实证据在上述核对起点之后提交；其提交号以 git log 为准，不将前一代码基线误当作永远最新的 HEAD。新环境务必取得 work 分支，不能假定默认分支已含这些改动。

主要已推送节点：

| 提交 | 目的 |
| --- | --- |
| 35c1745 | 初始研究和统一平台设计，使用当时的 AgentLab 工作名 |
| 536212b / 4057f49 | 确定名称、建立开发规范和日志 |
| 72e16ad / 0d8de02 | Python 工程与模拟模型下的真实 LangGraph 分支验证 |
| ef3a214 / 581d174 | 官方 SDK 的 live 入口及 DeepSeek 请求配置 |
| debcc72 / dcd84eb | 新增用量与价格估算、失败诊断 |
| 9ef7fe0 | 固定云端安装入口与配置说明 |
| 17c19c2 | 保存旧环境交接断点与读取入口 |

Git 保存了源码、锁文件、设计、日志和 examples 中的示例。本次新增的 [真实 DeepSeek 技术验证记录](examples/m0/deepseek-retry-live.json)也纳入版本管理。artifacts/、.venv/、缓存及 .env 文件不入库，不能将它们视为已备份。本环境 artifacts 含 synthetic、live 和不入库的账户查询产物；不可整目录提交。当前 checkpoint 只在单个进程内存中，JSON 报告不能恢复已退出进程的 checkpoint。

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
- examples/m0/ 中有 synthetic、首次真实技术验证记录及 DeepSeek 高峰/低峰价格快照。价格采集于 2026-10-08，2026-10-15 实跑前重新核对官方协议和适用价格，显式选择低峰快照；以后调用仍应重查，不自动按峰谷或节假日套价。
- 已离线复现一个待修边界：openai_model.py 在 choices 数量不为 1 时先抛异常，probe 只能记录调用失败，已返回的 usage/raw_response 丢失。修复时先保留响应观测，再进行协议校验，补针对性回归；本次审视没有改动运行代码。

## 5. 尚未实现的阶段

| 阶段 | 当前状态 / 下一阶段目标 |
| --- | --- |
| M0 | 进行中；真实分支记录、新增用量和价格估算已核对；实际费用仍待核对，异常响应观测待修复 |
| M1 | 未开始：正式对象/事件 schema、Run 状态机、SQLite、持久化、SSE 及续传去重 |
| M2 | 未开始：步骤列表/图、详情、时间线、历史记录播放 |
| M3 | 未开始：完整超时实验、单变量 fork、A/B 对比和内嵌讲解 |
| M4 | 未开始：第二个实验、评价、实验包导入导出、真实参考记录无密钥回看 |
| M5 | 未开始：实际工具对照与用户使用验证 |

仓库没有 FastAPI 服务、React/Vite 工程、网页预览、持久化 checkpoint、取消能力或公开部署。M0 的内存状态/span 和 JSON 输出不能当作 M1 已完成；synthetic 成功不能当作真实验收。

首版技术路线仍为 React/TypeScript/Vite + React Flow、Python/FastAPI/Pydantic、LangGraph、SQLite + 文件存储、HTTP + SSE。公开托管、域名、额外模型和外部工具服务尚未确定；当前不需要额外托管数据库或搜索服务账号。

## 6. 2026-10-15 新环境验证与环境快照

| 操作 | 实际结果 |
| --- | --- |
| UV_CACHE_DIR=/tmp/agenttinker-uv-cache bash scripts/setup.sh | 成功，锁定依赖同步通过；默认缓存只读，未修改依赖或安装脚本 |
| uv run pytest -q | 47 passed |
| uv run ruff check . | 通过 |
| uv run ruff format --check . | 通过 |
| uv run agenttinker-m0 --mode synthetic --output artifacts/m0-resume-synthetic.json | 7 项 checks 全部 true，m0_real_call_verified=false |
| git ls-remote origin refs/heads/work | 与本次核对起点一致 |
| curl HEAD https://api.deepseek.com（无密钥） | 到达服务端，HTTP 401；未被旧环境的代理 403 阻止 |
| SDK 鉴权模型列表 | 成功，配置的 deepseek-flash 可用 |
| live DeepSeek + 显式低峰价格 | 7 项 checks 全部 true，m0_real_call_verified=true；A/B 各新增一次模型请求，工具 attempts 为 1/2 |
| 真实用量与估算复算 | A 374 Token / 0.00007095 USD；B 新增 260 Token / 0.00007545 USD；合计 634 Token / 0.00014640 USD，仅为价格表估算 |
| SDK 账户余额查询 | HTTP 200，账户可用，币种 CNY；没有两次请求的独立实际扣费凭证 |

uv 命令在本环境使用 `UV_CACHE_DIR=/tmp/agenttinker-uv-cache`。网络命令需要命令工具的网络权限；继续保留继承的平台代理和 TLS，不通过修改策略文件或绕开代理解决访问。

环境状态接口 observations_current=true、running，已声明 unrestricted 网络、DEEPSEEK_API_KEY 绑定和 DEEPSEEK_MODEL；三者状态仍为 unknown，不能称平台已报告 ready/enforced。进程变量存在，模型为 deepseek-flash，正常 SDK 的鉴权和推理实际成功。实测成功与状态接口的未知分别记录，不再要求用户重复配置已可用密钥。

旧环境曾为 restricted/enforced、无变量并被代理以 403 拒绝，设置保存/发布问题的具体原因仍未确认；详见旧日志。它不是本环境的现状。本次真实请求发生在北京时间 20:14（UTC 12:14），7 项检查和 A 的 4 个 checkpoint 不变性均通过，估算已核对，但未取得逐笔账单。未来换环境仍需重查。

## 7. 下一步：补齐 M0 剩余证据

1. **先修复异常响应观测。** 让已返回响应的 usage/raw_response 在 choices 校验失败后仍保留，保持模型响应与协议接受分开；用离线 HTTP 回归测试验证，不需要再付费验证正常分支。
2. **核对实际费用。** 两次真实请求及价格估算已有 [记录](examples/m0/deepseek-retry-live.json)；取得可对应请求或明确调用时段的账户用量/费用证据，保留币种、价格版本和限制。余额接口不是逐笔账单，不将 CNY 余额当成 USD 估算，不让用户把密钥发入聊天。
3. **不重复已完成的实验。** 除非代码修改影响调用协议、分支语义或有新失败，不重复付费请求。下述命令只保留为未来必要时的入口；先核对当时协议和适用价格：

```bash
UV_CACHE_DIR=/tmp/agenttinker-uv-cache uv run agenttinker-m0 --mode live --provider deepseek \
  --output artifacts/m0-deepseek-live.json
```

需要费用估算时，先核对价格适用性，再通过 --pricing 显式选择版本化价格文件；可参考 [M0 验证说明](docs/m0-validation.md)，不能在未核对时默认采用高峰快照。

4. **形成可审阅结果。** 更新 M0 验证说明、日志和本文件；m0_real_call_verified=true 只表示真实调用/分支检查通过，不能替代完整费用验收。完整产品参考实验包仍由 M3/M4 实现。
5. **满足架构退出条件后进入 M1。** 先 CORE-01 定义事件、对象与状态机，再按 STORE-01 等任务实现 SQLite、事件追加与 SSE 续传去重，涵盖取消和中断；每块工作验证、记录、提交、推送并核对远程。

如环境仍受阻，准确记录错误及缺失配置，继续既定范围内不依赖真实调用的独立工作；不将 M0 标为完成，也不擅自跳过阶段依赖或改写产品范围。

## 8. 给新对话的最短接续提示

> 请在 Babapei/AgentTinker-preview 的 work 分支接续开发。先阅读 HANDOFF.md、AGENTS.md 和 docs/resumption-audit.md，再核对源码、日志及当前环境。M0 首次真实 DeepSeek 分支已通过，先补异常响应的用量保留和实际费用证据，不重复已通过的付费实验。沿用现有产品设计、M0–M5 路线和每块工作验证后记日志、提交推送的约定；不要重做工程或把旧环境故障当作现状，关键范围变更先与我确定。
