# Provider 开发

实现 `novelloom.providers.base.ProviderAdapter`，至少提供异步 `generate`：

```python
from novelloom.providers import ModelResponse, ProviderAdapter

class MyProvider(ProviderAdapter):
    name = "my_provider"

    async def generate(self, connection, request):
        return ModelResponse(content="...", input_tokens=10, output_tokens=20)
```

在第三方包的 `pyproject.toml` 注册：

```toml
[project.entry-points."novelloom.providers"]
my_provider = "my_package.provider:MyProvider"
```

要求：

- HTTP 错误转换为 `ProviderError`，不能记录请求密钥或未脱敏请求头。
- 结构化模式应返回 `ModelResponse.structured`。
- 返回真实 token 使用量；无可靠数据时返回 0，不编造。
- `base_url`、自定义头和模型名来自 `ProviderConnection`。
- 通过离线合约测试，不在 CI 调用真实模型。
