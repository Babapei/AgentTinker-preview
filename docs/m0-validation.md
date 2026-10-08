# M0：检查点分支与记录协议验证

对应 [架构路线 M0](03-architecture-roadmap.md#10-开发顺序与完成条件)。本阶段验证运行语义，不代表实验工作台已经实现。

## 本地环境

使用 Python 3.12 或更高版本及 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在仓库根目录执行：

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
```

`uv.lock` 固定实际解析的依赖版本；`.venv` 与本地运行产物不入库。产品 Python 包使用 `agenttinker`，仓库名的 `-preview` 不进入包名。本仓库尚未发布 Python 包。

## 当前进度

- 已建立 Python 工程、LangGraph/Pydantic 依赖与代码检查工具。
- 检查点分支、A/B 调用计数和历史不变性验证待实现。
- 真实模型调用待配置提供商、模型和凭据；M0 的真实调用验收尚未完成。
