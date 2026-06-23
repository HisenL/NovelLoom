# NovelLoom Codex 协作约定

## 项目边界

- NovelLoom 是 Python 3.11+、FastAPI、SQLAlchemy/SQLite、LangGraph 与 React/Vite 组成的本地单用户应用。
- SQLite 是唯一权威事实源；NetworkX 只做内存投影和 DAG 校验。
- 已批准版本不可就地修改。权威事实变化时，结构内容可重算，已批准正文只能标记过期；正文重写必须由用户明确确认。
- 模型输出先进入 draft/candidate，并经过人工门后才能发布。
- API、日志和数据库不得保存明文密钥。Provider 路由、fallback、token/cost 预算语义不得被静默绕过。
- 不提交运行数据库、生成小说、真实模型响应、密钥或本地配置。

## 多智能体路由

主线程负责理解目标、拆分任务、选择 agent、整合结果、处理冲突并做最终验收。不要把最终决策外包给多个 agent 投票。

按“任务的不确定性和风险”选择 agent，而不是只按改动行数选择：

- `scout`：默认的低成本入口。用于定位代码、调用链、影响面、现有测试和文档；只读。
- `mechanical-worker`：用于需求和目标文件都已明确的机械改动，例如重命名、局部样板、明确断言或文档同步。
- `implementer`：用于需要编码判断的行为改动、跨文件实现、API/前后端联动和非平凡测试。
- `architect`：用于需求含糊、跨层设计、数据模型、迁移、工作流恢复、并发、DAG/级联、一致性或预算语义；只读。
- `reviewer`：用于完成后的高风险审查；只读。涉及持久化、工作流、Provider、安全或跨书一致性的改动必须调用。

### 动态升降级

1. 信息不足时，先让一个或多个 `scout` 并行收集互不重叠的证据。
2. 若任务局部、可逆、验收条件明确且不触及核心不变量，交给 `mechanical-worker`。
3. 若需要跨文件推理、改变运行时行为或编写非平凡测试，升级给 `implementer`。
4. 若存在需求歧义，或触及数据库 schema/迁移、不可变版本、DAG、级联失效、LangGraph checkpoint/恢复、人工门、并发、Provider fallback、预算、密钥与隐私，先交给 `architect`，再由 `implementer` 落地。
5. 强模型拆出完全确定的独立子任务后，可以降级给 `mechanical-worker`；不得让低成本 agent 自行补齐业务假设。
6. 核心路径完成后交给 `reviewer`。普通低风险改动由主线程复核即可。

并行仅用于相互独立、最好是只读的任务。默认同时启动不超过 3 个子 agent；避免多个写 agent 修改同一文件。长周期、相互独立的功能开发使用 Codex worktree 线程隔离，而不是让子 agent 在同一工作区竞争写入。

## 工作流程

1. 先检查 `git status`，保留用户已有改动。
2. 阅读最接近改动位置的代码、测试和 `docs/architecture.md`，再决定是否需要 agent。
3. 先做最小验证，再按风险扩大验证范围。不要用增加并行度代替清晰拆分。
4. 不确定时上报证据、假设和风险；不要编造接口、配置或测试结果。

## 验证命令

后端优先使用项目环境：

```powershell
./.conda/python.exe -m pytest --cov=novelloom
./.conda/python.exe -m ruff check novelloom tests
./.conda/python.exe -m mypy novelloom
```

前端：

```powershell
cd web
pnpm test
pnpm build
```

Provider 改动必须有离线合约测试；真实 Provider 测试仅在对应环境变量存在时运行。发布前额外运行：

```powershell
./.conda/python.exe scripts/privacy_check.py
```
