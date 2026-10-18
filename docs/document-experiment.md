# 文档缺失实验与评价

M4 进行中。当前已实现版本化定义、本地工具、独立 LangGraph ReAct 执行器/分支、场景 HTTP 接口与纯记录规则评价；评价/人工复核已持久化并接 HTTP 与界面；实验包和无密钥文件回放已接，真实文档观测和参考包已保存，最终验收待完成。以下内容不代表 P06–P10 已验收。

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

模拟模型是确定性离线驱动，不能证明真实模型的自主行动或生成正确性。live 需显式 provider/服务端凭据，配置检查不发送推理请求；实际执行走官方 SDK。前端已接场景表单、检查/回放、首检索分支、过程对比与独立评价/复核。比较器完整列出配置差异，只有已知 document-react:1/Case 且 Variant 标识与 top_k 对应时，才把派生的 Variant ID 视为同一策略变化的元数据；任意版本/任务/用例差异或标识不符仍拒绝单因素归因。

## 独立 v2：多意图逐工具串行执行

2026-10-18，用户确认先完善自带 Agent，再接现成 Agent。新增 document-react:2 / document-missing:2 / document-react-v2，材料、工具、Case、规则评价器和 top_k 策略不变；旧 v1 定义/提示/图状态、检查点、参考包及失败保留。不能把 v1 A 与 v2 B 当作仅改 top_k 的对照。

v2 使用 LangGraph 状态图和既有 SDK/工具/日志，模型响应可包含多个工具调用。整批名称、参数、严格 index、call ID 去重及剩余工具预算先校验；任一项不合格则整批不执行，原响应/用量保留。合格后按原顺序逐项执行，每项独立 span/调用 ID/编号和工具前 checkpoint；全部结果按原序返回后才再次调用模型。最多8次模型调用、7次逻辑工具执行，当前实验 retry=0。某项失败或取消后，后续意图不执行，不能生成虚假工具结果；在途返回仍保留。

首次检索前且无工具已执行时才允许 top_k 分支，包括首响应包含检索和后续读取的情况。完整待执行队列、原消息和当前位置持久化；恢复还核对原模型观察（或祖先引用），不能只改队列/消息后冒用旧调用身份。各分支沿自身 checkpoint stream 继续；旧 v1 只交给旧执行器，v2 状态不迁移到 v1。

Python/HTTP 显式设置 DocumentRunRequest(agent_version="2", mode="synthetic") 创建 v2；旧客户端省略 agent_version 仍为 v1，并保留旧请求指纹。此节点界面场景仍沿用 v1，后续切换新建入口；历史 v1 保持可读/可恢复。请求 schema 接受缺省字段，与响应必须完整的记录 schema 分开；前端提交前核对请求/场景版本，避免错误版本写入。

采集器新增 --agent-version 2，默认仍为1；应使用独立数据库/输出，不改写旧失败。新的评价、上下文导出、严格导入和纯参考转换已识别两个已知版本，记录/回放基础通用，答案规则仍是固定文档用例，不冒充任意任务评分。

## 过程规则与人工复核

`evaluate_documents` 是不调用模型/工具的纯记录计算。只接受终态、匹配版本/用例/材料的记录，分支必须另提供完整的继承前缀；输入摘要绑定 RunView、前缀、用例与评价器版本。结果明确保留执行状态、样本数 1、无统计结论，并且不改写 Run 或事件。

规则分别检查必需文档是否返回、正文是否实际读取、显式 `[document-id]` 是否来自已读文档。正文读取需要和夹具内容相符；只有标题不算读到事实。引用检查只证明来源 ID 可用，不证明句子正确，也不通过字符串命中评价语义。没有答案或引用时相应结果为 unknown。取消、中断和材料缺失不会被隐藏。

事实覆盖与答案判断保持 `unreviewed`。HumanReview 单独记录每项事实的 covered/missing/uncertain、人工署名、说明、输入摘要及 judgement；其中 `justified_insufficiency` 可表达缺少材料时如实说明，不能由规则的材料 fail 自动推成“编造”。人工复核已接不可变存储与 HTTP。复核者为本地用户填写的署名，不代表经过身份认证；测试标签也不代表真实用户评价。

## 不可变评价存储与接口

SQLite schema v3 在原事件库增加 evaluations、reviews 与独立 assessment_requests 账本，升级不改 Run/事件或旧请求指纹。评价不向终态执行流追加事件；评价/复核及幂等账本均由数据库触发器禁止更新和删除。结果与请求标识在同一事务提交；同 key 同请求返回同一结果，换 key 明确追加一份新评价/意见。该账本与运行创建账本独立，各自命名空间内跨运行/操作冲突均拒绝。

