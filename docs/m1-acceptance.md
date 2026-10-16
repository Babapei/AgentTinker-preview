# M1 运行记录验收

2026-10-16 · 按 [架构路线](03-architecture-roadmap.md) 的既有 M1 条件核对，未调整范围或退出条件。

**结论：M1 完成，可进入 M2 检查与回放。** 核心协议、SQLite/文件存储、串行执行器、HTTP 控制和 SSE 已贯通。全套 136 项测试、ruff 检查和格式检查通过；固定安装入口和服务 CLI 通过验证。

| 完成条件 | 可检查证据 |
| --- | --- |
| 失败/重试可记录 | 原生 LangGraph 图注入首次工具超时；retry_limit=0 失败、1 重试成功，attempt、错误来源和新增调用顺序可由事件重建 |
| 取消可记录 | 队列取消不构造适配器；运行中先 cancel_requested，再保存在途返回/用量，禁止后续调用，最后 cancelled；HTTP 202 不冒充已停止 |
| 刷新后历史可读 | 关闭一个 API 实例并打开第二个，GET RunView、历史列表、SSE 返回原记录；相同幂等请求不再执行，测试适配器禁止任何新调用 |
| 断线补发且不重复 | 真实本机 TCP/Uvicorn/httpx 连接读到 span.started 与心跳后断开；运行继续，HTTP 取消，在途响应返回后 Last-Event-ID 补发；合并序号无缺口、event_id 无重复，纯重建与 SQLite 最终投影完全相同 |
| 中断和未知值准确 | 子进程在模型调用中 os._exit，旧 owner 消失后新 owner 标记 interrupted；已提交事实保留，未返回用量未知，不重新发请求 |
| 用量和费用可追溯 | 默认 SDK 工厂通过离线 MockTransport 验证 DeepSeek 请求配置、响应 ID、原始响应及缓存 Token；正常和异常 choices 均保留观测，估算带显式价格版本，密钥不在记录中 |
| 协议和存储完整性 | 类型化事件、非法状态/关联校验、并发 seq、原子写入回滚、事件不可改写、请求幂等、v1→v2 迁移、artifact 哈希与实际费用证据引用 |

验证代码：[运行服务测试](../tests/test_run_service.py)、[API 集成测试](../tests/test_api.py)、[存储测试](../tests/test_event_store.py)、[核心协议测试](../tests/test_core_protocol.py)。共 63 项 M0、32 项核心、13 项存储、12 项运行服务、16 项 API 验证。可通过 `uv run pytest -q` 重现。

本轮的真实部分是本机进程、SQLite 和 HTTP/SSE 网络行为；模型侧为 synthetic 或明确的离线 SDK 响应，不把它记成新的真实提供商验证。此前 M0 的真实 DeepSeek 调用和分支证据保持不变，实际账单独立待办。

运行服务仍为固定 `model → tool → model` 串行流程；CheckpointRef 已持久化，LangGraph saver 仍在内存，M1 不声明 checkpoint fork 或跨进程恢复执行。M2 开始实现 React/TypeScript/Vite 的历史列表、步骤详情、图与时间线，用实际事件驱动视图；历史播放只处理记录，不调用 provider/tool。完整实验、持久化 checkpoint 分支与 A/B 比较继续按 M3 推进。
