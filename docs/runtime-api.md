# M1：本地 HTTP 与 SSE

实现：[app.py](../src/agenttinker/api/app.py)、[启动入口](../src/agenttinker/api/cli.py)。运行语义见 [运行服务](runtime-service.md)，对象和事件见 [运行记录协议](runtime-records.md)。

## 启动

```bash
bash scripts/setup.sh
uv run agenttinker-server --database artifacts/runs.sqlite
```

默认 `127.0.0.1:8000`，单进程、单 owner、本机单用户。启动、历史读取和 SSE 不调用模型；只有显式 POST 创建新 Run 才排队执行。API 文档位于 `/docs`，OpenAPI 位于 `/openapi.json`，核心事件 JSON Schema 位于 `/api/v1/protocol`。类型来自同一组 Pydantic 模型。

可通过 `--pricing <版本价格表.json>` 指定服务端估算版本；未选时费用为 unknown。live 模式配置沿用服务端 `DEEPSEEK_*` 或 `OPENAI_*`，请求体不接收密钥。网络和 TLS 沿用环境设置，不自动选择价格时段。当前没有认证或公开托管，不以多 worker 启动同一数据库。

## 同一地址提供构建后的页面

```bash
npm --prefix web run build
uv run agenttinker-server --database artifacts/runs.sqlite --web-dist web/dist
```

打开 `http://127.0.0.1:8000` 使用页面，API 与 SSE 使用同一地址，运行/分支/导入仍由显式操作触发。未提供 --web-dist 时保持原 API 模式；不会自动启动前端开发服务或构造模型。

--web-dist 需指向包含 index.html 的现成构建目录；缺少/无效构建在打开数据库或监听前以 web_build_missing 拒绝，并提示构建命令。只服务所选目录，外部路径或指向目录外的符号链接不可读取；API/文档路由优先于静态页面，不将未知 API 回退成 HTML。这是原本机单用户服务的可选页面入口，没有增加认证、公共托管或多进程支持。

