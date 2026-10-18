# M5：Studio 与本机 Agent Server 对照

2026-10-19。**API 控制已验证，两个场景的 Studio 页面操作接续检查；M5 尚未完成。** 全部为助手操作与明确模拟模型，不是真实用户成绩，也没有新的提供商请求。

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

[机器摘要](../examples/m5/studio-control.json)标记 assistant_api_check、counts_as_user_session=false，用户成绩/耗时为 null；未新增提供商调用，模型用量与费用仍未知。三项新增回归逐步比较桥接与平台原生模拟 A/B 的输出，验证旧状态不变与冻结配置拒绝；308 Python 全量通过。Studio 页面内创建/编辑/分支的完成情况另记，不能从 API 成功推导全部界面操作通过。

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
```

打开 `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:12025`。这个地址连接浏览器所在机器的本地服务，不是公开部署。保留继承代理/TLS；没有公共隧道、域名或外部数据库。开发版本本次为 CLI 0.4.36、API 0.16.1、inmem 0.36.1、SDK 0.4.6，底层 LangGraph 仍为锁定的 1.2.14；依赖只用临时 uv --with，应用锁文件不变。

默认摘要与详细状态写到 artifacts/m5-studio-control.json / .state.json；开发服务的私有状态与日志也在准备目录，均不入 Git。证据摘要不是 saver 备份，结束后由启动终端停止服务。
