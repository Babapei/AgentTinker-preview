# AgentTinker 开发断点与交接

更新时间：2026-10-16（Asia/Shanghai）。面向新对话、新环境及中断后的接续开发。

**M0–M2 已完成，下一步 M3 首个实验闭环。** 已有持久化运行服务、HTTP/SSE、事件校验与补发、列表/实际执行图、步骤详情、时间线和只读历史播放；后端 136 项、前端 40 项单元与 15 项浏览器测试通过。证据见 [M2 验收](docs/m2-acceptance.md)、[M1 验收](docs/m1-acceptance.md)和 [M0 验收](docs/m0-acceptance.md)。实际账单按用户确认独立待办，不重复询问。

## 1. 接手先确认这几件事

1. 阅读本文件、[工作规则](AGENTS.md)、[开发约定](CONTRIBUTING.md)和 [README](README.md)。
2. 阅读 [产品设计](docs/02-product-design.md)、[架构路线](docs/03-architecture-roadmap.md)和 [开发日志](docs/development-log.md)；需要理解复用选择时查看 [竞品调研](docs/01-landscape.md)。
3. 执行 git status、git log、git remote，核对实际 checkout 和远程；保留已有改动。若后续代码与本快照不同，以实际提交和更新后的日志核对进度。
4. 检查当前环境的配置与真实可访问性。不要沿用旧环境“已发布”“已就绪”或“已失败”的推断。
5. 从第 7 节接续 M3，沿用已完成的 M0 证据，不重新要求用户确认账单等待口径。

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
- 2026-10-15 用户已明确批准：M0 以真实用量和可追溯费用估算验收，实际账单核对独立保留为未知/待办，继续进入 M1。该决定持续有效，不重复请求批准。

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
| 0c1f3d3 | 新环境全仓审视及首次真实 DeepSeek 分支证据 |

Git 保存了源码、锁文件、设计、日志和 examples 中的示例。本次新增的 [真实 DeepSeek 技术验证记录](examples/m0/deepseek-retry-live.json)也纳入版本管理。artifacts/、.venv/、缓存及 .env 文件不入库，不能将它们视为已备份。本环境 artifacts 含 synthetic、live 和不入库的账户查询产物；不可整目录提交。当前 checkpoint 只在单个进程内存中，JSON 报告不能恢复已退出进程的 checkpoint。

## 4. 已实现的代码及边界

| 文件/目录 | 已实现内容 |
| --- | --- |
| [pyproject.toml](pyproject.toml)、uv.lock | Python >=3.12、uv、LangGraph、Pydantic、OpenAI SDK、filelock、FastAPI/Uvicorn、pytest、ruff |
| [scripts/setup.sh](scripts/setup.sh) | 固定安装入口：定位仓库并执行 uv sync --locked；不调用模型 |
| [probe.py](src/agenttinker/m0/probe.py) | StateGraph、InMemorySaver、工具前 checkpoint、允许字段分支、A 历史不变性检查 |
| [fixtures.py](src/agenttinker/m0/fixtures.py) | 带版本与哈希的虚构发布说明、本地只读检索 |
| [models.py](src/agenttinker/m0/models.py)、[synthetic.py](src/agenttinker/m0/synthetic.py) | M0 模型/策略/span 类型与明确标注的模拟模型 |
| [openai_model.py](src/agenttinker/m0/openai_model.py) | 官方 SDK 薄适配、原始响应和请求/用量保留、独立配置校验 |
| [deepseek_model.py](src/agenttinker/m0/deepseek_model.py) | DeepSeek 非思考模式请求，保留工具调用与缓存用量 |
| [accounting.py](src/agenttinker/m0/accounting.py) | 每个 Run 新增 Token 覆盖率、缓存字段核对、版本化价格与 Decimal 估算 |
| [cli.py](src/agenttinker/m0/cli.py) | 显式 live/synthetic 模式、价格输入、原子写报告和单独失败诊断 |
| [core](src/agenttinker/core) | M1 的 Run/Span/CheckpointRef/Artifact、版本引用、能力、用量费用、类型化事件、状态转换与纯重建；与 M0 格式分开 |
| [storage/sqlite.py](src/agenttinker/storage/sqlite.py) | SQLite 原子事件追加与缓存投影、事务内序号、幂等重试、游标读取、重建、父分支引用与内容寻址 artifact |
| [runtime](src/agenttinker/runtime) | 单 owner、幂等启动、真实 LangGraph 串行执行、协作式取消和重启中断恢复 |
| [web](web) | React/Vite 检查页、共享协议生成/校验、历史/步骤/原始数据；事件校验/订阅/补读、列表/图、时间线与独立播放状态 |
| [api](src/agenttinker/api) | 本地服务入口、创建/读取/取消、分页、SSE 心跳和游标补发、协议 schema |
| [tests](tests) | 136 项 Python：M0 63 项，核心 32 项，存储 13 项，运行服务 12 项，API 16 项；另有前端 40 项 Vitest 与 15 项浏览器测试 |

