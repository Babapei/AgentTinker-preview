# 实验包 v1

M4 进行中。当前已实现 JSON 数据包契约、严格解析及原生闭合运行导出；持久化导入、能力降级与界面尚待接入。此节点不代表 P08/P10 或 M4 已验收。

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

## 验证与下一步

19 项新增离线测试覆盖两实验/祖先导出、源事实与 checkpoint/pending writes 不变、无 saver/密钥、原评价和双摘要、已识别凭据字段去除、摘要 trace 不补事件、篡改/路径/类型/版本/父引用/夹具/评价器拒绝、严格 JSON 和大小上限、只读 HTTP 与活动 Run 拒绝。全量 215 Python 和 ruff/格式检查通过；无新增真实提供商调用。

下一节点：事务导入和本地 ID 映射，保留来源，统一取消执行/分支能力；然后接文件界面、无密钥阅读及真实参考。导出包不是可迁移的 LangGraph checkpoint。
