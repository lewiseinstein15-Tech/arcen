"""CI describes real Docker separately from offline installed-wheel tests."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/harness-validation.yml"


def test_validation_workflow_uses_read_only_token_and_no_persisted_credentials():
    raw = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.load(raw, Loader=yaml.BaseLoader)
    assert data["permissions"] == {"contents": "read"}
    assert "pull_request" in data["on"] and "workflow_dispatch" in data["on"]
    assert "secrets." not in raw
    for job in data["jobs"].values():
        checkout = next(step for step in job["steps"] if step["name"] == "Checkout")
        assert checkout["with"]["persist-credentials"] == "false"
        assert "token" not in checkout["with"]


def test_validation_workflow_has_matrix_wheel_and_explicit_docker_opt_in():
    data = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    wheel = data["jobs"]["installed-wheel"]
    assert wheel["strategy"]["matrix"]["python"] == ["3.12", "3.13"]
    steps = {step["name"]: step for step in wheel["steps"]}
    assert "pip wheel" in steps["Build and install wheel with test dependencies"]["run"]
    assert (
        "python -m pytest" in steps["Run test suite without live providers or Docker opt-in"]["run"]
    )
    docker = data["jobs"]["docker-isolation"]
    steps = {step["name"]: step for step in docker["steps"]}
    assert "docker build" in steps["Build local sandbox image"]["run"]
    live = steps["Run explicitly enabled real-Docker checks"]
    assert live["env"]["ARCEN_TEST_DOCKER_ISOLATION"] == "1"
    for name in ("test_turn_isolation.py", "test_manual_campaign.py", "test_harness_canary.py"):
        assert name in live["run"]
