# M4：可用首版功能验收

2026-10-18（Asia/Shanghai）。**M4 按原定 P06–P10 与“两份可独立理解的实验包”条件完成。** 自带文档 Agent v2 的真实 A/B 均执行到最终答案，B 已读取两份必需正文；原 v1 的执行兼容阻塞已通过独立版本解决。

**本次真实 B 仍有错误引用 hrelease-v2，引用规则为 fail，采集预期为 18/19，real_reference_verified=false。** 这些值保持原样。阶段验收判断的是平台能否运行、展示、分支、独立评价和保存事实；P06–P10 没有要求模型每次回答全部正确。没有将这次答案判为完全正确，也没有降低采集检查或重复抽取全绿样本。

## 已有证据

- [三份参考包与独立讲解](../examples/m4/README.md)覆盖原定两类实验：超时、文档缺失。超时包复用 M3 的真实记录；文档 v1 包保留协议失败，新增 v2 包保留执行成功与引用失败。每组各一个 A/B，不是重复采样。
- [文档 v2 真实观测](../examples/m4/deepseek-document-v2-live-observed.json)：代码基线 9f6b52e，独立数据库录制一次有界 A/B；A 3 次模型/4 次工具、2491 Token，B 新增 2 次模型/4 次工具、1948 Token。首响应的两个搜索意图、查询、call ID 和顺序完整继承，B 只改 top_k；原 Run/事件/全部旧 checkpoint/pending writes 不变，原始 SDK 响应与用量保留。
- [旧 v1 观测](../examples/m4/deepseek-document-live-observed.json)与[首次 index 协议失败](../examples/m4/deepseek-document-protocol-failure.json)保持不变：分别 3620、552 Token。v1 B 返回材料后，两个读取意图在执行前被拒绝，无正文和答案，引用 unknown。
- [最新生产浏览器证据](../examples/m4/reference-browser-v2.json)：Chromium 154，实际文件表单导入三份包/六条来源记录；历史播放 API 请求 0、模型构造 0，前后 RunView 摘要与再导出一致，未配置 live 明确 503 且无新增运行。两版文档通过 390px/axe 检查；[旧四条记录证据](../examples/m4/reference-browser.json)保留。
- 当前回归为 **292 Python、81 Vitest、43 Chromium 全量**，协议生成、类型、生产构建、ruff/格式通过。后端全量在证据节点重跑；前端单元/浏览器/构建来自 9f6b52e，同一应用代码未再修改。上述生产文件核对单独列证据，不混入 43 项。新增检查覆盖首批第二个搜索被改动时拒绝。
- 实现节点：ed86d49（独立 v2/旧点兼容）、9f6b52e（界面/旧请求身份/完整浏览器）、3e99fb6（真实失败保留/参考包/生产阅读）。使用入口见[文档实验](document-experiment.md)、[实验包](experiment-packages.md)、[界面说明](web-inspector.md)。

## P06–P10 原条件核对

