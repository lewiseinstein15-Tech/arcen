"""The small semantic review references the immutable Phase-0 inventory."""

import csv
from pathlib import Path


def test_manual_review_references_real_inventory_and_is_not_complete():
    root = Path(__file__).resolve().parents[1] / "docs" / "audit"
    with (root / "python-exceptions.tsv").open(newline="") as f:
        inventory = list(csv.DictReader(f, delimiter="\t"))
    with (root / "sandbox-semantic-review.tsv").open(newline="") as f:
        reviewed = list(csv.DictReader(f, delimiter="\t"))
    keys = {(r["path"], r["line"]) for r in inventory}
    reviewed_keys = {(r["path"], r["phase0_line"]) for r in reviewed}
    assert len(reviewed) == len(reviewed_keys) == 16
    assert reviewed_keys <= keys
    assert all(r["classification"] and r["finding"] for r in reviewed)
    assert len(reviewed) < len(inventory)
