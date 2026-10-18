# M5：同案例工具操作记录

2026-10-19。**部分操作已观察，M5 尚未完成。** 本页是助手操作记录，不是真实用户会话，也没有人工诊断耗时/通过率。先完成内置首版的使用验证，再做可选外部 Agent；这里没有引入新的 Agent 执行对象。

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
| AgentTinker 内置首版 | [本轮生产 CLI/UI 演练](../examples/m5/native-walkthrough.json)实际创建两类原生模拟 A/B、单参数分支/过程对比、规则评价、导出→导入→回放→再导出；任务/夹具/Agent 与参考一致，另读相同两份真实包，共 12 条记录，原事实不变。 | 原生练习为明确的模拟模式，原模型真实结果另保留；这是助手脚本检查，不是真实用户成绩/耗时。 |
| Phoenix 20.23.0，本机单实例 | 相同 2 包进入 4 traces/22 spans；[初步追踪核对](../examples/m5/phoenix-observation.json)保留。新增[原生数据集/实验对照](../examples/m5/phoenix-comparison.json)：2 个案例、A/B 两个实验、4 条历史结果、6 项来源规则；实际选择两实验进入 Grid，并从单例打开超时和末轮引用错误。原记录、评价来源和用量不变。 | 这是历史结果和来源 CODE 规则的映射，未重新执行 Agent/评价器，未接可执行图或 checkpoint 恢复/分支。不能据此声称 Phoenix 没有相关能力，也没有人工耗时、产品排名或接入优势结论。 |
| LangSmith Studio / Agent Server | [本机对照](m5-studio.md)更正旧前提推断：关闭 tracing 后无需 key 启动开发 API，托管 Studio 可无登录连接。研究桥接复用两个现有执行器节点/图边，API 实际完成相同任务/材料下的模拟 A/B、旧点状态分支、前缀复用，3/8 个旧完整状态不变。 | 两场景页面内完整操作接续检查；没有配置 LangSmith tracing/原生评价。通用状态编辑不是平台 ForkRequest/Intervention；取消、重启等没有声明等价。没有新增账户或提供商调用，也不计为真人研究。 |

两次机器核对分别保存在 [phoenix-observation.json](../examples/m5/phoenix-observation.json)和 [phoenix-comparison.json](../examples/m5/phoenix-comparison.json)，都标为 assistant_tool_check、counts_as_user_session=false，用户成绩/耗时为 null；截图在忽略的 artifacts/m5-phoenix-*.png，不属于已部署网站。

## Phoenix 原生数据集与实验对照

本轮沿用 20.23.0 的本机 OpenAPI，实际使用 `/v1/datasets/upload`、`/v1/datasets/{id}/experiments`、`/v1/experiments/{id}/runs` 和 `/v1/experiment_evaluations`。新增 `phoenix-experiments` 离线格式与[操作检查器](../web/scripts/check-m5-phoenix-experiments.mjs)，应用运行时、依赖和 Agent 对象不变。安装/映射/检查脚本的工作不计为用户诊断耗时。

每个源包是一个案例，使用相同任务、Agent 版本和材料摘要。A/B 分别进入 history-A/history-B，同一数据集版本各一次；`observation_kind=imported_historical_record` 明确说明输出已在过去产生。保留完整来源视图、评价与绑定、原父项/检查点/补丁和未知费用；trace ID 沿用 OTLP 派生映射，B 不补写继承的模型调用。没有人工语义复核或 gold answer，因此 reference output 留空。

文档两条记录各 3 项规则复制为 `source/document-evidence:1/...` 的 CODE 评价，label、解释、证据 Span、原评价身份/input hash 和 sample_size=1 均保留。pass/fail 映射 1/0，unknown 保持 null；不把来源规则改称 Phoenix 新运行的判分器。没有评价的超时案例保持无评价；多个同名评价快照拒绝转换，避免静默覆盖。原失败评价仍保留在来源输出中，不补造分数。

实际选择两个实验的复选框后进入原生 Grid，逐案例核对：

| 案例 | A | B | 保留的判断边界 |
| --- | --- | --- | --- |
| 工具超时 | 执行 failed，374 Token | 执行成功，新增 250 Token | 从 A 的单例打开工具输入/输出，可见 TOOL_TIMEOUT；没有补造文档规则分数 |
| 文档 v2 | 执行成功，必需材料返回/读取 fail，引用来源规则 pass；2491 Token | 执行成功，必需材料返回/读取 pass，引用来源规则 fail；新增 1948 Token | B 的末轮模型仍含 hrelease-v2；读到正文不等于答案正确，双方都没有人工语义复核 |

