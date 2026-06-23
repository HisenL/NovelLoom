# NovelLoom 手动测试流程

本文用于本地验收 `v0.1-alpha`：先用离线 Mock 跑通管线，再切换真实第三方模型。

## 0. 环境检查

```powershell
conda activate novelloom
python --version
node --version
pnpm --version
```

期望：

- Python 为 3.11+。
- Node 为 22.x。
- pnpm 为 11.x。

如果 `pnpm` 不存在，重新安装环境依赖：

```powershell
conda install -n novelloom -c conda-forge nodejs=22 -y
corepack enable
corepack prepare pnpm@11.5.3 --activate
```

如果使用项目内 `.conda` 环境而不是命名环境：

```powershell
.\.conda\node.exe --version
.\.conda\corepack.cmd enable
.\.conda\corepack.cmd prepare pnpm@11.5.3 --activate
$env:Path = "$PWD\.conda;$env:Path"
```

## 1. 安装与构建

```powershell
pip install -e ".[dev]"

cd web
pnpm install --frozen-lockfile
pnpm build
cd ..
```

启动：

```powershell
ng serve
```

浏览器打开 `http://127.0.0.1:8123`。

## 2. 离线 Mock 冒烟测试

这个流程不调用真实模型，适合先检查 UI、数据库、人工门、版本和导出。

1. 在首页创建项目。
   - 正本：`main` / `雾港纪事`
   - 伴生书：`bio` / `伊澜传`
   - 故事梗概可填写：`退役领航员调查一座会遗忘人的港口。`
2. 进入“模型设置”。
3. 常用服务预设选择“离线 Mock 演示”。
4. 保存 Profile。
5. 在“已保存配置”中点击“测试连接”，应显示连接成功。
6. 点击“应用到全部角色”。
7. 进入“运行日志”，点击启动工作流。
8. 依次处理三个人工门：
   - 世界观审核：批准。
   - 事件总纲审核：批准。
   - 多书章节规划审核：批准。
9. 进入“正文编辑”，应看到正本 12 章、传记 4 章的章节大纲。
10. 如需测试正文批次，可用 API 或后续 UI 触发 `/api/projects/{project_id}/writing/batches`，事件键可先用 `event:arrival`。
11. 在导出页或 API 触发导出，检查 `exports/` 下 Markdown 与 DOCX。

Mock 的价值是验证流程，不代表真实创作质量。

## 3. 真实第三方 API 测试

进入“模型设置”，选择相应预设，例如 DeepSeek、通义千问、智谱 GLM、Moonshot 或自定义 OpenAI-compatible。

推荐配置方式：

- `API Key` 字段：直接粘贴真实密钥。系统只写入操作系统 Keyring。
- `密钥引用` 字段：可以留空，或填 `env:DEEPSEEK_API_KEY` 这类环境变量引用。
- `Base URL`：使用服务商 OpenAI-compatible endpoint。
- `模型名`：填账号当前可用的模型名。

如果采用环境变量方式：

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
ng serve
```

然后在 Web 中填写：

- 密钥引用：`env:DEEPSEEK_API_KEY`
- API Key：留空

保存后先点“测试连接”，再“应用到全部角色”。真实模型首次建议用同一模型跑通全流程；稳定后再按角色拆分：

- 世界构建、事件推演：强推理模型。
- 章节规划：中高档结构化模型。
- 正文写作：长上下文、文风稳定模型。
- 信息抽取、审核：便宜且结构化输出稳定的模型。

## 4. 常见失败与判断

- `尚未配置模型角色`：至少要给 `world_builder`、`plot_reasoner`、`chapter_planner`、`writer`、`extractor`、`critic` 配置主模型。可以先点“应用到全部角色”。
- `OpenAI-compatible provider requires base_url`：OpenAI-compatible 预设必须填写 Base URL。
- `未找到密钥引用`：环境变量未设置，或 Keyring 中没有该引用。
- `Provider returned 401/403`：密钥、Base URL 或模型名不正确。
- `没有返回合法结构化结果`：模型没有按 JSON Schema 输出。可换更强模型，或关闭不兼容的结构化输出能力后重试。
- `预算` 相关暂停：项目 token 或金额硬预算不足，需要调高预算或换低费用模型。

## 5. 发布前本地验证

```powershell
python -m ruff check novelloom tests
python -m mypy novelloom
python -m pytest --cov=novelloom

cd web
pnpm test
pnpm build
cd ..

python scripts/privacy_check.py
git status --short --ignored
```

发布前确认不要提交：

- `.env`、`novelloom.local.yaml`
- `data/*.db`、`*.sqlite*`
- `exports/*.docx`、生成稿、真实模型响应
- `.agents/`、`.codex/`
- 任何 `sk-...`、`Bearer ...`、真实手机号、身份证号或私人邮箱

## 6. 首次同步 GitHub

先保持 GitHub 仓库为 Private。确认上面的隐私检查通过后：

```powershell
git remote add origin https://github.com/HisenL/NovelLoom.git
git push -u origin main
```

推送后检查 GitHub Actions、安全告警、仓库文件列表和 Release 附件。确认没有用户数据、配置、数据库、导出稿、截图密钥后，再考虑转为 Public。
