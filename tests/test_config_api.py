"""T-036 — Settings backend: config persistence, masked round-trips,
provider bridge reload, and the /api/config/test connection probe.

Runs the real ASGI server on its own port; config writes land in a tmp
file so the suite never touches the user's ~/.arcen/config.yaml.
"""

import os

import httpx
import litellm
import pytest
import uvicorn

import arcen.server.app as server_app
from arcen.config import ArcenConfig
from arcen.server.app import ServerState, app

PORT = 3181
BASE = f"http://127.0.0.1:{PORT}"


class _Server:
    def __init__(self, tmp_path) -> None:
        server_app.STATE = ServerState(config=ArcenConfig())
        server_app.STATE.config_path = tmp_path / "config.yaml"
        config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
        self.server = uvicorn.Server(config)

    def __enter__(self):
        import threading

        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        import time

        deadline = time.time() + 15
        while time.time() < deadline:
            if self.server.started:
                break
            time.sleep(0.05)
        assert self.server.started, "uvicorn did not start"
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture()
def cfg_client(tmp_path):
    with _Server(tmp_path):
        with httpx.Client(base_url=BASE, timeout=30.0) as c:
            yield c


def test_put_persists_to_config_yaml_and_reloads_bridge(cfg_client) -> None:
    cfg = cfg_client.get("/api/config").json()
    cfg["provider"]["default"] = "openai"
    cfg["provider"]["api_keys"]["openai"] = ""  # no key → bridge goes offline
    resp = cfg_client.put("/api/config", json=cfg)
    assert resp.status_code == 200

    # persisted to the tmp config.yaml (never the user's real file)
    path = server_app.STATE.config_path
    assert path.exists()
    assert "default: openai" in path.read_text()

    # bridge reloaded in-memory: openai without a key → offline (None)
    assert server_app.STATE.llm is None

    # the file must be user-private
    assert (path.stat().st_mode & 0o777) == 0o600


def test_redacted_key_round_trip_never_wipes_a_key(cfg_client) -> None:
    # install a real key into the live state (as Settings save would)
    cfg = cfg_client.get("/api/config").json()
    cfg["provider"]["api_keys"]["openai"] = "sk-live-abc123"
    cfg["provider"]["default"] = "openai"
    cfg_client.put("/api/config", json=cfg)

    # a fresh GET shows <redacted>, never the literal
    fresh = cfg_client.get("/api/config").json()
    assert fresh["provider"]["api_keys"]["openai"] == "<redacted>"

    # PUT that redacted view back (untouched key field) → key survives
    resp = cfg_client.put("/api/config", json=fresh)
    assert resp.status_code == 200
    assert server_app.STATE.config.provider.api_keys["openai"] == "sk-live-abc123"
    assert server_app.STATE.llm is not None  # bridge usable again


def test_test_endpoint_rejects_unknown_provider(cfg_client) -> None:
    resp = cfg_client.post("/api/config/test", json={"provider": "warpdrive"})
    assert resp.status_code == 422


def test_test_endpoint_reports_missing_key(cfg_client) -> None:
    server_app.STATE.config.provider.api_keys.clear()
    resp = cfg_client.post("/api/config/test", json={"provider": "openai", "model": "gpt-4o-mini"})
    body = resp.json()
    assert resp.status_code == 200
    assert body["ok"] is False
    assert "no API key" in body["error"]


def test_test_endpoint_success(cfg_client, monkeypatch) -> None:
    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        from types import SimpleNamespace

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))],
        )

    monkeypatch.setattr(litellm, "completion", fake_completion)
    body = cfg_client.post(
        "/api/config/test",
        json={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-live-xyz"},
    ).json()
    assert body["ok"] is True
    assert body["sample"] == "pong"
    assert captured["model"] == "gpt-4o-mini"  # openai is bare in litellm
    assert captured["api_key"] == "sk-live-xyz"

    # a prefixed provider routes through its litellm namespace
    def fake_completion2(**kwargs):
        assert kwargs["model"] == "groq/llama-3.3-70b-versatile"
        from types import SimpleNamespace

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))],
        )

    monkeypatch.setattr(litellm, "completion", fake_completion2)
    body = cfg_client.post(
        "/api/config/test",
        json={"provider": "groq", "model": "llama-3.3-70b-versatile", "api_key": "gsk-x"},
    ).json()
    assert body["ok"] is True


def test_test_endpoint_error_never_echoes_the_key(cfg_client, monkeypatch) -> None:
    def boom(**kwargs):
        raise RuntimeError("connection refused for key sk-live-xyz at endpoint")

    monkeypatch.setattr(litellm, "completion", boom)
    body = cfg_client.post(
        "/api/config/test",
        json={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-live-xyz"},
    ).json()
    assert body["ok"] is False
    assert "sk-live-xyz" not in body["error"]  # sanitized
    assert "<redacted>" in body["error"]


def test_test_endpoint_uses_stored_key_when_field_redacted(cfg_client, monkeypatch) -> None:
    server_app.STATE.config.provider.api_keys["custom"] = "$ARCEN_TEST_KEY"
    os.environ["ARCEN_TEST_KEY"] = "sk-stored-123"

    def fake_completion(**kwargs):
        assert kwargs["api_key"] == "sk-stored-123"  # resolved from the live config
        from types import SimpleNamespace

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))],
        )

    monkeypatch.setattr(litellm, "completion", fake_completion)
    body = cfg_client.post(
        "/api/config/test",
        json={"provider": "custom", "model": "mock-1", "api_key": "<redacted>"},
    ).json()
    assert body["ok"] is True
    os.environ.pop("ARCEN_TEST_KEY", None)
