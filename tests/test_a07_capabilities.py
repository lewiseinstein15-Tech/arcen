"""A-07 capability reporting is distinct from registry inventory."""

from arcen.config import ArcenConfig
from arcen.sandbox.turn import execution_status


def test_unavailable_sandbox_has_no_effective_tools(monkeypatch):
    monkeypatch.setattr(
        "arcen.sandbox.runtime.docker_status",
        lambda image: {"docker_available": False, "image_present": False},
    )
    status = execution_status(ArcenConfig())
    assert status["effective"] == "unavailable"
    assert status["effective_tools"] == []
    assert status["supported_tools"] == ["bash"]


def test_available_image_reports_only_isolated_policy_tools(monkeypatch):
    monkeypatch.setattr(
        "arcen.sandbox.runtime.docker_status",
        lambda image: {"docker_available": True, "image_present": True},
    )
    status = execution_status(ArcenConfig())
    assert status["effective"] == "docker"
    assert status["effective_tools"] == []  # preflight is not an inspected turn
    assert status["candidate_tools"] == ["bash"]
    assert "file.read" not in status["candidate_tools"]
