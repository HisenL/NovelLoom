from __future__ import annotations

from .config import NovelLoomConfig, load_config
from .persistence import Database
from .providers import ProviderRegistry
from .providers.secrets import SecretStore
from .services.cascade import CascadeService
from .services.core import ArtifactService, GraphService, ProjectService
from .services.exporting import ExportService
from .services.prompts import PromptService
from .services.providers import ProviderService
from .services.reasoning import ReasoningService
from .services.writing import WritingService
from .workflows import StoryWorkflow


class NovelLoomEngine:
    """Public Python API shared by FastAPI and CLI."""

    def __init__(self, config: NovelLoomConfig | None = None) -> None:
        self.config = config or load_config()
        self.database = Database(self.config.app.database_url)
        self.database.create_schema()
        self.projects = ProjectService(self.database)
        self.graph = GraphService(self.database)
        self.artifacts = ArtifactService(self.database)
        self.providers = ProviderService(
            self.database, registry=ProviderRegistry(), secrets=SecretStore()
        )
        self.prompts = PromptService(self.database)
        self.reasoning = ReasoningService(
            self.database,
            self.providers,
            graph_service=self.graph,
            artifact_service=self.artifacts,
            prompt_service=self.prompts,
        )
        self.cascade = CascadeService(self.database, self.reasoning)
        self.writing = WritingService(
            self.database, self.providers, self.artifacts, self.graph, self.prompts
        )
        self.exporting = ExportService(self.database, self.config.app.output_dir)
        self.workflow = StoryWorkflow(
            self.database, self.reasoning, self.config.app.checkpoint_path
        )

    def close(self) -> None:
        self.workflow.close()
        self.database.close()

    def __enter__(self) -> NovelLoomEngine:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
