# AgentTinker 开发断点与交接

更新时间：2026-10-19（Asia/Shanghai）。面向新对话、新环境及中断后的接续开发。

**M0–M4 已完成，M5 进行中。** 当前回归：302 Python、81 Vitest 已重新全量通过；43 项 Chromium 全量沿用 M4 应用基线；M5 内置首版完整生产页面演练与 Phoenix 初步操作单独记证据，均不计为真实用户试用。文档 v2、规则评价/人工复核、实验包导入导出和无密钥阅读已接；三份参考包覆盖两类实验，生产页面六条来源记录只读核对通过。旧 v1 文档 B 的协议失败保留；新 v2 A/B 均完成执行，B 读到必需正文后生成 hrelease-v2 错误引用，规则判 fail，18/19 采集检查满足、real_reference_verified=false。M4 按原 P06–P10 完成功能验收，引用失败未改为通过。文档累计 11 次请求、8611 Token，另有 M3 超时案例 2 次、624 Token；费用/实际账单未知。实际账单按用户确认独立待办，不重复询问。

## 1. 接手先确认这几件事

1. 阅读本文件、[工作规则](AGENTS.md)、[开发约定](CONTRIBUTING.md)和 [README](README.md)。
2. 阅读 [产品设计](docs/02-product-design.md)、[架构路线](docs/03-architecture-roadmap.md)和 [开发日志](docs/development-log.md)；需要理解复用选择时查看 [竞品调研](docs/01-landscape.md)。
3. 执行 git status、git log、git remote，核对实际 checkout 和远程；保留已有改动。若后续代码与本快照不同，以实际提交和更新后的日志核对进度。
4. 检查当前环境的配置与真实可访问性。不要沿用旧环境“已发布”“已就绪”或“已失败”的推断。
5. 从第 7 节接续内置首版的 M5 剩余实操与真实使用验证，沿用已完成的 M0 证据，不重复询问账单等待口径。持久化/fork 后端见 [运行服务](docs/runtime-service.md)；不能把模拟/离线 SDK 测试写成新的真实提供商调用。

本文件是当前状态索引；详细设计以对应文档为准。每个完成的工作节点继续更新开发日志；阶段、阻塞、入口或下一步变化时，同步维护本文件。

## 2. 已确定的用户意图和开发约定

- 正式产品名 **AgentTinker**；仓库 **AgentTinker-preview**，完成后由用户移除仓库名的 -preview。本机旧目录名不决定产品或仓库名称。
- 愿景是 Learn、Playground、Builder、Debugger、Evaluation、Explore 六模块共享实验与运行记录。首版按文档先打通有证据的故障诊断、分支和对比闭环。
- 复用成熟执行引擎、模型 SDK、图形组件和可用能力，围绕既定产品做适配；“复用”不等于只拼接外部产品页面，也不意味着擅自删改原架构任务。
- 用户已授权按当前文档持续推进日常实现。产品定位、范围、关键架构或验收条件若需变更，先说明依据、影响并与用户确定；不要只因用户提出一个想法就直接改写方案。
- 2026-10-18 用户进一步确认“先把我们的这个做完再做成可选的”：先完成内置首版 M0–M5、实际使用验证与反馈修正，再把 Codex/OpenCode/DeepSeek Harness 等外部 Agent 做成可选接入。M4 完成不等于原计划全部完成；当前先推进 M5，不提前转入外部 Agent 适配。通用记录/回放/对比与适配器执行控制分开，外部能力须实际验证；独立 v2 的既有授权持续有效。
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

Git 保存了源码、锁文件、设计、日志和 examples 中的示例。本次新增的 [真实 DeepSeek 技术验证记录](examples/m0/deepseek-retry-live.json)也纳入版本管理。artifacts/、.venv/、缓存及 .env 文件不入库，不能将它们视为已备份。本环境 artifacts 含 synthetic、live 和不入库的账户查询产物；不可整目录提交。M0 checkpoint 仍在内存，JSON 报告不能恢复；新版服务另存真实 SQLite saver 数据库，详见第 7 节。

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
| [runtime](src/agenttinker/runtime) | 单 owner/幂等/取消；官方 SQLite saver、版本/可用性检查、单变量 fork、前缀继承和重启中断恢复 |
| [web](web) | React/Vite 实验表单、运行/取消/单变量分支、父子配置/过程/输出/新增量对比、讲解；事件检查/回放和图/详情 |
| [api](src/agenttinker/api) | 创建/读取/取消/fork、checkpoint 当前可用性、分页、SSE 心跳/补发、协议 schema |
| [tests](tests) | 302 项 Python、81 项 Vitest、43 项 Chromium全量；模型侧为模拟/离线 SDK |

