# 实验包 v1

M4 已按原 P06–P10 完成功能验收，见 [M4 证据与限制](m4-acceptance.md)。已实现 JSON 数据包契约、严格解析、原生闭合运行导出与事务导入、强制只读能力，以及文件下载/上传、来源/原意见界面。

## 内容与完整性

顶层 `format=agenttinker-package`、`format_version=1`。单文件 JSON 包含 manifest 和 files，不接受 ZIP，也不解压或安装文件。manifest 保存标题、来源声明、许可（未知为 null）、创建时间、producer 版本、root_run_id、experiment/trace 类型，以及每项路径、规范 JSON UTF-8 字节数和 SHA-256。哈希验证内容完整性，不证明来源身份或真实提供商调用。

仅允许 `context.json`、`runs/{ID}.json`、`artifacts/{ID}.json`，不接受绝对路径、目录跳转或未知文件类型；这些都是 JSON 内的键，不作为解压目标。总输入上限 8 MiB、单项规范内容 2 MiB、最多 128 项/32 条 Run，每条最多 5000 个事件与 1000 份评价/复核。重复 JSON 键、非有限数、未知格式版本、条目/字节/哈希不符均拒绝。没有远程资源获取或包内代码执行。

context 包含实验、Agent、Case、Fixture、Variant 和评价器定义。夹具按已声明版本的算法复核哈希；评价器只接受内置规则/人工 ID，不接受可执行实现。文档实验复用现有固定定义。旧 serial-checkpoint:2 缺少 Case/Variant 引用时，根据冻结任务/策略生成带版本的导出上下文，并明确声明这是导出时重建，源 Run 不补写新事实。旧模板仍是一次工具的 bounded 流程，不描述成完整 ReAct。

每个 PortableRun 保存来源 Run ID/模式、源视图摘要、脱敏视图及可选完整事件、原评价/复核和摘要绑定。来源一律标记为 `unverified_source_record`。有完整事件时必须能纯重建出所附视图，且当前格式只收闭合事件流；普通 normalized trace 可只附摘要，events=null，不生成假的中间事件。包内父运行、分支点、前缀、Span 父引用、评价/复核和费用凭据引用都需完整且无循环/身份冲突。

## 导出范围

`GET /api/v1/runs/{id}/export` 导出选中的终态原生 Run 及所需祖先，响应 JSON 附件。`GET /api/v1/experiments/{experiment_id}/export?run_id=...` 另核对实验 ID；run_id 明确限定这次导出范围，不把所有同场景运行混成一次实验。

默认保留观察到的模式、查询/call ID、消息、响应、用量、费用未知值和评价意见。去除 checkpoint locator/可修改字段，并关闭包内执行能力；manifest 明示转换。只读取事件/评价库及所引用可分发 artifact，不打开 saver、不构造 SDK、不运行工具。活动 Run 拒绝导出。源事件、配置和私有 saver 不变。

规则评价仍保留原 `input_hash` 和原意见。由于脱敏/能力/locator 转换会改变视图，另存 `source_input_hash` 与 `portable_input_hash`，后者可用所附 Case/评价版本/脱敏前缀复核；不把两个摘要冒充相同证据。评价与复核从同一事务快照读取，避免漏掉新意见引用的评价。

只对已识别凭据字段（如 Authorization、API key、Cookie）做递归去除。系统连接密钥不读入包；自由文本任务、消息、正文和人工署名仍是用户内容，不能声称通用私人信息识别。费用凭据必须显式 exportable、内容哈希有效，当前只支持 UTF-8 JSON/纯文本；私有或含已识别凭据的 JSON 凭据拒绝导出，不能默默丢失证明却保留实际费用结论。未取得实际账单的历史仍为未知。

## 事务导入与来源

`POST /api/v1/imports` 直接接收 JSON 文件字节，要求 Content-Type: application/json 和 Idempotency-Key。先严格验证全部内容，再统一去除执行能力、checkpoint locator/可改字段和已识别凭据；即使包自己声明可恢复也不授予执行。来源模式保存在来源记录，本地 Run.mode 固定 imported。

