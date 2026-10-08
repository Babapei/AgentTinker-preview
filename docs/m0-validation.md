# M0：检查点分支与记录协议验证

对应 [架构路线 M0](03-architecture-roadmap.md#10-开发顺序与完成条件)。本阶段验证运行语义，不代表实验工作台已经实现。

## 本地环境

使用 Python 3.12 或更高版本及 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在仓库根目录执行：

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run agenttinker-m0 --mode synthetic
```

`uv.lock` 固定实际解析的依赖版本；`.venv` 与本地运行产物不入库。产品 Python 包使用 `agenttinker`，仓库名的 `-preview` 不进入包名。本仓库尚未发布 Python 包。

## 当前进度

- 已建立 Python 工程、LangGraph/Pydantic 依赖与代码检查工具。
- 已用真实 LangGraph 引擎和模拟模型验证检查点分支、A/B 新增调用计数和历史不变性；模型来源明确标为 `synthetic`。
- 已加入官方 OpenAI SDK 的 Chat Completions 调用入口及配置校验；SDK 请求使用模拟 HTTP 响应进行测试。
- 已加入 DeepSeek 非思考模式的请求配置，复用同一个 SDK 和检查点流程；真实请求仍待密钥及网络访问就绪。
- 真实模型调用待配置提供商、模型和凭据；M0 的真实调用验收尚未完成，SDK 模拟响应不作为真实调用证据。

## 超时与重试验证

运行上面的 `--mode synthetic` 命令会生成 `artifacts/m0-synthetic.json`。仓库保存了一份 [模拟模型验证记录](../examples/m0/synthetic-retry.json)，包含 A/B 输入输出、span、checkpoint、夹具哈希和检查结果；它不是实际 LLM 运行。

流程使用一个模型节点和一个本地只读检索工具：

1. 模型选择 `search_documents` 后，LangGraph 保存工具执行前的 checkpoint。
2. A 的首次工具尝试按固定规则注入超时，重试次数为 0，运行失败。
3. 从该 checkpoint 创建 B，只将 `tool_retry_limit` 改为 1，保留模型产生的工具调用 ID、查询参数和对话前缀。
4. B 的 attempt 重新从 1 计数，仍在第一次尝试超时；第二次尝试检索夹具，随后模型节点生成答案。
5. 比较 A 的全部 checkpoint 祖先和 span 前后是否一致，检查 B 的来源、故障和新增调用计数。

本轮结果：

| 指标 | A | B 新产生的部分 |
| --- | --- | --- |
| 最终状态 | failed | succeeded |
| 模型调用 | 1 | 1（工具后的回答） |
| 逻辑工具调用 | 1 | 1 |
| 工具执行尝试 | 1 | 2 |
| Token / 费用 | 未知 | 未知 |

B 通过 `inherited_model_span_ids` 引用复用的模型前缀，其模型调用和费用不计入 B 的新增量。检索 `top_k=2 → 3` 的分支、不允许的补丁、无效参数、缺失 checkpoint 和多次分支后的旧运行可读性也有针对性测试。

## checkpoint 映射与当前边界

- 每次实验使用独立 LangGraph `thread_id`；A/B 使用同一线程中的不同 checkpoint，以及不同的 AgentTinker `run_id`。
- `update_state(source_checkpoint, patch, as_node="model")` 创建分支 checkpoint，之后从返回的配置恢复。Run 保存明确的终点配置和分支来源，不能用线程最新状态代替 A 的结果。
- 在当前 InMemorySaver 版本中，带 `checkpoint_id` 的历史查询只返回指定 checkpoint。因此验证通过 `parent_config` 遍历 A 的完整祖先，避免只比较终点而误称完整历史不变。
- checkpoint 仅保存在当前进程内；尚不支持进程重启恢复。span 记录是 M0 验证格式，不是 M1 的事件持久化和 SSE 协议。
- `tool_retry_limit` 和 `top_k` 是允许的工具策略补丁；查询、运行标识和任意状态不能通过该补丁入口修改。
- 此验证只处理一次串行工具调用，没有实现完整 ReAct 模板、取消、UI、评测或实验导入导出。
- 模拟模型不产生真实 Token 或费用；缺失值保留为 `null`。真实调用与新增费用验收仍需实际提供商及可核对的价格信息。可选价格文件只产生明确标注的估算，不代表账户实际扣费。

## 真实模型验证入口

适配器使用官方 OpenAI SDK（锁定版本 2.54.0）和 Chat Completions 的 function calling 协议。OpenAI 请求配置要求模型支持严格工具 schema、`tool_choice`、`parallel_tool_calls` 和 `max_completion_tokens`；自定义端点需实际验证协议兼容性。DeepSeek 使用下述独立请求配置。

运行前通过 shell 或执行环境配置以下变量，参照 [.env.example](../.env.example)。CLI 不自动加载 `.env`，也不将密钥写入验证报告。

- `OPENAI_API_KEY`：模型账户凭据。
- `OPENAI_MODEL`：明确的模型 ID，也可通过 `--model` 指定。没有默认模型。
- `OPENAI_BASE_URL`：可选的兼容端点；不设置时使用 SDK 默认的 OpenAI 端点。

配置好后执行：

```bash
uv run agenttinker-m0 --mode live
```

成功后生成 `artifacts/m0-live.json`，包含实际返回的模型 ID、完整提供商响应、请求参数、用量、A/B 谱系与检查结果。未配置凭据或模型时退出码为 2，提示 `provider_not_configured`；不生成成功记录，也不降级为 synthetic。调用或协议验证失败时退出码为 1，另存 `artifacts/m0-live.failed.json` 诊断，保留已有成功报告。

M0 通过明确的 `tool_choice` 要求首次调用检索，得到工具结果后要求模型回答；它验证执行边界，不评价模型自主选择工具的能力。SDK 自动重试关闭，单次请求超时为 30 秒，输出上限为 1024 个 completion tokens。B 复用真实产生的工具调用与对话前缀，仅新增工具后的模型请求。

当前环境没有就绪的模型凭据，受限网络也尚未允许模型端点。已加入 DeepSeek 验证配置；仍需通过环境配置提供凭据与网络访问，才能执行真实验收。

即使真实模型流程通过，费用仍需结合可核对的价格版本判断；未指定价格或必要用量缺失时，金额保留未知。`m0_real_call_verified` 仅标识真实模式的调用/分支检查通过，不代表 M0 的全部费用验收或后续应用已完成。

## DeepSeek 验证配置

截至 2026-10-08，官方推荐的 Flash 模型 ID 为 `deepseek-flash`。[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/) 推荐先用它进行本实验；具体模型由 `DEEPSEEK_MODEL` 或 `--model` 明确指定。

通过环境配置 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL=deepseek-flash`，可选 `DEEPSEEK_BASE_URL`，默认地址为 `https://api.deepseek.com`。DeepSeek 配置不回退到 OpenAI 的密钥或模型。

```bash
uv run agenttinker-m0 --mode live --provider deepseek
```

DeepSeek 请求显式关闭思考模式，使用 `max_tokens`，不发送 OpenAI 的 `parallel_tool_calls` 和 `max_completion_tokens`。标准端点不启用 Beta 的 strict 属性，工具参数仍由本地校验。named tool_choice 与非思考模式的配合依据 [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)；strict 的 Beta 条件依据 [Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)。

SDK 保留原始缓存命中/未命中用量，供费用核对使用。官方价格区分缓存和高峰/低峰，不应仅用一个固定输入单价推断实际扣费。真实运行仍需环境允许访问 `api.deepseek.com`；目前尚未配置。

## 新增用量和价格核对

每个 Run 的 `new_usage` 仅汇总该 Run 新产生的模型 span，报告用量覆盖的调用数。缺失或不一致的用量使完整总数保持 `null`，同时保留原始 span；B 继承的模型前缀不会重复计入。

DeepSeek 的缓存命中/未命中字段和 SDK 的 `prompt_tokens_details.cached_tokens` 会交叉核对。总 Token 必须等于输入加输出，缓存命中加未命中必须等于输入；字段冲突时不估算费用。缺失缓存分解而命中/未命中价格不同，也不能推断缓存为零。

价格快照包含提供商、精确模型 ID、来源 URL、采集日期、版本、美元币种与时段。仓库保存 [Flash 高峰快照](../examples/m0/pricing-deepseek-flash-peak.json)和 [Flash 低峰快照](../examples/m0/pricing-deepseek-flash-off-peak.json)，取自 2026-10-08 的官方页面；使用前核对是否仍适用于账户和调用时段。

明确选择适用的快照后，例如：

```bash
uv run agenttinker-m0 --mode live --provider deepseek \
  --pricing examples/m0/pricing-deepseek-flash-peak.json
```

金额用 Decimal 计算，以字符串保存；`new_cost_details.kind=estimate` 表明它是价格表估算。若部分调用缺少价格或用量，完整金额为 `null`，已知部分保存在明细和覆盖数中。价格按实际返回的模型及提供商匹配，不自动按请求别名套价。原始 span 不因新增估算而改写。

程序不自动判断节假日、调用跨时段或账户折扣；选择的快照及条件由报告保留，实际账单需另行核对。价格 JSON 在调用模型前校验，无效文件不会触发模型请求。

## 失败诊断与真实验收待办

执行失败时，诊断文件保留已发生的模型和工具调用、已知用量、分支来源以及最后一个 checkpoint。错误记录包含异常类型、执行阶段和可获取的 HTTP 状态，不保存异常原文、响应头或认证信息。模型已经返回、但响应截断或工具参数无效时，保留返回的响应，停止执行工具。

失败节点未写入新的 checkpoint 时，快照可能仍为 `running`；报告通过 `observed_status=failed` 单独记录观察到的失败，不改写旧历史。诊断始终标记 `m0_real_call_verified=false`，缺失用量保持未知。报告先完整序列化并写入临时文件，再替换目标文件，避免写入失败截断旧报告。

截至 2026-10-08，47 项测试及 synthetic 的 7 项分支检查通过；真实 DeepSeek 调用尚未执行。当前还需配置：

- 环境凭据 `DEEPSEEK_API_KEY`；不要将密钥粘贴到聊天或提交到仓库。
- 环境变量 `DEEPSEEK_MODEL=deepseek-flash`；默认端点已内置，无需另设地址。
- 执行环境允许访问 `api.deepseek.com`。

环境就绪后运行 live 验证，核对实际响应、A 的原始历史、B 的新增调用与用量，再用适用价格快照和账户账单核对费用。完成这些证据前，M0 保持进行中，不进入 M1。