本次实际安装版本：LangGraph 1.2.14、langgraph-checkpoint 4.3.0、langgraph-checkpoint-sqlite 3.1.2、OpenAI SDK 2.54.0、Pydantic 2.13.5、FastAPI 0.143.2、Uvicorn 0.54.0。SQLite saver 要求 checkpoint >=4.3.0，依赖以锁文件为准；原 M0 真实证据的版本不改写。

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
| M3 | 已完成：超时实验、单变量分支、A/B 对比/讲解、P01–P05/P09 和当前协议真实参考 |
| M4 | 已完成：原 P06–P10、文档 v2 真实执行/分支、规则与人工复核能力、两类实验的三份包及六条记录生产无密钥阅读；B 引用规则仍 fail、语义未复核，见 [M4 验收](docs/m4-acceptance.md) |
| M5 | 进行中：[内置首版完整生产页面助手演练](examples/m5/native-walkthrough.json)和[Phoenix 初步对照](docs/m5-tool-comparison.md)已完成；原定工具对照剩余操作、5 位真实试用者及反馈待完成 |

本地 FastAPI 与 React/Vite 已接任务/模式/策略配置、运行取消、历史检查及事件回放，尚未公开部署。服务的 LangGraph checkpoint 已由独立 SQLite saver 持久化；M0 CLI 的内存状态仍不能跨进程恢复。运行服务已验证在途模型/工具取消与队列取消；HTTP/SSE 已通过真实本机 TCP 断线续传与取消集成验证。

首版技术路线仍为 React/TypeScript/Vite + React Flow、Python/FastAPI/Pydantic、LangGraph、SQLite + 文件存储、HTTP + SSE。公开托管、域名、额外模型和外部工具服务尚未确定；当前不需要额外托管数据库或搜索服务账号。

## 6. 环境验证与快照

2026-10-19 M5 本机试用入口：环境修订224、观测当前、running/connected、网络unrestricted/enforced、DeepSeek配置ready。新增可选 --web-dist，同一进程/地址提供构建页面和原API，启动不调用模型；缺失构建在数据库/监听前拒绝。302 Python、81 Vitest全量、协议/类型/构建/ruff/格式通过；全量事件夹具在本环境约9.3秒，已改每轮统一生成后读取独立副本，原10秒测试钩子/全部断言保留。43浏览器沿M4，下一节点核对真实CLI的完整M5演练；无新增付费/用户成绩。主入口体积提示保持。

2026-10-18 M5 接续：修订 209、观测当前、running/connected、网络 unrestricted/enforced、DeepSeek 配置 ready；没有 LangSmith 凭据绑定，两个常见 key 变量也不存在。Phoenix 20.23.0 独立本机/无提供商配置/assistant 与 telemetry 关闭，相同两包 4 runs/18 源 spans + 4 展示容器、5063 历史 Token 完成 REST/Chromium 核对；费用原值未知，当前 collector 界面显示 $0，不当作账单。295 Python/ruff/格式及新增工具浏览器检查通过，81 Vitest/43 Chromium 应用基线沿用 M4；无新付费、无真人试用成绩。临时服务/数据只用于本地实操，未部署。

2026-10-18 M4 真实 v2 与最终功能核对：真实调用前修订 202、observations_current=true、running/connected、网络 unrestricted/enforced、DeepSeek 配置 ready。新增 5 次请求/4439 Token，两条执行成功但 B 引用规则 fail，18/19 checks、real_reference_verified=false。292 Python、81 Vitest、43 Chromium 全量及静态/构建检查通过；生产页面三包六记录无密钥阅读通过。M4 按原标准完成功能验收，M5/外部 Agent 未开始；以下保留之前快照。