本次实际安装版本：LangGraph 1.2.14、langgraph-checkpoint 4.2.0、OpenAI SDK 2.54.0、Pydantic 2.13.5、FastAPI 0.143.2、Uvicorn 0.54.0。依赖安装以仓库锁文件为准。

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
- M0-07 已修复异常 choices 响应丢失用量的问题：SDK 适配器先保留请求、响应 ID、choice_count、usage/raw_response；probe 记录 span 后在 model_protocol 阶段拒绝空/多个 choices。16 项离线回归覆盖两个适配器、A/B 两个阶段和用量已知/缺失，验证保留实际返回值、不调用后续工具、不重复计算继承前缀。本节点未重复付费调用。

## 5. 阶段进度与后续目标

| 阶段 | 当前状态 / 下一阶段目标 |
| --- | --- |
| M0 | 技术验收完成；真实分支、新增用量、价格估算与异常响应观测均已核对，实际账单独立待办 |
| M1 | 已完成：核心协议、存储、串行运行服务及 HTTP/SSE；失败/重试/取消、刷新、断线续传去重已验证 |
| M2 | 已完成：实际事件驱动的列表/图、节点详情、时间线、只读播放；未知值与缺失事件降级已验证 |
| M3 | 未开始：完整超时实验、单变量 fork、A/B 对比和内嵌讲解 |
| M4 | 未开始：第二个实验、评价、实验包导入导出、真实参考记录无密钥回看 |
| M5 | 未开始：实际工具对照与用户使用验证 |

本地 FastAPI 服务已实现；React/Vite 工程已建立；只读检查页已接后端历史与步骤，校验事件后跟随持久化进度，尚无持久化 LangGraph checkpoint 或公开部署。SQLite 已持久化对象、事件和 CheckpointRef，但引用不等于运行时可恢复状态；M0 内存 checkpoint 仍不能跨进程恢复。运行服务已验证在途模型/工具取消与队列取消；HTTP/SSE 已通过真实本机 TCP 断线续传与取消集成验证。

首版技术路线仍为 React/TypeScript/Vite + React Flow、Python/FastAPI/Pydantic、LangGraph、SQLite + 文件存储、HTTP + SSE。公开托管、域名、额外模型和外部工具服务尚未确定；当前不需要额外托管数据库或搜索服务账号。

## 6. 环境验证与快照

2026-10-16 M2-04：固定安装入口通过，后端 136 项、前端 40 项单元与 15 项浏览器集成通过；协议/类型/生产构建/格式检查与 ruff 通过。当前环境状态重查为 running、修订 71，网络 unrestricted/enforced，DeepSeek 密钥及模型变量 ready。本轮没有新增付费调用。服务入口见 [HTTP/SSE](docs/runtime-api.md)。以下保留首次接续时的实测依据。

| 操作 | 实际结果 |
| --- | --- |
| UV_CACHE_DIR=/tmp/agenttinker-uv-cache bash scripts/setup.sh | 成功，锁定依赖同步通过；默认缓存只读，未修改依赖或安装脚本 |
| uv run pytest -q | M1-02：108 passed |
| uv run ruff check . | 通过 |
| uv run ruff format --check . | 通过 |
| uv run agenttinker-m0 --mode synthetic --output artifacts/m0-core-regression-synthetic.json | M1-01：7 项 checks 全部 true，m0_real_call_verified=false；不重复真实付费实验 |
| git ls-remote origin refs/heads/work | 与本次核对起点一致 |
| curl HEAD https://api.deepseek.com（无密钥） | 到达服务端，HTTP 401；未被旧环境的代理 403 阻止 |
| SDK 鉴权模型列表 | 成功，配置的 deepseek-flash 可用 |
| live DeepSeek + 显式低峰价格 | 7 项 checks 全部 true，m0_real_call_verified=true；A/B 各新增一次模型请求，工具 attempts 为 1/2 |
| 真实用量与估算复算 | A 374 Token / 0.00007095 USD；B 新增 260 Token / 0.00007545 USD；合计 634 Token / 0.00014640 USD，仅为价格表估算 |
| SDK 账户余额查询 | HTTP 200，账户可用，币种 CNY；没有两次请求的独立实际扣费凭证 |

