# M1：原生串行运行服务

实现位于 [runtime](../src/agenttinker/runtime)，依赖 [运行记录协议与 SQLite](runtime-records.md)。当前提供 Python 入口，HTTP/SSE 在下一节点实现。

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

CheckpointRef 已写入 SQLite，但 LangGraph saver 仍仅在执行进程内存中，运行服务不声明 fork 能力。跨进程恢复执行和策略分支在后续任务接入持久化 saver 后实现；事件回看不调用模型。

12 项服务测试覆盖失败/重试、排队与在途取消、用量保留、并发幂等、调度失败、owner 排斥、子进程异常退出恢复和 SQLite v1 迁移；与核心/存储/M0 合计 120 项。全部使用本地或模拟调用，没有新付费请求。
