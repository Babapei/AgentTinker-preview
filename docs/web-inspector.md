# M2：运行检查界面

工程位于 [web](../web)，采用 React、TypeScript 和 Vite。当前已建立工程、协议生成、运行时结构校验和只读 HTTP 客户端，检查界面随后接入；M2 尚未完成。

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

浏览器使用 Ajv 校验来自网络的数据，拒绝未知版本、缺失字段与错误类型；这是结构验证，Pydantic 的跨字段语义检查仍以服务端为准。客户端只有 GET 历史/运行接口；未知用量和费用保持 null。10 项 Vitest 验证包括真实 LangGraph synthetic 生成的离线记录、未知值保留、错误协议、费用字符串、分页及请求取消信号；没有付费调用。
