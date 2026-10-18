# M5：同案例工具操作记录

2026-10-18。**部分操作已观察，M5 尚未完成。** 本页是助手操作记录，不是真实用户会话，也没有人工诊断耗时/通过率。先完成内置首版的使用验证，再做可选外部 Agent；这里没有引入新的 Agent 执行对象。

## 共同输入与转换

输入是已经发生的两组真实记录：[超时包](../examples/m4/tool-timeout.json)与[文档 v2 包](../examples/m4/document-missing-v2.json)。规范包摘要分别为 56bf96c2532e228fb92ed22bdd5fead415f0c0c576ac158b8abba3f6127c6121、d0122c09d264afb56ed89a7ef9ebaddafd968819948b1a690f62f2fd0a3b3f4b。每组 A/B 一例，跨工具使用同一记录，不是重新采样。

原始共 4 条 Run、18 个新发生 Span（7 模型、11 工具尝试）、5063 Token：374/250/2491/1948。这是历史观察量，不是本轮新增调用；当前没有新的模型执行。

为 Phoenix 增加一个明确的离线转换脚本 [m5_export_otlp.py](../scripts/m5_export_otlp.py)：

- 严格验证包后输出 OTLP，不打开 saver/SDK、不调用模型或工具，不改原包。
- 每条 Run 加一个标明 derived_container 的展示根节点，合计 22 spans；派生 trace/span ID 可确定性重建，原身份/状态、查询/调用、输入输出、用量与费用以属性保留。
- B 不复制继承模型步骤；根节点/跨运行父项附 OTLP links，并将原前缀 ID、父运行/检查点和 Intervention 单独存为属性。Phoenix 列表 API 未暴露 links，本轮只确认显式来源属性，没有把这一点写成链接功能已完整验证。
- 原规则/意见保留为来源属性，不冒充 Phoenix 新评价或人工意见；没有 HumanReview。旧失败中工具请求前的说明文字不当作最终答案。
- JSON 输出遵循 OTLP 的十六进制身份；Phoenix 20.23.0 的 HTTP collector 本轮对 JSON 返回 415，改用明确的 protobuf 编码后接收。协议编码依赖只通过临时 uv --with 提供，不增加应用依赖。

## 实际操作与尚缺内容

| 对象 | 已观察 | 未完成/限制 |
| --- | --- | --- |
| AgentTinker 内置首版 | M4 生产证据已验证相同来源包的导入、过程、播放与再导出，六条记录含旧文档失败；原生运行/分支另有真实证据和完整浏览器回归。 | 这些是已有功能/操作证据，本轮没有生成真实用户使用成绩。 |
| Phoenix 20.23.0，本机单实例 | 独立临时环境无提供商配置，assistant/telemetry 关闭；2 包通过 OTLP protobuf 进入 4 traces/22 spans。REST 逐属性核对原身份、父项映射、状态、输入输出、用量/未知费用；UI 打开超时错误和文档 B 最后模型输出，保留 TOOL_TIMEOUT/hrelease-v2。浏览前后数据摘要不变。 | 本桥接只提供历史观察；没有配置可执行图、checkpoint 恢复、平台内分支或新的 Phoenix 原生评价。不能据此声称 Phoenix 没有这些相关能力。没有人工任务耗时或接入优势结论。 |
| LangSmith Studio | 官方本地开发文档已读取，明确列出 LangSmith API key 前提；当前环境未绑定该配置，两个常见 key 变量也不存在。 | 未登录、未启动可用 Studio 对照，尚无界面实操结果。没有另建账户或请求提供商调用，也不据缺少配置推断工具能力。 |

最新机器核对在 [phoenix-observation.json](../examples/m5/phoenix-observation.json)。它标为 assistant_tool_check、counts_as_user_session=false，用户成绩/耗时为 null；截图在忽略的 artifacts/m5-phoenix-*.png，不属于已部署网站。

## 本次费用显示观察

所有原始 source_cost.amount 均为 null、kind=unknown，转换后仍相同。当前 Phoenix 版本/这份转换/未配置价格的条件下，表格和追踪详情显示累计费用 `$0`；它不是原始实际账单。原数据没有被补成零，观察指南仍要求参与者区分未知和实际零值。

这只记录当前配置的显示行为，没有验证 Phoenix 其他计价配置/适配器，也不推导产品排名或普遍缺陷。原 v2 B 引用规则 fail、real_reference_verified=false 与无人工作答复核保持，不从执行 OK 推导答案正确。

## 重现这部分本地操作

先安装仓库锁定依赖、准备 web/node_modules。在一个终端启动独立 Phoenix；提供商变量移除，保留继承代理与 TLS：

```bash
env -u DEEPSEEK_API_KEY -u DEEPSEEK_MODEL -u OPENAI_API_KEY -u OPENAI_MODEL \
  PHOENIX_HOST=127.0.0.1 PHOENIX_PORT=16007 PHOENIX_GRPC_PORT=14317 \
  PHOENIX_WORKING_DIR="$PWD/artifacts/m5-phoenix-final" \
  PHOENIX_DISABLE_AGENT_ASSISTANT=true PHOENIX_TELEMETRY_ENABLED=false \
  uv tool run --from arize-phoenix==20.23.0 phoenix serve
```

等服务 healthz 可达后，在另一个终端执行一次离线转换与本机导入：

```bash
uv run python scripts/m5_export_otlp.py \
  --package examples/m4/tool-timeout.json --package examples/m4/document-missing-v2.json \
  --output artifacts/m5-phoenix-final.json
uv run --with opentelemetry-proto==1.45.1 python scripts/m5_export_otlp.py \
  --package examples/m4/tool-timeout.json --package examples/m4/document-missing-v2.json \
  --format protobuf --output artifacts/m5-phoenix-final.pb
curl --fail -H 'Content-Type: application/x-protobuf' \
  --data-binary @artifacts/m5-phoenix-final.pb http://127.0.0.1:16007/v1/traces
node web/scripts/check-m5-phoenix.mjs
```

collector 后台接收有延迟，需等 agenttinker-m5 项目出现再执行检查。使用独立空目录，别把旧观察和本次数据混算；检查默认针对这两份固定输入与 20.23.0。页面时间筛选要覆盖来源日期（2026-10-16/18）；较晚重现时应调整时间范围。检查器只读核对，不自行推送数据、启动服务或调用模型。

## 接续

继续完成 Studio 的实际对照条件、原生模拟任务的完整操作观察，组织原定真实试用并处理反馈。当前只有 Phoenix 历史观察这一部分实测，不能宣布整个 M5 或原计划完成；外部 Agent 可选接入继续后移。

官方依据：[Phoenix 启动](https://arize.com/docs/phoenix/get-started)、[项目路由](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-projects)、[Studio 本地开发前提](https://docs.langchain.com/langsmith/local-dev-testing)。官方说明与本机实测在本文分别标记。
