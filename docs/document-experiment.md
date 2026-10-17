# 文档缺失实验与评价

M4 进行中。当前已实现版本化定义、本地工具和纯记录规则评价；运行适配、HTTP/界面、持久化评价和实验包尚待接入。以下内容不代表 P06–P10 已验收。

## 固定材料与版本

`experiments/models.py` 定义 ExperimentDefinition、AgentDefinition、DatasetCase、FactRequirement 和 Variant。实验、模板、用例、材料、提示、工具、评价器分别有明确版本；用例另记录材料内容 SHA-256。基线/候选必须只改一个允许字段。当前 `document-missing:1` 使用 `document-react:1`，同旧 `serial-checkpoint:2` 分开，旧 M0/M3 夹具和证据不变。

`experiments/documents.py` 提供全为虚构内容的固定材料：

| 顺序 | ID | 正文事实 |
| --- | --- | --- |
| 1 | release-v1 | v1 支持文档搜索 |
| 2 | release-v2 | v2 增加可配置工具重试 |
| 3 | release-v2-fix | v2 修复引用缺失 |

任务要求后两项事实。`search_documents:2` 只返回 ID/标题，固定按上述顺序截取，查询原文保留但不参与排序；这是一项受控教学实验，不是通用搜索质量测量。`top_k=2` 必然缺少第三份，`top_k=3` 才返回。`read_document:1` 只接受本次已返回 ID，才返回正文；不读取路径、不联网。检索配置由执行器持有，模型只提供 query/document_id。

基线 `document-top2:1` 与候选 `document-top3:1` 的 tool_retry_limit 都为 0，仅 top_k 从 2 变 3。定义同时提供成功标准、来源和 license 未知值，没有编造授权信息。新模板计划允许模型自主选择两个工具并循环，最多 8 次模型调用；旧模板的一次工具流程不会据此改变。

## 过程规则与人工复核

`evaluate_documents` 是不调用模型/工具的纯记录计算。只接受终态、匹配版本/用例/材料的记录，分支必须另提供完整的继承前缀；输入摘要绑定 RunView、前缀、用例与评价器版本。结果明确保留执行状态、样本数 1、无统计结论，并且不改写 Run 或事件。

规则分别检查必需文档是否返回、正文是否实际读取、显式 `[document-id]` 是否来自已读文档。正文读取需要和夹具内容相符；只有标题不算读到事实。引用检查只证明来源 ID 可用，不证明句子正确，也不通过字符串命中评价语义。没有答案或引用时相应结果为 unknown。取消、中断和材料缺失不会被隐藏。

事实覆盖与答案判断保持 `unreviewed`。HumanReview 单独记录每项事实的 covered/missing/uncertain、人工署名、说明、输入摘要及 judgement；其中 `justified_insufficiency` 可表达缺少材料时如实说明，不能由规则的材料 fail 自动推成“编造”。人工复核持久化与接口尚未实现。

## 当前验证与下一步

10 项针对性离线测试覆盖固定排序、读取白名单、严格参数、定义差异约束、诚实不足、带正确来源的错误答案、未知引用、取消/中断及输入版本不符。没有新增真实提供商调用。下一节点接入独立版本的 LangGraph ReAct 执行器及工具前分支，随后接评价存储/界面；M4 仍需实验包、真实文档参考和 P06–P10 证据。
