# M5：Studio 与本机 Agent Server 对照

2026-10-19。**API 控制与两个场景的 Studio 页面提交/状态分支已验证；M5 尚未完成。** 全部为助手操作与明确模拟模型，不是真实用户成绩，也没有新的提供商请求。

## 接入条件的更正

此前根据 local-dev-testing 的前提列表，将缺少 LangSmith API key 记为 Studio 未满足条件。进一步核对[官方 FAQ](https://docs.langchain.com/langsmith/faq#can-i-use-studio-without-logging-in-to-langsmith)、[Studio 快速开始](https://docs.langchain.com/langsmith/quick-start-studio)及[官方本机项目模板](https://github.com/langchain-ai/new-langgraph-project)后，实际启动并连接成功：开发服务使用 noop auth，关闭 LANGSMITH_TRACING/LANGCHAIN_TRACING_V2，移除 LangSmith 和提供商变量，托管 Studio 可无登录连接本机。

因此，**没有 LangSmith key 不等于本机图无法运行或 Studio 无法连接**。页面的缺少 key 提示涉及 LangSmith tracing；本轮不将 tracing、托管实验/评价或账户功能记为已配置。旧日志保留，当前状态以本页与新证据为准。

## 复用与适配边界

[研究入口](../scripts/m5_studio/graphs.py)复用 serial-checkpoint:2 和 document-react:2 的原 model/tool 节点、工具实现、故障与重试逻辑、图的边；固定使用现有 SyntheticModel/DocumentBatchSyntheticModel。任务、材料摘要、Agent/提示版本与共同参考一致；provider 明确替换为 synthetic，不将旧真实响应或旧用量当新执行。

Agent Server 提供自己的检查点、状态编辑和调度。桥接 journal 复用原 Span/用量费用处理，输出为 custom stream 观察；没有写平台数据库、私有 saver 或 Intervention。配置冻结检查拒绝更换提供商、任务和材料。文档 top_k 对应的 variant 是派生标签，编辑完整 run_config 时需同步；这是本桥接的配置约定，不是 Studio 的通用限制。

接入发现原图未声明条件路径的目标，LangGraph 的检查输出只有 start→model→end，工具成为孤立节点，虽然执行仍经过工具。已为串行和文档 v1/v2 补齐 path_map：model→tool/end、tool→model，以及 v2 队列的 tool→tool。原节点、路由判断与执行协议不变，图检查现在显示实际支持的路径；不是用 Studio 的错误图示作产品比较。

这里核对的是 Agent Server 的原生状态分支。它不等同于平台 ForkRequest 的单参数/允许边界/版本校验，也不证明取消、崩溃恢复、幂等和任意状态编辑已具备相同保证。没有新增可选外部 Agent 或生产适配器。

## 已完成的 API 操作

[控制检查器](../scripts/m5_studio/check_control.py)使用开发 API 的同一 thread，从旧的首工具前 checkpoint 创建新状态，再指定该新 checkpoint 执行后缀：

| 案例 | A | 仅改一个执行参数后的 B | 旧检查点核对 |
| --- | --- | --- | --- |
| 超时 | 1 模型、1 工具尝试，TOOL_TIMEOUT | retry 0→1；新增 1 模型、2 尝试，先失败再成功 | 3 个完整状态前后相同 |
| 文档 v2 | 3 模型、3 工具尝试 | top_k 2→3；新增 2 模型、4 工具尝试，首模型前缀复用 | 8 个完整状态前后相同 |

API 的 SSE error 对异常消息作了遮蔽；检查器从工具完成观察和持久化 task.error 核对 TOOL_TIMEOUT，没有把通用 “internal error” 当根因。B 的首个工具仍指向 A 的首模型身份；全部旧状态（含 metadata/tasks）摘要不变。A/B 共用 thread，当前 head 已变化，读取 A 必须指定原 checkpoint，不能用最新 head 代替。

文档规则由检查器在本机复用既有纯规则函数运行：A 为 fail/fail/pass，B 为 pass/pass/pass。输入是从完成的 Span 观察适配的临时快照，本地游标只计该观察流，不冒充平台事件序号；没有持久化为平台 Run。它们不是 Studio/LangSmith 原生评价，也不是人工语义复核。模拟 B 通过不替换真实 B 的 hrelease-v2 引用失败。

[API 机器摘要](../examples/m5/studio-control.json)标记 assistant_api_check、counts_as_user_session=false，用户成绩/耗时为 null；未新增提供商调用，模型用量与费用仍未知。三项新增回归逐步比较桥接与平台原生模拟 A/B 的输出，验证旧状态不变与冻结配置拒绝；308 Python 全量通过。页面操作以以下独立证据为准。

## 已完成的页面操作

[页面检查器](../web/scripts/check-m5-studio.mjs)使用全新 Chromium 访客会话，通过正常可见控件分别操作两个场景：显式选择图 → View Raw 填入完整初态 → Submit 创建 A → 从保存的 thread 重新打开历史 → 展开首模型 → Edit node state → 在原始状态编辑器填值 → Fork 执行 B。创建 thread、提交运行、状态编辑及后缀执行均由页面发起；检查器的本机 API 仅搜索/读取状态和历史，未代替点击执行。

编辑保留原首模型输出，只改一个策略字段；另换逻辑 run_id 标记新执行归属，文档 variant 随 top_k 同步派生。run_id/variant 是桥接记账约定，不是新增行为参数。实际捕获的当前 Studio 请求使用 `as_node=__copy__`，指定首模型的输入 checkpoint，以 `[[修改后输出, "model"]]` 应用该模型的写入；Agent Server 生成 `next=tool` 的新状态，后缀请求指定该新 checkpoint。这与 API 控制器直接在模型输出 checkpoint 上 `as_node=model` 的协议不同，均另核对实际前缀和执行步数。B 新增模型步骤为超时 1、文档 2，首模型消息/身份保持；原 A 的 3/8 个完整状态前后相同。超时页面显示 TOOL_TIMEOUT；分支与历史由页面呈现，本机读取进一步核对其持久化结果。

[页面机器摘要](../examples/m5/studio-browser.json)单独标记 scripted_hosted_studio_ui、counts_as_user_session=false，记录实际写入路径、流模式、版本及旧状态摘要。内部重试发生在同一 tool 图节点中；Studio 的图节点不能直接当成每次工具尝试，尝试级 Span 已由前述 custom stream API 检查核对。截图与详细状态仅保存在忽略的 artifacts。

检查器开发时曾在图选择尚未确认时把超时输入提交到默认文档图，冻结检查在模型构造前拒绝；已补为显式选择并核对当前图与请求 assistant 身份后重跑，不将这次拒绝当场景结果。页面列表采用虚拟滚动，检查器只展开对应首模型，不把未挂载节点误判为缺少编辑功能。

当前访客环境仍出现缺少 tracing key 的横幅及远程 onboarding 请求 403；每例另捕获页面异常名 e，未采集异常原文或确认归因。本机操作按以上范围完成，没有声称浏览器零错误。点击 Trace 实际到达 LangSmith 注册/登录页，没有登录或填写账户；Run experiment 在本次页面为不可用。没有据此宣布所有 Studio 操作需要账号，也没有把本机图历史当成 LangSmith 托管追踪或评价。

## 当前能说明的控制差异

| 项目 | 本次实际证据 | 判断边界 |
| --- | --- | --- |
| 图状态分支 | Studio 可从原首模型后的旧点编辑 JSON 并执行后缀；前缀和全部原 A 状态保留 | 不能再把“旧点分支”当作仅本平台具有的能力 |
| 实验约束 | 本平台通过允许点与单字段表单创建分支；Studio 本桥接需维护完整配置、run_id 和派生 variant | 这是当前集成与操作方式差异；没有测量人类难度或优劣 |
| 步骤与尝试 | 图展示 model/tool 步骤；同节点内部重试由原 Span custom 观察核对 | 不把一个图节点等同于一次工具尝试或一次模型请求 |
| 评价 | 本平台有既有规则记录与人工复核入口；本轮 Studio 规则仅在检查器本机执行 | LangSmith 原生评价、人工语义正确性仍未验证 |
| 执行所有权 | Studio 使用 Agent Server 的线程/检查点/调度；本平台使用 RunService/SQLite saver/Intervention | 本次没有验证两者取消、进程退出、恢复与幂等语义相同 |

这组操作说明现有引擎与工具已能提供通用图编辑/分支；AgentTinker 当前工作的价值假设是把实验条件、尝试、来源、比较与解释组织成可用流程。这个假设仍需原定真人试用判断，不能从助手脚本得出产品优势或扩展结论。

## 重现

安装仓库锁定依赖后，从仓库根目录准备一个新的私有目录。准备脚本生成绝对源码引用与两个输入 JSON，避免 CLI 按当前目录解析图路径；不把机器绝对路径提交到 Git。

```bash
export UV_CACHE_DIR=/tmp/agenttinker-uv-cache
STUDIO_REPO_DIR="$PWD"
STUDIO_TASK_DIR="$PWD/artifacts/m5-studio-local"
uv run python scripts/m5_studio/graphs.py --prepare-directory "$STUDIO_TASK_DIR"
cd "$STUDIO_TASK_DIR"
env -u DEEPSEEK_API_KEY -u DEEPSEEK_MODEL -u OPENAI_API_KEY -u OPENAI_MODEL \
  -u LANGSMITH_API_KEY -u LANGCHAIN_API_KEY \
  LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false \
  uv run --project "$STUDIO_REPO_DIR" \
  --with 'langgraph-cli[inmem]==0.4.36' --with 'langgraph-api==0.16.1' \
  --with 'langgraph-runtime-inmem==0.36.1' --with 'langgraph-sdk==0.4.6' \
  langgraph dev --config langgraph.json --host 127.0.0.1 --port 12025 \
  --no-browser --no-reload > server.log 2>&1
```

在另一终端的仓库根目录运行：

```bash
UV_CACHE_DIR=/tmp/agenttinker-uv-cache uv run --with 'langgraph-sdk==0.4.6' \
  python scripts/m5_studio/check_control.py
node web/scripts/check-m5-studio.mjs http://127.0.0.1:12025 artifacts/m5-studio-local
```

打开 `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:12025`。这个地址连接浏览器所在机器的本地服务，不是公开部署。保留继承代理/TLS；没有公共隧道、域名或外部数据库。开发版本本次为 CLI 0.4.36、API 0.16.1、inmem 0.36.1、SDK 0.4.6，底层 LangGraph 仍为锁定的 1.2.14；依赖只用临时 uv --with，应用锁文件不变。

页面检查需要仓库已安装 web/node_modules 和可用 Chromium，默认 /usr/bin/chromium，也可用 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH 指定。它显式沿用继承的 HTTP(S) 代理并仅让 localhost 直连，保留 TLS 校验；本轮没有公共隧道、路由修改或登录凭据。托管前端未锁定版本，重现时需重新核对可见控件，不能将第三方后续变化视为平台回归。

API 默认摘要与详细状态写到 artifacts/m5-studio-control.json / .state.json，页面另写 artifacts/m5-studio-browser.json / .state.json；开发服务的私有状态与日志也在准备目录，均不入 Git。证据摘要不是 saver 备份，结束后检查器关闭自己的 Chromium，启动终端停止开发服务。本轮仍未公开部署，真实用户试用、反馈修正和最终 M5 验收继续待完成。
