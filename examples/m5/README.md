# M5 使用验证材料

此目录包含[空白会话模板](session-template.json)、[内置首版完整助手演练](native-walkthrough.json)和[Phoenix 助手操作证据](phoenix-observation.json)，没有真实用户成绩。status=not_started、null 和空列表表示尚未记录，不表示成功、零耗时或零错误。

流程与共同输入见[M5 验证说明](../../docs/m5-validation.md)，分别使用[参与者任务卡](../../docs/m5/participant-tasks.md)和[观察指南](../../docs/m5/observer-guide.md)。实际记录先放 artifacts/m5-study；保留原观察、证据与未完成项。

作者/助手工具操作和自动化证据与真实用户会话分别保存。M4 的真实模型参考不会自动变成 M5 用户使用证据；原定 5 人/至少 4 人目标尚未实测。

Phoenix 实操来自固定两包的离线转换与本地浏览器核对，4 traces/22 派生 spans 中只有 18 个原始步骤；5063 Token 是历史用量，没有新增模型调用。源金额未知，当前界面显示 $0，不能当实际账单；操作步骤和限制见[工具对照记录](../../docs/m5-tool-comparison.md)。M5 整体未完成。

内置首版演练使用真实 CLI/生产构建，两个模拟 A/B、四份文件往返及历史播放共 12 条记录；原始模型参考只读，未新增人工复核或提供商请求。两份机器证据的 counts_as_user_session 均为 false，不能补成 5 位真人或写入诊断耗时；M5 剩余工具实操和真实用户反馈继续待完成。
