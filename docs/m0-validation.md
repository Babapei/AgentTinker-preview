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
- 真实模型调用待配置提供商、模型和凭据；M0 的真实调用验收尚未完成。

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
- 模拟模型不产生真实 Token 或费用；缺失值保留为 `null`。真实调用与新增费用验收仍需实际提供商及可核对的价格信息。