2026-10-18 M4 v2：环境修订200、观测当前、running/connected、网络 unrestricted/enforced、DeepSeek 配置 ready。290 Python、81 Vitest、43 Chromium全量及协议/类型/生产构建/格式/ruff通过；新建默认v2，旧未确认v1保留原内容/key，不自动升级。CLI离线v2采集19 checks全满足，A3/B新增2次模型、3/4工具，用量/费用未知、real_reference_verified=false；没有新增付费请求。主入口524.17kB/gzip157.62kB仍有体积提示。

2026-10-18 M4 接续：环境修订176、observations_current=true、running/connected、网络 unrestricted/enforced、DeepSeek 配置 ready。已核对官方文档，未找到 Chat Completions 单调用强制保证，Responses API 明确忽略并行开关；见[执行协议方案](docs/document-tool-protocol-decision.md)。请求配置冻结/兼容检查已实现：新模板完整冻结，旧模板从首次观察核对；独立 v2 串行多意图方案已确认，不先扩大执行范围，无新增付费调用。

2026-10-17 M4 参考：环境修订120、running/connected、网络 unrestricted/enforced、DeepSeek 配置 ready。248 Python、70 Vitest、41 Chromium、协议/类型/生产构建/格式/ruff 通过。额外生产浏览器在移除凭据/禁止模型构造后核对四条真实来源记录，哈希不变，live未配置503。M4仍进行中：真实候选B协议失败；六次新文档请求4172 Token，金额未知，详见 M4 退出核对。

2026-10-17 M4 文件界面：231 Python、70 Vitest、40 Chromium、共享协议/类型/构建/格式/ruff 通过。浏览器全量移除提供商密钥/模型变量，验证两个实验 A/B 文件往返、原意见/来源、显式重试和摘要降级。无新增付费调用；主入口约 523 kB/gzip 157 kB，仍有构建体积提示，加载性能未验收。

2026-10-17 M4 实验包：231 Python，ruff/格式/diff 通过；导出 19 项与导入 16 项新增离线验证。环境运行/连接、修订 119，网络 unrestricted/enforced、配置 ready；无新增付费调用。前端沿用此前 65 Vitest/35 独立 Chromium，当前节点未修改界面。

2026-10-17 M4 评价与界面：环境重查 running、修订 118，网络 unrestricted/enforced、配置 ready。196 Python、65 Vitest；33 项浏览器全量通过后补充边界，7 项文档定向通过，共 35 项独立用例。全为模拟/离线 SDK；无新增付费调用。实际账单独立未知。


2026-10-16 M3 验收：环境 running、修订 80，网络 unrestricted/enforced，DeepSeek 密钥/模型 ready，实际 SDK 两次成功。165 Python、55 Vitest、27 Chromium 与真实参考只读核对通过。本轮真实用量 624 Token；未选价格表，费用与扣费未知，旧阶段快照保留如下。

2026-10-16 M3 后端：165 项 Python、41 项 Vitest、15 项 Chromium 通过，版本/构建/格式检查通过；环境状态 running、修订 77，网络 unrestricted/enforced，DeepSeek 密钥及模型变量 ready，本轮无新增付费调用。以下保留 M2 与首次接续的历史核对。

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

## 7. 下一步：先完成内置首版 M5，再做可选接入