服务只运行内置 document-evidence:1，绑定 Case、版本和包含继承前缀的输入摘要。前置条件不符拒绝并且不消费 key；运行中的记录不能评分。不需要凭据、SDK 或 saver，连续分支从祖先的只读观测记录解析前缀。规则程序异常单独保存 status=failed 与异常类型，checks 为空，不显示成零分，也不改变 Run 执行状态。相同 key 保留此失败，新 key 可以重新评价。

人工复核请求必须指定 evaluation_id 和匹配的 input_hash，并显式填写两项 fact_coverage、judgement、说明和署名。拒绝错属运行、摘要不符或失败评价；不从材料 fail 推导“编造”，也不覆盖旧意见。每次复核保留自己的 ID/时间/评价版本。规则结果仍保留 answer_review=unreviewed，人工意见单独显示来源。

接口：POST/GET `/api/v1/runs/{id}/evaluations` 与 `/reviews`，单条可按 ID 读取；POST 需要 Idempotency-Key，新建 201/重读 200，返回 Location。列表以追加顺序倒序分页，含 total/next_offset；offset≥0、limit 1–100。见 [API](runtime-api.md)。

## 场景与评价界面

“新建实验”的场景选择保留超时实验，并增加文档实验。文档表单读取服务端定义，显示固定任务/成功标准及基线 top_k=2/候选 top_k=3，须显式选择模拟或真实模式；实时凭据不进入浏览器。从基线首检索前只改 top_k 才是分支对照。未确认创建、评价与复核分别暂存同标签页的规范化内容/请求 key，刷新后可显式重试；不自动重发调用。

规则面板显示返回、读取、引用 ID 及各项 verdict，保留未知值和评价器失败；没有语义总分。人工表单不预选意见，要求逐事实选择、判断、说明和本地署名，支持诚实不足。每份意见列出依据评价、输入摘要、版本和时间，与规则记录分开。规则和复核列表显示载入数/总数及更多入口；未读齐时不把“当前页未见意见”说成“未复核”。

面板缓存只读加载结果，历史前缀未结束时隐藏结束后的评价与表单，回到最新复用缓存。A/B 对比显示原查询/身份、派生 Variant 对应、返回材料和已读正文，文档实验讲解不套用超时故障结论；答案评价指向两条 Run 各自的独立意见，没有合成为统计结论。规则/人工页面当前针对内置版本用例，不代表任意数据集批评测已实现。

## 当前验证与下一步

评价存储/API 节点：196 项 Python（新增 9 项）与 ruff 通过；覆盖并发幂等、失败回滚、不可变触发器、旧库升级、继承前缀、评价错误/重评、意见绑定/追加、分页与无密钥 HTTP 重启，Run/SSE 不变。此前 M4-02 的 57 项 Vitest 与 28 项实际 Chromium 通过。新增文档运行覆盖持久化重启、A 原事件/checkpoint/pending writes 不变、连续及并发分支、不重复前缀、同调用/查询、取消保留用量、协议拒绝、调用上限、直接回答、未返回文档拒读、进程意外退出与幂等重读。离线 SDK 验证 auto 选择、双工具、DeepSeek 参数、响应/用量与无密钥回看；跨语言验证 A/B 每个事件前缀，实际浏览器检查/回放文档循环无写请求、记录不变。本节点没有新增真实提供商调用。

界面节点：196 Python、65 Vitest、35 项独立 Chromium 用例已通过（33 项全量后，补充边界并定向重跑 7 项文档用例），协议/类型/生产构建/格式/ruff 通过。浏览器验证实际场景创建、A/B 评价/复核、三类请求丢失响应后刷新重试不重复、播放隐藏未来评价且无新请求、52 份人工意见分页、键盘/窄屏/axe。同步修正事件时间线的可访问名称与可见文字不符；测试截图在忽略的 artifacts/m4-document-evaluation-*.png。均为模拟/离线验证，无新增真实提供商调用。

实验包/文件界面已接；下一节点录制真实文档参考、整理参考包，并核对 P06–P10；M4 尚未验收。

## 参考采集与离线转换

