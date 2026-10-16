# M1：原生串行运行服务

实现位于 [runtime](../src/agenttinker/runtime)，依赖 [运行记录协议与 SQLite](runtime-records.md)。Python 入口与 HTTP/SSE 均已提供，网络接口见 [API 说明](runtime-api.md)。

```python
from agenttinker.runtime.service import RunRequest, RunService

with RunService("artifacts/runs.sqlite") as service:
    view, created = service.submit(
        RunRequest(mode="synthetic", policy={"tool_retry_limit": 1}),
        request_key="local-example-1",
    )
    finished = service.wait(view.run.run_id)
    print(finished.run.status, len(finished.spans))
```

必须显式选择模式。synthetic 不调用提供商，也不生成 Token 或费用；live 需明确 provider，模型与密钥由服务端配置，缺少配置直接拒绝，不回退模拟。模型/工具异常仅保存类型和稳定错误码，不保存原始异常文本。默认未选价格表，费用未知；显式提供匹配 PriceBook 时保留版本化估算，不能当作账单。

## 执行与记录

- 实际执行 LangGraph `model → tool → model`，工具前保存真实 checkpoint 引用；首次超时可注入，重试由执行器唯一负责。仍限定一个逻辑工具调用，不是完整 ReAct。
- 每次外部调用前先提交 span.started，返回后提交 span.finished；保留原始 SDK 请求、响应、usage 和实际模型。协议不合格时结束 Run，但保留已经收到的响应和用量。
- task、工具策略、故障参数、模型参数、版本与 fixture 哈希保存在 RunConfig。共享的模型协议检查用于 M0 和 M1，旧 M0 报告不自动迁移。
- 默认两个线程执行不同 Run；同一 Run 串行。每次数据库操作打开独立连接，SSE 后续只读已提交事实。

## 幂等、取消与恢复

`request_key` 为 1–128 个可打印字符。SQLite v2 原子提交 key、完整请求指纹与 run.created。相同 key 和请求始终返回同一 Run，包括失败、取消和重启后；不同内容冲突，不再执行。排队后调度失败也保留身份和失败原因。

cancel 对终态和重复请求幂等。queued 直接经过 cancel_requested 进入 cancelled，不构造模型适配器。running 先标为 cancel_requested；当前调用返回后保留结果与真实用量，不再启动后续模型、工具或重试，最后进入 cancelled。取消和 span.started 使用同一锁；span.started 提交定义逻辑启动边界，随后收到取消时该调用已算在途。SDK 超时仍为 30 秒且自动重试关闭，不承诺撤回提供商已收到的请求。

每个数据库仅允许一个 RunService owner，通过跨进程文件锁确认；第二个 owner 拒绝启动。正常关闭停止接收请求、取消活动任务并等待在途结果。异常退出后，新 owner 获取锁再把旧非终态原生 Run 标为 interrupted，未返回的用量保持未知；不自动重试或重新发送调用。此机制适用于当前本机单用户服务，不提供分布式调度。

M3 已接入官方 SqliteSaver，真实状态保存在事件库旁的 `<database>.checkpoints.sqlite`。需同时保留两库，运行中备份须正确处理 WAL。saver 先提交状态，再追加 checkpoint.saved；跨库无原子事务，崩溃可能留下未发布状态，服务不据此自动恢复或重发调用。

新版 Agent 为 v2，记录 LangGraph、checkpoint、SQLite saver、SDK、prompt、工具与夹具版本。`resolve_checkpoint(run_id, checkpoint_id)` 只读明确历史配置，核对版本、所属 Run、配置和工具前边界，拒绝缺失、不兼容或错属状态。检查不构造模型、不调用工具、不改写事件。旧内存引用仍可查看，不能恢复；M0 CLI 保持内存 saver。

## M3：从旧点创建分支

新版 Run 声明 fork/patch_tool_policy 支持；声明保留在原始事件中，不因重启或环境变化被改写。`checkpoint_availability(run_id)` 逐项重新检查终态、能力、实际状态、运行时/夹具与价格版本，返回可用性和稳定拒绝原因。旧内存记录保持原能力。live 的凭据和请求参数在提交 fork 时额外检查；只读检测不构造 SDK。

`fork(source_run_id, ForkRequest(source_checkpoint_id=..., patch={"tool_retry_limit": 1}), request_key)` 每次只允许修改一个有效字段：tool_retry_limit 为 0–3，top_k 为 1–3，整数严格校验。空补丁、原值、多字段、任意状态/查询补丁拒绝。当前源 Run 必须终态；不会将活动运行暂停。模型原 tool call ID、查询、消息前缀、模型参数、数据/故障计划保持相同。

新 Run 的 Intervention 包含 ID、父运行、源点、patch、before/after，并随 run.created 和请求幂等账本原子提交。通过官方 update_state 在同一 LangGraph thread 的明确旧点派生新 checkpoint，保存 B 的工具前引用，再运行后续节点。B 的工具输入记录 intervention_id 和有效策略；attempt 从 1 重计，首次注入故障规则仍相同。A 的事件、配置、原 checkpoint 及其 pending writes 不变。

B 通过 inherited_span_ids 引用旧模型步骤，新增 spans、Token、估算只包含分支后调用。可从 B 再次分支，仍保留原模型前缀引用。模型仍可能返回不同答案。幂等 key 包含源运行、checkpoint 和规范化 patch；同 key 同请求即使 saver 后来丢失也返回原 B，冲突不创建新运行。取消、调度和服务退出沿用原有生命周期。

165 项后端、41 项 Vitest 与 15 项实际 Chromium 回归通过，包括子进程重启/意外退出、A 原始状态不变、连续分支、同故障、只执行后缀、幂等与排队取消。离线 SDK MockTransport 验证重启后只新增一次回答请求、保留 usage/价格版本及凭据缺失拒绝。没有新付费调用；界面运行控制、分支和 A/B 对比仍待接入，M3 尚未完成。
