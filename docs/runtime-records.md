# M1：运行记录协议与实现边界

协议版本：`0.1`。对应 CORE-01；实现位于 [core](../src/agenttinker/core)。M0 技术报告仍使用原有格式；本协议没有自动迁移或重新执行旧报告。

## 1. 当前已实现

| 模块 | 内容 |
| --- | --- |
| [records.py](../src/agenttinker/core/records.py) | Run、Span、CheckpointRef、Artifact、版本引用、能力、用量和费用 |
| [events.py](../src/agenttinker/core/events.py) | 类型化事件包络、payload 校验及 JSON 解析 |
| [states.py](../src/agenttinker/core/states.py) | Run 状态及合法转换；是否可启动下一次调用 |
| [projection.py](../src/agenttinker/core/projection.py) | 从原生事件流重建 Run、spans、checkpoints，校验流的完整性 |
| [schema.py](../src/agenttinker/core/schema.py) | 从上述 Pydantic 模型生成 JSON Schema |

Experiment、DatasetCase、Variant、Agent 和 FaultPlan 当前通过明确的 ID + version 引用连接运行配置；其完整内容模型和服务随实验功能实现。STORE-01 已加入 SQLite 事件存储及 artifact 内容存储，见第 6 节。整个 M1 仍在进行中，尚未接入执行器、HTTP 或 SSE。

## 2. 数据规则

- 所有顶层记录与事件带 `schema_version=0.1`；未知版本、事件类型、额外字段拒绝解析。计数禁止布尔值或字符串隐式转换；时间必须带时区，JSON 不接受 NaN/Infinity。
- Run 保存模式、状态、创建/更新时间、模型请求配置、prompt/tool/runtime/fixture/evaluator 版本及实验引用。实际返回模型属于具体 Span；未取得的字段保留未知。凭据不得放入这些配置或事件，模型连接仍由服务端配置。
- B 保存 parent_run_id、source_checkpoint_id 和 inherited_span_ids，缺少一半谱系、自引用或重复继承引用会被拒绝。继承步骤只作为引用，不复制进 B 的新增 spans。
- 工具 span 必须包含 logical_call_id 和 attempt；call_index 表示该逻辑节点的一次调用，工具重试保留 call_index，使用新 span ID 和递增 attempt。
- Usage 支持逐项未知；已知总数及缓存分解必须一致。Cost 的 unknown 不携带金额；estimate 需要币种和价格版本；actual 需要独立证据 artifact 引用。Decimal 金额以字符串序列化。
- 普通 imported 记录默认只有检查/回放能力，不得仅因导入数据而获得执行能力。原生能力也只是声明，运行服务仍需检查实际 checkpoint 和兼容版本。
- CheckpointRef 保存适配器版本、Agent/工具版本、内部 locator 和允许字段，仅声明工具前边界及 tool_retry_limit/top_k 补丁。JSON 引用本身不包含可恢复状态，也不保证能恢复。
- Artifact 保存 SHA-256、长度、类型、来源和分发范围，默认不可导出；对象协议不接收文件系统路径。

Pydantic 的 frozen 配置仅限制字段赋值，嵌套 JSON 仍可能被 Python 调用者修改。因此重建前会序列化并重新校验事件；后续存储必须以序列化的不可变事实为准，不能依靠内存对象的 frozen 属性保证历史不变。

## 3. 状态转换

| 当前状态 | 可进入 |
| --- | --- |
| queued | running、cancel_requested、failed、interrupted |
| running | cancel_requested、succeeded、failed、interrupted |
| cancel_requested | cancelled、failed、interrupted |
| succeeded / failed / cancelled / interrupted | 无；不覆盖终态 |

同状态重放不作为一次合法转换；HTTP 操作的幂等性由后续服务处理。只有 running 可启动新的模型/工具调用。cancel_requested 时仍可接收已经在途的 span 结果和真实用量，等待处理完后才进入 cancelled；不能把取消请求直接显示成已经停止，也不将随后收到的响应误丢弃。

进程中断通过 run.status_changed → interrupted 表达；仍在途的 spans 在投影中标为 interrupted，未取得的结束时间、结果和用量继续未知，不伪造 provider 返回。此处只实现事件语义，进程监测和取消执行逻辑由后续运行服务接入。

## 4. 事件和重建

所有事件有 event_id、run_id、seq、occurred_at、received_at；可关联 span、父 span、逻辑节点、逻辑调用和 attempt。服务端分配每个 Run 从 1 开始的连续 seq。时间戳允许时钟偏差，只作展示，不用于排序或推断依赖。

| type | data 与关联约束 |
| --- | --- |
| run.created | queued Run 快照，必须为 seq=1，Run ID 匹配 |
| run.status_changed | before/after/reason；before 必须与投影一致，after 符合转换表 |
| span.started | running Span 快照，属于当前 Run，父 span 已存在或在继承前缀中 |
| span.finished | 结束 Span 快照；不得改变原输入、父引用、调用标识或开始时间，不得重复结束 |
| tool.attempt_failed | 失败码、origin、retry_owner、will_retry、故障计划引用；关联已结束的失败工具 attempt |
| tool.retry_scheduled | executor 的 next_attempt；必须关联允许重试的失败事件，不得重复排队 |
| checkpoint.saved | 属于该 Run 的 CheckpointRef；不得覆盖重复 checkpoint ID |

