#!/usr/bin/env python3
"""Score a local task in Docker or format a SWE-bench prediction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arcen.config import ArcenConfig
from arcen.sandbox.turn import IsolationUnavailable
from bench.local_scorer import LocalDockerScorer
from bench.records import score_patch, swebench_prediction


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--instance-id")
    parser.add_argument("--model")
    parser.add_argument("--local-task", help="score one original local task in Docker")
    parser.add_argument("--image", default="ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0")
    args = parser.parse_args()
    try:
        if args.local_task:
            if args.instance_id or args.model:
                parser.error("local task and SWE-bench format options are mutually exclusive")
            config = ArcenConfig()
            config.sandbox.image = args.image
            config.sandbox.backend = "docker"
            scorer = LocalDockerScorer(config)
            row = score_patch(args.local_task, args.patch, scorer)
            if row["resolved"] is None:
                row["error"] = scorer.last_error
            print(json.dumps(row))
            return 0 if row["resolved"] is not None else 1
        if not args.instance_id or not args.model:
            parser.error("--instance-id and --model are required for SWE-bench format")
        print(json.dumps(swebench_prediction(args.instance_id, args.model, args.patch)))
    except (ValueError, OSError, IsolationUnavailable) as exc:
        parser.exit(2, f"benchmark rejected: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