1. **M0–M4 功能阶段已完成。** 对照 [M4 验收](docs/m4-acceptance.md)和原 P06–P10，当前内置实验已有真实模型执行/分支与只读阅读证据。v2 B 的 hrelease-v2 引用 fail、18/19 checks 和 real_reference_verified=false 保持；没有人工语义复核或普遍策略结论。
2. **下一项完成内置首版的 M5 实际验证。** [同案例任务/记录材料与内置完整助手演练](docs/m5-validation.md)、[Phoenix 初步操作](docs/m5-tool-comparison.md)已有证据。两个原生模拟 A/B 和四份文件往返在真实 CLI/生产构建中检查了 12 条记录，播放期间 API 请求为 0，原真实引用 fail 保留；不计为参与者。继续补齐 Studio/Phoenix 对照剩余操作、小规模真实试用及反馈；当前没有 LangSmith 配置或真实试用数据。首轮目标仍为 5 位试用者中至少 4 位无需作者代操作完成一个场景，并检查回放/执行及未知费用的理解；目前没有真实研究成绩，不能用自动化或助手自测代替。
3. **外部 Agent 后移，作为可选扩展。** 内置首版及 M5 反馈处理完成后，再选择首个现成 Agent，验证事件映射、启动/取消、会话续接与旧点分支边界。后续可复用通用记录/检查/回放/文件基础，执行控制与任务评价按对象适配；当前没有实现外部原始日志解析器、可执行适配或新的 Agent 选择界面，也不将其设为内置使用的前置条件。
4. **保留原生版本与数据规则。** serial-checkpoint:2 仍是 bounded model→tool→model；文档 v1 每响应单意图，v2 整批预检后逐工具串行，最多 8 模型/7 工具。仅首检索点允许 top_k 分支；原工具前超时点允许 retry 分支。每次只改一个允许非原值字段、源 Run 终态、动态检查版本/能力/配置。Intervention 原子保存、前缀只引用，原事件和全部旧 saver 行不变。旧未确认请求保留版本/内容/key，不自动升级。
5. **真实参考与费用。** [三份参考包](examples/m4/README.md)覆盖两类实验；[六条记录生产检查](examples/m4/reference-browser-v2.json)确认模型构造 0、播放 API 0、视图/再导出一致，未配置 live 503。新文档 5 次/4439 Token，加此前 6 次/4172，共 11 次/8611；旧 M3 超时 2 次/624 另列，原 M0 的 634 Token/价格估算不套用。金额/实际账单未知，不为绿色样本或账单等待重复付费。
6. **入口和持久化。** bash scripts/setup.sh 安装；先 npm --prefix web run build，再 uv run agenttinker-server --database artifacts/runs.sqlite --web-dist web/dist，即在 8000 同时提供页面/API；省略该参数仍为原 API，开发时 npm --prefix web run dev 默认 5173。状态在 `<database>.checkpoints.sqlite`，需保留事件库/saver 并正确处理 WAL；跨库无原子事务，未发布状态不自动恢复。Git 不备份 artifacts。公开部署和加载性能未验收，主入口 524.17 kB/gzip 157.62 kB 有体积提示。
7. **继续逐节点完成。** 验证、更新日志/受影响文档、提交并推送 work，核对远程。日常实现与既定账单口径已授权，关键范围变化先讨论；用户已确认先完成内置首版原计划，再做可选外部 Agent，不重复请求顺序确认。

## 8. 给新对话的最短接续提示

> 请在 Babapei/AgentTinker-preview 的 work 分支接续，先读 HANDOFF.md、AGENTS.md、M4 验收和日志，再核对 Git/环境。M0–M4 功能验收已完成，302 Python、81 Vitest、43 Chromium 全量及静态/构建通过。v2 真实 A/B 均完成、B 读到必需正文，但 hrelease-v2 引用规则 fail，18/19 checks、real_reference_verified=false，语义未复核。三份包覆盖两类实验、生产页面六条来源记录无密钥回放/再导出通过；旧 v1 失败/请求身份/全部旧历史保留。文档累计 11 次/8611 Token（本次 5/4439），费用和实际账单未知。用户进一步确认先完成内置首版 M0–M5 和试用反馈，再把现成 Agent 做成可选接入；M5 同案例任务/观察指南/空白记录已准备，Phoenix 20.23.0 用相同两包完成 4 runs/22 派生 spans 的初步历史观察，旧 Token/未知费用/错误引用保留；其 $0 汇总不当账单。内置首版真实 CLI/生产 UI 完整助手演练已通过，两类原生模拟 A/B 及四份文件往返共 12 条记录，播放 API 请求 0、人工复核新增 0；原真实引用 fail 保留。下一项补齐工具对照剩余操作/Studio 条件与真实试用，不提前做外部适配。真实用户成绩待取得，不生成虚构成绩；完整六模块的后续扩展也不能称全部做完。逐块验证、记录、提交推送，不重复询问既有账单口径。