uv 命令在本环境使用 `UV_CACHE_DIR=/tmp/agenttinker-uv-cache`。继续保留继承的平台代理和 TLS，不通过修改策略文件或绕开代理解决访问；命令工具权限以当前会话为准。

首次审视时状态接口为 unknown；M0-07 时修订 3 已就绪，M1 接续时重查修订 4，observations_current=true、running，网络 unrestricted/enforced，DEEPSEEK_API_KEY 和 DEEPSEEK_MODEL 均 ready。正常 SDK 的鉴权和推理此前已实测成功，不再要求用户重复配置已可用密钥。

旧环境曾为 restricted/enforced、无变量并被代理以 403 拒绝，设置保存/发布问题的具体原因仍未确认；详见旧日志。它不是本环境的现状。本次真实请求发生在北京时间 20:14（UTC 12:14），7 项检查和 A 的 4 个 checkpoint 不变性均通过，估算已核对，但未取得逐笔账单。未来换环境仍需重查。

## 7. 下一步：M3 首个实验闭环

1. **M0–M2 已完成。** 技术验证、运行记录、事件重建/订阅/补发、列表/图/详情/时间线及只读历史播放已有验收证据。前端 40 项 Vitest、15 项实际 Chromium 与后端 136 项回归通过；M2 模型侧为明确模拟，不重复付费。见 [M2 验收](docs/m2-acceptance.md)及 [前端说明](docs/web-inspector.md)。
2. **先接持久化 checkpoint 与 fork。** 复用 LangGraph saver，保存兼容版本和真实运行时状态；先验证服务重启后能定位旧工具前 checkpoint，再做能力检测、允许字段校验和 fork API。当前 fork_from_checkpoint=false、saver 仍为内存，不能用 UI 事件投影冒充 checkpoint。
3. **单变量对照语义。** 分支仅允许 tool_retry_limit/top_k，保留模型原查询/tool call ID、fixture/版本和同一故障计划。A 首次工具失败，B 新执行区间首次仍注入同样故障；B 引用而不重复执行/计费前缀，A 历史不变。
4. **随后接实验界面。** 任务/运行配置、明确模式、运行与取消、可用边界分支、A/B 差异和内嵌讲解。按产品 P01–P05/P09 验收，真实参考案例按实际需要调用并记录，不把模拟结果冒充真实验证。
5. **入口。** 固定 bash scripts/setup.sh 安装 Python/npm 锁定依赖；uv run agenttinker-server --database artifacts/runs.sqlite 默认本机 8000，npm --prefix web run dev 默认 5173。模拟预览用 uv run python scripts/serve_web_test.py，仅临时数据。生产静态托管和公开部署未实现。
6. **逐节点完成。** 每块验证、更新文档与日志，提交推送并核对远程；日常实现和既定 M0 费用口径已授权，关键范围变化先讨论。
7. **独立账单待办。** 实际扣费仍未知，余额不是逐笔账单；有可对应的费用证据时再核对，不为此重复付费。

## 8. 给新对话的最短接续提示

> 请在 Babapei/AgentTinker-preview 的 work 分支接续。先读 HANDOFF.md、AGENTS.md、docs/m2-acceptance.md、docs/03-architecture-roadmap.md 和开发日志，再核对 Git 与环境。M0–M2 已完成，136 项后端、40 项前端、15 项浏览器验证通过。下一步 M3：先持久化 LangGraph checkpoint、重启定位/能力检测和允许字段 fork API，再任务运行控制、A/B 对比和内嵌讲解。当前 fork 能力仍 false；事件播放不是恢复执行。逐块验证、记录、提交推送，不重复询问已批准事项。
