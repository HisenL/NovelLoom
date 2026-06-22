# NovelLoom（织语）

图谱驱动的多书联动 AI 小说创作系统。一个正本可关联多本人物传记、外传或不同视角伴生书；所有作品共享同一份世界事实与事件因果账本。

当前版本为 `v0.1.0-alpha` 工程基线，面向本地单用户与 GitHub 开发者。界面优先使用中文，作品语言可按项目配置。

## 已实现

- SQLite 唯一事实源，NetworkX 只用于内存 DAG 校验与遍历。
- 实体、关系、事件、大纲与正文的不可变版本和事实快照。
- 世界关系图与事件因果图；事件因果/时序边强制为 DAG。
- 图谱编辑后的递归失效传播与结构自动重算；已批准正文只标记过期，不自动覆盖。
- LangGraph + SQLite checkpoint 的世界、事件、多书规划三段人工审核流程。
- 一个正本 + N 本伴生书的同步章节规划与事件批次写作。
- 正文事实提取、跨书一致性审核和候选事实发布。
- OpenAI-compatible、Anthropic、Google Gemini 与离线 Mock Provider。
- 按模型角色配置主模型、回退链、能力与费用；密钥只使用环境变量或系统 Keyring。
- Token/金额硬预算预检、调用明细、任务状态与 SSE 进度。
- React 图谱驾驶舱、结构化正文编辑器、人工门、模型/Prompt 设置、版本对照与回滚。
- 分书 Markdown、DOCX 导出。

## 快速开始

### Conda（推荐）

```powershell
conda env create -f environment.yml
conda activate novelloom

cd web
pnpm install --frozen-lockfile
pnpm build
cd ..

ng serve
```

本机若使用独立 Conda 可执行文件，也可以创建项目内环境：

```powershell
conda create --prefix ./.conda python=3.11 pip -y
./.conda/python.exe -m pip install -e ".[dev]"
```

浏览器访问 `http://127.0.0.1:8123`。服务默认只监听 localhost。

### 常用 CLI

```powershell
ng init
ng project-create --name "雾港纪事" --premise "一座会遗忘人的港口" --main-title "雾港纪事" --companion "伊澜传"
ng project-list
ng start <project-id>
ng resume <run-id> --approve
ng export <project-id> --format md --format docx
```

### Provider 密钥

推荐在 Web 中填写环境变量引用，例如 `env:DEEPSEEK_API_KEY`，然后在启动前设置：

```powershell
$env:DEEPSEEK_API_KEY = "..."
ng serve
```

也可在 Web 中一次性提交密钥，NovelLoom 会写入操作系统 Keyring；数据库和 API 响应只保存/返回引用。

## 开发验证

```powershell
./.conda/python.exe -m ruff check novelloom tests
./.conda/python.exe -m mypy novelloom
./.conda/python.exe -m pytest --cov=novelloom

cd web
pnpm test
pnpm build
```

推送前额外执行隐私扫描：

```powershell
./.conda/python.exe scripts/privacy_check.py
```

当前自动化基线包含 28 项 Python 测试，核心服务覆盖率 93%、工作流覆盖率 94%，并覆盖 100 事件规划投影、12+4 章离线端到端流程、DAG、级联重算、恢复、预算、Provider 合约与双格式导出。真实模型的 12+4 成稿验收仍属于发布前门槛，不在仓库中伪造结果。

## 架构与扩展

- [架构说明](docs/architecture.md)
- [Provider 开发](docs/provider-development.md)
- [故障恢复](docs/recovery.md)
- [隐私、脱敏与 GitHub 发布](docs/privacy-and-publishing.md)
- [安全策略](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)
- [第三方许可证](THIRD_PARTY_NOTICES.md)

公开 Python 入口是 `NovelLoomEngine`；FastAPI、CLI 与后续 Skill 都调用同一应用服务层。首版扩展点限定为 Provider adapter、Exporter 与 Prompt pack。

## 明确不做

`v0.1` 不包含云端账户、多用户协作、PostgreSQL、Neo4j、EPUB、移动端，也不兼容旧 JSON 图谱或旧流水线数据库。

## License

[Apache License 2.0](LICENSE)
