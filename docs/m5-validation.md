# M5：内置首版使用验证

2026-10-19。**进行中，尚未完成。** M0–M4 的功能回归和真实模型参考已保存；它们不是用户使用成绩。按用户最新顺序，先完成内置首版 M5、处理反馈，再将现成 Agent 做成可选接入。

## 原计划与完成证据

沿用[产品设计第 9 节](02-product-design.md#9-如何判断值得继续扩展)和[架构路线](03-architecture-roadmap.md#10-开发顺序与完成条件)，不修改原出口：

1. 用相同案例在 AgentTinker、LangSmith Studio、Phoenix 实际操作，记录接入工作、定位证据、修改/对比方式和限制。文档检索只能说明预期能力；只有实际完成的操作才记为实操。
2. 小规模真实用户使用。首轮预设目标仍为 5 位试用者中至少 4 位无需作者代操作完成一个场景；多数人能区分历史回放和重新执行，不把缺失费用理解成零成本。记录诊断成功率、耗时和误解，保留未完成和求助。
3. 根据证据决定继续扩展、调整体验或采用插件形式；发现的问题逐项修正并核对。没有数据时保持待判断。

助手/作者操作、自动化、合成模型都可以证明流程可用，不能冒充参与者、填入用户耗时或通过人数。M5 的比较对象是调试/观测工具，不是在平台接入新的 Agent。

## 可复现任务

给参与者的是[任务卡](m5/participant-tasks.md)，给记录者的是[观察指南](m5/observer-guide.md)；两者分开，任务卡不包含预期诊断答案。空白[会话模板](../examples/m5/session-template.json)没有填写参与者或成绩。

| 任务 | 共同输入 | 要观察的动作 |
| --- | --- | --- |
| T1 工具超时 | 原 M3 超时案例及固定材料 | 定位失败与所属模型；原生模拟 A → 仅改一次重试策略创建 B → 解释结果与来源 |
| T2 文档证据 | document-react:2、固定材料及规则 | 原生模拟 A → 仅改检索策略创建 B → 检查实际返回/正文/输出，并说明规则与答案判断的边界 |
| T3 阅读真实记录 | 已保存的超时/v2 文档包 | 无密钥导入、检查、播放、再导出；说明来源、执行权限、用量和费用局限 |

参考记录是固定观察材料；新建模拟运行是可执行练习。导入包不带可恢复的私有 checkpoint，不要求参与者从导入记录创建分支。跨工具只读检查可使用相同记录；执行恢复须另列其实际适配工作，不把单纯导入当成完整闭环。

## 本机准备

```bash
bash scripts/setup.sh
npm --prefix web run build
env -u DEEPSEEK_API_KEY -u DEEPSEEK_MODEL -u OPENAI_API_KEY -u OPENAI_MODEL \
  uv run agenttinker-server --database artifacts/m5-study/runs.sqlite --web-dist web/dist
```

打开 `http://127.0.0.1:8000`，同一进程提供页面与 API，不必再启动开发服务。开始时显式选择模拟模式；试用进程移除提供商配置，保留继承代理/TLS，实时入口会明确返回未配置，本轮不需要新的付费模型调用。每位参与者使用独立数据库和浏览器会话，记录所用 Git 提交、工具版本、任务顺序和开始/结束时间；此处地址只对应运行服务的那台机器，不是公开试用网址。

前期内置浏览器仅排队、用户未见页面的尝试已单独保留；随后已实际发布[免费临时预览](https://agenttinker-preview.onrender.com)，用户名 preview，密码通过私有访问说明取得。Render 确认为 free/Docker/单实例/无付费磁盘，源码 1afff1f；[远端机器证据](../examples/m5/render-preview.json)核对 HTTPS/保护、两个模拟 A/B 和 Chromium 新建/SSE，共 5 条模拟。未配置提供商密钥，免费休眠/重启可能清空记录及 checkpoint，重要可读材料及时导出；首轮不承担长期保存或跨重启恢复验收。用户设备访问仍未知，此检查不计为真人任务完成；每位参与者仍需分开准备会话和记录。

参考文件：

- [tool-timeout.json](../examples/m4/tool-timeout.json)，包摘要 56bf96c2532e228fb92ed22bdd5fead415f0c0c576ac158b8abba3f6127c6121。
- [document-missing-v2.json](../examples/m4/document-missing-v2.json)，包摘要 d0122c09d264afb56ed89a7ef9ebaddafd968819948b1a690f62f2fd0a3b3f4b。
- 额外诊断材料：[旧文档 v1 失败](../examples/m4/document-missing.json)。不把它与 v2 作仅改 top_k 的比较。

源包/真实回答不修改，任务不要求模型每次答对。包摘要为规范 JSON SHA-256，具体来源和失败说明见[参考包说明](../examples/m4/README.md)。

## 内置首版的完整助手演练

[机器核对证据](../examples/m5/native-walkthrough.json)使用 9a2493b 的真实 agenttinker-server CLI 和生产构建，没有挂测试端点或替换运行服务。原生练习显式选择模拟模式，任务/材料摘要/Agent 版本与共同参考对应；已有真实参考只读查看。

T1/T2 已通过界面创建 A、在允许点仅改一个参数创建 B、核对过程和原 A 不变，再导出→导入→历史播放→再导出。文档 A/B 各有一份规则评价，没有填写人工意见。另读取两份真实参考，保留真实 B 的 hrelease-v2 引用 fail；模拟 B 的规则通过不替换这项失败。

共 4 条原生模拟记录、8 条只读导入记录；回放 API 请求 0、真人意见新增 0，实时未配置 503/历史不变，390px 和 axe 通过。每次启动用新数据目录/浏览器会话，原包不变，没有新增提供商调用。这个结果标记 scripted_production_ui、counts_as_user_session=false，用户完成率/耗时仍为 null。

```bash
npm --prefix web run build
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium node web/scripts/check-m5-native.mjs
```

脚本会临时启动单进程 CLI，移除提供商配置并保留代理/TLS，结束后关闭自己启动的服务。成功写 artifacts/m5-native-walkthrough.json，数据库/日志/截图留在忽略的 artifacts/m5-native-*，Git 不备份这些私有运行状态；保存到 examples 的是无私有 locator 的摘要证据。该演练不能计入原定 5 位真实试用者，也没有验证 Studio/Phoenix 的全部对应操作。

## 工具实操记录口径

[实际工具操作记录](m5-tool-comparison.md)已开始：Phoenix 的相同历史案例转换、REST/界面核对及[原生数据集/实验比较](../examples/m5/phoenix-comparison.json)完成；后者实际检查 2 案例/2 实验/4 历史结果/6 来源 CODE 规则及链接追踪，没有重新执行 Agent 或评价器。[Studio 本机开发 API](m5-studio.md)已实测无 key/tracing 运行原生模拟节点、旧点状态分支与前缀复用；两个场景的页面 Submit/编辑/Fork 与旧状态核对也已独立通过；通用状态编辑和平台实验约束的差异已记录，取消/重启等未验证等价。真实用户结果仍待取得。

按工具逐一保存版本、环境、输入摘要、实际操作/接口、观察结果与证据位置。状态区分：已观察、尚未操作、当前环境缺少条件、经过操作仍未完成。某工具需要额外适配或账户时，记录该条件与实际投入，不能据此宣布它没有能力。

安装/接入耗时、程序启动耗时、人工任务耗时分开；网络等待不混入用户诊断成绩。跨工具任务顺序在首轮前确定并记录，避免把第二次熟悉案例后的速度直接当成产品优势。5 人只是初轮产品门槛，不支持显著性或普遍效果结论。

## 当前状态

- 任务/观察/空白记录材料已准备，内置首版两个场景的完整生产页面助手演练已通过；尚无真实用户会话。
- [Phoenix 历史观察/原生实验比较](m5-tool-comparison.md)、[Studio API/页面控制](m5-studio.md)已有独立证据，接入/执行控制差异按实际范围记录；不从通用分支或历史导入推导全部语义等价。
- 反馈修正、最终结论和 M5 验收待真实证据；外部 Agent 可选接入尚未开始。