SQLite v4 在同一事务保存来源包、导入结果、原 ID 到新本地 ID 的映射、运行/完整事件和 artifact 元数据、请求身份。Run/Span/Checkpoint/Intervention/Event/Artifact 重新分配 ID；父运行、分支点、继承前缀、Span 父项和费用凭据随之映射。原查询、模型 tool call ID、消息、用量、未知值和意见不改写。异常回滚所有数据库新增记录；内容寻址文件若先落盘，事务失败可能留下不可访问的孤立 blob，不能称作文件系统回滚。

按严格验证后的规范包摘要去重，JSON 空白不改变身份。同 key 同内容、不同 key 同内容、重启或并发重试返回相同 import_id/本地 Run；同 key 不同包 409 冲突。重试不覆盖既有数据。原摘要（规范化前）与可分发摘要（强制只读/脱敏后）分别保存；只持久化后者及其来源声明，不保存含私有 locator 的输入原件。

完整事件导入后仍纯重建为本地视图，可从 SSE 回放。events=null 的摘要只支持检查，保留其观测状态，即使 running 也不是正在本机执行的任务；没有虚构事件，SSE 明确 409 unsupported_capability。重启恢复不接管导入记录；cancel/fork/新评价或复核均拒绝，数据库触发器同时禁止变更导入元数据/映射、运行和事件。

`GET /api/v1/imports/{import_id}` 返回稳定结果；`GET /api/v1/runs/{id}/provenance` 返回来源声明、原模式/ID/视图摘要、包摘要、上下文与原评价/复核，原生 Run 返回 null。原意见仍绑定源 ID 和原 input_hash，不冒充对重新分配本地 ID 后视图的评价；可分发证据摘要对应包内源 ID。它们不进入本地可追加评价列表。再次导出导入 Run 返回其完整的规范化来源包，保留原身份与意见；不把本地导入时间/新 ID 写成新的原始执行证据。

## 文件界面

运行上方“导出实验包”下载完整记录与祖先；“导入文件”选择 JSON 并显式提交，成功打开新本地记录。8 MiB 输入前置检查，响应未知时只暂存文件摘要/key，刷新后重选同文件手动重试，不保存文件正文或自动上传。来源面板展示原模式/声明/许可、实验任务与成功标准/材料、双摘要及原评价/意见，声明不证明来源身份、真实调用或账单。完整事件支持历史播放；摘要显示“仅摘要”，不提供执行、取消、分支或新增评价。详细交互与浏览器证据见[界面说明](web-inspector.md)。

## 验证与下一步

导出节点新增 19 项离线测试；导入节点新增 16 项，覆盖两实验 A/B 往返、谱系/尝试/查询与用量保留、原意见双摘要、并发去重/重启/冲突、事务及费用元数据回滚、artifact 映射、篡改能力和凭据清理、摘要重启不接管与禁止写入、无效引用/循环、只读触发器、v1/v2/v3 升级、无密钥 HTTP 导入/回放/再导出与大小/类型拒绝。后端全量 231 Python、ruff/格式通过。文件节点另通过 70 Vitest/40 Chromium、协议/类型/构建/格式，含导入每个事件前缀的跨语言核对、两实验文件往返、显式重试、摘要降级与无密钥浏览器验证；无新增真实提供商调用。

[三份参考包](../examples/m4/README.md)覆盖两类实验。旧 v1 执行失败保持；新 v2 两条执行成功、B 正文读取通过但引用 fail，采集 18/19、real_reference_verified=false，无人工复核。单 JSON v1 包格式携带两版 Agent/实验，已知上下文/评价严格核对。当前 292 Python、81 Vitest、43 Chromium 全量与静态/构建通过；[最新生产证据](../examples/m4/reference-browser-v2.json)核对三文件/六条记录的无密钥导入、检查、回放和再导出，模型构造/播放 API 为 0，live 未配置 503。M4 功能验收见[原条件核对](m4-acceptance.md)，外部 Agent 的原始日志解析与执行适配未接入；导出包不是可迁移的 LangGraph checkpoint。
