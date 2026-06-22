# Security Policy

NovelLoom 默认只监听 localhost。不要把开发服务器直接暴露到公网。

密钥只允许使用 `env:NAME` 或 `keyring:service/user` 引用。请勿把 `.env`、数据库、日志、导出稿或 Keyring 内容提交到 Git。

如发现漏洞，请通过 GitHub Security Advisory 私下报告，不要先公开 issue。提交报告时请包含受影响版本、复现步骤和影响范围。
