"""The HTTP API must not silently import or expose host workspaces."""

import uuid

import pytest
from fastapi.testclient import TestClient

from arcen.config import ArcenConfig
from arcen.server import app as server


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = ArcenConfig()
    config.session.dir = str(tmp_path / "sessions")
    state = server.ServerState(config)
    monkeypatch.setattr(server, "STATE", state)
    monkeypatch.setattr(server, "_turn_guard", lambda *args: None)
    return TestClient(server.app), state


def test_default_session_is_canonical_uuid_and_streamable(client):
    api, state = client
    response = api.post("/api/run", json={"goal": "hello"})
    assert response.status_code == 200
    session = response.json()["session"]
    assert str(uuid.UUID(session)) == session
    assert session in state.emitters
    assert api.get(f"/api/sessions/{session}/events").status_code == 200


@pytest.mark.parametrize(
    "session", ["../escape", "/tmp/escape", "not-a-uuid", "", 42, str(uuid.uuid4()).upper()]
)
def test_untrusted_session_cannot_choose_session_store_path(client, tmp_path, session):
    api, state = client
    response = api.post("/api/run", json={"goal": "hello", "session": session})
    assert response.status_code == 400
    assert state.emitters == {} and list((tmp_path / "sessions").iterdir()) == []


def test_api_explicitly_rejects_workspace_without_reading_it(client, tmp_path):
    api, state = client
    secret = tmp_path / "host-file"
    secret.write_text("private")
    response = api.post("/api/run", json={"goal": "hello", "workspace": str(tmp_path)})
    assert response.status_code == 422
    assert "not supported" in response.json()["detail"]
    assert state.emitters == {} and secret.read_text() == "private"
