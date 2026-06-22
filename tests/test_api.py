from __future__ import annotations

from fastapi.testclient import TestClient

from novelloom.api import create_app
from novelloom.engine import NovelLoomEngine


def test_project_and_graph_api(engine: NovelLoomEngine) -> None:
    with TestClient(create_app(engine)) as client:
        response = client.post(
            "/api/projects",
            json={
                "name": "潮汐档案",
                "premise": "一座城市每天重写自己的历史。",
                "books": [{"key": "main", "type": "main", "title": "潮汐档案"}],
            },
        )
        assert response.status_code == 201
        project = response.json()
        node = client.post(
            f"/api/projects/{project['id']}/graph/nodes",
            json={"stable_key": "location:city", "kind": "location", "label": "潮城"},
        )
        assert node.status_code == 201
        graph = client.get(f"/api/projects/{project['id']}/graph").json()
        assert graph["nodes"][0]["label"] == "潮城"


def test_provider_api_never_returns_secret_value(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    with TestClient(create_app(engine)) as client:
        response = client.post(
            f"/api/projects/{project_id}/providers",
            json={
                "key": "offline",
                "provider": "mock",
                "model": "fixture",
                "secret_ref": "env:NOVELLOOM_TEST_SECRET",
            },
        )
        assert response.status_code == 201
        serialized = response.text
        assert "secret_value" not in serialized
        assert "api_key" not in serialized
