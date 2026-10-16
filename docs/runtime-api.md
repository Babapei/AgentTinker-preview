# M1：本地 HTTP 与 SSE

实现：[app.py](../src/agenttinker/api/app.py)、[启动入口](../src/agenttinker/api/cli.py)。运行语义见 [运行服务](runtime-service.md)，对象和事件见 [运行记录协议](runtime-records.md)。

## 启动

```bash
bash scripts/setup.sh
uv run agenttinker-server --database artifacts/runs.sqlite
```

默认 `127.0.0.1:8000`，单进程、单 owner、本机单用户。启动、历史读取和 SSE 不调用模型；只有显式 POST 创建新 Run 才排队执行。API 文档位于 `/docs`，OpenAPI 位于 `/openapi.json`，核心事件 JSON Schema 位于 `/api/v1/protocol`。类型来自同一组 Pydantic 模型。

可通过 `--pricing <版本价格表.json>` 指定服务端估算版本；未选时费用为 unknown。live 模式配置沿用服务端 `DEEPSEEK_*` 或 `OPENAI_*`，请求体不接收密钥。网络和 TLS 沿用环境设置，不自动选择价格时段。当前没有认证或公开托管，不以多 worker 启动同一数据库。

## 已实现接口

| 方法与路径 | 行为 |
| --- | --- |
| `POST /api/v1/runs` | RunRequest；必须有 Idempotency-Key；新建 201，重复同请求 200，响应 RunView 和 Location |
| `GET /api/v1/runs` | 历史 Run 配置/状态分页；offset ≥ 0、limit 1–100，默认 50；按 Run ID 排序 |
| `GET /api/v1/runs/{run_id}` | RunView，包含当前 Run、spans、checkpoints、last_seq |
| `GET /api/v1/runs/{run_id}/spans` | 同样分页，支持 logical_node_id 和 failed_only；total 是筛选后的数量 |
| `GET /api/v1/runs/{run_id}/checkpoints` | CheckpointRef 列表；引用可读不等于可恢复 |
| `POST /api/v1/runs/{run_id}/cancel` | cancel_requested 返回 202；已取消或其他终态返回 200；响应 RunView，重复请求幂等 |
| `GET /api/v1/runs/{run_id}/events` | 已提交事件 SSE，支持游标补发；终态且追平后结束响应 |
| `GET /api/v1/protocol` | 核心 Pydantic JSON Schema，包括类型化 Event |

分页返回 `items`、`total`、`next_offset`，最后一页 next_offset=null。运行持续变化时分页不是整个数据库的固定快照；单个事件流仍以不可变 seq 排序。

```bash
curl -sS http://127.0.0.1:8000/api/v1/runs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: local-retry-1' \
  -d '{"mode":"synthetic","policy":{"tool_retry_limit":1}}'
```

synthetic 明确标注，无提供商用量或虚构费用。live 必须指定 provider，model 可显式传入或使用服务端变量。默认 inject_timeout=true、tool_retry_limit=0，得到带故障的失败基线；设置 retry_limit=1 可从头运行重试案例，这不是 checkpoint fork。请求策略字段为 `policy.tool_retry_limit`。

相同 key 与完整规范化请求始终返回原 Run，包括服务重启后；同 key 不同请求返回 409 `idempotency_key_payload_conflict`。缺失 provider 配置返回 503 `provider_not_configured`，未创建 Run；未知 Run 返回 404 `run_not_found`。输入/游标非法返回 422，运行服务不可用返回 503。异常响应不包含原始 SDK 错误文本。

## SSE 游标与消费规则

```text
id: run_…:3
event: span.started
data: {"schema_version":"0.1","event_id":"evt_…","run_id":"run_…","seq":3,…}

```

data 是完整、单行 JSON Event；上述仅省略展示。`id` 为 `<run_id>:<seq>`，防止把另一个 Run 的 Last-Event-ID 静默用作本 Run 游标；event_id 保留为事实去重键。

- 首次连接使用 `after_seq=0`（默认），或传当前已应用的序号。重连可带 `Last-Event-ID: <run_id>:<seq>`，返回严格大于该序号的事件；若同时给 after_seq，二者必须一致。
- 跨 Run、格式错误、负数、冲突或超出当前 head 的游标在发送 SSE 响应头之前返回 422。没有忽略错误游标后重新开始的隐式行为。
- 每次从 SQLite 读取最多 1000 条，追平后轮询；事实提交后才可发送。终态检查前若发生新提交，继续补读直至全部终态事件发出，避免空读取与终态之间的竞态。
- 空闲每 15 秒发送 `: keep-alive` 注释，不分配 seq、不产生运行事实。响应关闭代理缓冲和缓存。
- 断线只结束订阅；不会取消、重启或重发运行。HTTP cancel 才请求取消。运行进入终态且所有事件已送出后响应结束；浏览器消费者应在应用终态事件后主动关闭 EventSource。
- 消费者按 event_id 去重，仅在事件已成功应用后推进游标；seq 应连续，发现缺口则从最后已应用位置重新补读。刷新也可以重新 GET RunView，再从其 last_seq 订阅增量。不要将时间戳用作游标。

场景/实验定义、fork、比较和导入导出等架构草案接口在后续阶段实现。M1 的运行服务 fork 能力保持 false；React 只读检查页已接入，见 [前端说明](web-inspector.md)。16 项 API 测试包含真实本机 Uvicorn/HTTP 断线、重连、取消与心跳，离线 SDK 请求/响应与估算保存，以及服务重启后的只读回看；没有新付费调用。
