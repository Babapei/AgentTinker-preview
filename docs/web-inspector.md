# M2：运行检查界面

工程位于 [web](../web)，采用 React、TypeScript 和 Vite。共享协议、只读历史列表和运行/步骤详情已接入后端；事件重建、实时订阅及断线补发已接入；图、时间线与历史播放尚待实现，M2 继续进行。

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
- **事件订阅：**先读取快照，再从 seq=1 补读和校验事件；追平后只由已验证事实更新视图。连接断开按最后已应用序号补读，事件 ID 去重；跨 Run、冲突、持续缺口或快照不一致会停在保留快照并提示，不能进入历史播放。终态追平后停止订阅。切换记录只结束订阅，不取消执行。运行控制、图、时间线和播放随后接入。

31 项 Vitest 验证协议、请求身份、未知/部分观测、已知零值、逻辑计数和精确费用。11 项 Playwright 测试使用实际 Chromium 和本机 Vite/FastAPI/SQLite；真实 LangGraph synthetic 生成失败/重试记录，历史适配器拒绝新执行；新增受测试驱动端点控制的 gated synthetic 运行验证真实 SSE。另用明确的路由 fixture 覆盖分页、部分用量、错误响应及竞态。检查了键盘选择、390px 窄屏无横向溢出、减少动画，以及默认页 axe WCAG 2 A/AA 自动检查；这不替代完整人工可访问性评审。后端 136 项回归继续通过，没有付费调用。

## 浏览器验证与模拟预览

```bash
# 首次没有浏览器时安装 Chromium；已有系统浏览器可指定路径。
npm --prefix web exec -- playwright install chromium
UV_CACHE_DIR=/tmp/agenttinker-uv-cache npm --prefix web run test:e2e
```

本环境可直接使用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium`。测试自动占用本机 8000/5173 两端口，不复用其他服务，以免读写真实开发数据；完成后关闭服务。测试截图位于忽略的 artifacts/m2-inspector-desktop.png 和 m2-inspector-mobile.png，不是发布站点。

需要手动查看模拟记录时，可用以下命令代替普通后端入口，再另启前端：

```bash
uv run python scripts/serve_web_test.py
```

该服务在临时 SQLite 生成两条 native synthetic 记录；仅此测试脚本提供 /__test__ 驱动端点，可显式创建/放行 gated synthetic 验证订阅，普通 create_app 不含这些端点。关闭即删除，不使用 live 密钥、不修改 artifacts/runs.sqlite。空数据库的普通界面仍显示空态，不自动生成或冒充已有实验。生产静态托管、公开部署和完整实验工作台尚未实现。

事件读取复用 eventsource-parser，UTF-8 分片交由 TextDecoderStream；重连使用新的 after_seq，不将旧 query 与新 Last-Event-ID 混用。浏览器 EventLog 检查顺序、身份、状态、父引用和重试来源，只有投影成功才推进游标。跨语言测试通过实际模拟运行，把失败/重试/取消每个前缀与 Python project_events 输出逐一比较；没有从最终状态补造中间事实。
