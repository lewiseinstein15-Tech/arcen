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
    imported = steps["Assert package imports from installed wheel"]["run"]
    assert "arcen.__file__" in imported and "is_relative_to(root)" in imported
    selected = steps["Run selected installed-wheel harness and TUI tests from outside checkout"][
        "run"
    ]
    assert "cd /tmp" in selected and "--import-mode=importlib" in selected
    assert "test_harness_tui_demo.py" in selected and "test_harness_doctor_aux.py" in selected
    assert "test_harness_portability.py" in selected and "test_portability_cli.py" in selected
    assert "test_harness_conflict_resolution.py" in selected
    assert "test_harness_conflict_cli.py" in selected
    assert "test_harness_compose_test_workflow.py" in selected
    assert "test_harness_contrast_suggestions.py" in selected
    assert "test_harness_reflection_cli.py" in selected
    assert "test_harness_experience_editor.py" in selected
    assert "test_harness_parallel_trials.py" in selected
    assert "test_durable_trial_slots.py" in selected
    assert "test_h17e_docker.py" in selected
    docker = data["jobs"]["docker-isolation"]
    steps = {step["name"]: step for step in docker["steps"]}
    assert "docker build" in steps["Build local sandbox image"]["run"]
    assert "docker build" in steps["Build second local image for portability smoke test"]["run"]
    assert (
        "ARCEN_PORTABILITY_IMAGE_A"
        in steps["Build second local image for portability smoke test"]["run"]
    )
    live = steps["Run explicitly enabled real-Docker checks"]
    assert live["env"]["ARCEN_TEST_DOCKER_ISOLATION"] == "1"
    assert (
        live["env"]["ARCEN_H12_DOCKER_IMAGE"] == "ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0"
    )
    for name in (
        "test_turn_isolation.py",
        "test_h12c_docker.py",
        "test_h12d_docker.py",
        "test_h17e_docker.py",
        "test_durable_trial_slots.py",
        "test_manual_campaign.py",
        "test_harness_canary.py",
        "test_harness_portability.py",
    ):
        assert name in live["run"]


def test_portability_image_dockerfile_is_valid_multiline_text():
    import subprocess

    data = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = {step["name"]: step for step in data["jobs"]["docker-isolation"]["steps"]}
    line = steps["Build second local image for portability smoke test"]["run"].splitlines()[0]
    printf = line.split(" | ", 1)[0]
    result = subprocess.run(["sh", "-c", printf], capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [
        "FROM ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0",
        "LABEL org.arcen.profile=portability-smoke",
    ]
