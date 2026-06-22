from __future__ import annotations

import uvicorn

from .api import create_app
from .config import load_config

app = create_app()


def main() -> None:
    config = load_config()
    uvicorn.run(
        "novelloom.server:app",
        host=config.server.host,
        port=config.server.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
