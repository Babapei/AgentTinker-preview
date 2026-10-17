# 文档缺失实验与评价

M4 进行中。当前已实现版本化定义、本地工具、独立 LangGraph ReAct 执行器/分支、场景 HTTP 接口与纯记录规则评价；场景表单/评价界面、持久化评价和实验包尚待接入。以下内容不代表 P06–P10 已验收。

## 固定材料与版本

`experiments/models.py` 定义 ExperimentDefinition、AgentDefinition、DatasetCase、FactRequirement 和 Variant。实验、模板、用例、材料、提示、工具、评价器分别有明确版本；用例另记录材料内容 SHA-256。基线/候选必须只改一个允许字段。当前 `document-missing:1` 使用 `document-react:1`，同旧 `serial-checkpoint:2` 分开，旧 M0/M3 夹具和证据不变。

`experiments/documents.py` 提供全为虚构内容的固定材料：

| 顺序 | ID | 正文事实 |
| --- | --- | --- |
| 1 | release-v1 | v1 支持文档搜索 |
| 2 | release-v2 | v2 增加可配置工具重试 |
| 3 | release-v2-fix | v2 修复引用缺失 |

任务要求后两项事实。`search_documents:2` 只返回 ID/标题，固定按上述顺序截取，查询原文保留但不参与排序；这是一项受控教学实验，不是通用搜索质量测量。`top_k=2` 必然缺少第三份，`top_k=3` 才返回。`read_document:1` 只接受本次已返回 ID，才返回正文；不读取路径、不联网。检索配置由执行器持有，模型只提供 query/document_id。

基线 `document-top2:1` 与候选 `document-top3:1` 的 tool_retry_limit 都为 0，仅 top_k 从 2 变 3。定义同时提供成功标准、来源和 license 未知值，没有编造授权信息。新模板允许模型自主选择两个工具并循环，最多 8 次模型调用；旧模板的一次工具流程不会据此改变。

## 实际运行与持久化分支

`document-react:1` 使用独立状态图与提示。官方 SDK 适配器复用既有响应/usage 记录，仅替换成两个工具与 `tool_choice=auto`；没有强制模型先检索。模型可以直接回答，也可以逐次选择 search/read，实际调用编号与因果父引用分别保存。最多 8 次模型调用/7 次工具选择；无效参数、并行调用、重复 call ID 或超限均保留已发生响应/用量后停止。读取未返回文档会记录 `document_not_available`，不暴露其正文。

每次工具前保存持久化观察点，只有第一次检索前允许 top_k 补丁，读取或后续检索不授予 patch 能力。源 Run 必须终态。A/B 原查询和调用 ID 相同、前缀只引用；B 变体引用随策略更新，执行用量只算新增 spans。执行沿本次 LangGraph stream 发出的明确 checkpoint 继续，避免并发分支误用共享 thread head。旧 serial-checkpoint:2 仍按原实现/版本恢复。取消、重启标 interrupted、幂等与未知量规则沿用原服务。

```python
from agenttinker.runtime.service import DocumentRunRequest, ForkRequest, RunService

with RunService("artifacts/runs.sqlite") as service:
    a, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "document-A")
    a = service.wait(a.run.run_id)
    b, _ = service.fork(
        a.run.run_id,
        ForkRequest(
            source_checkpoint_id=a.checkpoints[0].checkpoint_id,
            patch={"top_k": 3},
        ),
        "document-B",
    )
    b = service.wait(b.run.run_id)
```

模拟模型是确定性离线驱动，不能证明真实模型的自主行动或生成正确性。live 需显式 provider/服务端凭据，配置检查不发送推理请求；实际执行走官方 SDK。当前前端能检查/回放文档记录，但新增场景表单与文档评价尚未接入；旧比较器也尚未把变体身份变化识别成同一配置因素，暂不借它宣称文档单因素对比已验收。

## 过程规则与人工复核

`evaluate_documents` 是不调用模型/工具的纯记录计算。只接受终态、匹配版本/用例/材料的记录，分支必须另提供完整的继承前缀；输入摘要绑定 RunView、前缀、用例与评价器版本。结果明确保留执行状态、样本数 1、无统计结论，并且不改写 Run 或事件。

规则分别检查必需文档是否返回、正文是否实际读取、显式 `[document-id]` 是否来自已读文档。正文读取需要和夹具内容相符；只有标题不算读到事实。引用检查只证明来源 ID 可用，不证明句子正确，也不通过字符串命中评价语义。没有答案或引用时相应结果为 unknown。取消、中断和材料缺失不会被隐藏。

事实覆盖与答案判断保持 `unreviewed`。HumanReview 单独记录每项事实的 covered/missing/uncertain、人工署名、说明、输入摘要及 judgement；其中 `justified_insufficiency` 可表达缺少材料时如实说明，不能由规则的材料 fail 自动推成“编造”。人工复核持久化与接口尚未实现。

## 当前验证与下一步

187 项 Python、57 项 Vitest 与 28 项实际 Chromium 通过。新增文档运行覆盖持久化重启、A 原事件/checkpoint/pending writes 不变、连续及并发分支、不重复前缀、同调用/查询、取消保留用量、协议拒绝、调用上限、直接回答、未返回文档拒读、进程意外退出与幂等重读。离线 SDK 验证 auto 选择、双工具、DeepSeek 参数、响应/用量与无密钥回看；跨语言验证 A/B 每个事件前缀，实际浏览器检查/回放文档循环无写请求、记录不变。本节点没有新增真实提供商调用。

下一节点接评价不可变存储/HTTP、规则结果与人工复核界面及场景表单；M4 仍需实验包、真实文档参考和 P06–P10 证据。
