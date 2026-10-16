# M2：运行检查界面

工程位于 [web](../web)，采用 React、TypeScript 和 Vite。共享协议、历史/步骤检查、事件订阅/补发、实际执行图、事件时间线和只读历史播放已实现；M2 验收完成，见 [验收记录](m2-acceptance.md)。

## 本地开发

需要 Python ≥3.12、uv、Node.js ≥22.12 和 npm；固定安装入口同时安装两端锁定依赖：

```bash
bash scripts/setup.sh
uv run agenttinker-server --database artifacts/runs.sqlite
```

另一个终端启动前端：

```bash
npm --prefix web run dev
```

默认 `http://127.0.0.1:5173`，`/api` 经 Vite 转发到本机 8000 后端，无需把密钥送入浏览器或配置 CORS。当前仅开发入口，未公开部署；后端接口见 [HTTP/SSE](runtime-api.md)。启动和读取记录不调用模型。

## 共享协议

[export_web_schema.py](../scripts/export_web_schema.py) 从现有 Pydantic 响应和 Event 生成 serialization schema。实际响应包含默认字段，因此响应 schema 将这些字段设为必填；Decimal 费用保持字符串。该出口不启动 RunService、不打开 SQLite、不读取密钥或调用模型。

```bash
npm --prefix web run schema
npm --prefix web run schema:check
npm --prefix web test
npm --prefix web run build
npm --prefix web run format:check
```

[生成脚本](../web/scripts/generate-protocol.mjs) 用 json-schema-to-typescript 产生 TypeScript 声明与 JSON Schema，两个产物一起提交，禁止手改。构建先与 Python 当前协议比对，发现漂移即失败。协议变更时更新 Python 源码再重新生成。

浏览器使用 Ajv 校验来自网络的数据，拒绝未知版本、缺失字段与错误类型，并检查返回的 Run ID 与请求一致；这是结构验证，Pydantic 的跨字段语义检查仍以服务端为准。客户端只有 GET 历史/运行接口；查看、切换、刷新均不执行 provider/tool。

## 当前检查能力

- **历史：**读取实际 SQLite API，分页加载、搜索已加载记录；当前已加载记录按创建时间倒序，不把它宣称为全库最新排序。地址栏保存 run/span，刷新和浏览器返回保留选择；快速切换会取消旧读取并忽略迟到结果。
- **步骤：**区分模型每次调用和工具每次尝试，筛选模型/工具/失败步骤；默认定位首个失败步骤，也可键盘操作。展示实际输入、输出、元数据及注入故障来源；JSON 作为文本显示。
- **观测：**逻辑工具调用和 attempts 分开；指标仅统计本 Run 新增步骤，继承前缀只说明引用数。用量不完整则总量未知并显示覆盖率；已知 0 保留为 0。费用用 Decimal 精确相加，只有币种/口径/价格版本一致且完整时显示合计；估算不称实际账单。
- **来源与限制：**显式显示 live/synthetic/recorded/imported；模型输出标注尚未评价。检查点分支由后端 capabilities 决定，不提供虚假分支入口；未知值不补造。空历史、无匹配步骤、缺失 Run、协议不兼容与服务不可达分别提示。
- **事件订阅：**先读取快照，再从 seq=1 补读和校验事件；追平后只由已验证事实更新视图。连接断开按最后已应用序号补读，事件 ID 去重；跨 Run、冲突、持续缺口或快照不一致会停在保留快照并提示，不能进入历史播放。终态追平后停止订阅。切换记录只结束订阅，不取消执行。运行控制随后续实验闭环接入。

41 项 Vitest 验证协议、请求身份、未知/部分观测、已知零值、逻辑计数和精确费用。15 项 Playwright 测试使用实际 Chromium 和本机 Vite/FastAPI/SQLite；真实 LangGraph synthetic 生成失败/重试记录，历史适配器拒绝新执行；新增受测试驱动端点控制的 gated synthetic 运行验证真实 SSE。另用明确的路由 fixture 覆盖分页、部分用量、错误响应及竞态。检查了键盘选择、390px 窄屏无横向溢出、减少动画，以及默认列表和图的 axe WCAG 2 A/AA 自动检查；这不替代完整人工可访问性评审。后端 165 项回归继续通过，没有付费调用。

## 浏览器验证与模拟预览

```bash
# 首次没有浏览器时安装 Chromium；已有系统浏览器可指定路径。
npm --prefix web exec -- playwright install chromium
UV_CACHE_DIR=/tmp/agenttinker-uv-cache npm --prefix web run test:e2e
```

