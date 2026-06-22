# 隐私、脱敏与 GitHub 发布

## 永远不要提交的内容

- `.env`、API Key、Authorization Header、Cookie、Keyring 导出或云服务凭据。
- `data/` 内的 SQLite 数据库、LangGraph checkpoint、运行日志和事实账本。
- `exports/` 内的小说成稿、DOCX、未公开设定、真实人物素材或授权受限内容。
- 私钥、证书、身份证号、手机号、私人邮箱和带真实用户路径的诊断信息。

Provider 配置只能提交 `env:VARIABLE_NAME` 或 `keyring:service/name` 形式的引用。不要把密钥值写进 `novelloom.config.yaml`、示例、测试、截图或 Issue。

## 每次推送前

在仓库根目录执行：

```powershell
python scripts/privacy_check.py
git status --short
git diff --cached
git ls-files data exports
```

最后一条命令正常情况下只能看到两个 `.gitkeep`。隐私扫描负责拦截常见密钥、数据库、DOCX、手机号、身份证号和私人邮箱，但它不能理解小说语义；人物原型、真实经历和未公开文本仍需要人工复核。

如果密钥曾经进入 Git 历史，仅删除当前文件是不够的：立即吊销密钥，然后使用 `git filter-repo` 清理所有历史，并在强制推送前通知其他协作者重新克隆。

## 推荐的首次发布流程

1. 先在 GitHub 创建私有空仓库，不要自动生成 README、License 或 `.gitignore`。
2. 本地完成隐私扫描与 `git diff --cached` 人工检查。
3. 推送到私有仓库，检查 GitHub 的 Security、Actions 和依赖告警。
4. 用 Mock Provider 跑 CI；真实 Provider Key 只放在本机 Keyring，CI 不运行真实模型。
5. 确认历史、Release 附件和截图均已脱敏后，再将仓库转为 Public。

发布命令见 README 的“推送到 GitHub”章节。
