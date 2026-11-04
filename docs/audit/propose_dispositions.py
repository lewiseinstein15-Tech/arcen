"""Non-authoritative syntax triage; no row is a semantic review."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def propose(body: str) -> str:
    if re.search(r"\braise\b", body):
        return "control-flow"
    if re.search(r"\b(?:emit|log|logger|warning|error|exception|print|append)\b", body):
        return "converted-to-event"
    if re.search(r"\b(?:close|cleanup|kill|unlink|remove|release|rollback)\b", body):
        return "cleanup"
    return "hidden-no-log"


def run(source: Path = ROOT / "python-exceptions.tsv") -> list[dict[str, str]]:
    with source.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file, delimiter="\t"))
    return [
        {
            "path": row["path"],
            "line": row["line"],
            "proposed": propose(row["body (static syntax; not a verdict)"]),
            "review": "unreviewed",
        }
        for row in rows
        if row["caught"] != "SUPPRESS"
    ]


def main() -> None:
    rows = run()
    print(
        json.dumps(
            {
                "records": len(rows),
                "unreviewed": len(rows),
                "non_authoritative_proposals": dict(
                    sorted(Counter(r["proposed"] for r in rows).items())
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