列表汇总显示原规则的差异，Grid 可逐项查看，View run trace 可打开原追踪。REST 再导出逐字段核对完整视图/来源规则及 metadata；浏览前后追踪与实验导出摘要相同，导航 GraphQL mutation 为 0。设置阶段共 13 次本机 POST：1 次创建数据集、2 次实验、4 次历史结果、6 次来源规则；没有调用模型、工具、远程评价或创建 HUMAN 意见。

运行起止时间沿用历史记录；规则只保存原创建时刻，原本没有评价耗时。接口要求的 start/end 均取该时刻，并以 `source_duration_seconds=null`、`adapter_interval_is_instant=true` 标识为点观察，不能当作测得 0 秒。原生界面会显示耗时/Token 变化及聚合百分比；两类任务不同、每类仅一例、A 含失败且 B 继承前缀，因此不作策略、速度或产品优势结论。

## 本次费用显示观察

所有原始 source_cost.amount 均为 null、kind=unknown，转换后仍相同。当前 Phoenix 版本/这份转换/未配置价格的条件下，表格和追踪详情显示累计费用 `$0`；它不是原始实际账单。原数据没有被补成零，观察指南仍要求参与者区分未知和实际零值。

本轮原生实验汇总显示 `No cost data`，费用列为 `--`；链接追踪详情仍显示 `$0`。原始 source_cost.amount=null 没有变化，不能把任何汇总显示当作账单。这只记录当前版本/映射/未配置价格的行为，没有验证其他计价配置，也不推导产品排名或普遍缺陷。原 v2 B 引用规则 fail、real_reference_verified=false 与无人工作答复核保持，不从执行 OK 推导答案正确。

## 重现这部分本地操作

先安装仓库锁定依赖、准备 web/node_modules。在一个终端启动独立 Phoenix；提供商变量移除，保留继承代理与 TLS：

```bash
env -u DEEPSEEK_API_KEY -u DEEPSEEK_MODEL -u OPENAI_API_KEY -u OPENAI_MODEL \
  PHOENIX_HOST=127.0.0.1 PHOENIX_PORT=16007 PHOENIX_GRPC_PORT=14317 \
  PHOENIX_WORKING_DIR="$PWD/artifacts/m5-phoenix-final" \
  PHOENIX_DISABLE_AGENT_ASSISTANT=true PHOENIX_TELEMETRY_ENABLED=false \
  uv tool run --from arize-phoenix==20.23.0 phoenix serve > artifacts/m5-phoenix-server.log 2>&1
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

在上述已收到 22 个 spans 的本机实例上，再完成原生实验对照：

```bash
uv run python scripts/m5_export_otlp.py \
  --package examples/m4/tool-timeout.json --package examples/m4/document-missing-v2.json \
  --format phoenix-experiments --output artifacts/m5-phoenix-experiments.json
node web/scripts/check-m5-phoenix-experiments.mjs http://127.0.0.1:16007
```

本轮实际使用独立目录 artifacts/m5-phoenix-comparison-20261019、HTTP 16009/gRPC 14319；端口可按启动参数调整。新检查器只允许 127.0.0.1，每次新建随机后缀的数据集，显式执行上述 13 次本机写入，再只读浏览/核对，不修改源追踪内容/文件；结束后关闭自己启动的 Chromium，Phoenix 由启动终端停止。成功摘要写 artifacts/m5-phoenix-comparison.json，原始映射/数据库/日志/截图只在忽略的 artifacts 中，不入 Git。

collector 后台接收有延迟，需等 agenttinker-m5 项目出现再执行检查。使用独立空目录，别把旧观察和本次数据混算；检查针对这两份固定输入与 20.23.0。页面时间筛选要覆盖来源日期（2026-10-16/18）；较晚重现时应调整时间范围。原 check-m5-phoenix.mjs 仍只读核对，不自行推送数据、启动服务或调用模型。

## 接续

内置首版完整助手演练、Phoenix 历史观察/原生实验比较和 Studio 开发 API 状态分支已有证据。继续完成 Studio 两场景的页面操作，执行控制差异仍按实际范围记录，不把历史导入、通用状态修改或 API 成功推导为完整等价。组织原定真实试用并处理反馈；不从助手演练生成用户完成率或产品排名，M5/原计划仍未完成，外部 Agent 可选接入后移。

注：本轮查阅旧 Phoenix “Run experiments” 文档地址时被重定向到 Arize AX 文档；没有用 AX 的接口说明或界面替代 Phoenix 实测。本节接口来自本机固定版本 OpenAPI 和实际响应。

官方依据：[Phoenix 启动](https://arize.com/docs/phoenix/get-started)、[项目路由](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-projects)、[Studio 本地开发前提](https://docs.langchain.com/langsmith/local-dev-testing)。官方说明与本机实测在本文分别标记。