原标准见[产品设计](02-product-design.md#8-验收标准)，阶段出口见[架构路线](03-architecture-roadmap.md#10-开发顺序与完成条件)；以下逐项判断，原标准不修改。

| 条件 | 结论与可检查证据 | 范围与限制 |
| --- | --- | --- |
| P06 证据可用性与答案评价分开；诚实不足不误判为编造 | **通过。** 返回/正文/引用规则各自列出，人工判断独立。真实 v2 A 为 fail/fail/pass，B 为 pass/pass/fail；两条执行均成功，answer_review 仍 unreviewed，无 HumanReview。纯评价回归验证缺材料不自动推导编造、引用可用不证明事实正确；浏览器覆盖人工意见追加/分页/证据锚定和历史隐藏。 | 本次未做人工作答复核，不从 A 的不足说明推导整篇正确，也不以 B 的执行成功覆盖引用失败。 |
| P07 个例、样本数、缺失、取消与错误不隐藏 | **通过。** 样本数 1、前缀复用和无统计结论保留。552/3620/4439 Token 三轮观测均保留；旧 v1 执行失败、新 v2 引用失败均可读。未知费用不补零，评价器异常独立失败；显式保留失败包仍必须通过结构/投影/谱系/原事实/规则摘要核对。 | 不能据此推断普遍策略效果；没有换样本或反复调用来获得全绿参考。 |
| P08 普通 trace 可读；不可恢复则无可用分支操作 | **通过。** normalized trace 可仅含摘要，events=null 不造事件；即使来源 running，也不接管/SSE/取消/分支/新增评价。完整包可读回放，导入身份映射、原模式/意见/双摘要及重启只读均有后端/实际浏览器回归。 | 当前接收平台规定的数据格式，未实现各厂商原始日志解析；导入包不携带可移植的 LangGraph 私有状态。 |
| P09 协作取消保留在途结果 | **通过。** 沿用 M3 原验收；原生在途模型/工具、排队取消、SDK usage 和 cancel_requested 展示有服务/浏览器验证。v2 新增批中取消：已收到的工具正文/模型用量保存，余项和后续模型不执行。 | 取消验证使用可控本地/离线模型；没有增加付费 DeepSeek 取消实验，也不承诺中断提供商已开始的请求。 |
| P10 无凭据回看；实时未配置明确；包无凭据 | **通过。** 移除提供商配置且禁止构造模型的生产服务完成六条来源记录阅读/回放/再导出；live 503。凭据字段清理、私有 locator/执行能力移除、导出不改源、非法包拒绝均有回归。 | 来源/哈希不认证提供商身份或实际账单；只清理已识别凭据字段，用户自由文本仍按内容保留。 |
| 两份可独立理解的实验包 | **通过。** 超时、文档各有任务、成功标准、版本、固定材料、A/B、来源、用量和局限；额外保留旧文档 v1 包。三份包均可严格验证、导入和再导出。 | 不是三个独立统计样本，不授予包内代码执行或跨环境恢复能力。 |

规则/人工意见回归见 tests/test_document_experiment.py、tests/test_evaluations.py；导入导出与拒绝写入见 tests/test_packages.py、tests/test_imports.py；原生取消和新版队列见 tests/test_run_service.py、tests/test_document_v2.py。浏览器文件在 web/e2e/documents.spec.ts、packages.spec.ts、controls.spec.ts，真实参考核对入口在 web/scripts/check-reference-packages.mjs。

## 平台验收与真实任务结果

此前阻塞是旧 v1 在两个读取意图处停止：B 没有正文和最终答案。新版已实际完成这些步骤，执行兼容有真实闭环证据。当前 B 在主要事实处使用有效来源，但后面的说明出现未知来源 [hrelease-v2]；规则按原标准检测为 fail。

采集器的 19 项检查同时包含完整性和期望任务结果。当前 18 项满足，唯一 false 是 candidate_citations_reference_read_sources；real_reference_verified 因而保持 false，CLI 的 .failed.json 表示这些参考预期没有全满足，两条 Run 本身均 succeeded。纯转换仅通过显式 include-observed-failure 保留这个结果，不跳过任何完整性条件。平台展示和检测失败符合原 P06/P07；这不构成答案质量通过的结论。

## 用量与已知限制

本次 v2 **5 次新增请求、4439 Token**。此前文档 **6 次、4172 Token**（首次失败 552、v1 A/B 3620）不隐藏，文档累计 **11 次、8611 Token**。每个 B 仅合计其新发生 spans，实际续问上下文 Token 按提供商 usage 保留；继承步骤不额外重复计入。旧 M3 超时的 2 次/624 Token 单独列示。

本次没有选择价格表或取得逐笔扣费凭证，金额/实际账单未知。M0 按用户已确认的真实用量/版本化估算口径完成，实际账单独立待办持续有效；不为等待账单重复调用。

生产主入口 524.17 kB（gzip 157.62 kB），仍有 Vite 500 kB 提示，加载性能未验收。尚未公开部署。M4 完成范围是当前内置实验首版；任意 Agent 的通用答案评分、所有工具节点分支、六模块完整工作台均未实现。

## 后续工作

按用户最新确认，先完成当前内置首版原计划，再将现成 Agent 做成可选接入。M4 已完成，接下来先推进 M5 的同案例工具对照、真实用户试用和反馈修正；当前不开始外部 Agent 适配。未来接入时复用 Run/事件、检查、回放、来源、比较和文件基础。执行控制、可改配置、任务评价按适配器验证，不能因日志可读就授予暂停/恢复/分支能力；见[协议与适配边界](document-tool-protocol-decision.md)。

[M5 同案例任务、观察指南与空白记录](m5-validation.md)已准备；Phoenix 初步历史操作已有[单独记录](m5-tool-comparison.md)，Studio/完整任务对照和真实用户研究仍待完成，不能从自动化回归或这次个例生成诊断成功率、用户耗时或产品优势结论。

## 重现无密钥阅读检查

```bash
npm --prefix web run build
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm --prefix web run check:references
```

检查器启动临时本机 FastAPI/生产静态构建，移除提供商密钥/模型变量，并禁止构造任何模型。统计端点只属于测试服务；结束后清理临时进程/数据库。默认写 artifacts/m4-reference-browser-v2.json，截图在 artifacts/m4-real-reference-*.png。此命令不录制新的提供商请求。
