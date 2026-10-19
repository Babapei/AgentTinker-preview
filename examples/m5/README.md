# M5 使用验证材料

此目录包含[空白会话模板](session-template.json)、[内置首版完整助手演练](native-walkthrough.json)、[Phoenix 历史观察](phoenix-observation.json)和[Phoenix 原生实验比较](phoenix-comparison.json)，没有真实用户成绩。status=not_started、null 和空列表表示尚未记录，不表示成功、零耗时或零错误。

[Studio 开发 API 控制](studio-control.json)记录两个当前原生执行器的模拟 A/B、Agent Server 旧检查点分支与前缀复用；3/8 个旧完整状态不变。它是 assistant_api_check；新增独立[页面操作证据](studio-browser.json)实际使用 Submit、Edit node state、Fork，复用首模型并核对同样的 3/8 个旧状态不变。两者不代表平台 ForkRequest 等价或真人成绩；本机规则只是适配观察后的纯函数检查，原真实引用失败保留。无 key 的开发服务/Studio 连接已实测，缺少 key 不再直接列为连接阻塞；见[接入说明](../../docs/m5-studio.md)。

流程与共同输入见[M5 验证说明](../../docs/m5-validation.md)，分别使用[参与者任务卡](../../docs/m5/participant-tasks.md)和[观察指南](../../docs/m5/observer-guide.md)。实际记录先放 artifacts/m5-study；保留原观察、证据与未完成项。

[容器与访问尝试](container-access.json)核对完整镜像、6 条原生模拟记录和保留数据卷重建后的旧点分支；container_check_passed=true，user_browser_access_verified=false，外部 URL=null。用户反馈内置浏览器未出现页面；没有创建托管服务或真人成绩。可重现说明见[容器与云端访问](../../docs/container-deployment.md)。

作者/助手工具操作和自动化证据与真实用户会话分别保存。M4 的真实模型参考不会自动变成 M5 用户使用证据；原定 5 人/至少 4 人目标尚未实测。

Phoenix 实操来自固定两包的离线转换与本地浏览器核对，4 traces/22 派生 spans 中只有 18 个原始步骤；5063 Token 是历史用量，没有新增模型调用。源金额未知，当前界面显示 $0，不能当实际账单；操作步骤和限制见[工具对照记录](../../docs/m5-tool-comparison.md)。M5 整体未完成。

内置首版演练使用真实 CLI/生产构建，两个模拟 A/B、四份文件往返及历史播放共 12 条记录；原始模型参考只读，未新增人工复核或提供商请求。所有机器证据的 counts_as_user_session 均为 false，不能补成 5 位真人或写入诊断耗时；Studio 页面操作已另存证据；真实用户试用、反馈和最终 M5 验收继续待完成。

Phoenix 原生比较将同一两组历史 A/B 映射为 2 个案例、2 个实验、4 条历史结果和 6 项来源 CODE 规则。Grid 与原追踪打开核对通过，文档 B 的正文读取 pass/引用 fail 同时保留；实验汇总显示 No cost data，追踪详情仍显示 $0，均不当账单。原生输出/规则再导出及浏览前后摘要不变，没有重新运行 Agent/评价器；耗时来自历史记录，原规则耗时和真实用户耗时仍未知。

[临时预览门禁](preview-access.json)验证本机密码保护、两类模拟 A/B、401/403/503、SSE/导出及 Chromium 登录后新建，共 5 条模拟记录；它没有外部网址或真人成绩，也不等于 Render 免费资源已验证。源文件摘要绑定本次门禁实现，访问密码不入该证据。
