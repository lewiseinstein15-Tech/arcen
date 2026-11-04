"""A-10 triage is explicitly not semantic classification."""

import importlib.util
from pathlib import Path


def test_every_historical_handler_is_accounted_for_but_unreviewed():
    path = Path(__file__).parents[1] / "docs/audit/propose_dispositions.py"
    spec = importlib.util.spec_from_file_location("a10_triage", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.run()
    assert len(rows) == 338
    assert all(row["review"] == "unreviewed" for row in rows)
    assert len({(row["path"], row["line"]) for row in rows}) == 338