## 已实现接口

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/v1/scenarios` | 已接入的版本化场景定义、Agent/Case 与虚构材料；当前文档实验 |
| `POST /api/v1/scenarios/{scenario_id}/runs` | 文档实验 DocumentRunRequest + Idempotency-Key，201/200；固定 Case，baseline/candidate |
| `POST /api/v1/runs` | RunRequest；必须有 Idempotency-Key；新建 201，重复同请求 200，响应 RunView 和 Location |
| `GET /api/v1/runs` | 历史 Run 配置/状态分页；offset ≥ 0、limit 1–100，默认 50；按 Run ID 排序 |
| `GET /api/v1/runs/{run_id}` | RunView，包含当前 Run、spans、checkpoints、last_seq |
| `GET /api/v1/runs/{run_id}/spans` | 同样分页，支持 logical_node_id 和 failed_only；total 是筛选后的数量 |
| `GET /api/v1/runs/{run_id}/checkpoints` | CheckpointRef 列表；引用可读不等于可恢复 |
| `GET /api/v1/runs/{run_id}/checkpoint-availability` | 每项含 checkpoint、available、reason、当前允许字段；只读实时检测 |
| `POST /api/v1/runs/{run_id}/forks` | ForkRequest + Idempotency-Key；201 新分支 / 200 原分支，响应 RunView 与 Location |
| `POST /api/v1/runs/{run_id}/cancel` | cancel_requested 返回 202；已取消或其他终态返回 200；响应 RunView，重复请求幂等 |
| `POST /api/v1/runs/{run_id}/evaluations` | 内置规则评价 + Idempotency-Key；独立不可变结果，新建 201/重复 200 |
| `GET /api/v1/runs/{run_id}/evaluations` | 评价倒序分页，offset/limit/total/next_offset |
| `POST /api/v1/runs/{run_id}/reviews` | 绑定评价与输入摘要的人工复核 + Idempotency-Key；201/200 |
| `GET /api/v1/runs/{run_id}/reviews` | 人工复核倒序分页；单条评价/复核均可再按各自 ID GET |
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

## M3 分支接口

源 Run 当前必须终态。先查看 checkpoint-availability，再显式 POST；服务端仍会重新检查，不能只依赖按钮或 Run 中的历史能力声明。

```json
{
  "source_checkpoint_id": "cp_...",
  "patch": {"tool_retry_limit": 1}
}
```

每次只修改 tool_retry_limit（0–3）或 top_k（1–3）中的一个，严格整数，不允许原值/空补丁/同时修改两个字段。模型原查询/tool call ID、前缀、版本及同一故障计划保留。B 含 parent_run_id、source_checkpoint_id、inherited_span_ids 和 intervention（patch/before/after）；后续工具输入含 intervention_id。费用/调用计数只算 B 新增 spans。

返回 422 invalid_patch、404 checkpoint_missing；不支持能力、活动源运行、版本/价格不兼容、错属或不可读状态分别返回 409 unsupported_capability / source_run_active / runtime_incompatible / checkpoint_state_invalid / checkpoint_unreadable。live 配置缺失返回 503 provider_not_configured。前置校验失败不创建 B、不消费 key。调度或执行失败保留原身份，不自动重发。重复同 key 请求先返回原 B，即使原 checkpoint 后来不可用。

availability 检查持久化状态和服务上下文；live 凭据/SDK 参数在显式提交时再校验。不可用时 allowed_patch_fields=[]，reason 为稳定码；不改写原 CheckpointRef 或能力声明。普通历史、SSE、可用性检测均不调用模型。

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

M3 的后端 fork 已接入；界面已接任务配置、运行取消、分支及基于 RunView 的父子对比。文档场景定义/创建已在 M4 接入；独立比较服务按后续节点实现，实验包导入导出已接 HTTP，见 [前端说明](web-inspector.md)。20 项 API 测试包含原有 HTTP/SSE、重启分支、幂等、可用性降级及离线 SDK 后缀请求/用量/估算；没有新付费调用。

## M4 文档场景接口

`GET /api/v1/scenarios` 当前按 v2、v1 顺序返回 document-missing 的两个已知版本，不构造 SDK。`POST /api/v1/scenarios/document-missing/runs` 接受 `{ "mode": "synthetic", "variant": "baseline" }`，也可显式 live/provider/model。新增可选 agent_version（"1"/"2"），缺省1以保留旧请求/指纹；显式2选择 document-react:2 与 document-missing:2。新字段属于输入契约，客户端可省略默认字段；场景/请求版本须匹配。baseline 为 top_k=2，candidate 为 3；不接受任意脚本、工具代码或状态。缺少 provider 配置明确 503；未知场景 404 scenario_not_found。既有 POST runs 的请求规范化/指纹保持原样，不因新增场景字段破坏旧幂等重试。

文档 Run 记录独立 Agent/prompt/工具/材料/Case/Variant/评价器版本，无超时注入；首个检索前 checkpoint 仅允许 top_k，其他工具点只可观察。复用 GET Run/SSE/cancel/forks 和稳定拒绝码；详情见[文档实验](document-experiment.md)。评价为独立的纯规则计算并已持久化；前端场景/评价/人工复核表单已接入，见[界面说明](web-inspector.md)。

## M4 评价与人工复核

评价 POST body 为 `{}`（默认 document-evidence:1），或显式 evaluator ID/version；仅终态文档用例可评价。结果有独立 evaluation_id、input_hash、status、checks 和执行状态，不向 SSE 追加事实。评价器异常保存 failed/异常类型和空 checks，不是答案零分。没有模型或工具调用。GET 列表每页最多 100，按追加顺序倒序，明确总数和下页。

复核 POST body 含 evaluation_id、input_hash、reviewer（最多 160 字符）、fact_coverage（configurable-retries/citation-fix 各为 covered/missing/uncertain）、judgement（supported/justified_insufficiency/unsupported/uncertain）、explanation（最多 8000 字符）。它是本地用户意见，不代表已认证身份。新意见用新 key 追加，旧意见不可覆盖；材料不足的诚实回答可标 justified_insufficiency，规则不自动判定语义。

两类 POST 必须有 Idempotency-Key，同 key 重试返回原结果及 Location；评价/复核使用独立于运行创建的同一份账本。冲突 409 idempotency_key_payload_conflict；活动运行 409 evaluation_run_active，版本/用例不符 409 evaluation_context_mismatch，不支持评价器 422 evaluator_unsupported，记录不存在/错属运行 404 assessment_not_found，摘要不符 409 review_evidence_mismatch，锚定失败评价 409 review_evaluation_failed。前置拒绝不消费 key；无效字段仍为 422。

## M4 实验包导入导出

GET `/api/v1/runs/{id}/export` 返回所选终态 Run 与所需祖先的 JSON 附件；GET `/api/v1/experiments/{experiment_id}/export?run_id=...` 同时核对场景 ID。它只读标准记录，不调用 SDK/工具/saver。包内去除私有定位和已识别凭据字段，源事实不变；摘要 trace 不补事件，评价保留原摘要及另算的可分发摘要。格式、限额和来源口径见[实验包 v1](experiment-packages.md)。

活动 Run 返回 409 package_run_active；不支持的模板/上下文或不可分发凭据返回 422（稳定 package_context_unsupported/package_context_mismatch/artifact_not_exportable 等码）。未知 Run 为 404，实验 ID 不匹配为 404 experiment_not_found。导入 Run 再导出时返回其完整规范化来源包。

POST `/api/v1/imports` 接收原始 JSON 文件字节（不是 multipart），要求 Content-Type: application/json、Idempotency-Key（1–128 字符）。8 MiB 流式输入上限在 JSON 解析前检查。新包 201，重复内容或同 key 重试 200，Location 指向 `/api/v1/imports/{import_id}`；结果含源/可分发包摘要、原 ID→本地 ID、root_run_id 和回放能力。原子保存，强制 imported/只读；同 key 异包 409 idempotency_key_payload_conflict。无 SDK/工具/saver。

GET `/api/v1/imports/{import_id}` 读取导入结果，未知为 404 import_not_found。GET `/api/v1/runs/{id}/provenance` 读取原来源/许可/上下文/评价和双摘要，原生 Run 为 null，未知 Run 404。源评价保持原 ID/摘要，不加入本地评价列表；向 imported Run 新增评价/复核 409 imported_record_read_only，cancel/fork 为 409 unsupported_capability。摘要 trace 无完整事件时 SSE 同样 409，不补造事件。

导入类型不符 415 unsupported_package_type，超限 413 package_too_large，JSON/版本/哈希/引用非法 422 package_invalid，凭据 artifact 422 artifact_contains_credentials；异常不返回输入正文。GET protocol 增加实验包、导入结果和来源 schema。文件界面与无密钥浏览器往返已接入，详见[界面说明](web-inspector.md)。