本环境可直接使用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium`。测试自动占用本机 8000/5173 两端口，不复用其他服务，以免读写真实开发数据；完成后关闭服务。测试截图位于忽略的 artifacts/m2-inspector-desktop.png、m2-inspector-mobile.png、m2-execution-graph.png 和 m2-execution-graph-mobile.png，不是发布站点。

需要手动查看模拟记录时，可用以下命令代替普通后端入口，再另启前端：

```bash
uv run python scripts/serve_web_test.py
```

该服务在临时 SQLite 生成两条 native synthetic 记录；仅此测试脚本提供 /__test__ 驱动端点，可显式创建/放行 gated synthetic 验证订阅，普通 create_app 不含这些端点。关闭即删除，不使用 live 密钥、不修改 artifacts/runs.sqlite。空数据库的普通界面仍显示空态，不自动生成或冒充已有实验。生产静态托管、公开部署和完整实验工作台尚未实现。

事件读取复用 eventsource-parser，UTF-8 分片交由 TextDecoderStream；重连使用新的 after_seq，不将旧 query 与新 Last-Event-ID 混用。浏览器 EventLog 检查顺序、身份、状态、父引用和重试来源，只有投影成功才推进游标。跨语言测试通过实际模拟运行，把失败/重试/取消/分支每个前缀与 Python project_events 输出逐一比较；没有从最终状态补造中间事实。

## 执行图与历史播放

执行图复用 React Flow 和 Dagre 布局，按实际 Span ID 生成独立节点，实线表示 parent_span_id，虚线表示同一逻辑调用的执行器重试。布局不把时间先后当作依赖；继承或缺失父步骤只显示引用，不计入新增调用。图节点与列表共用步骤详情和 URL 选择。图组件按需加载，默认列表无需加载画布代码。

时间线按 seq 展示当前已经应用的前缀，可筛选状态、调用、故障/重试及检查点，并查看原始 JSON。点击事件同时定位该前缀及关联步骤；后续事件的结果不会提前进入详情。更新时间比较保留 Python 记录中的微秒及其时区含义，不用毫秒截断值判断快照相等。

播放条支持首事件、上/下事件、滑条、0.5×/1×/2×/4×、暂停及返回最新。每个事件间隔为 700ms / 速度，是查看节奏，不是模拟实际请求耗时。进入历史后固定当前已保存的播放边界；新事件继续订阅，但只提示新增条数，不推动历史游标。实际运行状态单独显示，播放与暂停都不控制实际执行。刷新重新补读时保留同一 Run 已验证事实，避免历史位置跳到尚未验证的数据。

播放只调用纯 projectEvents；完整事件可用后，所有播放操作都不增加 API 请求，更不会调用 provider/tool。缺少完整事件或发现冲突时保留快照、禁用播放；ordinary imported 摘要不会凭空获得 checkpoint 或执行能力。当前播放游标不写入 URL，刷新回到最新记录并保留 Run/Span 选择。

M3 已有持久化/fork 后端/API，浏览器生成契约新增 Intervention 与 CheckpointAvailability；界面已接任务配置、执行/取消、分支入口与 A/B 对比。

## M3：任务配置与实际运行控制

点击“新建实验”配置任务、模式、重试上限、top_k 和首次超时注入。必须显式选择 synthetic/live；真实模式可选择提供商和模型，密钥仅由服务端配置。表单说明固定虚构文档与本地检索，故障由执行器注入；不自动调用模型或填造用量。

提交通过正式 POST runs，成功后进入相同事件检查/回放视图。未确认请求的规范化配置与幂等键临时保存在当前标签页 sessionStorage；网络错误、响应协议错误或刷新后可显式重试原请求。修改配置创建新的意图，相同未确认配置继续复用原 key；不会自动重试付费请求。双击和提交中编辑受控，错误提示只使用稳定码。

“实际任务”控制区始终使用最新状态，独立于历史游标。取消发送明确 POST，显示 cancel_requested 并等待在途调用；回放暂停仍只影响显示。查看/刷新历史不执行模型。165 后端、47 Vitest、20 Chromium 测试通过，新增浏览器验证实际表单创建、响应丢失后刷新重试只建一条运行、在途取消保留响应、明确未配置 live 的降级提示、键盘/390px/axe。模型均为模拟或离线适配，无新付费调用。

运行控制节点之后已接分支与对比，见下节；M3 尚待真实参考及最终验收。

## M3：单变量分支与父子对比

“检查分支可用性”明确读取当前 runtime 状态；仅对当前事件前缀中实际保存的 checkpoint 显示入口。旧内存/导入记录不提供执行按钮；状态缺失或不兼容时仍可检查历史。表单一次选择一个允许参数，显示原值→新值，拒绝原值；服务端再次核对，前端可用性不能绕过拒绝。

创建 B 后展示父运行/分支点、全部配置差异、执行状态、工具逻辑调用/attempt、材料 ID、回答、新增调用/Token/费用及调用耗时合计。B 的 inherited_span_ids 只作引用，不复制或计入新增量；A 为完整父运行，B 随当前事件前缀显示。未知不补零，费用区分估算与凭证；答案保持未评价。多处配置或来源不一致时提示不能单变量归因。

实验讲解由当前观测决定，区分同一首次注入故障、执行器重试和模型行动；讲解开关保留节点与运行选择。分支/比较按需加载，纯历史播放不增加 API 请求或调用外部服务。55 Vitest 与 26 Chromium 验证正常/丢失响应后恢复分支、服务端拒绝重查、缺失状态降级、A 不变、B 新增量、回放不泄露未来结果、top_k、键盘、390px 及 axe。截图位于忽略的 artifacts/m3-comparison-desktop.png 与 m3-comparison-mobile.png，均为模拟案例。
