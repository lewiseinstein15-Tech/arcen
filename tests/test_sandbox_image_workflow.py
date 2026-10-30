"""Sandbox image CI uses least-privilege GitHub job credentials."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/sandbox-image.yml"


def test_sandbox_image_workflow_uses_scoped_job_token_not_pat():
    raw = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.load(raw, Loader=yaml.BaseLoader)
    assert "secrets.GH_PAT" not in raw
    job = data["jobs"]["build-and-push"]
    assert job["permissions"] == {"contents": "read", "packages": "write"}
    steps = {step["name"]: step for step in job["steps"]}
    checkout = steps["Checkout"]
    assert checkout["uses"] == "actions/checkout@v4"
    assert "token" not in checkout.get("with", {})
    assert checkout["with"]["persist-credentials"] == "false"
    login = steps["Log in to GHCR"]
    assert login["with"]["password"] == "${{ github.token }}"
    assert login["with"]["registry"] == "${{ env.REGISTRY }}"


def test_sandbox_image_workflow_still_builds_pinned_image_on_main():
    data = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert data["on"]["push"]["branches"] == ["main"]
    assert "docker/sandbox/**" in data["on"]["push"]["paths"]
    assert ".github/workflows/sandbox-image.yml" in data["on"]["push"]["paths"]
    from arcen.sandbox.runtime import DEFAULT_IMAGE

    env = data["env"]
    assert f"{env['REGISTRY']}/{env['IMAGE_NAME']}:{env['VERSION']}" == DEFAULT_IMAGE
    build = next(
        step
        for step in data["jobs"]["build-and-push"]["steps"]
        if step["name"] == "Build and push (pinned tag)"
    )
    assert build["with"]["context"] == "docker/sandbox"
    assert build["with"]["push"] == "true"
    assert "${{ env.IMAGE_NAME }}:${{ env.VERSION }}" in build["with"]["tags"]
