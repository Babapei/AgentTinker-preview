# 完整平台容器与云端访问

2026-10-19。用户要求实际尝试从自己的浏览器访问本云环境。**免费临时预览已发布并通过外网 HTTPS、API 和 Chromium 核对：[AgentTinker 测试入口](https://agenttinker-preview.onrender.com)。用户设备能否打开尚待实际操作。** M5 的真人试用和反馈仍待取得。

## 这次访问尝试

环境修订 299，观测当前、running/connected、出站网络 unrestricted/enforced；未配置 VPN，TCP grant 为空。启动现有 CLI/生产页面后，云机器上的 `/` 和 `/api/v1/runs` 均返回 200，空数据库 total=0；启动进程移除提供商和 tracing 配置，没有模型调用。

应用内置浏览器打开 `http://127.0.0.1:8000` 的调用只返回 queued。请求附加了唯一的非秘密探测参数，云端没有收到对应请求；用户反馈没有出现新页面。不能把排队当作访问成功，也不能由此认定发生了网络拒绝。云环境技能所述 VPN/TCP 转发用于向外访问授权端点，明确不提供入站连接；开放出站 HTTP 不等于向用户发布 Web 端口。

同时核对 Sites：当前托管运行于 Workers，无法直接原样运行本项目的 Python 长驻服务和本机 SQLite saver；本轮没有做此架构迁移或仅发布静态页面。插件发现找到支持此类后端的 Render/Railway；已提供 Render 连接建议，随后确认插件已安装并启用，用户随后确认已完成账户连接；M5-09 当时的工具与技能目录没有其账户/服务管理入口，尚未通过 API 核验账户与服务，没有创建服务、购买资源或发布地址。后续只读连接核对见下一节。

## 当前入口目标：临时测试优先

用户随后明确当前处于测试阶段。先让用户打开现有平台进行短期试用；上一节点的 7.25 USD/月持久托管方案保留为可选项，不作为测试前置条件，也不视为已获付费授权。优先核对已有云环境的 Web 预览/端口转发；当前工具目录没有对应的转发/发布操作，环境状态也没有给出入站入口，但这不能证明云平台整体不提供该功能。不得把出站 VPN/TCP 指南当作入站预览能力的完整清单。

若已有环境暂时没有可用入口，可以评估 Render 免费 Web Service 作为临时演示。已直接获取并阅读官方[免费服务说明](https://render.com/docs/free)：免费服务可运行后端和 HTTPS，但闲置 15 分钟会休眠，重启、重新部署或休眠会丢失本机 SQLite/checkpoint，不能承诺跨会话恢复。重要可读实验记录可通过现有实验包导出留存；只读导入不恢复原生可执行 checkpoint。免费实例仍有工作区共享额度，带支付方式时流量/构建超额可能收费，因此不能保证账户总费用必为零，也不擅自升级或购买。本轮已完成免费实例的实际发布和模拟功能检查，见下一节；账户额度/账单及真实用户设备访问仍待核验，可选共享密码已启用。

2026-10-19 较早接续核对：环境修订 305、观测当前、running/connected、网络 unrestricted/enforced。当时仅确认运行环境正常和免费服务文档，没有新增访问成功、付费资源、模型调用或真人成绩。入口在后续免费部署中打通，不把长期托管需求混作临时测试的必需条件。

## 免费临时预览：已上线并验证

用户已授权本次临时测试入口实施。已创建 **agenttinker-preview**，服务 ID `srv-dbars2mq1p3s73crvj90`，部署 ID `dep-dbars3mq1p3s73crvnt0`，目标工作区 My Workspace。管理接口确认 `plan=free`、singapore、Docker、单实例、work 分支、`autoDeploy=no`；未配置付费磁盘、额外数据库或提供商密钥。初次部署源码为 `1afff1f31ef55a46be335cf876dc64620e6d1129`；后续仅记录文档的提交不自动替换此部署。

入口：[AgentTinker 临时预览](https://agenttinker-preview.onrender.com)。部署终态已核对为 live，完成于 2026-10-19 06:53:58 UTC；[独立远端证据](../examples/m5/render-preview.json)保存服务/部署/源码身份。共享用户名为 `preview`；密码只在本环境私有访问说明和 [Render 服务设置](https://dashboard.render.com/web/srv-dbars2mq1p3s73crvj90)的秘密环境配置中，不写入此文档。外网 HTTPS 的最小健康状态 200，页面/API/文档/SSE 无密码 401、异站写入 403、未配置 live 503 均已核对；两类原生模拟 A/B 的执行、分支、原 A 不变、SSE/导出通过。Chromium 154 登录后加载 4 条种子并从页面新建第 5 条，实时事件核对通过、页面异常 0。没有新提供商请求或人工意见；用户设备访问仍未知，这不是 M5 真人试用成绩。

## 临时预览的访问保护

用户“来弄吧”后继续临时测试入口实施，不购买计算方案、磁盘或额外数据库。当前工具仍未提供可用的入站端口转发操作；沿已连接 Render 工作区核对服务列表，返回 null，未发现可复用服务。本轮使用单个 `free` Docker Web Service、work 分支、singapore，关闭自动部署；免费实例的原文件系统用作可丢弃的试用数据，不冒充持久磁盘。

当前 CLI 支持 `AGENTTINKER_ACCESS_PASSWORD`，用户名为 `preview`；容器同时设置 `AGENTTINKER_REQUIRE_ACCESS_PASSWORD=1`，缺失/过短密码在创建数据库/监听前拒绝。页面、静态资源、API、文档及 SSE 均由同一密码保护；公开的 `/healthz` 仅返回最小状态，容器健康检查改用该路径。启用保护时拒绝浏览器跨站写入，默认本机模式不受影响，细节见 [HTTP 与 SSE](runtime-api.md#临时预览的可选访问密码)。

随机访问密码只在私有 artifacts 和托管秘密环境配置中保存，不写入 Git、URL、实验包、日志或页面。初次演示不配置提供商/追踪凭据，显式使用模拟场景；导入的真实记录仍只读。此功能是单 owner 共享门禁，没有租户隔离或独立账户系统；已先通过本机容器验证，再完成上一节的远端发布核对。

## Render 部署预检与待确认方案

2026-10-19 M5-10：当前环境修订 303，观测当前、running/connected，出站网络 unrestricted/enforced。Render 的管理工具及部署技能现在已可用，不再沿用上一节点的入口缺失判断。两个连接的 `get_selected_workspace` 均报告未选工作区；分别调用 `list_workspaces` 均成功，返回相同的唯一工作区 **My Workspace**（`tea-dbar3u4s728c739bot70`）。这是连接和工作区发现验证，没有读取该工作区的服务、账单、支付方式或秘密；尚未确认账户套餐、GitHub 仓库授权或既有资源名称冲突。按 Render 的访问约定，用户确认工作区后再将其 ID 显式传给资源操作，不静默选择或切换。

下面保留 M5-10 的持久托管候选配置；当前已暂缓，没有按此付费方案创建资源，现有免费临时实例见上文：

| 项目 | 拟采用值与依据 |
| --- | --- |
| 服务 | 单个 Docker Web Service，名称暂定 agenttinker-preview；创建前检查同名资源 |
| 来源 | https://github.com/Babapei/AgentTinker-preview，明确使用 work 分支，仓库根目录 Dockerfile |
| 资源 | 最低付费计算方案 0.5c-512mb（旧称 starter），0.5 CPU / 512 MB，单实例；云端容量尚未验证，不自动升级 |
| 地区 | 拟用 singapore；尚未核对关联资源，地区创建后不可修改 |
| 存储 | 1 GB 持久磁盘挂到 /data，事件库、checkpoint saver、artifact/WAL 均在此目录；不另建托管数据库 |
| 网络 | 使用容器既有 PORT 和 0.0.0.0，同源页面/API，由 Render 提供 HTTPS |
| 首轮模式 | 仅 synthetic，保留真实历史的只读导入；不复制本开发环境模型密钥到 Render |
| 发布控制 | 首轮手动部署，确认入口、状态与持久化后再决定自动部署行为 |
| 访问保护 | 当前应用无登录/租户隔离；先补齐单用户受控入口并验证，再交付可操作网址，不将公开端口视为保护 |

本次已直接获取并阅读官方[计算方案](https://render.com/docs/compute-plans)、[磁盘说明](https://render.com/docs/disks)、[Blueprint 规范](https://render.com/docs/blueprint-spec)和[价格页](https://render.com/pricing)：0.5c-512mb 为 **7 USD/月**，磁盘为 **0.25 USD/GB/月**，上述 1 GB 方案的基础费用为 **7.25 USD/月**。这是整月基础估算，不是已产生的账单或总额上限；计算资源按实际运行时间计费，磁盘按预留容量收费，流量超额、税费、模型调用与已有工作区订阅另计。Hobby 工作区订阅标价 0 USD/月，但当前工作区套餐未核验，不假定已经是 Hobby 或擅自升级。创建时以实际账户报价为准。

免费 Web Service 不能挂持久磁盘，因此不将免费临时文件系统当作本方案的持久化。带磁盘服务仅运行单实例，重新部署会短暂中断；当前无跨机器恢复或云端容量验收。MCP 的创建 Web Service 参数没有磁盘配置，需要通过当前支持的 Blueprint、Dashboard 或 API 完整配置，不能只创建一个会丢失 SQLite 的裸服务。

若以后采用此持久托管候选方案，再确认目标工作区与基础预算；日常测试准备沿既有授权推进。实际创建前完成访问保护、所选部署配置验证及 Git 同步；发布后检查 HTTPS 页面/API、两类模拟分支及重启后的记录/checkpoint，再请用户实际打开。此付费候选尚无独立部署结果，不与上面的免费实例混用；用户访问成功和真人试用成绩仍待实际取得。

## 容器包含什么

[Dockerfile](../Dockerfile)构建当前仓库的完整前端与原 Python 服务，保持 React/Vite、FastAPI、LangGraph、SQLite 的原架构。Python 3.12.14、Node 24.19.0、uv 0.12.23；Python/npm 依赖仍取各自锁文件。构建会执行原协议检查、TypeScript 检查和 Vite 生产构建，原主入口体积提示保留。Node/npm、pytest/ruff 只留在构建阶段，最终进程以 UID 10001 运行。

[入口脚本](../deploy/entrypoint.sh)用 exec 启动现有 CLI，单进程/单 owner；同一地址提供页面和 API。`PORT` 默认 8000，`AGENTTINKER_DATABASE` 默认 `/data/runs.sqlite`。数据库、checkpoint saver、artifact 及相关锁/WAL 文件都需随整个 `/data` 目录保留；不能只保留事件库。容器不携带模型密钥、运行数据库、私有 artifacts 或会话 CA。初次试用不传提供商配置，明确使用 synthetic；启动与健康检查不调用模型。

## 已执行的容器验证

[机器摘要](../examples/m5/container-access.json)区分 `container_check_passed=true` 与 `user_browser_access_verified=false`，外部 URL 为 null，用户成绩/耗时为空。实际镜像使用生产依赖、UID 10001；Node、pytest、提供商 key 和构建 secret 均不在运行环境。自定义 PORT=8123 的健康检查通过，宿主仅映射至 127.0.0.1:8001。

先创建超时与文档 v2 两组模拟 A/B 共 4 条记录，再停止并删除这个测试容器，使用同一数据卷创建新容器。4 份完整视图前后摘要不变，原分支请求的幂等返回相同 B；两个原 A 的旧 checkpoint 仍可创建新分支，各新增模型 1/2 步且执行成功，合计 6 条模拟记录。Chromium 实际加载容器页面和全部 6 条历史，再进入执行步骤，页面异常为 0；实时未配置请求返回 503 且不创建运行。

没有新增提供商调用或人工意见；原真实引用失败和未知费用保留。这不是跨机器备份/恢复演练，也不是生产可用性或公网访问验证。验证结束后停止本轮启动的服务/容器，镜像和私有测试 volume 留在本机，Git 仅保存代码与摘要。

## 本机重现

普通 Docker 主机从仓库根目录运行：

```bash
docker build -t agenttinker:preview .
docker run --detach --name agenttinker-preview --stop-timeout 45 \
  --publish 127.0.0.1:8000:8000 \
  --mount type=volume,source=agenttinker-preview-data,target=/data \
  agenttinker:preview
```

在该主机上访问 `http://127.0.0.1:8000`。容器内监听 0.0.0.0 是为了容器端口映射，示例只发布到宿主回环地址；它不会自动产生公网 URL。原应用 CLI 的默认监听地址保持不变。

宿主若使用代理与额外 CA，保留其代理/TLS 配置，通过临时构建 secret 传证书，不写入镜像。在本托管云环境中，本次实际构建命令为：

```bash
env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS \
  -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
  docker --host=unix:///var/run/docker.sock build \
  --secret id=proxy_ca,src="$CODEX_PROXY_CERT" \
  --secret id=system_ca,src=/etc/ssl/certs/ca-certificates.crt \
  --tag agenttinker:access-check .
```

只清除 Docker endpoint/context/TLS 选择器以核对平台的本机 daemon，保留 DOCKER_CONFIG、registry 凭据与原出站代理。Node 额外信任与 uv CA bundle 仅在相应构建步骤挂载，TLS 校验保持开启。普通无额外 CA 的宿主不必提供这两个可选 secret。

停止或重新创建容器时保留同一 volume；Docker stop 的 45 秒窗口对应原服务的 40 秒优雅退出配置。没有自动迁移数据库、自动重发运行或新增多副本调度。

## 对外发布仍需什么

临时试用网址需要能承载该容器的托管账户或服务器，以及用于单用户服务的受控访问入口；跨服务重启持续保存 SQLite 才需要持久磁盘或等效存储。当前 API 仍为单用户协议，可选共享密码门禁不提供账户/租户隔离，不能将此容器直接当作公开多用户服务。本轮仅验证免费临时实例的 HTTPS/共享密码与模拟功能；没有配置持久磁盘或执行云端重启/跨机恢复验收，也不承诺免费长期保存数据。

只有实际发布成功、返回网址并验证其入口后，才将链接交付为可访问平台。本轮已通过 Render 管理接口确认 live 和免费方案，并实际完成上述远端检查；下一步由用户打开共享密码入口试用。以后也可使用已有支持 Python/Docker 的服务器，无需为此改写 Agent 或更换执行引擎。
