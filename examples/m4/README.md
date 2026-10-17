# 两份可导入的参考实验包

这两份 JSON 都包含任务、成功标准、Agent/工具版本、固定虚构材料、A/B 事件和来源；不需要密钥就能导入检查和回放。来源模式保留为 live 声明，本地一律 imported/只读。哈希验证内容完整性，不认证提供商身份、实际账单或人工判断。

| 文件 | 要观察的问题 | 实际结果 |
| --- | --- | --- |
| [tool-timeout.json](tool-timeout.json) | 相同首次超时下，只改执行器重试次数会发生什么？ | A 超时失败；B 重试后完成。复用 M3 真实记录，无新增调用。 |
| [document-missing.json](document-missing.json) | 文档未返回、正文未读取、回答是否有依据是同一件事吗？ | A 完成并说明材料不足；B 返回全部材料，但模型请求两个工具被串行协议拒绝。保留失败，不包装为成功候选。 |

## 无密钥阅读

按仓库安装说明同步依赖，在两个终端启动本地服务和页面：

```bash
uv run agenttinker-server --database artifacts/reference-reading.sqlite
npm --prefix web run dev
```

打开页面点击“导入文件”，选择上面任一 JSON，再点击“导入并打开记录”。在“导入来源与原意见”中展开任务、成功标准和材料；选择父运行查看 A，回到 B 看配置差异、步骤和新增用量。播放只重建已保存事件，不调用模型或工具。原评价仍绑定源 ID/摘要，不是对新本地 ID 的重评；结束前的历史位置隐藏原评价。可再次导出相同来源包。

包不包含可恢复的私有 checkpoint、定位值或连接密钥，不授予运行/分支/取消/新增评价能力。只处理已识别凭据字段；自由文本任务、消息和署名是保留的内容。许可未知，没有编造外部授权。

## 超时实验

来源：[M3 原生真实参考](../m3/deepseek-timeout-live.json)。一次逻辑 search_documents，A/B 使用同一查询、call ID 和首次故障；仅 tool_retry_limit 从 0 变 1。B 的第二次工具尝试成功后生成回答，前缀引用不算作新的模型调用。模板是有界 model→tool→model，不是完整 ReAct，也不是模型学会重试。

| 新增观测 | A | B |
| --- | --- | --- |
| 执行状态 | failed | succeeded |
| 模型调用 / 工具尝试 | 1 / 1 | 1 / 2 |
| 提供商总 Token | 374 | 250 |
| 费用 / 实际账单 | 未知 / 未知 | 未知 / 未知 |

合计 624 Token 属于先前 M3 调用，本次只转换，没有重新运行。答案语义未评价。

## 文档实验：包含真实失败的诊断例

来源：[原生真实观测](deepseek-document-live-observed.json)，2026-10-17（Asia/Shanghai）。document-react:1 自主选择工具，tool_choice=auto；固定排序搜索只返回元数据，read_document 才返回正文。A top_k=2；B 从首检索前持久化点只改为 3，复用 A 的首个模型步骤。查询和调用身份相同。

| 观测 | A | B |
| --- | --- | --- |
| 执行状态 | succeeded | failed（model_protocol:ValueError） |
| 搜索返回 | release-v1、release-v2 | release-v1、release-v2、release-v2-fix |
| 已读取正文 | release-v2、release-v1 | 无 |
| 必需材料返回 / 正文读取 / 引用来源规则 | fail / fail / pass | pass / fail / unknown |
| 新增模型调用 / 工具尝试 | 4 / 3 | 1 / 1 |
| 提供商总 Token | 2925 | 695 |
| 人工答案复核 | 未复核 | 未复核 |
| 费用 / 实际账单 | 未知 / 未知 | 未知 / 未知 |

A 的回答明确确认可配置工具重试，并说明现有材料无法支持引用修复结论。它的执行成功不代表材料完整，材料规则 fail 也不等于回答编造；没有自动创建 HumanReview 或语义分数。

B 检索后，模型在一个响应中请求读取 release-v2 和 release-v2-fix。当前串行协议要求每响应最多一个工具调用，因此在执行这两个读取前停止；原返回、两个请求意图、用量和失败原因全部保留。不能把“文档已返回”说成“正文已读取”，也不能把执行失败说成模型已生成错误答案。此记录没有最终答案，引用规则为 unknown。

19 项采集检查中 16 项满足；“两条执行均成功”“候选材料返回且读取”“候选引用对应已读来源”3 项预期未满足，real_reference_verified=false。原记录/旧 checkpoint/pending writes 不变、单变量/同查询/前缀、事件投影、规则摘要重算及提供商用量保留均通过。转换时明确使用 include-observed-failure，仍要求完整性检查通过；源失败和未满足的预期写进包，不改成绿色成功。

该轮 5 次新模型请求共 3620 Token。此外，[首次协议失败](deepseek-document-protocol-failure.json)为 1 次请求、552 Token：原解析器不接受 DeepSeek 的 index 元数据，工具/分支均未执行，随后修复。两次文档录制合计 **6 次新请求、4172 Token**；不隐藏首轮失败消耗，不自动重试/反复抽取成功结果，不将其与旧 M3 的 624 Token 混算。所有金额与实际账单仍未知。

## 重建与验证

纯转换不需要凭据、SDK 或 saver。用相同输入会生成相同内容和摘要：

```bash
uv run python scripts/package_reference.py --reference examples/m3/deepseek-timeout-live.json \
  --output artifacts/tool-timeout.json
uv run python scripts/package_reference.py --reference examples/m4/deepseek-document-live-observed.json \
  --output artifacts/document-missing.json --include-observed-failure
```

普通转换默认拒绝未满足预期的录制。显式保留文档失败也不能绕过事件投影、谱系、原事实不变、规则摘要及其他完整性检查；不能用该选项把失败改成成功。

这是两个单例，B 复用了前缀，不是两组从头独立运行的统计基准。人工使用验证属于 M5；当前没有真实用户研究成绩。M4 仍进行中，真实文档 B 未完成；见[退出条件核对](../../docs/m4-acceptance.md)。

[生产浏览器检查](reference-browser.json)已验证无凭据导入四条记录、保留成功/失败与原规则、播放无 API 请求/模型构造、再导出一致；实时未配置明确返回 503。这证明阅读流程，不把源失败改成成功。
