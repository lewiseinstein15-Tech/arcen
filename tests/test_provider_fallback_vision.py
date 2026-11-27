"""Provider fallback and the vision capability probe.

Both features exist so a provider failure or a non-multimodal model produces
an honest answer instead of a silent one: fail over, or refuse. These tests
pin the refusal paths, because those are the ones that would otherwise be
tempting to fake.
"""

from __future__ import annotations

import base64

import pytest

from arcen.llm.client import LLMResponse, ProviderError
from arcen.llm.fallback import FallbackClient
from arcen.llm.vision import (
    VisionError,
    VisionUnsupported,
    describe_image,
    load_image,
    supports_vision,
)


class _Client:
    def __init__(self, *, name: str, model: str = "m", error: Exception | None = None) -> None:
        self.name = name
        self.model = model
        self.error = error
        self.calls = 0

    def model_for(self, role: str) -> str:
        return self.model

    def is_available(self) -> bool:
        return True

    def complete(self, role, messages, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMResponse(text=f"answer from {self.name}", model=self.model, tokens={"input": 1, "output": 1})


# -- fallback ---------------------------------------------------------------


def test_primary_is_used_when_healthy() -> None:
    primary = _Client(name="primary")
    backup = _Client(name="backup")
    client = FallbackClient([primary, backup])
    assert client.complete("executor", []).text == "answer from primary"
    assert backup.calls == 0
    assert client.last_used == 0


def test_provider_error_fails_over() -> None:
    primary = _Client(name="primary", error=ProviderError("502 upstream"))
    backup = _Client(name="backup")
    reasons: list[str] = []
    client = FallbackClient([primary, backup], on_fallback=lambda i, exc: reasons.append(str(exc)))
    assert client.complete("executor", []).text == "answer from backup"
    assert client.last_used == 1
    assert reasons == ["502 upstream"]


def test_all_providers_failing_raises_with_every_reason() -> None:
    client = FallbackClient(
        [
            _Client(name="a", error=ProviderError("first died")),
            _Client(name="b", error=ProviderError("second died")),
        ]
    )
    with pytest.raises(ProviderError) as excinfo:
        client.complete("executor", [])
    assert "first died" in str(excinfo.value)
    assert "second died" in str(excinfo.value)


def test_a_programming_error_is_not_retried_elsewhere() -> None:
    broken = _Client(name="a", error=TypeError("bad call"))
    backup = _Client(name="b")
    with pytest.raises(TypeError):
        FallbackClient([broken, backup]).complete("executor", [])
    assert backup.calls == 0


def test_fallback_needs_at_least_one_client() -> None:
    with pytest.raises(ValueError):
        FallbackClient([])


# -- vision -----------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    ["gpt-4o", "claude-sonnet-4-5", "qwen2.5-vl-72b", "glm-4.5v", "gemini-2.0-flash"],
)
def test_known_multimodal_models_are_supported(model: str) -> None:
    assert supports_vision(model) is True


@pytest.mark.parametrize("model", ["deepseek-chat", "glm-4.6", "", None])
def test_text_only_models_are_not_supported(model) -> None:
    assert supports_vision(model) is False


def test_load_image_sniffs_content_not_extension(tmp_path) -> None:
    fake = tmp_path / "picture.png"
    fake.write_bytes(b"not an image at all")
    with pytest.raises(VisionError):
        load_image(fake)


def test_load_image_returns_a_data_url(tmp_path) -> None:
    png = tmp_path / "ok.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    data_url, mime = load_image(png)
    assert mime == "image/png"
    assert data_url.startswith("data:image/png;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == png.read_bytes()


def test_load_image_refuses_oversized_files(tmp_path) -> None:
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 5000)
    with pytest.raises(VisionError):
        load_image(big, max_bytes=1024)


def test_describe_image_refuses_a_text_only_model(tmp_path) -> None:
    png = tmp_path / "ok.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    client = _Client(name="text", model="deepseek-chat")
    with pytest.raises(VisionUnsupported):
        describe_image(client, png)
    assert client.calls == 0  # nothing was sent to a model that cannot see


def test_describe_image_sends_content_parts_for_a_multimodal_model(tmp_path) -> None:
    png = tmp_path / "ok.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    sent: list = []

    class _VisionClient(_Client):
        def complete(self, role, messages, **kwargs):
            sent.append(messages)
            return LLMResponse(text="a small logo", model=self.model, tokens={"input": 1, "output": 1})

    client = _VisionClient(name="vision", model="gpt-4o")
    assert describe_image(client, png, "what is this?") == "a small logo"
    parts = sent[0][0]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_describe_image_without_a_provider_is_an_error_not_a_guess() -> None:
    with pytest.raises(VisionUnsupported):
        describe_image(None, "whatever.png")
