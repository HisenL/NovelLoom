# Contributing to NovelLoom

NovelLoom uses Python 3.11+ and Node.js LTS. Never commit API keys, generated novels,
runtime databases, or model responses containing private material.

## Development checks

```bash
python -m pytest --cov=novelloom
python -m ruff check .
python -m mypy novelloom
cd web && pnpm test && pnpm build
```

Provider integrations must include an offline contract test. Live-provider tests are optional
and must be skipped unless their environment variable is present.
