# 架构说明

## 边界

NovelLoom 是本地单用户应用。FastAPI 只监听 `127.0.0.1`，React、CLI 和公开 Python API 共用同一个 `NovelLoomEngine` 与应用服务层。

```text
React / CLI / Python API
          │
       FastAPI
          │
 Project / Graph / Artifact / Provider / Reasoning / Writing / Export Services
          │                              │
 SQLAlchemy + SQLite                 LangGraph runtime
   （权威事实源）                    （ID-only state）
          │                              │
      NetworkX 投影                 SQLite checkpoint
```

## 事实账本

`StoryNode`/`StoryEdge` 是稳定身份；每次编辑分别创建 `NodeRevision`/`EdgeRevision`。快照只引用已批准版本，不复制内容。事件的 `causes` 与 `precedes` 边投影为 NetworkX `DiGraph` 并进行 DAG 校验，人物关系仍可循环。

内容由 `Artifact` 与不可变 `ArtifactRevision` 表示。`ArtifactDependency` 记录节点、边或其他生成物到下游内容的依赖。权威事实变化时进行广度遍历：结构内容加入重算任务，已批准正文仅设置 `stale=true`。

## 工作流

LangGraph state 只保存项目、运行、决策等 ID。世界构建、事件推理和多书规划分别停在人工门；checkpoint 使用独立 SQLite 文件。任务失败会写回 `WorkflowRun`/`Job`，预算不足进入暂停，其余错误进入失败状态。

模型输出先写 draft/candidate。批准动作发布图谱版本或内容版本并创建快照；驳回不会污染事实账本。同一项目只允许一个运行中的规划工作流。

依赖边支持从节点、关系或内容版本向下遍历。世界事实变化会自动形成“事件候选 → 事件门 → 多书大纲候选 → 大纲门”的级联任务；事件变化跳过事件生成，仅确定性刷新事件总纲并重算大纲。正文永远不在级联任务中自动覆盖，只被标记为过期并等待批量重写确认。

## Provider

内置协议适配器：

- `openai_compatible`：自定义 Base URL、模型与请求头。
- `anthropic`：Messages API。
- `google_gemini`：GenerateContent API。
- `mock`：离线合约与演示测试。

角色路由支持 primary + ordered fallbacks。每个 profile 声明结构化输出、流式、工具、推理、上下文、输出和单价能力。第三方适配器通过 `novelloom.providers` Python entry point 注册。

## 数据写入原则

- SQLite 是唯一权威事实源，不持久化 NetworkX JSON。
- API/日志/数据库禁止保存明文密钥。
- 已批准版本不就地修改。
- 正文重写必须由用户显式确认。
- SSE 只广播任务状态，不承载业务命令。
