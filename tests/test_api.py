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


def test_plain_api_key_in_secret_ref_is_moved_to_keyring_reference(
    engine: NovelLoomEngine, project: dict[str, object], monkeypatch
) -> None:
    project_id = str(project["id"])
    captured: dict[str, str] = {}

    def fake_set_keyring(reference: str, value: str) -> None:
        captured["reference"] = reference
        captured["value"] = value

    monkeypatch.setattr(engine.providers.secrets, "set_keyring", fake_set_keyring)
    with TestClient(create_app(engine)) as client:
        response = client.post(
            f"/api/projects/{project_id}/providers",
            json={
                "key": "deepseek-main",
                "provider": "mock",
                "model": "fixture",
                "secret_ref": "sk-test-short",
            },
        )
        assert response.status_code == 201
        payload = response.json()
        serialized = response.text
        assert payload["secret_ref"] == f"keyring:novelloom/{project_id}-deepseek-main"
        assert captured == {
            "reference": payload["secret_ref"],
            "value": "sk-test-short",
        }
        assert "sk-test-short" not in serialized


def test_invalid_secret_reference_returns_actionable_error(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    with TestClient(create_app(engine)) as client:
        response = client.post(
            f"/api/projects/{project_id}/providers",
            json={
                "key": "bad-ref",
                "provider": "mock",
                "model": "fixture",
                "secret_ref": "DEEPSEEK_API_KEY",
            },
        )
        assert response.status_code == 400
        assert "env:DEEPSEEK_API_KEY" in response.json()["detail"]


def test_long_env_name_without_prefix_is_not_treated_as_secret(
    engine: NovelLoomEngine, project: dict[str, object], monkeypatch
) -> None:
    project_id = str(project["id"])

    def fail_if_called(_reference: str, _value: str) -> None:
        raise AssertionError("invalid references must not be written to keyring")

    monkeypatch.setattr(engine.providers.secrets, "set_keyring", fail_if_called)
    with TestClient(create_app(engine)) as client:
        response = client.post(
            f"/api/projects/{project_id}/providers",
            json={
                "key": "bad-long-ref",
                "provider": "mock",
                "model": "fixture",
                "secret_ref": "DEEPSEEK_PRODUCTION_API_KEY",
            },
        )
        assert response.status_code == 400
        assert "env:DEEPSEEK_API_KEY" in response.json()["detail"]


def test_provider_connection_test_reports_missing_secret_without_500(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    with TestClient(create_app(engine)) as client:
        profile = client.post(
            f"/api/projects/{project_id}/providers",
            json={
                "key": "missing-env",
                "provider": "mock",
                "model": "fixture",
                "secret_ref": "env:NOVELLOOM_MISSING_SECRET",
            },
        ).json()
        response = client.post(f"/api/providers/{profile['id']}/test")
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert "NOVELLOOM_MISSING_SECRET" not in response.text


def test_route_api_persists_ordered_fallback_chain(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    with TestClient(create_app(engine)) as client:
        profiles = [
            client.post(
                f"/api/projects/{project_id}/providers",
                json={"key": key, "provider": "mock", "model": "fixture"},
            ).json()
            for key in ("primary", "fallback-a", "fallback-b")
        ]
        response = client.put(
            f"/api/projects/{project_id}/routes/world_builder",
            json={
                "primary_profile_id": profiles[0]["id"],
                "fallback_profile_ids": [profiles[1]["id"], profiles[2]["id"]],
                "parameters": {"temperature": 0.2},
            },
        )
        assert response.status_code == 200
        route = response.json()
        assert route["fallback_profile_ids"] == [profiles[1]["id"], profiles[2]["id"]]

        routes = client.get(f"/api/projects/{project_id}/routes").json()["items"]
        saved = next(item for item in routes if item["role"] == "world_builder")
        assert saved["primary_profile_id"] == profiles[0]["id"]
        assert saved["fallback_profile_ids"] == [profiles[1]["id"], profiles[2]["id"]]
        assert saved["parameters"] == {"temperature": 0.2}