原生工具失败事件顺序为 span.started → span.finished(failed) → tool.attempt_failed → 可选 tool.retry_scheduled → 新 attempt 的 span.started。重试保持查询输入、父引用和调用身份，attempt 从 1 连续增加。

`project_events()` 拒绝序号缺口、重复事件 ID、混合 Run、陈旧状态、无来源重试及终态后的执行事件；只做数据重建，不调用 SDK、工具或恢复 checkpoint。返回的 RunView 只含本 Run 新产生的 spans。运行本身成功与答案是否正确仍分别由 Run 状态与后续评价表达。

该重建器当前针对完整原生事件流。只有 span 摘要的外部记录需由后续导入适配器保留信息缺口，不能为了满足本地事件格式补造模型/工具开始事件。

## 5. 生成 schema 与验证

```python
import json
from agenttinker.core.schema import protocol_schemas

print(json.dumps(protocol_schemas(), ensure_ascii=False, indent=2))
```

Run、Span、CheckpointRef、Artifact、Event 和 RunView 的 schema 均来自同一实现；Event 包含 type 判别器。后续 API/前端以此生成类型，不另写一份协议定义。生成产物可写入忽略的 artifacts，不手工维护副本。

CORE-01 新增 32 项验证，覆盖状态转换、取消与在途结果、中断、分支引用、版本/来源/关联校验、费用与未知值、事件顺序、重试与 schema 往返。STORE-01 新增 13 项 SQLite/文件集成验证；全套共 108 项测试通过。整个 M1 的退出条件还包含 HTTP/SSE 与运行服务的集成验证。

## 6. SQLite 事件日志与 artifact 存储（STORE-01）

实现位于 [storage/sqlite.py](../src/agenttinker/storage/sqlite.py)，仅使用 Python 标准库 sqlite3；数据库 schema 版本当前为 1，通过 user_version 校验，不静默使用未知版本或其他应用的非空数据库。

```python
from agenttinker.storage.sqlite import SQLiteEventStore

with SQLiteEventStore("artifacts/runs.sqlite") as store:
    view = store.get_view("run_A")
    backlog = store.events("run_A", after_seq=2, limit=100)
    restored = store.rebuild_view("run_A")
```

上述读取例子要求已通过追加接口保存相应 Run；首次打开数据库只建表，不生成运行或执行请求。

- **原子追加：**BEGIN IMMEDIATE 内校验事实、重建投影、写入缓存和事件后一起提交。事件 ID 全局唯一，Run 内 seq 唯一；数据库触发器拒绝 UPDATE/DELETE 事件。中途写入失败会回滚事件与投影，提交后才可以向订阅者发送。
- **序号与幂等：**原生服务使用 append_next，在事务中分配下一个 seq 和首次 received_at；draft 不接受 seq。同 event ID 且内容完全一致时返回原记录，不重复追加，received_at 保持原值；同 ID 不同内容或显式序号冲突报 EventConflict。append 保留为接受已确定序号的内部入口，仍执行相同校验。
- **续传读取：**events 按 seq 返回 after_seq 之后的事实，支持每页 1–1000 条；拒绝负数、布尔游标和超出当前 head 的游标。当前提供持久化游标基础，HTTP Last-Event-ID、SSE 订阅与去重集成尚未实现。
- **投影与谱系：**get_view 读取持久化缓存；rebuild_view 从完整事件重建，事实不被重写。创建分支记录前检查父 Run、源 checkpoint 和继承 span 已存在；B 不复制父 spans。此步骤只保存分支谱系，不恢复 LangGraph。
- **内容存储：**put_artifact 先校验元数据，用 SHA-256 分目录保存内容，经临时文件写入、flush/fsync 和替换后登记 SQLite 元数据。相同内容共用 blob，不同来源可以有不同 artifact ID。read_artifact 检查长度和哈希；已知 actual 费用的证据引用必须可读取。保存证据不等于程序已经判断其财务真实性。
- **文件与数据库边界：**内容文件先写、元数据后登记；两者不是跨资源事务。中断可能留下无元数据引用的 blob，但不会先提交元数据再写内容。本节点未实现孤立文件回收或整机掉电保证，导入导出仍按后续阶段实现。
- **进程边界：**每个线程/worker 使用自己的 SQLiteEventStore 连接。打开数据库不会将其他 worker 的运行擅自标为 interrupted，也不会重发 provider 请求；由运行服务在确认 worker 消失后追加中断事件。当前测试以真实子进程 os._exit 验证已提交事件可恢复；自动监测尚未接入。

当前每次追加会重建该 Run 的完整原生事件投影，优先保证语义一致，适合当前单用户、小规模记录。后续按实际规模优化增量投影，不把此实现宣传为多 worker 分布式调度服务。
