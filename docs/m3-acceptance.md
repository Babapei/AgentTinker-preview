# M3：首个超时实验闭环验收

2026-10-16（Asia/Shanghai）。M3 按原定 P01–P05、P09 和真实参考案例条件完成；M4 尚未开始。此结论不代表完整 v0.1、答案评价、公开部署或用户使用验证完成。

## 证据与范围

- 运行控制界面提交 `7d0888d`，分支/对比界面提交 `4daf9a0`；协议、持久化与 fork 后端见前序提交和 [运行服务](runtime-service.md)。
- 当前回归：165 项 Python、55 项 Vitest、27 项实际 Chromium；协议/类型/构建、Prettier、ruff 检查通过。模型侧以模拟/离线 SDK 为主，浏览器通过本机 FastAPI、SQLite 和 LangGraph 的实际事件验证。
- [原生真实 DeepSeek 参考](../examples/m3/deepseek-timeout-live.json)：当前 Run/Span/Event 协议的 A/B、Intervention、usage/raw_response、runtime/工具/夹具版本及 12 项检查结果。
- [真实参考只读浏览器核对](../examples/m3/deepseek-timeout-browser.json)：Chromium 154.0.8037.57，读取生产构建，0 个写请求，回放 B 的早期前缀后返回最新；前后 RunView SHA-256 一致。此为独立实测，不混入 27 项模拟集成测试计数。

当前原生适配器仍限定 `model → search_documents → model`、一次逻辑工具调用、固定虚构发布说明、执行器重试和明确工具前边界。真实模式使用官方 SDK，不代表完整 ReAct 或模型自主恢复能力。后续扩展不可静默用不兼容代码恢复旧状态。

## 原退出条件核对

| 条件 | 结果与证据 |
| --- | --- |
| P01 实时事实与后端一致，未知值准确 | 表单显式选择模式；生产 POST 后沿同一 SSE 检查实际事件。真实参考为 live/deepseek-flash，A 374、B 新增 250 Token；未选价格版本，费用未知。模拟/部分/已知零值另有回归。 |
| P02 独立调用与错误来源可追溯 | 每个 model/tool attempt 有独立 Span；父模型、原 tool call ID/查询、有效策略、注入来源与 executor 重试事件可检查。B 两次尝试保留同一调用身份。 |
| P03 回看不执行 | 纯事件投影、时间线和播放不调用 provider/tool；真实参考浏览器使用禁止构造模型的服务，0 个写请求，前后观察记录哈希一致。 |
| P04 有效旧点分支，A 不变、来源/改动可见 | 重新打开服务读取持久化旧点，动态核对能力/版本；只改 retry 0→1。A 全部原事件、checkpoint 与 pending writes 保持不变；B 展示父运行、分支点、Intervention 和配置差异。未确认 fork 刷新后重试仍返回同一 B。 |
| P05 同一首次故障，区分执行器与模型行为 | A/B 首次工具尝试均为 injected TOOL_TIMEOUT，B 第二次读取材料。讲解明确 executor 负责重试，不能称模型学会恢复；模型协议失败未到工具时标“故障条件未触发”，不纳入超时结论。 |
| P09 协作取消保留在途结果 | UI 实际取消独立于播放，显示 cancel_requested；原生在途模型/工具、排队取消及 SDK 用量保留有后端回归，浏览器验证在途返回后进入 cancelled。真实 DeepSeek 参考未额外发送取消实验请求。 |
| 保存真实参考 | 两次必要提供商请求：A 选择工具，B 仅新增一次回答请求。12 项检查全部 true，事件重建吻合；真实数据已保存为版本管理中的 JSON。 |

## 真实参考的量与限制

| 指标 | A | B 新增区间 |
| --- | --- | --- |
| 模式 / 实际返回模型 | live / deepseek-flash | live / deepseek-flash |
| 执行状态 | failed（首次工具超时） | succeeded |
| 新增模型调用 | 1 | 1 |
| 工具逻辑调用 / 尝试 | 1 / 1 | 1 / 2 |
| 提供商返回总 Token | 374 | 250 |
| 复用前缀 | 无 | 引用 A 的一个模型步骤，不重复计入新增量 |
| 费用估算 / 实际扣费 | 未选价格表 / 未知 | 未选价格表 / 未知 |

合计 624 Token。原 M0 的 634 Token 和版本化估算属于旧技术验证，不套用到本次请求。本次没有价格估算或逐笔账单凭证，余额不能替代实际扣费。

采集在同一 Python 进程内关闭并重建 RunService/saver owner，再从持久化状态派生 B；实际子进程退出/工具中 os._exit 后的恢复另由 `tests/test_checkpoints.py` 验证。源运行全部原 checkpoint/pending writes 的前后摘要在参考 JSON 中一致。再次读取采集器时以禁止构造模型的替身核对，A/B 幂等记录均复用，没有新模型构造。

真实回答只作为本次输出保存，尚未评分，也不能根据单例声称策略对所有任务有效。比较 A 的完整新增量与 B 的后缀新增量时，必须说明 B 复用了前缀；费用、调用耗时合计都不是逐笔账单或端到端延迟。截图保存在忽略的 `artifacts/m3-real-reference-*.png`，不视为已发布网站。

## 重现入口

先使用模拟模式验证；以下命令默认复用固定请求幂等键，保留同一数据库时不会重新执行已完成案例：

```bash
uv run python scripts/capture_timeout_reference.py \
  --mode synthetic --database artifacts/m3-reference-synthetic.sqlite \
  --output artifacts/m3-reference-synthetic.json
```

需要重新采集真实案例时显式选择 live，可能产生提供商费用；脚本不自动重试失败请求，配置与网络沿用服务端环境：

```bash
uv run python scripts/capture_timeout_reference.py \
  --mode live --provider deepseek --database artifacts/m3-reference-live.sqlite \
  --output artifacts/m3-reference-live.json
```

失败保留在 `.failed.json`，不覆盖成功产物。真实调用已返回的记录保留在数据库；异常仅报告类型，不输出原始异常。成功参考包含观测和 locator，不包含私有 saver 状态，不能仅凭 JSON 在另一环境执行。Git 不备份 artifacts 数据库；跨库备份须保留事件库、saver 和正确处理 WAL。

## 下一阶段

进入 M4：第二个文档缺失实验、独立规则评价/人工复核、实验包导入导出及无密钥参考回看，按 P06–P10 验收。沿用版本化夹具、允许字段和能力降级边界；M3 的真实 JSON 是证据，尚不是完整可导入实验包。