`capture_document_reference.py` 明确选择 synthetic/live，按固定请求 key 保存 A，关闭并重开服务后从首检索前只改 top_k=3 派生 B。保留 A/B 原事件与用量、分别创建幂等规则评价，核对 A 观察记录和全部旧 checkpoint/pending writes 不变；B 只计新增后缀。逐项检查材料、正文和引用 ID，不生成 HumanReview、不把规则 pass 写成语义正确。单例、复用前缀与费用未知均保留。

```bash
uv run python scripts/capture_document_reference.py --mode synthetic \
  --database artifacts/m4-reference-synthetic.sqlite --output artifacts/m4-reference-synthetic.json
```

真实录制需明确 `--mode live --provider deepseek`，使用独立数据库/输出，可能产生提供商费用。默认最多每路径 8 次模型调用，SDK 不自动重试；已有固定请求在同库重用，不因重新运行采集器再次调用。直接回答、协议失败或无首检索边界保留实际记录，不伪造分支。失败写 `.failed.json`，保留已收到事实/用量，只报告异常类型，不覆盖成功输出。

```bash
uv run python scripts/package_reference.py \
  --reference artifacts/m4-reference-synthetic.json --output artifacts/m4-document-synthetic-package.json
```

转换器纯读取 m3-reference-1 或 m4-document-reference-1，严格核对事件投影/引用；文档规则结果按相同视图和前缀重算，不只相信保存的 checks。转换输出与生产导出的记录相同，创建时间固定来自采集时间，便于重复核对哈希；不打开 saver、构造 SDK 或调用工具。M3 624 Token 真实参考可直接转换，不需重复提供商请求。来源摘要/声明仍不证明身份或独立认证真实调用。

本节点新增 9 项离线测试，全量 240 Python、ruff/格式通过；覆盖幂等无模型重读、请求冲突、无检索/协议失败停止、无效引用保留失败、生产导出一致、确定性转换、旧 M3 转换、篡改评价重算拒绝、失败不覆盖/不泄露异常。该工具节点为离线验证；后续真实结果见下文。

首次真实文档尝试发现 DeepSeek 最终 tool call 附带 `index` 元数据；原解析器拒绝后保留了 552 Token、原响应和失败状态，没有执行工具/分支。现显式允许严格非负 index，只保留为观察元数据，不作为参数或身份，也不回传到后续模型请求；raw_response 不变。失败证据见 [原记录](../examples/m4/deepseek-document-protocol-failure.json)。245 Python 已覆盖官方 SDK 的带/不带字段往返与非法类型；成功真实 A/B 仍待新数据库录制，不篡改已失败运行。

## 已保存的真实文档观测

[参考包与独立阅读说明](../examples/m4/README.md)已保存两份 JSON。第二次真实文档录制 A 完成并明确说明不足，B 返回三份材料后因一次请求两个工具被既定串行协议拒绝；A 2925/B 新增 695 Token、4/1 次模型请求，合计 3620 Token。加上第一次 index 协议失败 552 Token，本轮共 6 次新请求、4172 Token，未选择价格表，费用/实际账单未知。

原记录保留 3 项未满足的结果预期与 real_reference_verified=false，不将 B 改成成功，也不继续付费重抽。材料返回/读取/引用规则为 A fail/fail/pass、B pass/fail/unknown；原评价/人工作答标签分开，均没有人工复核。单变量、同检索身份、前缀/原历史/旧状态不变、纯投影和规则摘要重算通过。

纯转换器默认拒绝未满足预期；显式 `--include-observed-failure` 可保留闭合文档失败，但仍要求全部结构/证据完整性检查通过，并在上下文注明未满足项，不能绕过摘要或改写运行状态。按 P07 保留失败，避免只展示成功样本。248 Python、ruff/格式通过；生产浏览器和 M4 最终核对仍在进行。

生产构建已用两个实际参考文件无密钥导入四条记录，回放无 API 请求/模型构造、哈希不变，明确显示文档 B 的 failed 和 pass/fail/unknown。见 [M4 退出条件核对](m4-acceptance.md)；M4 仍进行中；提供商约束与后续方案见下文，不能以放宽记录校验或反复抽样替代真实闭环。

2026-10-18 已完成[官方核对与独立 v2 方案](document-tool-protocol-decision.md)：没有已确认的 DeepSeek Chat Completions 单调用强制开关，不进行参数猜测后的付费重试。既有 SDK 路径已补完整请求模板冻结与旧首次请求核对，配置漂移在 fork/执行器启动前拒绝；原 v1 语义、真实失败及 checkpoint 保留。按序执行多意图的 v2 方案待确认，尚未实现。
