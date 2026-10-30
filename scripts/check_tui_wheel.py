"""Check that a built ARCEN wheel contains the single TUI and replay data."""

from __future__ import annotations

import sys
from pathlib import Path
from zipfile import ZipFile


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/check_tui_wheel.py PATH_TO_WHEEL")
    path = Path(sys.argv[1])
    with ZipFile(path) as wheel:
        names = set(wheel.namelist())
        required = {
            "arcen/tui/__init__.py",
            "arcen/tui/live.py",
            "arcen/tui/composer.py",
            "arcen/tui/sessions.py",
            "arcen/tui/modals.py",
            "arcen/tui/fixtures/server-replan.jsonl",
            "arcen/prompts/system.md",
            "arcen/prompts/draft.md",
            "arcen/prompts/forge.md",
            "arcen/prompts/temper.md",
            "arcen/tool-guidance.md",
            "arcen/harness.toml",
            "arcen/harness/manifest.py",
            "arcen/harness/cli.py",
            "arcen/harness/editor.py",
            "arcen/harness/probe.py",
            "arcen/harness/policy.py",
            "arcen/harness/judge.py",
            "arcen/harness/composer.py",
            "arcen/harness/probe_workspace.py",
            "arcen/harness/probe_container.py",
            "arcen/harness/probe_model.py",
            "arcen/harness/probe_execution.py",
            "arcen/harness/comparison.py",
            "arcen/harness/proposal_comparison.py",
            "arcen/harness/review.py",
            "arcen/harness/budget.py",
            "arcen/harness/experience.py",
            "arcen/harness/manual_campaign.py",
            "arcen/harness/campaign_journal.py",
            "arcen/harness/durable_budget.py",
            "arcen/harness/selection.py",
            "arcen/cli.py",
            "arcen/harness/model.py",
            "arcen/harness/lineage.py",
            "arcen/harness/store.py",
            "arcen/guardrails/__init__.py",
            "arcen/guardrails/policy.py",
            "arcen/guardrails/policy.yaml",
        }
        missing = required - names
        legacy = [name for name in names if name.startswith("arcen/tui/_legacy/")]
        if missing or legacy:
            raise SystemExit(f"wheel invalid: missing={sorted(missing)}, legacy={legacy}")
    print(f"Wheel {path.name}: {len(names)} entries")
    print(
        "Single TUI, replay fixture, prompts, tool guidance and guardrail policy present; legacy TUI absent."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
