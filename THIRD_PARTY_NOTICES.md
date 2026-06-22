# Third-party notices

NovelLoom 自身使用 Apache-2.0。直接运行依赖在引入时已检查许可证；锁文件是实际解析版本的权威记录。

主要依赖：

| Component | License |
|---|---|
| FastAPI, Pydantic, SQLAlchemy, Alembic, LangGraph, keyring, python-docx, Rich, Typer | MIT |
| httpx, NetworkX, Uvicorn, sse-starlette | BSD family |
| PyYAML | MIT |
| React, TipTap, XYFlow | MIT |
| Lucide | ISC |
| ELK / elkjs | EPL-2.0 |
| Vite, Vitest, TypeScript, Playwright | MIT / Apache-2.0 |

EPL-2.0 组件以独立 JavaScript 库形式使用，未复制或修改其源码。发布前 CI 应重新扫描 `pyproject.toml`、`web/pnpm-lock.yaml` 和构建产物；禁止引入未知许可证、GPL/AGPL 或不可再分发依赖而不经过维护者审核。
